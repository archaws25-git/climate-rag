# ClimateRAG — Requirements Document

**Project:** ClimateRAG — Production-Grade RAG Pipeline for Historical Climate Trend Analysis
**Date:** 2026-03-26 | **Version:** 1.0 | **Status:** Draft

---

## 1. Executive Summary

ClimateRAG enables NOAA researchers to query historical climate trend data across NOAA GHCN v4, NASA GISTEMP v4, and NASA POWER datasets using natural language. Built on Amazon Bedrock AgentCore, it showcases all core services: Runtime, Memory, Gateway, Identity, Code Interpreter, Browser, Observability, Evaluations, and Policy.

## 2. Stakeholders

| Role | Description |
|---|---|
| End Users | NOAA researchers performing historical climate trend analysis |
| System Owner | NOAA software engineering team |
| Data Providers | NOAA NCEI (GHCN v4), NASA GISS (GISTEMP v4), NASA POWER |

## 3. Problem Statement

Researchers must manually query multiple disparate climate data sources, download datasets, write custom scripts, and cross-reference results. No unified conversational interface exists that answers questions across datasets, generates visualizations, remembers research context, and provides cited answers.

## 4. Functional Requirements

| ID | Priority | Requirement |
|---|---|---|
| FR-1 | P0 | Ingest GHCN v4, GISTEMP v4, and NASA POWER data into a vector store |
| FR-2 | P0 | Answer natural-language queries with cited sources |
| FR-3 | P0 | Generate inline charts via AgentCore Code Interpreter |
| FR-4 | P0 | Multi-turn conversations with short-term and long-term memory |
| FR-5 | P1 | Expose NOAA/NASA APIs as MCP tools via AgentCore Gateway |
| FR-6 | P1 | Enforce access policies via Cedar policy engine |
| FR-7 | P0 | Streamlit chat UI with inline chart rendering |
| FR-8 | P1 | Web-based data retrieval via AgentCore Browser |
| FR-9 | P0 | Full observability with OTEL traces to CloudWatch |
| FR-10 | P1 | Automated evaluation of answer quality |

## 5. Non-Functional Requirements

| ID | Category | Requirement | Target |
|---|---|---|---|
| NFR-1 | Performance | Simple query response time | < 10 seconds |
| NFR-2 | Performance | Chart-generating query response time | < 30 seconds |
| NFR-3 | Scalability | Concurrent sessions | 10+ users |
| NFR-4 | Data Volume | Total ingested data | ≤ 5 GB |
| NFR-5 | Security | Region | us-east-1 |
| NFR-6 | Security | FedRAMP-High | Documented gap analysis |
| NFR-7 | Cost | Free tier optimized | S3, Lambda, CloudWatch, Titan Embeddings |
| NFR-8 | Observability | Trace coverage | 100% of invocations |
| NFR-9 | Quality | Eval pass rate | ≥ 80% correctness |

## 6. Example User Queries

1. "How has average temperature changed in the US Southeast over the last 50 years?"
2. "Compare temperature anomaly trends between coastal and inland stations since 1950"
3. "Show me the warmest decades on record for station USW00013874"
4. "Plot annual temperature anomalies for the contiguous US from 1950 to 2025"
5. "Now overlay the global average on that same chart" (follow-up with memory)

## 7. Data Requirements

| Dataset | Content | Format | Access | Size |
|---|---|---|---|---|
| NOAA GHCN v4 | Monthly temp records, 27K+ stations, since 1880 | CSV | NCEI API | ~500 MB (US filtered) |
| NASA GISTEMP v4 | Global surface temp anomalies since 1880 | CSV | Direct download | ~100 MB |
| NASA POWER | Solar, temp, precip, wind — 1981-present | JSON/CSV | REST API (no key) | ~200 MB |

Total: ~800 MB raw → ~2-3 GB with embeddings + FAISS index.

## 8. Constraints

- Timeline: production-ready within 8 hours
- AgentCore is GA but not yet FedRAMP-authorized
- Requires Claude Sonnet + Titan Embeddings v2 enabled in Bedrock
- NASA POWER: max 5 concurrent requests
- NOAA NCEI: requires free API token

## 9. Assumptions

1. Bedrock model access enabled in us-east-1
2. AWS credentials configured with AgentCore/S3/Lambda/CloudWatch/IAM permissions
3. Python 3.10+ available
4. Public APIs remain stable during development

## 10. Out of Scope

- Real-time weather forecasting
- Climate model simulations (CMIP6)
- Streamlit UI authentication (demo mode)
- Multi-region deployment
- Scheduled re-ingestion
