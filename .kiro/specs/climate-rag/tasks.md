# Tasks: ClimateRAG Implementation Tasks

## Task 1: Project Scaffolding and Configuration

- [x] Create project directory structure (agent/, gateway/, ingest/, eval/, ui/, infra/, docs/, cdk/)
- [x] Create `.bedrock_agentcore.yaml` with project config (strands framework, Python 3.12, entry point)
- [x] Create `agent/requirements.txt` with all dependencies (strands-agents, boto3, faiss-cpu, pandas, matplotlib)
- [x] Create `.gitignore` for Python, .venv, .env, __pycache__, .mypy_cache
- [x] Create `agent/prompts/system_prompt.txt` with NOAA researcher assistant persona

## Task 2: CDK Data Stack (S3 Bucket)

- [x] Create `cdk/stacks/data_stack.py` with S3 bucket (public access blocked, SSE-S3)
- [x] Export bucket name and ARN as CloudFormation outputs
- [x] Set RemovalPolicy to RETAIN to protect long-lived index data

## Task 3: CDK Compute Stack (Lambda + IAM)

- [x] Create `cdk/stacks/compute_stack.py`
- [x] Define Lambda execution role (AWSLambdaBasicExecutionRole only)
- [x] Define Gateway invocation role (trust: bedrock-agentcore.amazonaws.com, action: lambda:InvokeFunction)
- [x] Create NASA POWER Lambda proxy function (Python 3.12, 30s timeout, code from gateway/lambda_nasa_power/)
- [x] Create NOAA NCEI Lambda proxy function (Python 3.12, 30s timeout, code from gateway/lambda_noaa_ncei/)
- [x] Add S3 bucket policy granting AgentCore service principal read access
- [x] Export nasa_lambda, noaa_lambda, gateway_role for consumption by AgentCore stack

## Task 4: Lambda Proxy Handlers

- [x] Create `gateway/lambda_nasa_power/handler.py` — proxies requests to `power.larc.nasa.gov/api/temporal/daily/point`
- [x] Create `gateway/lambda_noaa_ncei/handler.py` — proxies requests to `ncei.noaa.gov/access/services/data/v1`
- [x] Both handlers: parse event dict, construct URL, make outbound HTTPS call, normalize JSON response
- [x] Both handlers: return compact JSON with source attribution, handle errors with 500 status

## Task 5: CDK AgentCore Stack (Memory + Code Interpreter + Gateway)

- [x] Create `cdk/stacks/agentcore_stack.py` with Provider pattern (on_event + is_complete)
- [x] Create `cdk/custom_resources/agentcore_handler/handler.py` with on_event and is_complete entry points
- [x] Implement Memory creation (name, eventExpiryDuration=30)
- [x] Implement Code Interpreter creation (name, networkConfiguration={networkMode: PUBLIC})
- [x] Implement Gateway creation (name, roleArn, protocolType=MCP, authorizerType=NONE)
- [x] Implement is_complete polling for all three resource types
- [x] Implement Delete handlers for all three resource types
- [x] Store resource IDs in SSM Parameters (/climate-rag/memory-id, /climate-rag/code-interpreter-id, /climate-rag/gateway-id)
- [x] Set Provider query_interval=30s, total_timeout=25min

## Task 6: CDK App Entry Point

- [x] Create `cdk/app.py` wiring DataStack → ComputeStack → AgentCoreStack with explicit dependencies
- [x] Create `cdk/cdk.json` with app command pointing to `app.py`
- [x] Document deploy order and independent destroy capability in comments

## Task 7: Data Ingestion — GHCN v4

- [x] Create `ingest/ingest_ghcn.py` — download US station monthly temp data from NCEI
- [x] Parse station metadata (ID, name, state, lat, lon) and monthly values
- [x] Chunk by station + decade (~500 tokens per chunk)
- [x] Write chunked JSONL with text + metadata fields

## Task 8: Data Ingestion — GISTEMP v4

- [ ] Create `ingest/ingest_gistemp.py` — download global anomaly CSV from data.giss.nasa.gov
- [ ] Parse rows (year, month, anomaly by latitude band)
- [ ] Chunk by decade + latitude band (~500 tokens per chunk)
- [ ] Write chunked JSONL with text + metadata (baseline: 1951-1980)

## Task 9: Data Ingestion — NASA POWER

- [ ] Create `ingest/ingest_power.py` — query NASA POWER REST API for 6 US regions
- [ ] Parameters: T2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN
- [ ] Chunk by region + year (~500 tokens per chunk)
- [ ] Write chunked JSONL with text + metadata

## Task 10: Embeddings Generation

- [x] Create `ingest/embeddings.py` — read all chunks from JSONL files
- [x] Call Bedrock Titan Embeddings v2 (model: amazon.titan-embed-text-v2:0) in batches
- [x] Generate 1024-dimension embeddings per chunk
- [x] Save embeddings alongside chunk metadata

## Task 11: FAISS Index Build and Upload

- [x] Create `ingest/build_index.py`
- [x] Load all embeddings into FAISS IndexFlatIP (cosine similarity)
- [x] Save faiss.index + metadata.jsonl to local disk
- [x] Upload to S3: `s3://{bucket}/index/faiss.index` and `s3://{bucket}/index/metadata.jsonl`

## Task 12: Agent RAG Tool

- [x] Create `agent/tools/rag_tool.py`
- [x] On first call: download faiss.index + metadata.jsonl from S3
- [x] Embed query text via Titan v2
- [x] Search FAISS index for top-k results
- [x] Return matched chunks with metadata (source, region, time range)

## Task 13: Agent Chart Tool (Code Interpreter)

- [x] Create `agent/tools/chart_tool.py`
- [x] Accept data + chart type + title from the agent
- [x] Submit Python code to AgentCore Code Interpreter SDK
- [x] Save returned PNG to local chart directory
- [x] Return file path for UI rendering

## Task 14: Agent Memory Tool

- [x] Create `agent/tools/memory_tool.py`
- [x] `recall_research_context(actor_id)` — semantic search in long-term memory
- [x] `get_recent_turns(actor_id, session_id)` — retrieve last N turns
- [x] `save_turn(actor_id, session_id, role, content)` — write turn to memory

## Task 15: Strands Agent Definition

- [x] Create `agent/main.py`
- [x] Configure BedrockModel with Claude Sonnet
- [x] Register tools: search_climate_data, generate_chart, recall_research_context, get_recent_turns
- [x] Load system prompt from `prompts/system_prompt.txt`
- [x] Implement `handle_request()` with memory save before/after
- [x] Implement `lambda_handler()` for AgentCore Runtime entry point
- [x] Detect new chart files and include paths in response

## Task 16: Streamlit UI

- [ ] Create `ui/app.py` with Streamlit chat interface
- [ ] Maintain session state (messages, session_id, actor_id)
- [ ] Call `handle_request()` or AgentCore Runtime invoke depending on mode
- [ ] Render inline PNG charts from returned file paths
- [ ] Source config from environment variables (SSM values)

## Task 17: Observability Setup

- [x] Create `infra/setup_observability.py` — CloudWatch dashboard with agent metrics
- [x] AgentCore Runtime auto-instruments OTEL traces via `agentcore launch`
- [x] Document CloudWatch Transaction Search enablement steps

## Task 18: Evaluation Framework

- [x] Create `eval/eval_config.py` — 10 benchmark queries with expected tools, sources, keywords
- [x] Create `eval/run_eval.py` — execute queries, assess with LLM-as-Judge, report pass/fail
- [x] Targets: correctness ≥ 80%, tool invocation accuracy ≥ 90%, relevance ≥ 85%

## Task 19: Documentation

- [x] Create comprehensive `docs/` folder with:
  - [x] `01-requirements.md` — functional and non-functional requirements
  - [x] `02-architecture-design.md` — system context, services, RAG pipeline
  - [x] `03-architecture-decision-records.md` — ADRs for key technology choices
  - [x] `04-data-flow-integration.md` — ingestion flows, runtime query flow, API integration
  - [x] `05-cost-analysis.md` — free tier optimization, cost breakdown
  - [x] `06-security-compliance.md` — IAM, encryption, network security
  - [x] `07-observability-evaluation.md` — tracing, logging, eval methodology
  - [x] `08-implementation-plan.md` — timeline, project structure, risk register
  - [x] `09-deployment-runbook.md` — step-by-step deployment instructions
  - [x] `10-dataset-reference.md` — dataset descriptions, schemas, access methods
- [x] Create top-level `README.md` with quick start guide and phase-based deployment

## Task 20: Agent Deployment

- [x] Create `infra/deploy.sh` — wrapper for `agentcore dev` (local test) and `agentcore launch` (deploy)
- [x] Configure `.bedrock_agentcore.yaml` with runtime settings
- [ ] Verify end-to-end: Streamlit → AgentCore Runtime → Agent → Tools → Response
