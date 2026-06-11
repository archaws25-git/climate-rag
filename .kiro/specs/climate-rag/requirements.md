# Requirements: ClimateRAG — Production-Grade RAG Pipeline for Historical Climate Trend Analysis

## Overview

ClimateRAG enables NOAA researchers to query historical climate trend data across NOAA GHCN v4, NASA GISTEMP v4, and NASA POWER datasets using natural language. Built on Amazon Bedrock AgentCore, it demonstrates core services including Runtime, Memory, Gateway, Code Interpreter, and Observability.

## Requirements

### Requirement 1: Vector Store Ingestion Pipeline

**User Story:** As a NOAA researcher, I want historical climate data from GHCN v4, GISTEMP v4, and NASA POWER to be indexed in a searchable vector store so that the system can find relevant context for my questions.

**Acceptance Criteria:**
- GHCN v4 monthly temperature records are downloaded, chunked by station + decade (~500 tokens), embedded via Titan Embeddings v2, and stored in FAISS
- NASA GISTEMP v4 anomaly data is chunked by decade + latitude band and indexed
- NASA POWER data (temperature, precipitation, solar) is chunked by region + year and indexed
- FAISS index and metadata are uploaded to S3 bucket `climate-rag-index-{account_id}`
- Total vector store supports ~800 MB raw data with ~2-3 GB index + embeddings

### Requirement 2: Natural Language Question Answering with Citations

**User Story:** As a researcher, I want to ask natural language questions about climate data and receive answers with cited sources so that I can trust and verify the results.

**Acceptance Criteria:**
- The system uses a Strands Agent with Claude Sonnet to process queries
- Answers include citations with dataset name, station ID or region, and time range
- GISTEMP answers note the 1951-1980 baseline when presenting anomalies
- When vector store lacks data, the system falls back to live API tools
- Simple query response time is under 10 seconds

### Requirement 3: Chart Generation via Code Interpreter

**User Story:** As a researcher, I want the system to generate inline visualizations (time series, bar charts, scatter plots) when I ask for visual analysis so that I can see trends more clearly.

**Acceptance Criteria:**
- The system uses AgentCore Code Interpreter with a sandboxed Python environment
- Charts are generated using matplotlib/plotly when the user asks to "plot", "chart", or "visualize"
- Generated chart images (PNG) are returned inline to the Streamlit UI
- Chart-generating queries respond within 30 seconds

### Requirement 4: Multi-Turn Conversations with Memory

**User Story:** As a researcher, I want the system to remember my conversation context and prior findings so that I can have follow-up discussions without repeating myself.

**Acceptance Criteria:**
- AgentCore Memory stores short-term session turns and long-term semantic context
- The agent retrieves recent turns and researcher preferences at the start of each query
- Follow-up queries like "Now overlay the global average on that same chart" work correctly
- Memory uses semantic strategy with namespace `/strategies/{memoryStrategyId}/actors/{actorId}/`
- Memory events expire after 30 days

### Requirement 5: Live Data Access via AgentCore Gateway

**User Story:** As a researcher, I want to access real-time or recent climate data from NASA POWER and NOAA NCEI APIs when the vector store lacks coverage so that my answers are always up-to-date.

**Acceptance Criteria:**
- AgentCore Gateway exposes two MCP tool targets: `nasa-power-proxy` and `noaa-ncei-proxy`
- Each target is backed by a Lambda function that proxies HTTP calls to the external API
- Gateway uses MCP protocol with semantic search enabled
- Gateway IAM role only allows lambda:InvokeFunction on the two proxy Lambdas
- Lambda functions have 30-second timeout and handle API errors gracefully

### Requirement 6: Streamlit Chat UI

**User Story:** As a researcher, I want a conversational chat interface where I can ask questions and see responses with inline charts so that the experience feels natural.

**Acceptance Criteria:**
- Streamlit app provides a chat interface with message history
- Inline PNG charts render within the chat flow
- Session ID is maintained for multi-turn conversations
- Environment variables (Memory ID, Code Interpreter ID, bucket) are sourced from SSM or .env

### Requirement 7: Infrastructure as Code via CDK

**User Story:** As a DevOps engineer, I want all AWS infrastructure defined in CDK so that deployments are repeatable, reviewable, and version-controlled.

**Acceptance Criteria:**
- Three CDK stacks: `ClimateRagDataStack` (S3), `ClimateRagComputeStack` (IAM + Lambda), `ClimateRagAgentCoreStack` (Memory + CodeInterpreter + Gateway)
- AgentCore resources provisioned via Lambda-backed Custom Resources with async polling (on_event + is_complete)
- Resource IDs stored in SSM Parameters (`/climate-rag/memory-id`, `/climate-rag/code-interpreter-id`, `/climate-rag/gateway-id`)
- AgentCore stack can be destroyed and redeployed independently of Data and Compute stacks
- CDK bootstrap version 6+ required

### Requirement 8: Observability with OTEL Traces

**User Story:** As an SRE, I want full distributed tracing across all agent invocations so that I can monitor latency, errors, and tool call frequency.

**Acceptance Criteria:**
- 100% of agent invocations produce OTEL spans
- Spans cover: user_query, vector_retrieval, gateway_tool_call, llm_invocation, code_interpreter, memory_write
- Traces are sent to CloudWatch Transaction Search
- CloudWatch dashboard shows latency, error rate, token usage, and tool call frequency

### Requirement 9: Evaluation Framework

**User Story:** As a quality engineer, I want automated evaluation of answer quality against benchmark queries so that regressions are detected early.

**Acceptance Criteria:**
- 10 benchmark queries defined with expected tools, sources, and keywords
- LLM-as-Judge (Claude Sonnet) evaluates correctness, tool accuracy, and relevance
- Targets: correctness ≥ 80%, tool invocation accuracy ≥ 90%, answer relevance ≥ 85%
- Evaluation is runnable on-demand via `python eval/run_eval.py`

### Requirement 10: Security and Access Control

**User Story:** As a security engineer, I want the system to follow least-privilege principles and protect data in transit and at rest.

**Acceptance Criteria:**
- Lambda execution role has only AWSLambdaBasicExecutionRole (CloudWatch Logs)
- Gateway invocation role is scoped to only the two Lambda ARNs
- S3 bucket has public access blocked
- All external API calls use HTTPS TLS 1.2+
- No secrets hardcoded — all configuration via environment variables or SSM
- S3 bucket uses SSE-S3 encryption at rest
