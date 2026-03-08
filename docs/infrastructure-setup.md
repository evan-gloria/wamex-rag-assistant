# Infrastructure Setup Guide: WAMEX Serverless RAG Pipeline

This document outlines the step-by-step process for bootstrapping the local development environment and deploying a $0.00, true-serverless RAG architecture to AWS using Amazon Bedrock and an in-memory FAISS vector store.

## 1. Local Toolchain Prerequisites

We use Homebrew on macOS to manage system-level dependencies cleanly, isolating them from our Python environment.

**Install the AWS CLI and SAM CLI:**

```bash
brew install awscli
brew tap aws/tap
brew install aws-sam-cli
```

**Install Poetry (Dependency Management):**
```bash
brew install poetry
```

## 2. AWS Authentication (IAM Identity Center)

This project uses enterprise-grade SSO instead of static long-lived IAM keys to ensure secure, short-lived session management.

**Step 2.1: Configure the SSO Profile**
*(Skip this step if your profile is already configured).*
```bash
aws configure sso
```
- SSO start URL: https://<your-id>.awsapps.com/start
- SSO Region: ap-southeast-2
- CLI default client Region: ap-southeast-2
- CLI profile name: wamex-poc-profile

**Step 2.2: Authenticate and Export Variables**
Whenever your session token expires, authenticate via your browser and lock your terminal session to the correct environment:
```bash
aws sso login --profile wamex-poc-profile
export AWS_PROFILE=wamex-poc-profile
export AWS_DEFAULT_REGION=ap-southeast-2
```

**Step 2.3: Verify Identity (Safety Check)**
Before running any infrastructure commands, verify your active session to prevent accidental deployments to the wrong AWS account:
```bash
aws sts get-caller-identity
```


## 3. Python Environment & Dependency Management
We use Poetry to ensure deterministic builds and isolate our development environment. Because AWS SAM expects a `requirements.txt` file, we use Poetry strictly for dependency resolution and export the lockfile for SAM.

*Note: We strictly target Python 3.11 and use `faiss-cpu==1.7.4` to guarantee compatibility with AWS Graviton (ARM64) pre-compiled binaries.*

**Install Dependencies & the Export Plugin:**

```Bash
poetry install
```
*(Note: Ensure `package-mode = false` is set in `pyproject.toml` to prevent Poetry from attempting to package the AWS SAM directory structure as a standard Python library).*


## 4. Building and Deploying the Architecture
With the local environment ready and the vector database active, we use AWS SAM to package and deploy the event-driven architecture (S3, Lambda, IAM roles).

**Step 4.1: Export Requirements for SAM**
Generate a clean, hash-free requirements file for the Lambda build process:

```Bash
poetry export -f requirements.txt --output src/ingestion/requirements.txt --without frontend --without-hashes
poetry export -f requirements.txt --output src/api/requirements.txt --without frontend --without-hashes
```

**Step 4.2: Build the Containerized Artifact**
*Requirement: Docker must be running locally.*

Compile the deployment artifact. Using `--use-container` ensures the Python packages are compiled specifically for the AWS Graviton (ARM64) architecture defined in the `template.yaml`.

```Bash
sam build --use-container
```

**Step 4.3: Execute the Guided Deployment**
Deploy the CloudFormation stack to the AWS Sandbox:

```Bash
sam deploy --guided
```

**Deployment Parameters:**
- Stack Name: `wamex-rag-pipeline`
- AWS Region: `ap-southeast-2`
- Confirm changes before deploy: `Y`
- Allow SAM CLI IAM role creation: `Y`
- Disable rollback: `N`
- Save arguments to configuration file: `Y`

Once CloudFormation completes, the pipeline is fully active. Dropping a PDF into the newly created S3 bucket will automatically trigger the ingestion Lambda.

## 5. Execution & Validation
This pipeline operates on a strict scale-to-zero model.

To trigger the ingestion pipeline:

1. Upload a geological report (`.pdf`) to the `wamex-raw-pdfs-...` S3 bucket.
2. The `ObjectCreated` event will trigger the Lambda function to download the PDF, chunk the text, generate Amazon Bedrock embeddings, and build the FAISS index in memory.
3. The resulting vectors (`index.faiss` and `index.pkl`) are automatically saved back to an `index/` directory within the same S3 bucket, ensuring zero ongoing database costs.

---

## 🚨 Critical Configuration: Anthropic Claude 3 Access

AWS recently overhauled how third-party foundation models are provisioned in Bedrock. Accessing Anthropic Claude now requires two distinct security clearances: Account-level EULA acceptance and Resource-level IAM permissions.

### Step 1: Account-Level EULA Acceptance (Admin/Root Required)
The centralized "Model Access" page has been retired in favor of an auto-provisioning system tied to AWS Marketplace. To trigger the subscription for Claude:

1. Log into the AWS Console using an **Admin or Root** account. Ensure you are in the `ap-southeast-2` (Sydney) region.
2. Navigate to **Amazon Bedrock** -> **Chat** (under the Playgrounds section).
3. Click **Select model**, choose **Anthropic** > **Claude 3 Haiku**, and click **Apply**.
4. Type a test message (e.g., "Hello") and hit Enter.
5. AWS will intercept the request and prompt the **Anthropic Use Case Details** form. Fill it out:
   - **Company Name:** Personal Portfolio / <Your Name>
   - **Website URL:** https://github.com
   - **Industry:** Technology
   - **Use Case:** Internal RAG Proof of Concept.
   - **User Type:** Internal users.
6. Submit the form. **Wait 5 to 15 minutes** for the Marketplace subscription to propagate globally across AWS servers (Eventual Consistency).

### Step 2: Resource-Level IAM Permissions
Even after the account is subscribed, the Lambda execution role must be explicitly granted permission to verify the Marketplace subscription during runtime. 

Ensure your `template.yaml` includes this wildcard statement in the function's policies, entirely separate from the `bedrock:InvokeModel` ARNs:

```yaml
        - Statement:
            - Effect: Allow
              Action:
                - aws-marketplace:ViewSubscriptions
                - aws-marketplace:Subscribe
              Resource: "*"
```

*(Note: If your API returns an `AccessDeniedException` or an Internal Server Error immediately after deployment, the AWS Marketplace synchronization is likely still pending. Wait a few minutes and try the query again).*


## 6. Launching the Local UI
With the AWS backend deployed and your first reports ingested, you can launch the Streamlit chat interface locally:

```bash
poetry run streamlit run frontend/app.py
```

---