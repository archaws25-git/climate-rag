# ClimateRAG

Production-grade RAG pipeline for historical climate trend analysis, built on Amazon Bedrock AgentCore.

## Quick Start

Deployment is divided into four sequential phases. Each phase uses a different
tool — run them in order.

### Phase 1 — Infrastructure (CDK)

> Provisions S3, IAM, Lambda, and all AgentCore resources.
> Run once on first deploy; re-run only when AWS resources change.

```bash
# Install CDK CLI (one-time)
npm install -g aws-cdk

# Bootstrap CDK for your account/region (one-time)
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-east-1

# Set up CDK Python environment
cd cdk/
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Deploy all three stacks (~12 min on first run)
cdk deploy --all
```

### Phase 2 — Data Ingestion

> Builds the FAISS vector index from NOAA/NASA data and uploads it to S3.
> Run once; re-run only when source climate data changes.

```bash
cd ..   # back to repo root

# Source config from CDK outputs + SSM (no manual copy-paste)
export CLIMATE_RAG_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name ClimateRagDataStack \
  --query "Stacks[0].Outputs[?OutputKey=='IndexBucketName'].OutputValue" \
  --output text)
export CLIMATE_RAG_MEMORY_ID=$(aws ssm get-parameter \
  --name /climate-rag/memory-id --query Parameter.Value --output text)
export CLIMATE_RAG_CODE_INTERPRETER_ID=$(aws ssm get-parameter \
  --name /climate-rag/code-interpreter-id --query Parameter.Value --output text)
export AWS_REGION=us-east-1

# Set up agent Python environment
python3 -m venv .venv-agent && source .venv-agent/bin/activate
pip install -r agent/requirements.txt

# Run ingestion pipeline
python ingest/ingest_ghcn.py
python ingest/ingest_gistemp.py
python ingest/ingest_power.py
python ingest/embeddings.py
python ingest/build_index.py
```

### Phase 3 — Agent Deploy

> Deploys the Strands agent to AgentCore Runtime.
> Re-run whenever agent code or prompts change.

```bash
cd agent/

# Test locally first
agentcore dev
# In a second terminal: agentcore invoke --dev '{"prompt": "Global temperature trend?"}'

# Deploy to AgentCore Runtime
agentcore launch

# Verify
agentcore invoke '{"prompt": "How has temperature changed in the US Southeast?"}'
```

### Phase 4 — UI

> Re-run on every session or after agent changes.

```bash
# From repo root
streamlit run ui/app.py

# Evaluate answer quality
python eval/run_eval.py
```

---

## When to Re-run Each Phase

| Change made | Phase 1 (CDK) | Phase 2 (Ingest) | Phase 3 (agentcore) | Phase 4 (UI) |
|---|:---:|:---:|:---:|:---:|
| First-time setup | ✅ | ✅ | ✅ | ✅ |
| Agent code / prompts changed | — | — | ✅ | ✅ |
| Lambda proxy handler changed | ✅ ComputeStack only | — | — | — |
| AgentCore config changed | ✅ AgentCoreStack only | — | — | — |
| Monthly NOAA/NASA data refresh | — | ✅ | — | ✅ |
| S3 bucket config changed | ✅ DataStack only | — | — | — |

---

## AgentCore Services Used

| Service | Purpose |
|---|---|
| Runtime | Serverless agent hosting (microVM) |
| Memory | Multi-session researcher context |
| Gateway | NASA POWER + NOAA NCEI as MCP tools |
| Identity | Workload identity + IAM auth |
| Code Interpreter | Chart generation (matplotlib/plotly) |
| Observability | OTEL traces → CloudWatch |
| Evaluations | Answer quality assessment |
| Policy | Cedar policies on Gateway |

## Datasets

- NOAA GHCN v4 — US station monthly temperatures (1950–present)
- NASA GISTEMP v4 — Global surface temperature anomalies (1880–present)
- NASA POWER — Solar, temperature, precipitation (1981–present)

## Infrastructure

| Approach | Location | Status |
|---|---|---|
| CDK (Python) | `cdk/` | ✅ Active |
| Terraform | `terraform/` | ⚠️ Deprecated — replaced by CDK |
| Manual setup scripts | `infra/` | ⚠️ Reference only — superseded by CDK |

## Documentation

See [docs](docs/) for full architecture and operations documentation.
