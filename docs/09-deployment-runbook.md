# ClimateRAG — Deployment & Operations Runbook

**Date:** 2026-03-26 | **Version:** 1.0

---

## 1. Deployment Architecture

```
us-east-1
├── AgentCore Runtime (microVM) — Strands Agent
├── AgentCore Memory — ClimateRAGMemory
├── AgentCore Gateway — ClimateDataGateway
│   ├── Lambda: nasa-power-proxy
│   └── Lambda: noaa-ncei-proxy
├── AgentCore Code Interpreter — ClimateChartInterpreter
├── S3: climate-rag-index-{account_id}
├── CloudWatch: traces, logs, eval results
└── Streamlit UI (local or ECS Fargate)
```

## 2. Deployment Steps

### 2.1 Infrastructure Setup

```bash
# 1. Create S3 bucket
aws s3 mb s3://climate-rag-index-$(aws sts get-caller-identity --query Account --output text) --region us-east-1

# 2. Setup AgentCore Memory
python infra/setup_memory.py

# 3. Setup AgentCore Gateway + Lambda targets
python infra/setup_gateway.py

# 4. Setup Code Interpreter
python infra/setup_code_interpreter.py

# 5. Enable observability
python infra/setup_observability.py
```

### 2.2 Data Ingestion

```bash
# 1. Ingest all datasets and build FAISS index
python ingest/ingest_gistemp.py
python ingest/ingest_ghcn.py
python ingest/ingest_power.py
python ingest/build_index.py

# 2. Verify index uploaded to S3
aws s3 ls s3://climate-rag-index-$(aws sts get-caller-identity --query Account --output text)/index/
```

### 2.3 Agent Deployment

```bash
# 1. Test locally
cd agent/
agentcore dev

# In another terminal:
agentcore invoke --dev '{"prompt": "What is the global temperature trend?"}'

# 2. Deploy to AgentCore Runtime
agentcore launch

# 3. Test deployed agent
agentcore invoke '{"prompt": "How has temperature changed in the US Southeast?"}'
```

### 2.4 UI Deployment

```bash
# Local
streamlit run ui/app.py

# Or ECS (production)
# Build Docker image, push to ECR, deploy to Fargate
```

## 3. Operations

### 3.1 Health Checks

| Check | Command | Expected |
|---|---|---|
| Agent reachable | `agentcore invoke '{"prompt": "ping"}'` | Response received |
| S3 index exists | `aws s3 ls s3://climate-rag-index-.../index/` | faiss.index + metadata.jsonl |
| Memory active | `agentcore memory list --region us-east-1` | ClimateRAGMemory listed |
| Gateway active | Check AWS console | ClimateDataGateway ACTIVE |
| CloudWatch traces | Check Transaction Search | Recent traces visible |

### 3.2 Troubleshooting

| Issue | Diagnosis | Fix |
|---|---|---|
| Agent timeout | Check CloudWatch logs | Increase timeout in .bedrock_agentcore.yaml |
| No vector results | Check S3 index | Re-run build_index.py |
| Gateway tool failure | Check Lambda logs | Verify Lambda deployed, API endpoints up |
| Chart not rendering | Check Code Interpreter logs | Verify matplotlib installed in sandbox |
| Memory not persisting | Check Memory status | Verify memory ID in agent config |

### 3.3 Scaling

- AgentCore Runtime auto-scales based on invocations
- Lambda auto-scales (1000 concurrent default)
- S3 scales automatically
- For high load: consider Bedrock provisioned throughput

## 4. Cleanup

```bash
# Stop agent
agentcore destroy

# Delete S3 data
aws s3 rb s3://climate-rag-index-{account_id} --force

# Delete Memory
agentcore memory delete ClimateRAGMemory --region us-east-1

# Delete Gateway (via console or API)
# Delete Lambda functions
# Delete CloudWatch log groups
```
