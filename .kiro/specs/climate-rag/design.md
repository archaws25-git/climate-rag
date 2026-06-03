# Design: ClimateRAG — Architecture and Technical Design

## Overview

ClimateRAG is a 4-layer architecture: Data Layer (S3 + FAISS), Compute Layer (Lambda proxies + IAM), AgentCore Layer (Memory + Code Interpreter + Gateway), and Presentation Layer (Streamlit UI). Each layer maps to an independent CDK stack enabling iterative development.

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│  Presentation Layer (Streamlit)                                     │
│    ├─ Chat UI with message history                                  │
│    ├─ Inline chart rendering (PNG)                                  │
│    └─ Session management (actor_id, session_id)                     │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ boto3 / AgentCore SDK
┌──────────────────────────────▼─────────────────────────────────────┐
│  AgentCore Layer                                                    │
│    ├─ Runtime: Strands Agent (Claude Sonnet) in microVM             │
│    ├─ Memory: Semantic strategy, 30-day expiry                      │
│    ├─ Gateway: MCP protocol, semantic search, 2 Lambda targets      │
│    ├─ Code Interpreter: Sandboxed Python, PUBLIC network mode       │
│    └─ Observability: OTEL → CloudWatch Transaction Search           │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────────┐
│  Compute Layer                                                      │
│    ├─ Lambda: NASA POWER proxy (handler.py, Python 3.12, 30s)       │
│    ├─ Lambda: NOAA NCEI proxy (handler.py, Python 3.12, 30s)        │
│    ├─ IAM Role: Lambda execution (CW Logs only)                     │
│    └─ IAM Role: Gateway invocation (lambda:Invoke on 2 ARNs)        │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────────┐
│  Data Layer                                                         │
│    ├─ S3: climate-rag-index-{account_id}                            │
│    │     ├─ index/faiss.index + metadata.jsonl                      │
│    │     ├─ raw/ (GISTEMP, GHCN, POWER source files)                │
│    │     └─ chunks/all_chunks.jsonl                                 │
│    └─ Bucket policy: AgentCore service principal read access         │
└────────────────────────────────────────────────────────────────────┘
```

## Component Design

### 1. Data Ingestion Pipeline

**Technology:** Python scripts (offline, run once)

| Component | Input | Output | Key Library |
|---|---|---|---|
| `ingest_ghcn.py` | NOAA NCEI CSV download | Chunked JSONL (station + decade) | pandas |
| `ingest_gistemp.py` | NASA GISS CSV download | Chunked JSONL (decade + latitude band) | pandas |
| `ingest_power.py` | NASA POWER REST API (6 regions) | Chunked JSONL (region + year) | requests |
| `embeddings.py` | Chunked JSONL | Embeddings via Bedrock Titan v2 (1024 dims) | boto3 |
| `build_index.py` | Embeddings + chunks | FAISS IndexFlatIP + metadata.jsonl → S3 | faiss-cpu |

**Chunking Strategy:** ~500 tokens per chunk to balance context richness with retrieval precision.

### 2. Strands Agent

**Technology:** strands-agents SDK, BedrockModel

| Aspect | Design Decision |
|---|---|
| Model | Claude Sonnet (us.anthropic.claude-sonnet-4-5) |
| Embedding Model | Amazon Titan Embeddings v2 (1024 dimensions) |
| System Prompt | Role-based: "expert climate data analyst for NOAA researchers" |
| Tool Selection | Agent autonomously chooses: RAG search, live API (Gateway), chart generation |
| Memory Integration | Pre-loads recent turns + semantic context before each query |
| Entry Point | `agent/main.py:lambda_handler()` for AgentCore Runtime |

**Tools registered with the Agent:**
- `search_climate_data` — FAISS vector search against S3-hosted index
- `generate_chart` — Delegates code to AgentCore Code Interpreter
- `recall_research_context` — Reads long-term memory (semantic)
- `get_recent_turns` — Reads short-term session turns

### 3. AgentCore Gateway Design

**Protocol:** MCP (Model Context Protocol) with semantic search
**Auth:** NONE (internal, IAM-protected at the AgentCore layer)

| Target | Lambda Function | External API | Key Parameters |
|---|---|---|---|
| `nasa-power-proxy` | `climate-rag-nasa-power` | `power.larc.nasa.gov` | latitude, longitude, start, end, parameters |
| `noaa-ncei-proxy` | `climate-rag-noaa-ncei` | `ncei.noaa.gov/access/services/data/v1` | dataset, stations, startDate, endDate, dataTypes |

**Gateway targets defined with inline tool schemas** so the agent can discover them via semantic search and invoke with structured parameters.

### 4. CDK Stack Design

```
ClimateRagDataStack (long-lived)
  └─ S3 Bucket + public access block

ClimateRagComputeStack (medium-lived)
  ├─ Lambda: NASA POWER proxy
  ├─ Lambda: NOAA NCEI proxy
  ├─ IAM: Lambda execution role
  ├─ IAM: Gateway invocation role
  └─ S3 bucket policy for AgentCore read access

ClimateRagAgentCoreStack (frequently redeployed)
  ├─ Custom Resource Lambda: on_event (60s timeout)
  ├─ Custom Resource Lambda: is_complete (30s timeout)
  ├─ Provider (query_interval=30s, total_timeout=25min)
  ├─ CustomResource: Memory (ClimateRAGMemory)
  ├─ CustomResource: Code Interpreter (ClimateChartInterpreter)
  ├─ CustomResource: Gateway (ClimateDataGateway + 2 targets)
  └─ SSM Parameters: /climate-rag/{memory-id, code-interpreter-id, gateway-id}
```

**Deploy order:** DataStack → ComputeStack → AgentCoreStack
**Destroy order:** AgentCoreStack → ComputeStack → DataStack

### 5. Custom Resource Async Polling Pattern

```
                    CFN Create event
                         │
                         ▼
               ┌─────────────────┐
               │   on_event()    │  Calls create_memory / create_code_interpreter / create_gateway
               │   Returns ID    │  Returns in < 5 seconds
               └────────┬────────┘
                         │ PhysicalResourceId = resource_id
                         ▼
               ┌─────────────────┐
               │  is_complete()  │  Called every 30s by Provider framework
               │  Polls status   │  Returns IsComplete: True when ACTIVE
               └────────┬────────┘
                         │ (repeats up to 25 min)
                         ▼
                  CFN CREATE_COMPLETE
```

### 6. Observability Design

| Signal | Source | Destination |
|---|---|---|
| Distributed traces | AgentCore Runtime OTEL auto-instrumentation | CloudWatch Transaction Search |
| Agent logs | CloudWatch Log Group `/aws/bedrock-agentcore/...` | CloudWatch Logs |
| Dashboard | CloudWatch custom dashboard `ClimateRAG-Dashboard` | CloudWatch Console |

### 7. Security Model

| Boundary | Mechanism |
|---|---|
| Streamlit → AgentCore | IAM SigV4 via boto3 |
| AgentCore → Bedrock models | IAM role on Runtime |
| AgentCore → S3 | Resource-based bucket policy (service principal) |
| Gateway → Lambda | IAM invocation role (scoped to 2 ARNs) |
| Lambda → External APIs | Outbound HTTPS TLS 1.2+ (no credentials needed) |
| S3 data at rest | SSE-S3 encryption |
| Agent execution isolation | microVM per session |

## Technology Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Vector store | FAISS (IndexFlatIP) | Simple, fast, no external service dependency; ~3 GB fits in memory |
| Embeddings | Amazon Titan v2 (1024 dims) | Native Bedrock integration; good balance of quality and speed |
| Agent framework | Strands | First-class AgentCore integration; tool registration is declarative |
| IaC | CDK (Python) | Same language as agent; L2 constructs reduce boilerplate; custom resources for AgentCore |
| UI | Streamlit | Rapid prototyping; built-in chat component; inline image support |
| Chart generation | Code Interpreter (matplotlib) | Sandboxed; no need for local dependencies; supports arbitrary Python |
