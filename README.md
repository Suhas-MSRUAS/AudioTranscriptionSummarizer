
# AWS Lambda Transcript Summarizer using RunPod

This AWS Lambda function automates the process of summarizing large audio transcriptions. It orchestrates a workflow that retrieves transcription files from S3, sends them to a RunPod Serverless AI endpoint for summarization, and stores the results back in S3.


## Model Recommendation
### Primary Choice: Mistral-Small-3.1-24B-Instruct-2503
This model is ideal for the transcription summarization task for several key reasons:

* **Context Window**: Supports a 32K token context window, comfortably handling our ~10,000+ word transcription requirement
* **Instruction Following**: Fine-tuned for following detailed instructions, making it excellent for generating structured summaries
* **Performance Balance**: At 24B parameters, it offers strong summarization capabilities while being efficient enough to run on A100/H100 GPUs
* **Quantization Support**: Compatible with AWQ/GPTQ quantization techniques to optimize VRAM usage on RunPod
* **Production Ready**: Designed for production deployment with vLLM for efficient inference
### Alternative: Llama 3 70B Instruct
If higher quality is needed and GPU resources are sufficient:

* **Context Window**: 128K tokens, providing ample room for even larger transcriptions
* **Enhanced Performance**: Larger parameter count (70B) delivers potentially higher quality summaries
* **AWQ Quantization**: Available in quantized versions for efficient deployment on high-end GPUs
## How the Lambda Function Works
The Lambda function operates in a sequence of well-defined steps:

* **Event Parsing**: When triggered by an S3 event notification (file upload), the function extracts the bucket name and object key.
* **Data Retrieval**: It fetches the transcription text file from S3 using the boto3 client.
* **RunPod Job Submission**: The function sends the text to the RunPod serverless endpoint with appropriate parameters: 
    * A carefully crafted prompt instructing the model to generate a 4,000 word summary
    * Sets max_tokens to 6000 (accounting for the token-to-word ratio)
    * Uses appropriate temperature and top_p settings for high-quality summarization


* **Status Polling**: After submission, the function polls the RunPod API to check job status until completion or failure.
* **Result Processing**: Upon successful completion, it extracts the summary from the RunPod response.
* **Output Storage**: The summary is stored as a new text file in the designated S3 bucket under a "summaries/" prefix.
## Environment Variables

To run this project, you will need to add the following environment variables to your .env file

* `RUNPOD_API_KEY`(Required): Authentication key for the RunPod API

* `RUNPOD_API_ENDPOINT`(Required): Base URL for the RunPod serverless endpoint

* `OUTPUT_BUCKET`(Optional): The S3 bucket for storing summaries (defaults to "summaries")

* `MAX_POLLING_ATTEMPTS`(Optional): Maximum number of status check attempts (defaults to 10)

* `POLLING_INTERVAL`(Optional): Time between polling attempts in seconds (defaults to 5)




## Design Decisions
### Efficient S3 Handling

Uses S3's streaming capabilities through `get_object()['Body'].read()` to efficiently handle large transcription files without excessive memory usage.

### RunPod API Integration

Implements the correct endpoint structure with `/run` and`/status/{job_id}` paths
Sets appropriate headers and authentication for all API requests
Structures the payload to optimize for the ~4,000 word summary requirement

### Polling Strategy

Implements a configurable polling mechanism with MAX_POLLING_ATTEMPTS and POLLING_INTERVAL
Logs each polling attempt for monitoring and debugging
Handles various response scenarios (completion, failure, still running)

### Error Handling

Comprehensive try/except blocks at key processing points
Detailed error logging with specific error types for different failure scenarios
Graceful handling of RunPod API errors through proper HTTP response status checking

## Alternative "Pull" Approach
### Current "Push" Architecture

In the implemented solution, the Lambda:

* Reads the entire transcription from S3
* Sends the content to RunPod
* Polls for completion
* Retrieves and stores the result

### Alternative "Pull" Architecture
An alternative approach would have the RunPod worker pull the data directly:

* Lambda generates a pre-signed S3 URL for the transcription file
* Lambda sends only this URL to RunPod (rather than the entire file content)
* A custom RunPod worker fetches the file content directly from S3
* After processing, the worker stores results back in S3 directly or returns them to Lambda

### Pros of Pull Approach

* Reduced Lambda Memory Usage: Only handles URLs, not entire file contents
* No Lambda Timeout Issues: Lambda completes quickly after job submission
* Efficient for Very Large Files: Handles transcriptions of any size
* Direct Data Transfer: S3→RunPod without Lambda as intermediary

### Cons of Pull Approach

* Custom Worker Required: Needs a modified RunPod container with AWS SDK
* Additional Security Setup: Requires proper IAM permissions and URL expiration control
* More Complex Infrastructure: Additional components to maintain
* Potential S3 Egress Costs: Data transfer fees from S3 to RunPod

### Recommendation
The current "push" approach is simpler and sufficient for transcriptions that can be processed within Lambda's execution limits. For extremely large files or unpredictable processing times, the "pull" approach offers better scalability but requires additional setup.

### Testing Strategy
Before receiving the actual RunPod API key, the function can be tested through:
#### Unit Testing

* Mock S3 event payloads to verify parsing logic
* Test error handling paths with simulated exceptions
* Verify output path generation for different input filenames

#### Integration Testing with Mocks

* Mock RunPod API responses to simulate job submission and status checking
* Use boto3's mock framework to test S3 interactions
* Verify the entire workflow with controlled inputs and outputs

#### Local Execution Environment

* Use AWS SAM or LocalStack to simulate the Lambda environment
* Run the function with sample event data locally
* Verify environment variable handling

#### RunPod API Simulation

* Create a simple HTTP server that mimics the RunPod API
* Test with various response scenarios (success, failure, timeout)
* Verify proper handling of different API response formats

Once the actual API key is available, conduct end-to-end tests with smaller transcription files before deploying to production.
