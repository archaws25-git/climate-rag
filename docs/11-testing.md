# ClimateRAG — Testing & Evaluation Documentation

**Date:** 2026-06-11 | **Version:** 3.0

---

## 1. Overview

ClimateRAG uses a four-tier testing and evaluation strategy:

| Tier | Location | AWS Required | Run Command |
|---|---|---|---|
| **Unit Tests** | `tests/unit/` | No (all mocked) | `python -m pytest tests/unit -v` |
| **Integration Tests** | `tests/integration/` | Yes (Memory ID + credentials) | `python -m pytest tests/integration -m integration -v` |
| **Load/Stress Tests** | `tests/load/` | Yes (deployed infra) | `python -m pytest tests/load/ -v -s --timeout=300` |
| **Eval Suites** | `eval/` | Yes (Bedrock + FAISS) | `python eval/run.py` |

## 2. Test Suite Summary

### Unit Tests (243 tests — run offline, 78% coverage)

| Module | Tests | Coverage | What it validates |
|---|---|---|---|
| `test_rag_tool.py` | 23 | 87% | Hybrid search (Vector + BM25 + RRF), confidence scoring, citations, multi-entity |
| `test_history_reconstruction.py` | 17 | 84% | Memory reconstruction, EventMessage handling, role validation |
| `test_metadata_filter.py` | 20 | 96% | Temporal parsing, geo filter, haversine, city word-boundary, combined filters |
| `test_ingest_ghcn.py` | 16 | 99% | CSV parsing, chunking, 37 stations, 7 regions, precipitation, aliases |
| `test_chart_tool.py` | 6 | 90% | Sandbox guards (.merge rejection), error detection, CI not configured |
| `test_latency_tracker.py` | 14 | 100% | Timing, TTFT, token counting, percentiles, formatting |
| `test_tracing.py` | 6 | 65% | OTel spans, request lifecycle, timed_span context manager |
| `test_embeddings.py` | 5 | 95% | Titan embedding invocation, field preservation |
| `test_embeddings_full.py` | 2 | 95% | Main orchestration, missing file handling |
| `test_retrieval_metrics.py` | 16 | 100% | Recall@K, Precision@K, MRR, NDCG, is_relevant |
| `test_index_versioning.py` | 4 | 17% | Hash computation, S3 upload, version listing |
| `test_ingest_ghcn.py` (stations) | 4 | — | Station dict validation (37 stations, required fields, regions) |
| Other unit tests | ~110 | varies | Agent main, guardrails, cost tracker, BM25, reranker, query planner |

### Integration Tests (5 tests — requires live AgentCore Memory)

| Test | What it validates |
|---|---|
| `test_save_five_turns` | Saves 10 messages (5 pairs) to Memory |
| `test_reconstruct_five_turns` | Reconstructs valid Bedrock messages from Memory |
| `test_reconstructed_history_has_correct_content` | Content preserved through save/reconstruct cycle |
| `test_cross_session_isolation` | Different sessions don't leak data |
| `test_reconstruction_survives_empty_session` | Empty session returns [] gracefully |

### Load/Failover Tests (11 tests — requires AWS or mocks)

| Class | Tests | What it validates |
|---|---|---|
| `TestVectorDBFailover` | 3 | S3 connection failure, bucket not found, index missing |
| `TestEmbeddingModelFailover` | 2 | Throttling, model not ready |
| `TestRagSearchThroughput` | 3 | Single query latency, sequential QPS, burst throughput |
| `TestConcurrentThroughput` | 2 | 5-thread and 10-thread concurrent search |
| `TestFullAgentThroughput` | 1 | End-to-end agent request latency |

## 3. Evaluation Framework (Consolidated)

**Entry point:** `python eval/run.py`

| Suite | Command | Metrics | Duration |
|---|---|---|---|
| `retrieval` | `--suite retrieval` | Recall@K, Precision@K, MRR, NDCG | ~30s |
| `e2e` | `--suite e2e` | 6-dimension LLM-as-Judge (composite score) | ~5min |
| `multiturn` | `--suite multiturn` | Context resolution, coherence, progressive quality | ~8min |
| `latency` | `--suite latency` | E2E P50/P95/P99, per-query timing | ~2min |

### Eval Architecture

```
eval/
├── run.py              ← Unified entry point (replaces legacy scripts)
├── golden_dataset.py   ← All test data (10 retrieval + 10 E2E + 5 multiturn flows)
├── judge.py            ← Shared LLM-as-Judge (single-turn + multi-turn)
├── metrics.py          ← IR + generation + latency metrics
└── results/            ← JSON reports (timestamped)
```

### Current Scores (as of 2026-06-11)

| Metric | Score | Target |
|---|---|---|
| Retrieval Recall@K | 90% | 90% ✅ |
| Retrieval Precision@K | 77% | 90% |
| E2E Composite | 74% | 90% |
| Multi-turn Context Resolution | 4.5/5 | 4.0/5 ✅ |
| Multi-turn Coherence | 4.0/5 | 4.0/5 ✅ |
| Latency P50 | 12.5s | — |

### Running Evaluations

```bash
# All suites
python eval/run.py

# Individual suites
python eval/run.py --suite retrieval
python eval/run.py --suite e2e --id e2e_01 e2e_03
python eval/run.py --suite multiturn --id mt_01
python eval/run.py --suite latency

# With custom top-K
python eval/run.py --suite retrieval --top-k 10
```

### Eval Dashboard

A Streamlit page at `http://localhost:8501/eval_dashboard` displays:
- Metric cards with pass/fail indicators
- Per-query result tables
- Latency bar charts
- Historical trend lines across multiple eval runs

## 4. CI/CD Pipeline

**File:** `.github/workflows/ci.yml`

| Job | What it does |
|---|---|
| `lint` | Ruff check + format (sole linter, flake8 removed) |
| `type-check` | mypy with `--ignore-missing-imports` |
| `security` | Bandit scan (fails on HIGH severity) |
| `unit-tests` | All unit tests with 78% coverage threshold |
| `cdk-synth` | Validates CDK templates synthesize |

**Load tests:** `.github/workflows/load-tests.yml` (manual dispatch, requires AWS OIDC role)

## 5. Running Tests Locally

```bash
# Unit tests (no AWS, instant)
python -m pytest tests/unit -v

# Unit tests with coverage
python -m pytest tests/unit --cov=agent --cov=ingest --cov-fail-under=78

# Integration tests (requires AWS + Memory ID)
$env:CLIMATE_RAG_MEMORY_ID = "ClimateRAGMemory-tdkH1G52GJ"
$env:AWS_PROFILE = "AdministratorAccess-357312912554"
python -m pytest tests/integration -m integration -v

# Load tests (requires deployed infra)
$env:AWS_PROFILE = "AdministratorAccess-357312912554"
python -m pytest tests/load -v -s --timeout=300

# All tests (unit only, skip AWS-dependent)
python -m pytest tests/unit tests/load/test_failover.py -v
```

## 6. Key Testing Patterns

### Mocking boto3.Session (not boto3.client)

The project uses `boto3.Session(profile_name=...).client(...)` for all AWS calls. Tests must patch `boto3.Session`, not `boto3.client`:

```python
with patch("boto3.Session") as mock_session_cls:
    mock_client = MagicMock()
    mock_session_cls.return_value.client.return_value = mock_client
    # ... test code
```

### Resetting RAG module state

The FAISS index and BM25 are cached as module globals. Tests must reset them:

```python
rag_module._index = None
rag_module._metadata = None
rag_module._bm25_index = None
rag_module._bm25_corpus_tokens = None
```

### Integration test conftest

`tests/integration/conftest.py` overrides the root `env_defaults` fixture to preserve real AWS env vars instead of replacing them with test values.
