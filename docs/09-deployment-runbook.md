# ClimateRAG — Deployment & Operations Runbook

**Date:** 2026-04-28 | **Version:** 2.0
**Supersedes:** Version 1.0 (2026-03-26) — Terraform + manual `infra/setup_*.py` scripts

---

## Overview: Two Toolchains, One Pipeline

ClimateRAG deployment is split across two distinct toolchains that must be
run in a specific order. Understanding which tool owns which concern is the
most important thing to get right before starting.

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1 — Infrastructure                                           │
│  Tool: AWS CDK  (cdk/)                                              │
│  Provisions: S3, IAM, Lambda, AgentCore Memory/CI/Gateway           │
│  Run: once on first deploy; re-run only when AWS resources change   │
├─────────────────────────────────────────────────────────────────────┤
│  PHASE 2 — Data Ingestion                                           │
│  Tool: Python scripts  (ingest/)                                    │
│  Provisions: FAISS vector index uploaded to S3                      │
│  Run: once on first deploy; re-run only when source data changes    │
├─────────────────────────────────────────────────────────────────────┤
│  PHASE 3 — Agent Deploy                                             │
│  Tool: agentcore CLI  (agent/)                                      │
│  Provisions: AgentCore Runtime (microVM hosting the Strands agent)  │
│  Run: on every agent code change                                    │
├─────────────────────────────────────────────────────────────────────┤
│  PHASE 4 — UI                                                       │
│  Tool: Streamlit  (ui/)                                             │
│  Run: on every session / after agent changes                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Scripts that are no longer used

The following scripts existed in the original deployment but are **superseded
by CDK** and should not be run for new deployments. They are kept as
reference only.

| Script | Superseded by |
|---|---|
| `infra/setup_memory.py` | `ClimateRagAgentCoreStack` (CDK) |
| `infra/setup_gateway.py` | `ClimateRagAgentCoreStack` (CDK) |
| `infra/setup_code_interpreter.py` | `ClimateRagAgentCoreStack` (CDK) |
| `infra/setup_observability.py` | CloudWatch dashboard in `ClimateRagAgentCoreStack` (CDK) |
| `infra/setup_all.py` | Entire CDK app |
| `terraform/` | Entire CDK app |

---

## 1. Deployment Architecture

```
us-east-1
│
├── [CDK: ClimateRagDataStack]
│   └── S3: climate-rag-index-{account_id}   ← FAISS index lives here
│
├── [CDK: ClimateRagComputeStack]
│   ├── IAM Role: climate-rag-lambda-role
│   ├── IAM Role: climate-rag-gateway-role
│   ├── Lambda: climate-rag-nasa-power
│   └── Lambda: climate-rag-noaa-ncei
│
├── [CDK: ClimateRagAgentCoreStack]
│   ├── AgentCore Memory — ClimateRAGMemory
│   ├── AgentCore Code Interpreter — ClimateChartInterpreter
│   ├── AgentCore Gateway — ClimateDataGateway
│   │   ├── Target: nasa-power-proxy → Lambda
│   │   └── Target: noaa-ncei-proxy  → Lambda
│   └── SSM Parameters: /climate-rag/{memory-id, code-interpreter-id, gateway-id}
│
├── [agentcore launch]
│   └── AgentCore Runtime (microVM) — Strands Agent
│
└── [streamlit run]
    └── Streamlit UI (local or ECS Fargate)
```

---

## 2. Prerequisites

Complete all of the following before starting Phase 1.

```bash
# Python 3.12+
python3 --version

# Node.js 18+ (CDK CLI is Node-based)
node --version

# AWS CDK CLI v2
npm install -g aws-cdk
cdk --version   # must be 2.170.0+

# AWS credentials configured
aws configure   # or export AWS_PROFILE / AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY

# Verify Bedrock model access in us-east-1:
#   - Claude Sonnet 4  (inference profile)
#   - Amazon Titan Embeddings v2
# Enable via: AWS Console → Bedrock → Model access → Request access

# CDK bootstrap (one-time per account/region — safe to re-run)
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-east-1
```

---

## 3. Phase 1 — Infrastructure (CDK)

> **CDK owns all AWS resource provisioning.** Do not run any `infra/setup_*.py`
> scripts for new deployments. Do not run `terraform apply`.

### 3.1 Set up the CDK Python environment

```bash
cd cdk/
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3.2 Preview what will be created

```bash
cdk diff --all
```

### 3.3 Deploy all three stacks

```bash
cdk deploy --all
```

Deployment proceeds in dependency order automatically:
`ClimateRagDataStack` → `ClimateRagComputeStack` → `ClimateRagAgentCoreStack`

Expected duration per stack:

| Stack | Typical duration | Notes |
|---|---|---|
| `ClimateRagDataStack` | ~1 min | S3 bucket + encryption config |
| `ClimateRagComputeStack` | ~2 min | IAM roles + Lambda packaging |
| `ClimateRagAgentCoreStack` | ~10–12 min | Custom resource Lambda polls until AgentCore Memory and Code Interpreter reach `ACTIVE` |

> **The ~12 minute wait on AgentCoreStack is normal.** CloudFormation is
> waiting for AgentCore Memory and Code Interpreter to finish provisioning.
> Monitor live progress in CloudWatch Logs:
> ```bash
> aws logs tail /aws/lambda/climate-rag-agentcore-cr --follow
> ```

### 3.4 Verify outputs

```bash
# All three stacks should show CREATE_COMPLETE
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?starts_with(StackName,'ClimateRag')].{Name:StackName,Status:StackStatus}" \
  --output table

# Confirm SSM parameters were written (used by the agent at runtime)
aws ssm get-parameter --name /climate-rag/memory-id --query Parameter.Value --output text
aws ssm get-parameter --name /climate-rag/code-interpreter-id --query Parameter.Value --output text
aws ssm get-parameter --name /climate-rag/gateway-id --query Parameter.Value --output text
```

---

## 4. Phase 2 — Data Ingestion

> **Ingestion scripts are independent of CDK.** They read the S3 bucket name
> and AgentCore IDs from environment variables (which can be sourced from CDK
> outputs or SSM). CDK must complete successfully before ingestion can run.

### 4.1 Set environment variables from CDK outputs

```bash
# S3 bucket (from CDK stack output)
export CLIMATE_RAG_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name ClimateRagDataStack \
  --query "Stacks[0].Outputs[?OutputKey=='IndexBucketName'].OutputValue" \
  --output text)

# AgentCore IDs (from SSM — written by CDK AgentCoreStack)
export CLIMATE_RAG_MEMORY_ID=$(aws ssm get-parameter \
  --name /climate-rag/memory-id --query Parameter.Value --output text)

export CLIMATE_RAG_CODE_INTERPRETER_ID=$(aws ssm get-parameter \
  --name /climate-rag/code-interpreter-id --query Parameter.Value --output text)

export AWS_REGION=us-east-1

# Verify
echo "Bucket:          $CLIMATE_RAG_BUCKET"
echo "Memory ID:       $CLIMATE_RAG_MEMORY_ID"
echo "Code Interp ID:  $CLIMATE_RAG_CODE_INTERPRETER_ID"
```

### 4.2 Set up the Python environment

```bash
cd ..   # back to repo root (if still in cdk/)
python3 -m venv .venv-agent
source .venv-agent/bin/activate
pip install -r agent/requirements.txt
```

### 4.3 Run the ingestion pipeline

Run these scripts in order. Each step depends on the output of the previous one.

```bash
# Step 1: Download + chunk NOAA GHCN v4 station data
python ingest/ingest_ghcn.py

# Step 2: Download + chunk NASA GISTEMP v4 global anomalies
python ingest/ingest_gistemp.py

# Step 3: Query + chunk NASA POWER regional data (makes live API calls)
#         Takes ~2 min due to rate limiting (2s sleep between 6 regions)
python ingest/ingest_power.py

# Step 4: Generate embeddings for all chunks via Bedrock Titan v2
#         Takes ~5 min; incurs Bedrock API costs (~$0.10 total)
python ingest/embeddings.py

# Step 5: Build FAISS index and upload to S3
python ingest/build_index.py
```

### 4.4 Verify the index was uploaded

```bash
aws s3 ls s3://${CLIMATE_RAG_BUCKET}/index/
# Expected output:
#   faiss.index    (~380 KB)
#   metadata.jsonl (~150 KB)
```

> **When to re-run ingestion:** Only when the source datasets change
> (GHCN/GISTEMP/POWER publish monthly updates) or when you change chunking
> strategy or the embedding model. The FAISS index in S3 persists indefinitely
> — even across CDK stack destroys and redeploys — because the S3 bucket has
> `RemovalPolicy.RETAIN`.

---

## 5. Phase 3 — Agent Deploy

> **The `agentcore` CLI deploys the Strands agent to AgentCore Runtime.**
> This is separate from CDK because the Runtime (the microVM that hosts the
> agent process) is managed by the `agentcore` CLI, not CloudFormation.
> CDK provisions the *supporting resources* the agent uses; `agentcore launch`
> deploys the *agent code itself*.

### 5.1 Test locally first

```bash
cd agent/

# Start the local dev server (runs the agent in a local process)
agentcore dev
```

In a second terminal:

```bash
cd agent/
agentcore invoke --dev '{"prompt": "What is the global temperature trend since 1950?"}'
```

Confirm you get a coherent response with citations before deploying.

### 5.2 Deploy to AgentCore Runtime

```bash
cd agent/

# Deploy the agent to the AgentCore Runtime (builds + pushes to CodeBuild/ECR)
agentcore launch
```

### 5.3 Test the deployed agent

```bash
agentcore invoke '{"prompt": "How has temperature changed in the US Southeast over 50 years?"}'
agentcore invoke '{"prompt": "Plot global temperature anomalies since 1980"}'
```

### 5.4 When to re-run `agentcore launch`

Re-run `agentcore launch` whenever any of the following change:

- `agent/main.py`
- `agent/tools/*.py`
- `agent/prompts/system_prompt.txt`
- `agent/requirements.txt`

Do **not** re-run `agentcore launch` when only AWS infrastructure changes
(CDK handles that), or when only the FAISS index changes (the agent loads
it lazily from S3 at query time).

---

## 6. Phase 4 — UI

```bash
# From repo root
streamlit run ui/app.py
```

For HTTPS (production / remote access):

```bash
# Nginx reverse proxy with self-signed cert (local demo)
sudo cp infra/nginx-climate-rag.conf /etc/nginx/sites-enabled/climate-rag
sudo systemctl restart nginx
# UI available at https://localhost
```

---

## 7. Health Checks

Run after a full deployment to confirm all components are working end-to-end.

```bash
# 1. CDK stacks all in a good state
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?starts_with(StackName,'ClimateRag')].{Name:StackName,Status:StackStatus}" \
  --output table

# 2. FAISS index present in S3
aws s3 ls s3://$(aws cloudformation describe-stacks \
  --stack-name ClimateRagDataStack \
  --query "Stacks[0].Outputs[?OutputKey=='IndexBucketName'].OutputValue" \
  --output text)/index/

# 3. AgentCore Memory active
aws bedrock-agentcore-control list-memories \
  --query "memorySummaries[?name=='ClimateRAGMemory'].{Name:name,Status:status}" \
  --output table

# 4. AgentCore Gateway active
aws bedrock-agentcore-control list-gateways \
  --query "gatewaySummaries[?name=='ClimateDataGateway'].{Name:name,Status:status}" \
  --output table

# 5. AgentCore Runtime reachable
agentcore invoke '{"prompt": "ping"}'

# 6. CloudWatch traces appearing
#    → CloudWatch → X-Ray traces → Transaction Search → filter by service=climate-rag
```

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ClimateRagAgentCoreStack` stuck >15 min | AgentCore ACTIVE wait longer than usual | Check `/aws/lambda/climate-rag-agentcore-cr` logs; re-deploy — handler is idempotent |
| `BucketAlreadyOwnedByYou` on first CDK deploy | Bucket exists from previous manual setup | `cdk import ClimateRagDataStack` to adopt it |
| `No index found` on first agent query | Ingestion not run yet | Complete Phase 2 |
| Agent returns `Code Interpreter not configured` | `CLIMATE_RAG_CODE_INTERPRETER_ID` env var missing | Read from SSM (see Phase 2 step 4.1) |
| Gateway tool calls fail | Lambda not deployed or ARN changed | Re-run `cdk deploy ClimateRagComputeStack` then `ClimateRagAgentCoreStack` |
| `ValidationException: Invocation of model ID` | Wrong Bedrock model ID format | Claude Sonnet 4 requires inference profile ID: `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| Streamlit chart not rendering | Code Interpreter session expired | Restart Streamlit; Code Interpreter sessions are ephemeral |

---

## 9. Re-deploy Scenarios

### "I changed the agent prompt / tool logic"

```bash
# Agent code only — no CDK, no ingestion needed
cd agent/
agentcore launch
```

### "I changed a Lambda proxy handler"

```bash
# Re-deploy compute stack to update Lambda code
cd cdk/
cdk deploy ClimateRagComputeStack
# No agent redeploy needed — Gateway picks up new Lambda code automatically
```

### "I want to update the AgentCore Memory strategy"

```bash
# Update the properties in cdk/stacks/agentcore_stack.py, then:
cd cdk/
cdk deploy ClimateRagAgentCoreStack
# CDK Update event triggers the custom resource Lambda, which reconciles the resource
```

### "Source climate data has been updated (monthly NOAA/NASA refresh)"

```bash
# Re-run ingestion only — no CDK or agent changes needed
source .venv-agent/bin/activate
python ingest/ingest_ghcn.py
python ingest/ingest_gistemp.py
python ingest/ingest_power.py
python ingest/embeddings.py
python ingest/build_index.py
# New index is live immediately — agent loads it lazily on next query
```

### "I need to rotate the FAISS index without downtime"

```bash
# Build new index to a staging prefix, then swap atomically
export CHUNK_OUTPUT_DIR=/tmp/climate-rag-chunks-new
python ingest/ingest_ghcn.py && python ingest/ingest_gistemp.py && \
  python ingest/ingest_power.py && python ingest/embeddings.py

# Upload to a staging prefix first
aws s3 sync /tmp/climate-rag-chunks-new/index/ \
  s3://${CLIMATE_RAG_BUCKET}/index-staging/

# Verify staging index looks correct, then promote
aws s3 sync s3://${CLIMATE_RAG_BUCKET}/index-staging/ \
  s3://${CLIMATE_RAG_BUCKET}/index/ --delete
# Agent's lazy-load cache will refresh on the next cold start / new session
```

### "I need to run the evaluation suite"

```bash
# Evaluation runs against the deployed agent — no changes needed
source .venv-agent/bin/activate
python eval/run_eval.py
# Results saved to /tmp/climate-rag-eval-results.json
```

---

## 10. Teardown

### Teardown AgentCore resources only (safe — S3 and Lambda untouched)

```bash
# Stop the agent Runtime first
agentcore destroy

# Tear down AgentCore stack (Memory, Code Interpreter, Gateway)
cd cdk/
cdk destroy ClimateRagAgentCoreStack
```

### Teardown compute resources (after AgentCore)

```bash
cd cdk/
cdk destroy ClimateRagAgentCoreStack   # if not already done
cdk destroy ClimateRagComputeStack
```

### Full teardown (everything, including FAISS index)

> ⚠️ **Irreversible.** Back up the FAISS index first if you may need it:
> ```bash
> aws s3 sync s3://climate-rag-index-$(aws sts get-caller-identity \
>   --query Account --output text)/index/ ./backup-index/
> ```

```bash
# Step 1: Stop the agent Runtime
agentcore destroy

# Step 2: Destroy CDK stacks in reverse dependency order
cd cdk/
cdk destroy ClimateRagAgentCoreStack
cdk destroy ClimateRagComputeStack

# Step 3: Empty the S3 bucket manually
#   (RemovalPolicy=RETAIN means CDK will NOT empty or delete the bucket)
aws s3 rb s3://climate-rag-index-$(aws sts get-caller-identity \
  --query Account --output text) --force

# Step 4: Destroy the DataStack (now that the bucket is empty/gone)
cdk destroy ClimateRagDataStack

# Step 5: Clean up resources not managed by CDK
#   CloudWatch log groups
aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore \
  --query "logGroups[].logGroupName" --output text | \
  tr '\t' '\n' | xargs -I{} aws logs delete-log-group --log-group-name {}

#   Cognito User Pool (auto-created by AgentCore Gateway; not CDK-managed)
#   Find: aws cognito-idp list-user-pools --max-results 10
#   Delete: aws cognito-idp delete-user-pool --user-pool-id <id>

# Step 6: Clean up local processes
pkill -f streamlit
sudo rm -f /etc/nginx/sites-enabled/climate-rag && sudo systemctl restart nginx
rm -rf /tmp/climate-rag-*
```

### Teardown order summary

```
agentcore destroy                        ← stop Runtime first
      ↓
cdk destroy ClimateRagAgentCoreStack     ← safe to destroy alone at any time
      ↓
cdk destroy ClimateRagComputeStack       ← requires AgentCore gone first
      ↓
aws s3 rb ... --force                    ← manual: RETAIN policy protects this bucket
      ↓
cdk destroy ClimateRagDataStack          ← bucket must be empty/deleted first
```
