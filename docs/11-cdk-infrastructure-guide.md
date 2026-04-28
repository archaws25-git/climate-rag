# ClimateRAG — CDK Infrastructure Guide

**Date:** 2026-04-28 | **Version:** 1.0
**Replaces:** `terraform/` directory (Terraform + null_resource workarounds)

---

## Table of Contents

1. [Why CDK Replaced Terraform](#1-why-cdk-replaced-terraform)
2. [Architecture Decisions & Trade-offs](#2-architecture-decisions--trade-offs)
3. [CDK Project Structure](#3-cdk-project-structure)
4. [Stack Reference](#4-stack-reference)
5. [Custom Resource Design](#5-custom-resource-design)
6. [Prerequisites](#6-prerequisites)
7. [How to Deploy](#7-how-to-deploy)
8. [How to Destroy](#8-how-to-destroy)
9. [Runtime Configuration](#9-runtime-configuration)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Why CDK Replaced Terraform

The Terraform implementation had a fundamental structural problem: AgentCore
resources (`Memory`, `Code Interpreter`, `Gateway`) have no native
CloudFormation resource types and therefore no native Terraform provider
support. The workaround was `null_resource` blocks with `local-exec`
provisioners that called `tf_agentcore.py` — a CLI script — from within
Terraform's plan/apply cycle.

This created several compounding issues:

| Problem | Terraform workaround | Impact |
|---|---|---|
| No provider support for AgentCore | `null_resource` + `local-exec` | Terraform state does not track AgentCore resources |
| Resource IDs must persist between runs | Write to `.txt` files on disk | Brittle; breaks on CI/CD or new machines |
| IAM propagation timing | Hard-coded `time.sleep(15)` | Races on slow environments; wastes time on fast ones |
| `tf_agentcore.py` is a CLI script | Wrapped in shell calls from HCL | Two layers of indirection; hard to debug |
| No lifecycle hooks for AgentCore | `when = destroy` provisioners | Destroy runs are unreliable if the `.txt` file is missing |

The CDK approach solves all of these at the platform level:

- **State**: CloudFormation tracks every resource's `PhysicalResourceId`. No `.txt` files.
- **Lifecycle**: CloudFormation calls `Create`, `Update`, `Delete` automatically on the correct resource.
- **Timing**: The custom resource Lambda runs a proper exponential-backoff polling loop inside a 14-minute timeout window.
- **IAM propagation**: Replaced `time.sleep(15)` with a retry loop that backs off gracefully.
- **Debugging**: Lambda logs go to CloudWatch. Every invocation is traceable.

---

## 2. Architecture Decisions & Trade-offs

### ADR-CDK-001: Separate Stacks vs Nested Stacks

**Decision:** Three independent top-level CloudFormation stacks.

**Context:** The original Terraform used a flat resource list with manual
`depends_on`. Two CDK patterns were evaluated:

| Concern | Nested Stacks | Separate Stacks (chosen) |
|---|---|---|
| FAISS index protection | Single `cdk destroy` tears down everything including S3 | `cdk destroy ClimateRagAgentCoreStack` leaves S3 intact |
| Iteration speed | Must redeploy entire parent to change one child | Deploy only the changed stack |
| Cross-stack references | Pass construct refs through nested stack props | CDK cross-stack exports (`CfnOutput` + `Fn.import_value`) |
| CloudFormation console | One parent stack with nested children | Three independent stacks, each with its own events log |
| Destroy order | Cascade from parent | Must destroy in reverse dependency order (documented below) |

**Rationale:** The FAISS index in S3 is expensive to rebuild (ingestion
pipeline + Bedrock Titan embedding costs). Separate stacks make it
structurally impossible to accidentally destroy S3 while iterating on
Gateway configuration. This was the deciding factor.

---

### ADR-CDK-002: Lambda-backed Custom Resource vs AwsCustomResource

**Decision:** Lambda-backed Custom Resource (`custom_resources.Provider`).

**Context:** AgentCore resources have no CloudFormation support. Two CDK
patterns can bridge this gap:

**AwsCustomResource** fires a single SDK call and returns immediately. It
cannot wait for an asynchronous resource to become `ACTIVE`.

```
AwsCustomResource timeline:
  T+0s    create_memory() API call fires
  T+1s    API returns { memoryId: "xyz", status: "CREATING" }
  T+1s    CloudFormation marks resource CREATE_COMPLETE  ← WRONG
  T+3min  Memory actually reaches ACTIVE in the background
  T+3min  Gateway creation fails: depends on Memory being ACTIVE
```

**Lambda-backed Custom Resource** runs arbitrary Python inside a Lambda
with up to 14 minutes of execution time, enabling a proper polling loop:

```
Lambda Custom Resource timeline:
  T+0s    create_memory() API call fires
  T+1s    Polling loop starts (10s → 20s → 40s backoff)
  T+3min  Memory reaches ACTIVE; Lambda returns successfully
  T+3min  CloudFormation marks resource CREATE_COMPLETE  ← CORRECT
  T+3min  Gateway Custom Resource starts (dependency satisfied)
```

**Trade-off accepted:** A dedicated Lambda function is deployed as
infrastructure-of-infrastructure. It adds ~30 seconds to the first `cdk
deploy` (Lambda packaging) but is a one-time cost.

---

### ADR-CDK-003: Single Shared Handler vs Per-Resource Lambdas

**Decision:** One Lambda function handles Memory, CodeInterpreter, and Gateway.

**Rationale:** The `ResourceType` property in each Custom Resource's
`ResourceProperties` routes to the correct handler function. This mirrors the
subcommand dispatcher in `tf_agentcore.py` and keeps the provisioner surface
small: one IAM role, one Lambda, one CloudWatch Log Group to monitor.

**Trade-off:** A bug in one handler function could theoretically affect a
different resource type's execution. In practice the dispatch is a simple
dictionary lookup and each handler is fully isolated.

---

### ADR-CDK-004: SSM Parameters for Runtime Configuration

**Decision:** AgentCore resource IDs are written to SSM Parameter Store
(`/climate-rag/memory-id`, etc.) rather than a generated `.env` file.

**Context:** `setup_all.py` and the Terraform `outputs.tf` both generated
shell environment variable snippets that had to be manually copy-pasted. This
broke on CI/CD and was error-prone.

**SSM approach:** The agent reads its own config at startup via:
```python
import boto3
ssm = boto3.client("ssm", region_name="us-east-1")
memory_id = ssm.get_parameter(Name="/climate-rag/memory-id")["Parameter"]["Value"]
```

**Trade-off:** Requires `ssm:GetParameter` in the AgentCore Runtime role.
This is a minor IAM addition but eliminates all manual ID management.

---

### ADR-CDK-005: RemovalPolicy.RETAIN on S3

**Decision:** The S3 bucket has `RemovalPolicy.RETAIN`.

**Consequence:** Running `cdk destroy ClimateRagDataStack` does **not**
delete the bucket or its contents. The bucket must be manually emptied and
deleted if a true full teardown is required (see [Section 8](#8-how-to-destroy)).

**Rationale:** This is intentional protection against accidental data loss.
The FAISS index represents hours of ingestion work and real Bedrock API costs.

---

## 3. CDK Project Structure

```
cdk/
├── app.py                              # CDK app entry point; defines stack order
├── cdk.json                            # CDK CLI configuration and feature flags
├── pyproject.toml                      # Python project metadata (Poetry)
├── requirements.txt                    # CDK Python dependencies
│
├── stacks/
│   ├── __init__.py
│   ├── data_stack.py                   # Stack 1: S3 bucket (long-lived)
│   ├── compute_stack.py                # Stack 2: IAM roles + Lambda functions
│   └── agentcore_stack.py              # Stack 3: Memory / Code Interpreter / Gateway
│
└── custom_resources/
    ├── __init__.py
    └── agentcore_handler/
        ├── handler.py                  # Lambda handler (replaces tf_agentcore.py)
        └── requirements.txt            # Lambda runtime dependencies
```

### Mapping: Terraform → CDK

| Terraform resource | CDK equivalent | Stack |
|---|---|---|
| `aws_s3_bucket.index` | `s3.Bucket` | DataStack |
| `aws_s3_bucket_server_side_encryption_configuration` | `encryption=S3_MANAGED` (inline) | DataStack |
| `aws_s3_bucket_public_access_block` | `block_public_access=BLOCK_ALL` (inline) | DataStack |
| `aws_iam_role.lambda` | `iam.Role` (LambdaExecutionRole) | ComputeStack |
| `aws_iam_role.gateway` | `iam.Role` (GatewayInvocationRole) | ComputeStack |
| `aws_iam_role_policy.gateway_invoke_lambda` | `role.add_to_policy()` | ComputeStack |
| `aws_lambda_function.nasa_power` | `lambda_.Function` | ComputeStack |
| `aws_lambda_function.noaa_ncei` | `lambda_.Function` | ComputeStack |
| `null_resource.memory` + `tf_agentcore.py create_memory` | `CustomResource` (Memory) | AgentCoreStack |
| `null_resource.code_interpreter` + `tf_agentcore.py create_code_interpreter` | `CustomResource` (CodeInterpreter) | AgentCoreStack |
| `null_resource.gateway` + `tf_agentcore.py create_gateway` | `CustomResource` (Gateway) | AgentCoreStack |
| Manual `.txt` file ID persistence | SSM Parameter Store + `CfnOutput` | AgentCoreStack |

---

## 4. Stack Reference

### ClimateRagDataStack

**Purpose:** Provisions the S3 bucket that stores the FAISS vector index.

| Resource | Logical ID | Notes |
|---|---|---|
| `s3.Bucket` | `IndexBucket` | `RemovalPolicy.RETAIN` — survives stack destroy |

**Exports:**
- `ClimateRag-IndexBucketName`
- `ClimateRag-IndexBucketArn`

**Deploy frequency:** Once. Only re-deploy if bucket configuration changes.

---

### ClimateRagComputeStack

**Purpose:** IAM roles and Lambda proxy functions for the NASA/NOAA API bridge.

| Resource | Logical ID | Notes |
|---|---|---|
| `iam.Role` | `LambdaExecutionRole` | `AWSLambdaBasicExecutionRole` only |
| `iam.Role` | `GatewayInvocationRole` | `lambda:InvokeFunction` on both proxies |
| `lambda_.Function` | `NasaPowerProxy` | `climate-rag-nasa-power` |
| `lambda_.Function` | `NoaaNceiProxy` | `climate-rag-noaa-ncei` |

**Exports:**
- `ClimateRag-NasaLambdaArn`
- `ClimateRag-NoaaLambdaArn`
- `ClimateRag-GatewayRoleArn`

**Deploy frequency:** When Lambda handler code changes.

---

### ClimateRagAgentCoreStack

**Purpose:** AgentCore Memory, Code Interpreter, and Gateway.

| Resource | Logical ID | Notes |
|---|---|---|
| `iam.Role` | `AgentCoreCRLambdaRole` | Provisioner Lambda execution role |
| `lambda_.Function` | `AgentCoreCRLambda` | 14-min timeout; handles all 3 resource types |
| `custom_resources.Provider` | `AgentCoreCRProvider` | CDK Provider wrapper |
| `CustomResource` | `AgentCoreMemory` | Provisions Memory, waits for ACTIVE |
| `CustomResource` | `AgentCoreCodeInterpreter` | Provisions Code Interpreter, waits for ACTIVE |
| `CustomResource` | `AgentCoreGateway` | Provisions Gateway + 2 targets |
| `ssm.StringParameter` | `MemoryIdParam` | `/climate-rag/memory-id` |
| `ssm.StringParameter` | `CodeInterpreterIdParam` | `/climate-rag/code-interpreter-id` |
| `ssm.StringParameter` | `GatewayIdParam` | `/climate-rag/gateway-id` |

**Deploy frequency:** When AgentCore configuration changes (e.g., memory strategy, gateway targets).

**Safe to destroy independently** — does not affect S3 or Lambda code.

---

## 5. Custom Resource Design

The `agentcore_handler/handler.py` Lambda replaces `tf_agentcore.py` with a
purpose-built CloudFormation Custom Resource handler.

### Lifecycle event mapping

```
CloudFormation event   handler.py function     AgentCore API call
─────────────────────  ──────────────────────  ──────────────────────────────
Create                 _handle_memory()         create_memory() + wait_active()
Update                 _handle_memory()         no-op (returns existing ID)
Delete                 _handle_memory()         delete_memory() (idempotent)

Create                 _handle_code_interpreter() create_code_interpreter() + wait_active()
Update                 _handle_code_interpreter() no-op
Delete                 _handle_code_interpreter() delete_code_interpreter() (idempotent)

Create                 _handle_gateway()        create_gateway_with_retry()
                                                + wait_active()
                                                + _reconcile_gateway_targets()
Update                 _handle_gateway()        _reconcile_gateway_targets() only
Delete                 _handle_gateway()        _delete_gateway_targets()
                                                + delete_gateway() (idempotent)
```

### IAM propagation: retry vs sleep

`tf_agentcore.py` used `time.sleep(15)` before creating the Gateway to allow
the IAM role to propagate. The handler replaces this with
`_create_gateway_with_retry()` — an exponential backoff retry loop
(10s → 20s → 40s → 60s cap) that retries specifically on
`InvalidParameterException` and `ValidationException`. This is both more
robust and faster on environments where IAM propagates quickly.

### Idempotency

All Create handlers begin with a list call to check whether the resource
already exists by name. If it does, the existing ID is reused and the
`_wait_active()` loop confirms it is in a good state. This means:

- Re-running `cdk deploy ClimateRagAgentCoreStack` after a partial failure
  is safe — it will not create duplicate resources.
- Importing manually-created AgentCore resources into CDK management is
  supported as long as the names match.

---

## 6. Prerequisites

```bash
# 1. Python 3.12+
python3 --version

# 2. Node.js 18+ (CDK CLI is Node-based)
node --version

# 3. AWS CDK CLI v2
npm install -g aws-cdk
cdk --version   # should be 2.170.0+

# 4. AWS credentials configured
aws configure   # or set AWS_PROFILE / AWS_ACCESS_KEY_ID

# 5. Bedrock model access enabled in us-east-1
#    - Claude Sonnet 4 (inference profile)
#    - Amazon Titan Embeddings v2

# 6. CDK bootstrap (one-time per account/region)
cdk bootstrap aws://<ACCOUNT_ID>/us-east-1

# 7. Python virtual environment for CDK app
cd cdk/
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 7. How to Deploy

### Full deployment (first time)

Deploy all three stacks in dependency order:

```bash
cd cdk/
source .venv/bin/activate

# Preview what will be created
cdk diff --all

# Deploy all stacks (order is enforced by add_dependency() in app.py)
cdk deploy --all
```

Expected output per stack:

```
✅  ClimateRagDataStack
    Outputs:
      ClimateRagDataStack.IndexBucketName = climate-rag-index-123456789012

✅  ClimateRagComputeStack
    Outputs:
      ClimateRagComputeStack.NasaLambdaArn = arn:aws:lambda:...
      ClimateRagComputeStack.NoaaLambdaArn = arn:aws:lambda:...

✅  ClimateRagAgentCoreStack   ← takes ~12 minutes (AgentCore ACTIVE waits)
    Outputs:
      ClimateRagAgentCoreStack.MemoryId          = mem-xxxxxxxxxx
      ClimateRagAgentCoreStack.CodeInterpreterId = ci-xxxxxxxxxx
      ClimateRagAgentCoreStack.GatewayId         = gw-xxxxxxxxxx
```

> **Note:** `ClimateRagAgentCoreStack` will take approximately 10–12 minutes
> on first deploy. This is normal — the CloudFormation custom resources are
> polling until AgentCore Memory and Code Interpreter reach `ACTIVE` status.
> Monitor progress in CloudWatch Logs:
> `/aws/lambda/climate-rag-agentcore-cr`

### Deploy a single stack

```bash
# Re-deploy only the AgentCore stack (safe — S3 and Lambda are untouched)
cdk deploy ClimateRagAgentCoreStack

# Re-deploy only the Lambda proxy code (after updating handler.py)
cdk deploy ClimateRagComputeStack

# Re-deploy only the S3 bucket configuration
cdk deploy ClimateRagDataStack
```

### Preview changes before deploying

```bash
# Show all changes across all stacks
cdk diff --all

# Show changes for one stack only
cdk diff ClimateRagAgentCoreStack
```

### After deployment: run the ingestion pipeline

The CDK stacks provision infrastructure only. After a successful deploy,
run the ingestion pipeline to populate the FAISS index:

```bash
# Read the bucket name from CDK outputs (or SSM)
export CLIMATE_RAG_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name ClimateRagDataStack \
  --query "Stacks[0].Outputs[?OutputKey=='IndexBucketName'].OutputValue" \
  --output text)

# Read AgentCore IDs from SSM (no manual copy-paste needed)
export CLIMATE_RAG_MEMORY_ID=$(aws ssm get-parameter \
  --name /climate-rag/memory-id --query Parameter.Value --output text)

export CLIMATE_RAG_CODE_INTERPRETER_ID=$(aws ssm get-parameter \
  --name /climate-rag/code-interpreter-id --query Parameter.Value --output text)

# Run ingestion
cd ..   # back to repo root
python ingest/ingest_gistemp.py
python ingest/ingest_ghcn.py
python ingest/ingest_power.py
python ingest/embeddings.py
python ingest/build_index.py

# Start the UI
streamlit run ui/app.py
```

---

## 8. How to Destroy

### Destroy AgentCore resources only (most common)

Safe to run at any time. Does not affect S3, Lambda, or the FAISS index.

```bash
cdk destroy ClimateRagAgentCoreStack
```

CloudFormation will:
1. Call the custom resource Lambda with `RequestType=Delete` for each resource.
2. The Lambda deletes Gateway targets, then the Gateway, then Code Interpreter,
   then Memory.
3. The Lambda itself and its IAM role are deleted as part of the stack teardown.
4. SSM parameters are deleted automatically (no `RemovalPolicy.RETAIN` on SSM).

### Destroy compute resources

Only do this if you also want to remove the Lambda proxy functions and IAM roles.
Must destroy AgentCoreStack first (it has a declared dependency).

```bash
cdk destroy ClimateRagAgentCoreStack   # first
cdk destroy ClimateRagComputeStack     # then
```

### Full teardown (everything)

> ⚠️ **Warning:** This is irreversible. The FAISS index will be lost.
> Back up the index first if you may need it again:
> ```bash
> aws s3 sync s3://climate-rag-index-<account_id>/index/ ./backup-index/
> ```

```bash
# Step 1: Destroy stacks in reverse dependency order
cdk destroy ClimateRagAgentCoreStack
cdk destroy ClimateRagComputeStack

# Step 2: Empty the S3 bucket (required because RemovalPolicy=RETAIN
#          means CDK/CloudFormation will not empty or delete it)
aws s3 rb s3://climate-rag-index-$(aws sts get-caller-identity \
  --query Account --output text) --force

# Step 3: Now destroy the DataStack (bucket is already gone)
cdk destroy ClimateRagDataStack

# Step 4: Clean up residual resources not managed by CDK
#         (only present if you previously used the manual setup scripts)

# Cognito User Pool (auto-created by AgentCore Gateway CLI)
# Find it: aws cognito-idp list-user-pools --max-results 10
# Delete:  aws cognito-idp delete-user-pool --user-pool-id <id>

# CloudWatch log groups
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore \
  --query "logGroups[].logGroupName" --output text | \
  tr '\t' '\n' | \
  xargs -I{} aws logs delete-log-group --log-group-name {}

# Nginx config and Streamlit process (if running locally)
pkill -f streamlit
sudo rm -f /etc/nginx/sites-enabled/climate-rag
sudo systemctl restart nginx
```

### Destroy order summary

```
Correct destroy order (reverse of deploy):

  cdk destroy ClimateRagAgentCoreStack    ← safe to destroy alone
       ↓
  cdk destroy ClimateRagComputeStack      ← requires AgentCore destroyed first
       ↓
  aws s3 rb ... --force                   ← manual: CDK will not delete RETAIN bucket
       ↓
  cdk destroy ClimateRagDataStack         ← bucket must be empty first
```

---

## 9. Runtime Configuration

The agent reads its configuration from SSM at startup. Update
`agent/main.py` to use SSM instead of environment variables:

```python
import boto3

def _get_ssm(name: str) -> str:
    ssm = boto3.client("ssm", region_name="us-east-1")
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]

MEMORY_ID          = os.environ.get("CLIMATE_RAG_MEMORY_ID") \
                     or _get_ssm("/climate-rag/memory-id")
CODE_INTERPRETER_ID = os.environ.get("CLIMATE_RAG_CODE_INTERPRETER_ID") \
                     or _get_ssm("/climate-rag/code-interpreter-id")
```

Environment variables take precedence, so local development (with `.env`)
continues to work unchanged. SSM is the fallback for deployed environments.

---

## 10. Troubleshooting

### Custom Resource Lambda timeout

**Symptom:** `ClimateRagAgentCoreStack` fails with `Custom Resource failed to stabilise`.

**Cause:** The AgentCore Memory or Code Interpreter took longer than 14
minutes to reach `ACTIVE` (unusual, but possible during AWS degraded events).

**Fix:**
```bash
# Check Lambda logs for the last error
aws logs tail /aws/lambda/climate-rag-agentcore-cr --since 30m

# Re-deploy — the Create handler is idempotent (will reuse existing resource if it became ACTIVE)
cdk deploy ClimateRagAgentCoreStack
```

### Gateway creation fails with InvalidParameterException

**Symptom:** Lambda logs show repeated `InvalidParameterException` for `create_gateway`.

**Cause:** IAM propagation is taking longer than expected (rare in us-east-1).

**Fix:** The retry loop will handle this automatically for up to 5 attempts
(~2.5 minutes). If it still fails, re-deploy — the retry loop starts fresh.

### S3 bucket already exists on first deploy

**Symptom:** `ClimateRagDataStack` fails with `BucketAlreadyOwnedByYou`.

**Cause:** A bucket with the same name exists (from a previous manual setup).

**Fix:**
```bash
# Import the existing bucket into CDK state
cdk import ClimateRagDataStack
# Follow prompts to map the existing bucket to the IndexBucket logical ID
```

### Stacks deployed out of order

**Symptom:** `ClimateRagComputeStack` fails because `ClimateRagDataStack` does not exist.

**Fix:** Always deploy with `--all` or in the documented order:
```bash
cdk deploy ClimateRagDataStack
cdk deploy ClimateRagComputeStack
cdk deploy ClimateRagAgentCoreStack
```
