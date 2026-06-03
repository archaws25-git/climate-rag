# ClimateRAG — Testing Documentation

**Date:** 2026-06-03 | **Version:** 1.0

---

## 1. Overview

ClimateRAG uses a two-tier testing strategy:

| Tier | Location | AWS Required | Run Command |
|---|---|---|---|
| **Unit Tests** | `tests/unit/` | No (all mocked) | `python -m pytest tests/unit` |
| **Integration Tests** | `tests/integration/` | Yes (real credentials) | `python -m pytest tests/integration -m integration` |

## 2. Test Suite Summary

### Unit Tests (71 tests — run offline)

| Module | Tests | Coverage | What it validates |
|---|---|---|---|
| `test_ingest_ghcn.py` | 16 | 74% | CSV parsing, chunking by station+decade, filtering, metadata |
| `test_build_index.py` | 5 | 60% | FAISS index construction, dimension, search correctness |
| `test_embeddings.py` | 5 | 72% | Titan embedding invocation, text truncation, field preservation |
| `test_rag_tool.py` | 3 | 96% | Vector search with mocked S3 download and Bedrock embedding |
| `test_chart_tool.py` | 5 | 95% | Code Interpreter invocation, PNG saving, error handling |
| `test_memory_tool.py` | 6 | 92% | Memory read/write via mocked AgentCore SDK |
| `test_lambda_handlers.py` | 8 | 100%/95% | NASA POWER and NOAA NCEI proxy handlers |
| `test_agent_main.py` | 8 | 83% | Request handling, session management, chart detection |
| `test_cdk_handler.py` | 9 | 67% | Custom resource on_event + is_complete for all 3 resource types |

### Integration Tests (10 tests — require AWS credentials)

| Class | Tests | What it validates |
|---|---|---|
| `TestSTSIdentity` | 1 | AWS credentials are valid |
| `TestS3Connectivity` | 3 | Bucket exists, FAISS index and metadata files present |
| `TestBedrockEmbeddings` | 2 | Titan Embeddings v2 model invocation, dimension consistency |
| `TestAgentCoreControlPlane` | 3 | List memories, code interpreters, and gateways |
| `TestSSMParameters` | 1 | SSM Parameter Store read access |

## 3. Coverage Report

```
Name                                                Stmts   Miss  Cover
---------------------------------------------------------------------------------
agent/main.py                                          48      8    83%
agent/tools/chart_tool.py                              41      2    95%
agent/tools/memory_tool.py                             24      2    92%
agent/tools/rag_tool.py                                46      2    96%
cdk/custom_resources/agentcore_handler/handler.py     139     14    90%
gateway/lambda_nasa_power/handler.py                   16      0   100%
gateway/lambda_noaa_ncei/handler.py                    21      1    95%
ingest/build_index.py                                  52      2    96%
ingest/embeddings.py                                   39      2    95%
ingest/ingest_ghcn.py                                  66      1    98%
---------------------------------------------------------------------------------
TOTAL                                                 492     34    93%
```

**Overall: 93% coverage** (target: ≥ 80%)

**Critical path coverage (target: ≥ 90%):**
- RAG tool (vector search): 96%
- Chart tool (Code Interpreter): 95%
- Memory tool: 92%
- CDK custom resource handler: 90%
- Lambda handlers: 100% / 95%
- FAISS index build: 96%
- Embeddings: 95%
- GHCN ingestion: 98%

**Excluded from coverage** (not yet implemented):
- `ingest/ingest_gistemp.py`
- `ingest/ingest_power.py`

## 4. Running Tests

### Prerequisites

```powershell
# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install test dependencies
pip install pytest pytest-cov
```

### Run all unit tests (no AWS needed)

```powershell
python -m pytest tests/unit -v
```

### Run with coverage report

```powershell
python -m pytest tests/ -m "not integration" --cov=agent --cov=ingest --cov=gateway --cov=cdk/custom_resources --cov-report=term-missing
```

### Run integration tests (requires `aws sso login`)

```powershell
# Ensure credentials are active
aws sso login --profile YOUR_PROFILE
$env:AWS_PROFILE = "YOUR_PROFILE"
$env:CLIMATE_RAG_BUCKET = "climate-rag-index-YOUR_ACCOUNT_ID"

# Run integration tests only
python -m pytest tests/integration -m integration -v
```

### Run everything

```powershell
python -m pytest tests/ -v --cov=agent --cov=ingest --cov=gateway --cov=cdk/custom_resources
```

## 5. Test Architecture

### Mocking Strategy

Unit tests mock all AWS service calls at the boto3 client level:

- **S3:** `boto3.client("s3")` → mocked `download_file`, `head_bucket`, `upload_file`
- **Bedrock Runtime:** `boto3.client("bedrock-runtime")` → mocked `invoke_model`
- **AgentCore Control:** `boto3.client("bedrock-agentcore-control")` → mocked CRUD operations
- **AgentCore Runtime:** `boto3.client("bedrock-agentcore")` → mocked Code Interpreter sessions
- **Memory SDK:** `MemorySessionManager` → mocked at the session level

### Fixtures (conftest.py)

| Fixture | Purpose |
|---|---|
| `env_defaults` | Sets safe environment variables for all tests (autouse) |
| `sample_chunks` | 10 sample embedded chunks with random 1024-dim vectors |
| `sample_chunks_dir` | Writes sample chunks to a temp JSONL file for index tests |
| `ghcn_csv_sample` | Sample GHCN-format CSV text for parsing tests |

### Test Markers

| Marker | Purpose |
|---|---|
| `integration` | Tests that require real AWS credentials |

Deselect integration tests: `python -m pytest -m "not integration"`

## 6. Adding New Tests

Follow these patterns when adding tests for new functionality:

1. **New ingest module** — copy `test_ingest_ghcn.py` pattern; test parsing logic with sample data
2. **New agent tool** — mock the boto3 client; test success path, error path, and edge cases
3. **New CDK resource** — add to `test_cdk_handler.py`; test on_event Create/Delete and is_complete status transitions
4. **New Lambda handler** — add to `test_lambda_handlers.py`; mock `urllib.request.urlopen`

## 7. Security Analysis (Bandit)

The project uses [bandit](https://bandit.readthedocs.io/) for static security analysis.

### Running Bandit

```powershell
pip install bandit
bandit -r agent/ gateway/ ingest/ cdk/custom_resources/ -f txt
```

### Findings Summary (as of 2026-06-03)

| Severity | Count | Description |
|---|---|---|
| Medium | 7 | **B108** — Hardcoded `/tmp` directory as default for `CHUNK_OUTPUT_DIR` and `CHART_DIR` |
| Medium | 5 | **B310** — `urllib.request.urlopen` without explicit scheme restriction |
| Low | 1 | **B110** — `try/except/pass` in chart tool session cleanup |

### Assessment

| Finding | Risk | Justification |
|---|---|---|
| B108 (hardcoded /tmp) | **Acceptable** | These are env-var overridable defaults. In Lambda/AgentCore Runtime, `/tmp` is the only writable directory. Production deployments set `CHUNK_OUTPUT_DIR` and `CLIMATE_RAG_CHART_DIR` explicitly. |
| B310 (urllib.urlopen) | **Acceptable** | URLs are hardcoded constants (NASA/NOAA API endpoints), never user-supplied. No `file://` scheme possible. The Lambda handlers only call well-known HTTPS APIs. |
| B110 (try/except/pass) | **Acceptable** | This is a best-effort cleanup of Code Interpreter sessions in a `finally` block. Session leak is harmless — AgentCore auto-expires idle sessions. |

### Suppressing Known Acceptable Findings

If desired, add `# nosec B108` inline comments to suppress known-acceptable findings:
```python
CHART_DIR = os.environ.get("CLIMATE_RAG_CHART_DIR", "/tmp/climate-rag-charts")  # nosec B108
```

## 8. CI/CD Integration

Recommended pipeline steps:

```yaml
steps:
  - name: Unit Tests
    run: python -m pytest tests/unit -v --cov --cov-fail-under=80

  - name: Security Scan
    run: bandit -r agent/ gateway/ ingest/ cdk/custom_resources/ -f json -o bandit-report.json

  - name: Integration Tests (after deploy)
    run: python -m pytest tests/integration -m integration -v
    env:
      AWS_REGION: us-east-1
      CLIMATE_RAG_BUCKET: ${{ outputs.bucket_name }}
```

Unit tests and bandit should gate every PR. Integration tests should run post-deployment to validate infrastructure.
