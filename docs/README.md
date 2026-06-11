# ClimateRAG

Production-grade RAG pipeline for historical climate trend analysis, built on Amazon Bedrock AgentCore.

## Quick Start

See `DEPLOYMENT.md` in the project root for complete step-by-step deployment instructions.

```bash
# TL;DR (after AWS credentials are configured):
pip install -r requirements.txt
python infra/provision_agentcore.py    # AgentCore resources (~15 min)
python ingest/ingest_all.py            # Data pipeline (~5 min)
streamlit run ui/app.py                # Launch UI
```

## Architecture

```
User Query → Streamlit (streaming)
    → Strands Agent (Claude Sonnet 4)
        → Hybrid Search (FAISS + BM25 + RRF + metadata filtering)
        → AgentCore Code Interpreter (charts)
        → AgentCore Memory (multi-session)
    → Token-by-token streaming response
```

## Key Features

- **Hybrid search**: FAISS vector + BM25 keyword + Reciprocal Rank Fusion
- **Metadata pre-filtering**: Temporal (decade range) + geographic (50-mile radius or region)
- **3 climate datasets**: NOAA GHCN v4 (37 stations, temp + precip), NASA GISTEMP v4 (global anomalies), NASA POWER (solar radiation)
- **Token streaming**: Real-time response via Bedrock ConverseStream
- **Memory persistence**: Multi-turn conversations survive restarts via AgentCore Memory
- **Evaluation framework**: 4-suite eval (retrieval, E2E, multi-turn, latency)
- **Observability**: OpenTelemetry tracing + latency tracker with P50/P95/P99
- **Embedding cache**: LRU cache for repeated queries (saves ~500ms per cache hit)
- **Optional re-ranker**: Cross-encoder for precision improvement (opt-in via env var)

## Documentation

| Doc | Contents |
|---|---|
| `DEPLOYMENT.md` (root) | Step-by-step deployment guide |
| `01-requirements.md` | Functional/non-functional requirements |
| `02-architecture-design.md` | System architecture and component design |
| `03-architecture-decision-records.md` | ADRs (why FAISS, why RRF, why BM25, etc.) |
| `04-data-flow-integration.md` | Data pipeline and integration flows |
| `05-cost-analysis.md` | AWS cost breakdown and projections |
| `06-security-compliance.md` | Security posture and compliance |
| `07-observability-evaluation.md` | OTel tracing, latency metrics, eval suites |
| `10-dataset-reference.md` | Dataset schemas, stations, parameters |
| `11-cdk-infrastructure-guide.md` | CDK stack architecture |
| `11-testing.md` | Testing strategy (243 tests, 78% coverage) |
| `12-changelog.md` | Version history and change log |
| `presentation.md` | Marp-compatible slide deck for portfolio demos |

## Running Tests

```bash
python -m pytest tests/unit -v              # Unit tests (no AWS)
python eval/run.py --suite retrieval        # Retrieval quality (30s)
python eval/run.py                          # All eval suites
```

## Tech Stack

Python 3.13 | AWS Bedrock (Claude Sonnet + Titan Embeddings) | AgentCore (Memory, Code Interpreter, Gateway) | FAISS | BM25 | Streamlit | CDK | OpenTelemetry
