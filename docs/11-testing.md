# ClimateRAG — Testing & Evaluation Documentation

**Date:** 2026-06-06 | **Version:** 2.0

---

## 1. Overview

ClimateRAG uses a four-tier testing and evaluation strategy:

| Tier | Location | AWS Required | Run Command |
|---|---|---|---|
| **Unit Tests** | `tests/unit/` | No (all mocked) | `python -m pytest tests/unit` |
| **Integration Tests** | `tests/integration/` | Yes (credentials) | `python -m pytest tests/integration -m integration` |
| **Load/Stress Tests** | `tests/load/` | Partial (failover=mocked, throughput=AWS) | `python -m pytest tests/load/` |
| **Eval Scripts** | `eval/` | Yes (Bedrock + FAISS) | `python eval/run_retrieval_eval.py` / `python eval/run_eval.py` |

## 2. Test Suite Summary

### Unit Tests (136+ tests — run offline)

| Module | Tests | Coverage | What it validates |
|---|---|---|---|
| `test_ingest_ghcn.py` | 20 | 99% | CSV parsing, chunking, 37 stations, all 7 regions, warming rates |
| `test_build_index.py` | 8 | 96% | FAISS construction, save/upload, main orchestration |
| `test_build_index_full.py` | 4 | 96% | S3 upload, index readability |
| `test_embeddings.py` | 5 | 95% | Titan embedding invocation, text truncation, field preservation |
| `test_embeddings_full.py` | 2 | 95% | Main orchestration, missing file handling |
| `test_rag_tool.py` | 14 | 93% | Vector search, confidence scoring, citations, multi-entity |
| `test_chart_tool.py` | 5 | 95% | Code Interpreter invocation, PNG saving, error handling |
| `test_memory_tool.py` | 6 | 92% | Memory read/write via mocked AgentCore SDK |
| `test_guardrails.py` | 7 | 88% | Input/output guardrails, fail-open behavior |
| `test_lambda_handlers.py` | 8 | 100%/95% | NASA POWER and NOAA NCEI proxy handlers |
| `test_agent_main.py` | 8 | 76% | Request handling, session management, chart detection |
| `test_cdk_handler.py` | 12 | 75% | Custom resource on_event + is_complete |
| `test_cdk_handler_full.py` | 14 | 75% | Edge cases, unsupported types, gateway update/delete |
| `test_retrieval_metrics.py` | 19 | N/A | Recall@K, Precision@K, MRR, NDCG correctness |
| `test_ingest_ghcn_full.py` | 4 | 99% | Download, fallback, main orchestration |

### Load/Stress Tests (18 tests)

| Module | Tests | What it validates |
|---|---|---|
| `test_throughput.py` | 7 | QPS benchmarks, concurrency, agent latency |
| `test_failover.py` | 11 | Graceful degradation when S3/Bedrock/Guardrails/LLM unavailable |

### Integration Tests (10 tests — require AWS)

| Class | Tests | What it validates |
|---|---|---|
| `TestSTSIdentity` | 1 | AWS credentials are valid |
| `TestS3Connectivity` | 3 | Bucket exists, FAISS index present |
| `TestBedrockEmbeddings` | 2 | Titan v2 model invocation |
| `TestAgentCoreControlPlane` | 3 | List memories, code interpreters, gateways |
| `TestSSMParameters` | 1 | SSM Parameter Store read access |

## 3. Evaluation Scripts

### Retrieval Evaluation (`eval/run_retrieval_eval.py`)

Measures retrieval quality independent of LLM generation.

**Metrics and thresholds (all at 90%):**

| Metric | Threshold | What it measures |
|---|---|---|
| Recall@K | 90% | Fraction of expected relevant items found in top-K |
| Precision@K | 90% | Fraction of top-K results that are relevant |
| MRR | 0.9 | Reciprocal rank of first relevant result |
| NDCG@K | 0.9 | Normalized ranking quality (0-1 scale) |

**Key features:**
- Uses LOCAL FAISS index (bypasses potentially stale S3)
- Resets module-level index cache before each run
- Multi-entity query support (comparison queries search separately per entity)
- Per-query `top_k_override` for queries with limited relevant documents
- 10 ground truth queries covering all 3 datasets and 7 regions

**Run:** `python eval/run_retrieval_eval.py`

### LLM-as-Judge Evaluation (`eval/run_eval.py`)

End-to-end quality assessment using Claude Sonnet as judge.

**Dimensions scored (1-5 each, threshold 4.5):**

| Dimension | Weight | What it measures |
|---|---|---|
| Correctness | 30% | Factual accuracy vs. known climate science |
| Relevance | 20% | Does the answer address the question? |
| Source attribution | 20% | Inline [SOURCE: Dataset \| Station \| Period] citations |
| Confidence appropriate | 15% | Proper uncertainty expression |
| Citation | 10% | Dataset name referenced correctly |
| Tool use | 5% | Correct tools called |

**Composite threshold:** 0.9

**Key features:**
- Disables memory during eval (non-critical, avoids token expiry issues)
- Captures actual tool calls from agent for accurate tool_use scoring
- 15 benchmark queries covering all regions, datasets, comparisons
- Saves results to `eval/results/` with timestamps

**Run:** `python eval/run_eval.py`

### Keyword Evaluation (`eval/run_keyword_eval.py`)

Simple legacy scorer. Deprecated in favor of `run_eval.py`.

## 4. Data Ingestion Pipeline

### Cleanup Script (`ingest/cleanup.py`)

**MUST be run before re-ingestion when chunk text format changes.**

Removes:
1. `CHUNK_OUTPUT_DIR/embedded/` (old Titan v2 embeddings)
2. `CHUNK_OUTPUT_DIR/index/` (old local FAISS index)
3. `CHUNK_OUTPUT_DIR/*.jsonl` (old raw chunk files)
4. `s3://{CLIMATE_RAG_BUCKET}/index/` (stale S3 index)

### Full Pipeline (`ingest/ingest_all.py`)

Single command that:
1. Calls `cleanup.py` automatically
2. Ingests GHCN v4 (37 stations, region-forward chunk text with synonyms)
3. Ingests GISTEMP v4 (global anomalies with "warmest decade" annotations)
4. Ingests NASA POWER (6 regions, precipitation/solar/temperature)
5. Generates Titan v2 embeddings for all chunks
6. Verifies all embedded files were generated (exits on failure)
7. Builds FAISS IndexFlatIP and uploads to S3
8. Prints verification of final index content

**Run:** `python ingest/ingest_all.py`

## 5. Configuration

### Environment Variables (`.env` + `config.py`)

All scripts use `config.py` which:
1. Loads `.env` file from project root
2. Auto-detects AWS profile from `aws configure list-profiles`
3. Sets `AWS_PROFILE` for boto3 Session usage
4. Reads missing values from SSM Parameter Store
5. Resolves `CLIMATE_RAG_BUCKET` from CloudFormation stack output

**Key env vars:**

| Variable | Source | Purpose |
|---|---|---|
| `AWS_PROFILE` | `.env` or auto-detected | SSO profile for boto3 |
| `AWS_REGION` | `.env` (default: us-east-1) | AWS region |
| `CLIMATE_RAG_BUCKET` | CloudFormation / SSM | S3 bucket for FAISS index |
| `CLIMATE_RAG_MEMORY_ID` | SSM | AgentCore Memory ID |
| `CLIMATE_RAG_CODE_INTERPRETER_ID` | SSM | AgentCore Code Interpreter ID |
| `CHUNK_OUTPUT_DIR` | `.env` | Local chunk/embedding/index output |

### Profile-Aware boto3 Sessions

All scripts that call AWS use profile-aware sessions:
```python
profile = os.environ.get("AWS_PROFILE")
session = boto3.Session(profile_name=profile, region_name=REGION)
client = session.client("service-name")
```

Files updated: `embeddings.py`, `build_index.py`, `rag_tool.py`, `cleanup.py`, `config.py`

## 6. Architecture Decisions

### Multi-Entity Search (`rag_tool.py`)

For queries comparing two locations ("Compare NY and LA"):
- Detects comparison patterns: "compare", "between X and Y", "vs"
- Splits into two sub-queries, one per entity
- Searches each with `top_k=5` independently
- Merges, deduplicates, and ranks by score
- Returns top-K combined results ensuring both entities are represented

### Confidence Scoring

FAISS cosine similarity mapped to confidence levels:
- **HIGH** (≥ 0.75): Direct confident answer
- **MEDIUM** (≥ 0.55): Present with partial-data caveat
- **LOW** (≥ 0.40): Strong uncertainty hedging
- **INSUFFICIENT** (< 0.40): "I don't know" fallback

### Memory Resilience

Memory (`save_turn`) is wrapped in try/except in `main.py`:
- If memory fails (expired token, service down), the request still completes
- Warning is printed but never crashes the agent
- Eval scripts explicitly disable memory to avoid token issues

### Chunk Text Design (Embedding Optimization)

GHCN chunks lead with:
```
Southeast (US Southeast, Southeastern US) United States climate data:
Atlanta Hartsfield, GA temperature records.
City: Atlanta, GA. This is NOAA GHCN v4 monthly temperature data for
Atlanta in the US Southeast region.
```

This ensures:
- Region synonyms match diverse query phrasings
- City name appears prominently for city-specific queries
- Region is repeated at the end for embedding weight

### Synthetic Data Calibration

When live APIs are unavailable:
- **GHCN**: Region-specific warming rates (Alaska 0.015°C/yr, Hawaii 0.004°C/yr — Arctic amplification)
- **GISTEMP**: Verified decadal anomalies from NASA GISS published data
- **NASA POWER**: Temperatures from NOAA Climate Normals, solar from NREL NSRDB

## 7. Security

### Bandit Scan Results

**0 High, 0 Medium severity issues.**

All findings resolved:
- B108 (hardcoded /tmp): Replaced with `tempfile.gettempdir()`
- B310 (urlopen): Suppressed with `# nosec B310` (hardcoded HTTPS constants)

### Bedrock Guardrails

Production guardrail covers:
- Content filters (hate, violence, sexual, misconduct, prompt attacks)
- Topic policy (blocks political/medical/financial/illegal queries)
- PII protection (anonymize email/phone, block SSN/credit cards/AWS keys)
- Contextual grounding (hallucination detection, relevance check)
- Profanity filter

Guardrails fail-open: if the service is unavailable, requests proceed.

## 8. CI/CD Integration

```yaml
steps:
  - name: Lint (ruff)
    run: ruff check agent/ gateway/ ingest/ cdk/custom_resources/

  - name: Unit Tests
    run: python -m pytest tests/unit -v --cov --cov-fail-under=80

  - name: Security Scan (bandit)
    run: bandit -r agent/ gateway/ ingest/ cdk/custom_resources/ --severity-level high

  - name: Integration Tests (post-deploy)
    run: python -m pytest tests/integration -m integration -v

  - name: Retrieval Eval (post-ingest)
    run: python eval/run_retrieval_eval.py
```

## 9. Running Tests

```powershell
# Unit tests (no AWS needed)
python -m pytest tests/unit -v

# Unit tests with coverage
python -m pytest tests/unit --cov=agent --cov=ingest --cov=gateway --cov=cdk/custom_resources --cov-report=term-missing

# Load tests - failover (mocked, no AWS)
python -m pytest tests/load/test_failover.py -v

# Load tests - throughput (requires AWS)
python -m pytest tests/load/test_throughput.py -v -s --timeout=300

# Integration tests (requires AWS)
python -m pytest tests/integration -m integration -v

# Retrieval eval
python eval/run_retrieval_eval.py

# Full LLM-as-Judge eval
python eval/run_eval.py

# Single query eval
python eval/run_eval.py --id eval_01 eval_03
```

## 10. Full Rebuild Sequence

When chunk text format or ingestion logic changes:

```powershell
aws sso login
python ingest/cleanup.py          # Clear local + S3 stale data
python ingest/ingest_all.py       # Rebuild everything
python eval/run_retrieval_eval.py # Verify retrieval quality
python eval/run_eval.py           # Verify end-to-end quality
```
