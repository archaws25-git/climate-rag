# ClimateRAG

Production-grade RAG pipeline for historical climate trend analysis, built on Amazon Bedrock AgentCore.

Step-by-step instructions to deploy and run the ClimateRAG system from scratch.

---

## Prerequisites

- **Windows 10/11** with PowerShell
- **Python 3.12+** installed
- **Node.js 18+** installed (for CDK CLI)
- **AWS Account** with Bedrock model access enabled (Claude Sonnet + Titan Embeddings v2)
- **AWS SSO** configured (`aws configure sso` already done)

---

## Step 1: AWS Credentials Setup

```powershell
# 1a. Find your SSO profile name
aws configure list-profiles
# Example output: YOUR_AWS_PROFILE

# 1b. Log in via SSO (MUST include --profile)
aws sso login --profile YOUR_AWS_PROFILE

# 1c. Verify credentials work
aws sts get-caller-identity --profile YOUR_AWS_PROFILE

# 1d. Set profile for current PowerShell session
#     This is REQUIRED — .env only works inside Python scripts, not the terminal.
#     You MUST set this BEFORE running any Python script or AWS CLI command.
$env:AWS_PROFILE = "YOUR_AWS_PROFILE"
$env:AWS_REGION = "us-east-1"

# 1e. (Optional) Set permanently so you never have to type it again:
[System.Environment]::SetEnvironmentVariable("AWS_PROFILE", "YOUR_AWS_PROFILE", "User")
# Then restart your terminal.
```

> **IMPORTANT:** The `.env` file sets `AWS_PROFILE` for Python scripts only.
> Your PowerShell terminal does NOT read `.env`. You MUST set `$env:AWS_PROFILE`
> in your terminal before running `aws sso login`, `python ingest/ingest_all.py`,
> `streamlit run`, or any other command that touches AWS.

---

## Step 2: Python Virtual Environment

```powershell
# 2a. Navigate to project directory
cd C:\Users\archs\Downloads\workshop-Kiro\climate-rag

# 2b. Create virtual environment (if not exists)
python -m venv .venv

# 2c. Activate it
.venv\Scripts\Activate.ps1

# 2d. Install all dependencies
pip install -r requirements.txt

# 2e. Verify installation
python -c "import boto3, faiss, strands; print('All dependencies OK')"
```

---

## Step 3: Configure Environment (.env)

The `.env` file is auto-loaded by all scripts via `config.py`.

```powershell
# 3a. Copy the example file (if .env doesn't exist)
Copy-Item .env.example .env

# 3b. Edit .env — set your AWS profile:
#     AWS_PROFILE=YOUR_PROFILE
#     (Leave CLIMATE_RAG_BUCKET empty — it's auto-resolved from CloudFormation)
```

---

## Step 4: Deploy Infrastructure (CDK)

```powershell
# 4a. Install CDK CLI (one-time)
npm install -g aws-cdk

# 4b. Bootstrap CDK (one-time per account/region)
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-east-1

# 4c. Deploy Data + Compute stacks
cd cdk
cdk deploy ClimateRagDataStack ClimateRagComputeStack --require-approval never

# 4d. Go back to project root
cd ..
```

---

## Step 5: Provision AgentCore Resources

The AgentCore stack (Memory, Code Interpreter, Gateway) is provisioned directly:

```powershell
python infra/provision_agentcore.py
```

This takes 10-20 minutes (Code Interpreter activation is slow).
Wait for the "Done!" message with all three resource IDs.

---

## Step 6: Ingest Climate Data

> **PREREQUISITE:** `$env:AWS_PROFILE` MUST be set in your terminal.
> If not set, the S3 upload WILL fail silently or with a 403/expired token error.

```powershell
# Verify profile is set
echo $env:AWS_PROFILE
# Should print your profile name. If blank, set it:
# $env:AWS_PROFILE = "YOUR_AWS_PROFILE"

# Verify credentials are fresh
aws sts get-caller-identity

# 6a. Full pipeline (cleanup → ingest → embed → build index → upload to S3)
python ingest/ingest_all.py
```

This takes 5-10 minutes (embedding ~340 chunks via Bedrock Titan v2).
Wait for "✅ All files uploaded and verified in S3" confirmation.

If the upload step fails, the script will print the exact `aws s3 cp` command
to run manually as a fallback.

---

## Step 7: Set Up Guardrails

```powershell
python infra/setup_guardrails.py
```

---

## Step 8: Launch Streamlit UI

```powershell
streamlit run ui/app.py
```

Opens at **http://localhost:8501**. The sidebar shows config status (✅/❌) for Memory and Code Interpreter.

---

## Step 9: Verify with Evaluations

The consolidated eval runner supports multiple suites from a single entry point:

```powershell
# Run ALL suites (retrieval + e2e + multiturn + latency)
python eval/run.py

# Individual suites
python eval/run.py --suite retrieval      # Retrieval quality (fast, ~30s, no LLM)
python eval/run.py --suite e2e            # End-to-end LLM-as-Judge (~5 min)
python eval/run.py --suite multiturn      # Multi-turn conversation flows (~8 min)
python eval/run.py --suite latency        # Performance P50/P95/P99 (~2 min)

# Multiple suites
python eval/run.py --suite retrieval latency

# Specific queries/flows
python eval/run.py --suite e2e --id e2e_01 e2e_03
python eval/run.py --suite multiturn --id mt_01

# Adjust retrieval top-K
python eval/run.py --suite retrieval --top-k 10
```

Results are saved to `eval/results/eval_{timestamp}.json` as a unified report containing all suite results, summaries, and pass/fail status.

**Eval Architecture:**
| File | Purpose |
|---|---|
| `eval/run.py` | Unified entry point (replaces legacy scripts) |
| `eval/golden_dataset.py` | All test data — retrieval ground truth, E2E benchmarks, multi-turn flows |
| `eval/judge.py` | Shared LLM-as-Judge (single-turn + multi-turn scoring) |
| `eval/metrics.py` | All metric computations (IR + generation + latency percentiles) |

**Metrics measured:**
- **Retrieval:** Recall@K, Precision@K, MRR, NDCG@K (thresholds: 90%)
- **E2E:** Correctness, relevance, tool_use, citation, confidence, source_attribution (composite ≥ 90%)
- **Multi-turn:** Context resolution, session coherence, progressive quality (threshold: 4.0/5)
- **Latency:** E2E P50/P95/P99, per-query timing

---

## Step 10: Run Tests

```powershell
# Unit tests (no AWS needed, instant)
python -m pytest tests/unit -v

# Specific test suites
python -m pytest tests/unit/test_rag_tool.py -v        # Hybrid search (BM25 + Vector + RRF)
python -m pytest tests/unit/test_history_reconstruction.py -v  # Memory reconstruction

# Integration tests (requires AWS credentials + AgentCore Memory)
$env:CLIMATE_RAG_MEMORY_ID = "YOUR_MEMORY_ID"
python -m pytest tests/integration -m integration -v

# Load/failover tests (requires AWS)
python -m pytest tests/load/test_failover.py -v
python -m pytest tests/load/test_throughput.py -v -s --timeout=300
```

**Test coverage:**
| Suite | Tests | What it validates |
|---|---|---|
| `tests/unit/test_rag_tool.py` | 23 | Hybrid search, BM25, RRF fusion, confidence scoring |
| `tests/unit/test_history_reconstruction.py` | 17 | Memory reconstruction, EventMessage handling, validation |
| `tests/integration/test_history_reconstruction_integration.py` | 5 | 5-turn persistence + recall via live AgentCore Memory |
| `tests/integration/test_memory_integration.py` | 3 | Memory save/recall + semantic search |
| `tests/load/test_throughput.py` | 6 | QPS benchmarks (RAG, embedding, full agent) |
| `tests/load/test_failover.py` | 5 | LLM timeout, throttling, model unavailable handling |

---

## Credential Refresh

AWS SSO tokens expire every 8-12 hours. When you see `ExpiredTokenException`:

```powershell
# MUST include --profile
aws sso login --profile YOUR_AWS_PROFILE

# Verify it worked
aws sts get-caller-identity

# Then re-run whatever command failed
```

If you get "Missing sso_start_url" when running `aws sso login` without `--profile`,
it means your default profile isn't configured for SSO. Always use `--profile`.

---

## Full Rebuild (After Code Changes)

When chunk text format, ingestion logic, or embedding model changes:

```powershell
# FIRST: ensure credentials are fresh
$env:AWS_PROFILE = "YOUR_AWS_PROFILE"
aws sso login --profile YOUR_AWS_PROFILE
aws sts get-caller-identity

# THEN: rebuild
python ingest/cleanup.py          # Clears local + S3 stale data
python ingest/ingest_all.py       # Rebuilds everything (watch for ✅ on S3 upload)
python eval/run.py --suite retrieval  # Verify retrieval quality
python eval/run.py --suite latency    # Check performance regression
streamlit run ui/app.py           # Restart UI
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `ExpiredTokenException` | Run `aws sso login --profile YOUR_AWS_PROFILE` |
| `NoCredentialsError` | Set `$env:AWS_PROFILE = "YOUR_AWS_PROFILE"` in terminal |
| `Missing sso_start_url` | Use `aws sso login --profile YOUR_AWS_PROFILE` (include --profile) |
| `ParameterNotFound` for SSM | Run `python infra/provision_agentcore.py` |
| Memory: ❌ in Streamlit sidebar | SSM params not written — re-run provision script |
| `ModuleNotFoundError: No module named 'strands'` | Activate venv: `.venv\Scripts\Activate.ps1` |
| Retrieval eval 0% recall on Southeast | Run `python ingest/cleanup.py && python ingest/ingest_all.py` |
| Code Interpreter timeout (CDK) | Use `python infra/provision_agentcore.py` instead |
| S3 403 Forbidden | `$env:AWS_PROFILE` not set in terminal — set it |
| S3 404 Not Found (vector store unavailable) | S3 index missing — run `python ingest/ingest_all.py` |
| `AccessDenied` on PutObject | Expired token — `aws sso login --profile YOUR_AWS_PROFILE` then retry |
| Gateway teardown ConflictException | Targets still deleting — script now auto-waits up to 60s; if it times out, re-run `--teardown` |

---

## Project Structure (Key Files)

```
climate-rag/
├── .env                      ← Your local config (never committed)
├── config.py                 ← Centralized config loader (loads .env + SSM)
├── agent/
│   ├── main.py               ← Agent entry point (handle_request + streaming)
│   ├── tracing.py            ← OpenTelemetry tracing with in-memory span collector
│   ├── latency_tracker.py    ← Per-request latency tracking for UI
│   ├── tools/
│   │   ├── rag_tool.py       ← Hybrid search (FAISS + BM25 + RRF fusion)
│   │   ├── chart_tool.py     ← Code Interpreter charts (with sandbox guards)
│   │   ├── memory_tool.py    ← AgentCore Memory (save/recall turns)
│   │   └── history_reconstruction.py ← Rebuild Bedrock messages from Memory
│   └── prompts/
│       └── system_prompt.txt  ← Agent persona + rules
├── ingest/
│   ├── cleanup.py            ← Delete old data (local + S3)
│   ├── ingest_all.py         ← Full pipeline (single command)
│   ├── ingest_ghcn.py        ← 37 US stations (with city aliases for BM25)
│   ├── ingest_gistemp.py     ← Global anomalies
│   ├── ingest_power.py       ← NASA POWER (6 regions)
│   ├── embeddings.py         ← Titan v2 embedding generation
│   └── build_index.py        ← FAISS IndexFlatIP builder
├── eval/
│   ├── run.py                ← Unified eval runner (all suites)
│   ├── golden_dataset.py     ← All test data (retrieval + E2E + multiturn)
│   ├── judge.py              ← Shared LLM-as-Judge module
│   ├── metrics.py            ← IR + generation + latency metrics
├── ui/
│   └── app.py                ← Streamlit chat (streaming + latency expander)
├── cdk/                      ← CDK stacks (Data + Compute + AgentCore)
├── infra/
│   ├── provision_agentcore.py ← Direct provisioning (--teardown supported)
│   └── setup_guardrails.py    ← Bedrock Guardrails setup
├── tests/
│   ├── unit/                 ← Unit tests (mocked, offline)
│   ├── integration/          ← AWS connectivity + Memory reconstruction
│   └── load/                 ← Throughput + failover benchmarks
├── .github/workflows/
│   ├── ci.yml                ← Lint + type-check + security + unit tests
│   └── load-tests.yml        ← Manual-dispatch load tests (requires AWS)
└── docs/                     ← Architecture, testing, changelog docs
```

## Documentation

See [docs](docs/) for full architecture and operations documentation.
