import json
import boto3
import requests
import os
import time
import logging
import urllib.parse
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

#Runpod API key and endpoint
RUNPOD_API_KEY = os.environ.get('RUNPOD_API_KEY')
RUNPOD_API_ENDPOINT = os.environ.get('RUNPOD_API_ENDPOINT') 
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET','summaries')
MAX_POLLING_ATTEMPTS = int(os.environ.get('MAX_POLLING_ATTEMPTS', 20))
POLLING_INTERVAL = int(os.environ.get('POLLING_INTERVAL', 10))

# Initialize the S3 client
s3_client = boto3.client('s3')

def lambda_handler(event,context):
    logger.info("Received event: %s", json.dumps(event))
    try:
        # parse the input from the event
        bucket_name, object_key = parse_s3_event(event)
        logger.info(f"Processing file {object_key} from bucket {bucket_name}")

        # get file from s3
        transcript_text = get_transcript_from_s3(bucket_name, object_key)
        if not transcript_text.strip():
            raise ValueError("Transcript file is empty.")
        logger.info(f"Transcript size: {len(transcript_text)} characters")

        # Send the transcript to Runpod for summarization
        job_id = submit_job_to_runpod(transcript_text)
        logger.info(f"Runpod job submitted with ID: {job_id}")

        # Poll for job completion
        summary = poll_runpod_job(job_id)
        logger.info(f"Generated summary length: {len(summary)} characters")

        # generate the output file name
        output_key = generate_output_key(object_key)

        # Upload the summary to S3
        upload_summary_to_s3(summary, OUTPUT_BUCKET, output_key)


        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Summary generated successfully',
                'input_file': f"s3://{bucket_name}/{object_key}",
                'output_file': f"s3://{OUTPUT_BUCKET}/{output_key}"
            })
        }
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': 'Error processing file',
                'error': str(e)
            })
        }
    
def parse_s3_event(event):
    """
    Parse the S3 event to extract bucket name and object key.
    """
    try:
        s3_record = event['Records'][0]['s3']
        bucket_name = s3_record['bucket']['name']
        object_key = urllib.parse.unquote_plus(s3_record['object']['key'])
        return bucket_name, object_key 
    except (KeyError, IndexError) as e:
        logger.error(f"Error parsing S3 event: {str(e)}")
        raise ValueError(f"Invalid S3 event format: {str(e)}")
    
def get_transcript_from_s3(bucket, key):
    """
    Get the transcript text from S3.
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        transcript_text = response['Body'].read().decode('utf-8')
        return transcript_text
    except ClientError as e:
        logger.error(f"Error getting object {key} from bucket {bucket}: {str(e)}")
        raise    


def submit_job_to_runpod(text):
    """
    Submit a job to Runpod's serverless endpoint.

    Args:
        text (str): The transcript text to be summarized.

    Returns:
        str: The job ID returned by Runpod.    
    """    

    if not RUNPOD_API_KEY:
        raise ValueError("Runpod API key is not set.")
    
    if not RUNPOD_API_ENDPOINT:
        raise ValueError("Runpod API endpoint is not set.")
    
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }


    # Configure prompt for summarization
    prompt = f"""Your task is to create a comprehensive summary of the following transcription. 
    The summary should be detailed and approximately 4,000 words in length.
    
    Transcription:
    {text}
    
    Summary:"""

    # Assume using vLLM model for summarization
    payload = {
        "input": {
            "prompt": prompt,
            "max_tokens": 6000,         # Increased to better match the 4,000 word requirement
            "temperature": 0.5,
            "top_p": 0.9,
        }
    }

    try:
        run_url = f"{RUNPOD_API_ENDPOINT}/run"
        response = requests.post(run_url, headers=headers, json=payload)
        response.raise_for_status() # Raise an error for bad responses
        
        result = response.json()

        if "id" not in result:
            raise ValueError(f"No job ID returned from Runpod: {result}")
        return result["id"]
    except requests.exceptions.RequestException as e:
        logger.error(f"Error submitting job to Runpod: {str(e)}")
        raise

def poll_runpod_job(job_id):
    """
    Poll the Runpod job status.

    Args:
        job_id (str): The ID of the job to poll.

    Returns:
        dict: The job status response.
    """
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }

    for attempt in range(MAX_POLLING_ATTEMPTS):

        try:
            status_url = f"{RUNPOD_API_ENDPOINT}/status/{job_id}"
            response = requests.get(status_url, headers=headers)
            response.raise_for_status()

            result = response.json()
            status = result.get("status", "")

            if status == "COMPLETED":
                output = result.get("output", {})

                if isinstance(output, dict) and "text" in output:
                    return output["text"]
                elif isinstance(output, str):
                    return output
                else:
                    return output.get("text", json.dumps(output))
                
            elif status == "FAILED":
                error_message = result.get("error", "Unknown error")
                raise Exception(f"Runpod job failed: {error_message}")


            # If job is still running, wait and poll again
            logger.info(f"Runpod job {job_id} is still running. Attempt {attempt + 1}/{MAX_POLLING_ATTEMPTS}.")
            time.sleep(POLLING_INTERVAL)


        except requests.exceptions.RequestException as e:
            logger.error(f"Error polling Runpod job {job_id}: {str(e)}")
            time.sleep(POLLING_INTERVAL)


    # If we exhaust the polling attempts, raise an error    
    raise TimeoutError(f"Polling for Runpod job {job_id} timed out after {MAX_POLLING_ATTEMPTS} attempts.")


def generate_output_key(input_key):
    """
    Generate the output S3 key based on the input key.

    Args:
        input_key (str): The S3 key of the input file.

    Returns:
        str: The generated S3 key for the output file.
    """
    base_name = input_key.rsplit('.', 1)[0] if '.' in input_key else input_key

    return f"summaries/{base_name}_summary.txt"




def upload_summary_to_s3(summary, bucket, key):
    """
    Store the generated summary in S3.
    """
    try:
        s3_client.put_object(
            Body=summary.encode('utf-8'),
            Bucket=bucket,
            Key=key,
            ContentType='text/plain'
        )
        logger.info(f"Summary stored in S3: s3://{bucket}/{key}")
    except ClientError as e:
        logger.error(f"Error storing summary in S3: {str(e)}")
        raise
