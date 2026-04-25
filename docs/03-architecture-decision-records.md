# ClimateRAG — Architecture Decision Records (ADRs)

**Date:** 2026-03-26 | **Version:** 1.0

---

## ADR-001: Agent Framework — Strands Agents

**Status:** Accepted
**Context:** Need a Python agent framework with native AgentCore integration.
**Options:** Strands Agents, LangGraph, LlamaIndex, CrewAI
**Decision:** Strands Agents
**Rationale:** First-class AgentCore starter toolkit support, simplest deployment path via `agentcore launch`, built-in OTEL instrumentation.
**Consequences:** Tied to Strands SDK patterns; community smaller than LangChain.

---

## ADR-002: LLM — Claude Sonnet via Amazon Bedrock

**Status:** Accepted
**Context:** Need a strong reasoning model for climate data Q&A.
**Options:** Claude Sonnet, Claude Haiku, Amazon Nova, GPT-4o
**Decision:** Claude Sonnet via Bedrock
**Rationale:** Strong reasoning, available in us-east-1, native Bedrock integration, good balance of quality and cost.
**Consequences:** Pay-per-token cost (~$3/1M input tokens). No free tier for Sonnet.

---

## ADR-003: Embedding Model — Amazon Titan Embeddings v2

**Status:** Accepted
**Context:** Need embeddings for vector search over climate data chunks.
**Options:** Titan Embeddings v2, Cohere Embed, OpenAI ada-002
**Decision:** Titan Embeddings v2 (1024 dimensions)
**Rationale:** Free tier eligible (first 3 months), native Bedrock, good quality for retrieval.
**Consequences:** 1024-dim vectors; FAISS index size proportional.

---

## ADR-004: Vector Store — FAISS on S3

**Status:** Accepted
**Context:** Need a vector store for ~2-3 GB of embedded climate data.
**Options:** FAISS on S3, OpenSearch Serverless, Bedrock Knowledge Base, Pinecone
**Decision:** FAISS index stored on S3, loaded into agent memory at startup
**Rationale:** Zero infrastructure cost (S3 free tier), no managed service needed, dataset fits in memory (~2-3 GB), simplest to operate.
**Trade-offs:** No real-time index updates (must rebuild); limited to single-node memory. Acceptable for this dataset size.
**Consequences:** Agent cold start includes S3 download + FAISS load (~5-10 seconds).

---

## ADR-005: Gateway Targets — Lambda Proxies

**Status:** Accepted
**Context:** AgentCore Gateway needs targets to expose NASA/NOAA APIs as MCP tools.
**Options:** Direct API targets (OpenAPI), Lambda proxies, API Gateway stage targets
**Decision:** Lambda proxy functions
**Rationale:** Allows request transformation, error handling, rate limiting, and response normalization before returning to the agent. Public APIs don't have OpenAPI specs suitable for direct Gateway integration.
**Consequences:** Lambda free tier (1M requests/month) covers demo usage. Two Lambda functions to maintain.

---

## ADR-006: UI — Streamlit

**Status:** Accepted
**Context:** Need a chat UI with inline chart rendering for researchers.
**Options:** Streamlit, Gradio, plain HTML/JS/CSS, React
**Decision:** Streamlit
**Rationale:** Fastest to build chat+visualization UI, native Python, supports inline image rendering, `st.chat_message` for conversation UI.
**Consequences:** Streamlit's execution model (re-runs on interaction) requires session state management. Acceptable complexity.

---

## ADR-007: Observability — Built-in AgentCore + CloudWatch

**Status:** Accepted
**Context:** Need production-grade tracing, logging, and monitoring.
**Options:** AgentCore built-in OTEL, Datadog, custom OTEL collector
**Decision:** AgentCore built-in observability → CloudWatch Transaction Search
**Rationale:** Zero additional infrastructure, native integration, CloudWatch dashboards for visualization.
**Consequences:** Locked to CloudWatch ecosystem. Acceptable for AWS-native deployment.

---

## ADR-008: Memory Strategy — Semantic Long-Term Memory

**Status:** Accepted
**Context:** Researchers do iterative analysis across sessions; agent should remember context.
**Options:** Short-term only, summary strategy, semantic strategy
**Decision:** Semantic strategy for long-term + automatic short-term
**Rationale:** Semantic strategy extracts factual information (researcher preferences, key findings, frequently queried stations) and makes it searchable. Short-term handles within-session context automatically.
**Consequences:** Long-term memory extraction adds latency (~1-2 seconds per turn). Acceptable.

---

## ADR-009: Policy Engine — Cedar on Gateway

**Status:** Accepted
**Context:** Need to restrict what the agent can do when calling external APIs.
**Options:** No policy, IAM-only, Cedar policy engine
**Decision:** Cedar policy engine attached to Gateway
**Rationale:** Fine-grained, declarative policies. Restrict to GET-only, approved endpoints. Demonstrates AgentCore Policy service.
**Consequences:** Cedar policy authoring required. Simple for read-only use case.

---

## ADR-010: Deployment — AgentCore Runtime via Starter Toolkit

**Status:** Accepted
**Context:** Need serverless, scalable agent hosting.
**Options:** ECS Fargate, Lambda, AgentCore Runtime, EC2
**Decision:** AgentCore Runtime via `agentcore launch`
**Rationale:** Serverless microVM isolation, no Docker required locally (CodeBuild handles it), built-in identity and observability, consumption-based pricing.
**Consequences:** Dependency on AgentCore Runtime availability. Not yet FedRAMP-authorized.
