---
marp: true
theme: default
paginate: true
---

# ClimateRAG
## Production-Grade RAG Pipeline for Climate Trend Analysis

**Built on Amazon Bedrock AgentCore**

Senior AI/GenAI FDE Portfolio Project

---

# Problem Statement

Climate researchers need to query 75+ years of multi-source climate data and get **cited, accurate answers** — not hallucinations.

**Challenges:**
- 3 disparate datasets (NOAA GHCN, NASA GISTEMP, NASA POWER)
- 37 weather stations × 8 decades = 340+ data chunks
- Abbreviations/aliases: "NYC", "LA", "Southeast" must all resolve correctly
- Scientific accuracy is non-negotiable — every claim must cite its source

---

# Architecture Overview

```
User Query → Streamlit UI (streaming)
    → Strands Agent (Claude Sonnet 4)
        → Hybrid Search (FAISS Vector + BM25 Keyword + RRF Fusion)
            → Metadata Pre-Filter (temporal + geographic)
            → FAISS Inner Product Search (Titan Embeddings v2)
            → BM25 Keyword Search (rank_bm25)
            → Reciprocal Rank Fusion (weighted merge)
        → AgentCore Code Interpreter (chart generation)
        → AgentCore Memory (multi-session persistence)
    → Token-by-token streaming response
```

---

# Tech Stack

| Layer | Technology |
|---|---|
| **LLM** | Claude Sonnet 4 via Amazon Bedrock |
| **Embeddings** | Amazon Titan Embeddings v2 (1024-dim) |
| **Vector Store** | FAISS IndexFlatIP (cosine similarity) |
| **Keyword Search** | BM25Okapi (rank_bm25) |
| **Fusion** | Reciprocal Rank Fusion (RRF, k=60) |
| **Memory** | Bedrock AgentCore Memory |
| **Code Execution** | Bedrock AgentCore Code Interpreter |
| **Infrastructure** | AWS CDK (3 stacks) |
| **UI** | Streamlit with token streaming |
| **Observability** | OpenTelemetry + custom latency tracker |
| **CI/CD** | GitHub Actions (lint, type-check, security, tests) |

---

# Hybrid Search: Why Not Just Vector?

| Query | Vector-Only | Hybrid (Vector + BM25) |
|---|---|---|
| "NYC temperature" | ❌ Misses (embedding doesn't resolve abbreviation) | ✅ BM25 matches "NYC" keyword in chunk |
| "LA trends since 1950" | ❌ Matches "Alaska" (substring "la") | ✅ Word-boundary regex + BM25 exact match |
| "Southeast 1990s" | ⚠️ Returns globally similar chunks | ✅ Metadata filter pre-restricts to Southeast + 1990s |

**Result:** Recall improved from 70% → 90% after adding BM25 + metadata filtering

---

# Metadata Pre-Filtering

Hard filters applied BEFORE vector/BM25 search:

**Temporal:**
- "since 1950" → filter to decades ≥ 1950s
- "in the 1990s" → only 1990s chunks
- "last 50 years" → computed decade range

**Geographic:**
- City names → 50-mile radius filter (haversine)
- Region names → exact region match
- Word-boundary regex prevents "LA" matching inside "Alaska"

**Impact:** Reduces candidate set from 340 → ~40-80 chunks before search runs

---

# Source Preference & Data Integrity

| Data Type | Preferred Source | Rationale |
|---|---|---|
| Temperature | GHCN v4 (station) | Ground-truth rain gauge measurements |
| Precipitation | GHCN v4 (station) | Direct observation > satellite estimates |
| Solar radiation | NASA POWER (satellite) | Only available source |
| Global anomalies | GISTEMP v4 | Authoritative NASA global dataset |

**GHCN boost:** 1.5x RRF score for station data on temperature/precip queries
**Solar bypass:** No boost applied for solar/radiation queries

---

# Memory-Based History Reconstruction

**Problem:** Bedrock rejects conversations with orphaned tool_use messages (crashed mid-request)

**Solution:** 
1. Save every turn to AgentCore Memory
2. On restart/crash, reconstruct history from Memory
3. Validate role alternation (user→assistant→user...)
4. Handle `EventMessage` objects from the SDK (not plain dicts)

**Result:** Multi-turn conversations survive process restarts and orphaned tool_use errors

---

# Performance Optimization Journey

| Metric | Before | After | Improvement |
|---|---|---|---|
| **TTFT** | 17s | 2-7s | 59-88% faster |
| **E2E (simple)** | 24s | 8-12s | 50-67% faster |
| **E2E (comparison)** | 60s | 13-28s | 53-78% faster |
| **Error rate** | 20% | 0% | Eliminated |

**Key optimizations:**
- Trimmed system prompt (80 lines → 15 lines, -600 tokens)
- Metadata pre-filtering (less to search)
- Dynamic top_k (3 for focused, 15 for trends, 16 for comparisons)
- Celsius only (no duplicate Fahrenheit charts)
- One chart max per response

---

# Evaluation Framework

**Unified eval runner** with 4 suites:

```
python eval/run.py                    # All suites
python eval/run.py --suite retrieval  # IR metrics only (30s)
python eval/run.py --suite e2e        # LLM-as-Judge (5min)
python eval/run.py --suite multiturn  # Conversation flows (8min)
python eval/run.py --suite latency    # P50/P95/P99 (2min)
```

| Suite | Metrics | Current Score |
|---|---|---|
| Retrieval | Recall, Precision, MRR, NDCG | 90% recall, 77% precision |
| E2E | 6-dimension LLM-as-Judge (composite) | 74% composite |
| Multi-turn | Context resolution, coherence, progressive quality | 4.5/5 context |
| Latency | P50, P95, P99 | P50: 12.5s |

---

# Test Coverage

**243 unit tests | 5 integration tests | 6 load tests**

| Module | Coverage |
|---|---|
| RAG hybrid search | 87% |
| Metadata filter | 96% |
| Chart tool guards | 90% |
| History reconstruction | 84% |
| GHCN ingestion | 99% |
| **Overall** | **78%** |

**CI pipeline:** Lint (ruff) → Type-check (mypy) → Security (bandit) → Unit tests → CDK synth

---

# Infrastructure as Code

**3 CDK stacks:**

1. **ClimateRagDataStack** — S3 bucket for FAISS index
2. **ClimateRagComputeStack** — Lambda proxies for NASA/NOAA APIs + Gateway IAM role
3. **ClimateRagAgentCoreStack** — Custom Resources for Memory, Code Interpreter, Gateway (async polling pattern)

**Also:** `provision_agentcore.py` with idempotent `--teardown` flag for direct API provisioning when CDK times out

---

# Key Engineering Decisions (ADRs)

| Decision | Rationale |
|---|---|
| FAISS over Weaviate/S3 Vectors | 340 chunks — no need for a managed service. In-process = <5ms search |
| BM25 over query expansion | Zero-latency keyword matching vs +200ms LLM call per search |
| RRF over linear combination | Parameter-free fusion, proven in academic IR benchmarks |
| Metadata hard filters over soft ranking | Deterministic exclusion prevents irrelevant results from ever scoring |
| Token streaming over batch response | Perceived latency drops from 28s to 2s (first token visible immediately) |
| AgentCore Memory over in-process state | Survives crashes, process restarts, and scaling events |

---

# Challenges & How I Solved Them

| Challenge | Solution |
|---|---|
| AgentCore `list_memories` API doesn't return resources | Multi-strategy lookup: list → SSM → CloudFormation → manual ID |
| LLM generates `.merge()` in chart code | Pre-execution guard + sandbox error detection + retry prompt |
| "LA" matches inside "Alaska" | Word-boundary regex in geo filter |
| Orphaned tool_use crashes Bedrock | History sanitizer + retry with Memory reconstruction |
| 60s E2E for comparisons | Eliminated unnecessary charts, reduced context, metadata filtering |
| Confidence thresholds too aggressive | Calibrated against actual Titan v2 score distribution |

---

# What I'd Do Next

1. **Query expansion at search time** — LLM rewrites query to canonical terms before embedding
2. **Model routing** — Haiku for simple queries (3x faster), Sonnet for complex
3. **OpenTelemetry → CloudWatch** — Full distributed tracing in production
4. **S3 Vectors migration** — Native AWS managed vector store (real-time upsert)
5. **Guardrails enforcement** — Bedrock Guardrails for content filtering on input/output
6. **Cost optimization** — Per-query cost tracking, caching frequent queries

---

# Live Demo Queries

Try these in the Streamlit UI:

1. **Simple:** "What was the average temperature in Chicago in the 1990s?"
2. **Comparison:** "Compare temperature trends between New York Central Park and Los Angeles Intl from the 1950s to 2020s"
3. **Global:** "Which are the warmest decades on record globally?"
4. **Chart:** "Plot global temperature anomalies"
5. **Multi-turn:** Ask about Atlanta → "I meant the 1990s" → "Compare to current decade"

---

# Summary

**ClimateRAG demonstrates:**

✅ Production-grade hybrid RAG (vector + keyword + metadata filtering)
✅ Multi-dataset ingestion with scientific data integrity
✅ Real-time streaming with latency observability
✅ Memory-based multi-turn conversation persistence
✅ Comprehensive eval framework (retrieval + generation + latency)
✅ Infrastructure as Code with idempotent provisioning
✅ 78% test coverage with CI/CD pipeline
✅ Performance optimization from 60s → 12s E2E

**Stack:** Python | AWS Bedrock | AgentCore | CDK | FAISS | BM25 | Streamlit | OpenTelemetry

---

# Thank You

**Repository:** github.com/[your-handle]/climate-rag
**Live Demo:** http://localhost:8501

Questions?
