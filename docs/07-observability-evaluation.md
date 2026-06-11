# ClimateRAG — Observability & Evaluation Specification

**Date:** 2026-06-11 | **Version:** 2.0

---

## 1. Observability Architecture

### 1.1 Trace Structure (OpenTelemetry)

Every agent invocation produces OTel spans via `agent/tracing.py`:

```
climate_rag.request (root)
├── climate_rag.memory.save_user_turn
├── climate_rag.history.reconstruct (if applicable)
├── climate_rag.history.sanitize
├── climate_rag.search.hybrid
│   ├── climate_rag.search.embed_query (Titan v2, ~500ms)
│   ├── climate_rag.search.faiss (~3ms)
│   └── climate_rag.search.bm25 (~2ms)
├── climate_rag.llm.stream (model generation)
└── climate_rag.memory.save_assistant_turn
```

### 1.2 Latency Tracking

The `agent/latency_tracker.py` module provides:
- Per-request E2E timing
- Time-to-First-Token (TTFT)
- Token chunk counting
- Session-level P50/P95/P99 percentile computation
- Streamlit inline latency expander

### 1.3 Exporters

Configured via `OTEL_EXPORTER` env var:
- `none` (default): In-memory span collection for Streamlit UI only
- `console`: Prints spans to terminal (debugging)
- `otlp`: Sends to OTLP collector (Jaeger, Grafana Tempo, X-Ray)
├── Span: memory_retrieval (short_term_turns, long_term_records)
├── Span: vector_retrieval (query_embedding_time, chunks_returned, relevance_scores)
├── Span: gateway_tool_call (tool_name, api_endpoint, latency, status_code)
├── Span: llm_invocation (model_id, input_tokens, output_tokens, latency)
├── Span: code_interpreter (code_snippet, execution_time, output_type)
└── Span: memory_write (events_written, insights_extracted)
```

### 1.2 Setup

1. Enable CloudWatch Transaction Search in us-east-1
2. AgentCore Runtime auto-instruments Strands Agent with OTEL
3. Custom spans added for RAG-specific operations (vector search, chart gen)

### 1.3 CloudWatch Dashboard Metrics

| Metric | Source | Alert Threshold |
|---|---|---|
| Agent invocation latency (p50, p95, p99) | OTEL traces | p99 > 30s |
| Error rate | OTEL traces | > 5% |
| Token usage per query | OTEL span attributes | > 10K input tokens |
| Tool call success rate | Gateway traces | < 95% |
| Chart generation success rate | Code Interpreter spans | < 90% |
| Memory write latency | Memory spans | > 5s |

### 1.4 Logging

- Agent logs: CloudWatch Logs (auto-configured by `agentcore launch`)
- Lambda logs: CloudWatch Logs (standard Lambda integration)
- Streamlit logs: stdout (local) or CloudWatch (ECS)

## 2. Evaluation Framework

### 2.1 Evaluation Method

- Type: On-demand evaluation via AgentCore Evaluations
- Judge: LLM-as-Judge (Claude Sonnet)
- Framework: Strands Agents (supported by AgentCore Evaluations)
- Instrumentation: OpenTelemetry traces from agent invocations

### 2.2 Evaluation Metrics

| Metric | Description | Target | Weight |
|---|---|---|---|
| Correctness | Does the answer match known climate data? | ≥ 80% | 30% |
| Tool Invocation Accuracy | Did the agent call the right tools? | ≥ 90% | 25% |
| Answer Relevance | Is the response relevant to the query? | ≥ 85% | 25% |
| Citation Accuracy | Are sources correctly attributed? | ≥ 80% | 20% |

### 2.3 Benchmark Test Set (20 queries)

| # | Query | Expected Tool | Expected Source |
|---|---|---|---|
| 1 | "Average temp change in US Southeast, last 50 years" | FAISS + GHCN | GHCN v4 |
| 2 | "Global temp anomaly in 2020" | FAISS + GISTEMP | GISTEMP v4 |
| 3 | "Compare coastal vs inland stations since 1950" | FAISS + GHCN | GHCN v4 |
| 4 | "Solar radiation trend in Arizona 2010-2020" | Gateway (NASA POWER) | NASA POWER |
| 5 | "Warmest decade for station USW00013874" | FAISS + GHCN | GHCN v4 |
| 6 | "Plot annual temp anomalies 1950-2025" | FAISS + Code Interpreter | GISTEMP v4 |
| 7 | "Precipitation trend in Midwest" | FAISS + POWER | NASA POWER |
| 8 | "Northern vs Southern hemisphere warming" | FAISS + GISTEMP | GISTEMP v4 |
| 9 | "Current month temperature for Miami" | Gateway (NOAA NCEI) | NOAA NCEI |
| 10 | "Correlation between solar radiation and temp" | FAISS + Code Interpreter | NASA POWER |
| 11-20 | (Additional variations of above patterns) | Mixed | Mixed |

### 2.4 Evaluation Workflow

```
1. Deploy agent to AgentCore Runtime
2. Run benchmark queries via agentcore invoke
3. Traces collected in CloudWatch
4. Run: agentcore evaluate (on-demand)
5. Evaluations service downloads spans from CloudWatch
6. LLM-as-Judge scores each response
7. Results written to CloudWatch dashboard
8. Review pass/fail rates per metric
```

### 2.5 Continuous Evaluation

- Run benchmark suite after each agent code change
- Track metric trends over time in CloudWatch
- Alert if any metric drops below target threshold
