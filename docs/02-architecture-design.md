# ClimateRAG — Architecture Design Document

**Date:** 2026-03-26 | **Version:** 1.0 | **Status:** Draft

---

## 1. System Context

```
  Researcher → Streamlit UI → AgentCore Runtime (Strands Agent)
                                    │
                 ┌──────────┬───────┼────────┬──────────┐
                 ▼          ▼       ▼        ▼          ▼
              S3/FAISS   Memory  Gateway  CodeInterp  CloudWatch
                                   │
                            ┌──────┴──────┐
                            ▼             ▼
                         Lambda        Lambda
                        (NASA API)   (NOAA API)
```

## 2. AgentCore Services

| Service | Role |
|---|---|
| Runtime | Hosts Strands Agent in serverless microVM |
| Memory | Short-term (session turns) + long-term (semantic: preferences, findings) |
| Gateway | Exposes NASA POWER + NOAA NCEI as MCP tools; semantic search enabled |
| Identity | Workload identity for Gateway; IAM auth for Streamlit→AgentCore |
| Code Interpreter | Sandboxed Python for matplotlib/plotly chart generation |
| Browser | (Stretch) Navigate GISTEMP downloads page for latest data |
| Observability | OTEL traces → CloudWatch Transaction Search |
| Evaluations | On-demand: correctness, tool accuracy, relevance via LLM-as-Judge |
| Policy | Cedar policies on Gateway: read-only, approved endpoints only |

## 3. RAG Pipeline

```
Query → Agent decides: vector search OR live API OR both
  → FAISS retrieval (S3-hosted index, Titan v2 embeddings)
  → Gateway MCP tool call (live NASA/NOAA data)
  → Context assembly + Memory context
  → Claude Sonnet generates answer with citations
  → Code Interpreter generates chart if needed
  → Memory records turn + extracts insights
  → OTEL trace emitted
```

## 4. Vector Store

- Engine: FAISS (IndexFlatIP, cosine similarity)
- Embeddings: Amazon Titan Embeddings v2 (1024 dimensions)
- Storage: S3 bucket, loaded into agent memory at startup
- Chunk size: ~500 tokens per chunk

| Dataset | Chunk Granularity | Metadata |
|---|---|---|
| GISTEMP v4 | Per decade + latitude band | source, decade, lat_band, anomaly_range |
| GHCN v4 | Per station + decade | source, station_id, name, state, lat, lon, decade |
| NASA POWER | Per region + year | source, region, year, parameters |

## 5. Gateway Configuration

- Name: `ClimateDataGateway`
- Semantic search: enabled
- Targets: Lambda proxies for NASA POWER API and NOAA NCEI API
- Policy: Cedar — allow GET only, deny POST/PUT/DELETE/PATCH

## 6. Memory Configuration

- Name: `ClimateRAGMemory`
- Strategy: Semantic (extracts researcher preferences, key findings)
- Namespace: `/strategies/{memoryStrategyId}/actors/{actorId}/`

## 7. Observability

Every invocation produces OTEL spans for:
- user_query, vector_retrieval, gateway_tool_call, llm_invocation, code_interpreter, memory_write
- CloudWatch dashboard: latency, error rate, token usage, tool call frequency

## 8. Evaluations

| Metric | Target |
|---|---|
| Correctness | ≥ 80% |
| Tool Invocation Accuracy | ≥ 90% |
| Answer Relevance | ≥ 85% |
| Citation Accuracy | ≥ 80% |

Method: on-demand via `agentcore evaluate`, LLM-as-Judge (Claude Sonnet), 20 benchmark queries.

## 9. Security

| Layer | Mechanism |
|---|---|
| Streamlit → AgentCore | IAM SigV4 via boto3 |
| AgentCore → Bedrock | IAM role on Runtime |
| AgentCore → S3 | Scoped IAM read permissions |
| Gateway → Lambda | IAM invocation role |
| Lambda → External APIs | HTTPS TLS 1.2+ (public APIs, no creds) |
| Policy | Cedar deny-by-default on Gateway |
| Data at rest | S3 SSE-S3, CloudWatch encryption |
| Agent isolation | microVM per session |
