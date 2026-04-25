# ClimateRAG on Bedrock AgentCore — Build Guide

A step-by-step walkthrough of how this production-grade RAG pipeline was built, what each component does, and the trade-offs behind every decision.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Step 1: Requirements Gathering](#2-step-1-requirements-gathering)
3. [Step 2: Dataset Selection](#3-step-2-dataset-selection)
4. [Step 3: Project Scaffolding](#4-step-3-project-scaffolding)
5. [Step 4: Data Ingestion Pipeline](#5-step-4-data-ingestion-pipeline)
6. [Step 5: Embedding Generation](#6-step-5-embedding-generation)
7. [Step 6: Vector Index Construction](#7-step-6-vector-index-construction)
8. [Step 7: Agent Implementation](#8-step-7-agent-implementation)
9. [Step 8: AgentCore Services Setup](#9-step-8-agentcore-services-setup)
10. [Step 9: Gateway and Lambda Proxies](#10-step-9-gateway-and-lambda-proxies)
11. [Step 10: Streamlit UI](#11-step-10-streamlit-ui)
12. [Step 11: Evaluation](#12-step-11-evaluation)
13. [Decision Trade-offs](#13-decision-trade-offs)

---

## 1. Project Overview

ClimateRAG is a conversational AI system that lets NOAA researchers ask natural-language questions about historical climate data. It combines three public datasets, a vector search index, live API access, chart generation, and conversation memory — all orchestrated through Amazon Bedrock AgentCore.

The system showcases every AgentCore service: Runtime, Memory, Gateway, Identity, Code Interpreter, Observability, Evaluations, and Policy.

---

## 2. Step 1: Requirements Gathering

We started by identifying the problem domain (historical climate trend analysis), the target users (NOAA researchers), and the constraints (8-hour timeline, free-tier cost optimization, us-east-1 deployment).

Key requirements that shaped the architecture:
- Researchers need cited, traceable answers — not just summaries
- Inline visualizations are essential for trend analysis
- Multi-session memory lets researchers build on prior work
- The system must handle queries across multiple datasets simultaneously

These requirements drove us toward an agentic architecture (not a simple RAG chain) because the agent needs to decide which tools to use: vector search, live API calls, chart generation, or memory retrieval.

---

## 3. Step 2: Dataset Selection

We evaluated several NOAA and NASA datasets and selected three that complement each other:

### NASA GISTEMP v4
- **What**: Global surface temperature anomalies since 1880
- **Why chosen**: The gold standard for global temperature trends. Small (~100MB), clean CSV format, publicly downloadable, well-documented baseline (1951-1980)
- **Trade-off**: Only provides anomalies, not absolute temperatures. Only global/zonal — no station-level detail

### NOAA GHCN v4
- **What**: Monthly temperature records from individual weather stations
- **Why chosen**: Station-level granularity lets researchers ask about specific cities. We filtered to 6 representative US stations to keep data manageable
- **Trade-off**: We limited to 6 stations instead of the full 27,000+ network. This keeps ingestion fast but limits geographic coverage. A production system would ingest thousands of stations

### NASA POWER
- **What**: Satellite-derived meteorological data (temperature, solar radiation, precipitation) since 1981
- **Why chosen**: Fills the gap between GISTEMP (global only) and GHCN (station only) by providing gridded regional data. REST API with no authentication required
- **Trade-off**: 0.5-degree resolution means it's not as precise as station data. We only ingested temperature parameters — precipitation and solar radiation were available but would have increased chunk count significantly

### Datasets we considered but rejected:
- **NOAA Climate Data Records (CDRs)**: NetCDF format requires heavy processing libraries. Not worth the complexity for a demo
- **NEX-GDDP-CMIP6**: Climate projections, not historical observations. Out of scope
- **NOAA Storm Events**: Interesting but not relevant to temperature trend analysis

---

## 4. Step 3: Project Scaffolding

The project follows a modular structure where each directory has a single responsibility:

```
climate-rag/
├── agent/          # The AI agent (Strands framework)
│   ├── main.py     # Agent definition and entry point
│   ├── tools/      # Tools the agent can call
│   └── prompts/    # System prompt
├── gateway/        # Lambda functions for live API access
├── ingest/         # One-time data pipeline
├── eval/           # Evaluation framework
├── ui/             # Streamlit frontend
├── infra/          # AWS resource setup scripts
└── docs/           # Architecture documentation
```

This separation means you can run ingestion independently of the agent, swap the UI without touching the agent, or replace the vector store without changing the tools interface.

---

## 5. Step 4: Data Ingestion Pipeline

### `ingest/ingest_gistemp.py`

**What it does**: Downloads the GISTEMP v4 CSV from NASA GISS, parses it, and creates text chunks grouped by decade.

**How it works**:
1. Fetches `GLB.Ts+dSST.csv` from `data.giss.nasa.gov` — this is the Land-Ocean Temperature Index
2. Parses each row (year + monthly anomalies + annual average)
3. Groups years into decades (1880s, 1890s, ... 2020s)
4. For each decade, creates a text chunk containing: decade label, average anomaly, min/max range, and year-by-year values
5. Attaches metadata: dataset name, region ("Global"), decade, time range, baseline period
6. Writes chunks as JSONL (one JSON object per line)

**Output**: 15 chunks (one per decade from 1880s to 2020s)

**Design decision — chunking by decade**: We chose decade-level granularity because researchers typically think in decadal trends ("how did the 1990s compare to the 2000s?"). Year-level chunks would create 145 tiny chunks with too little context each. Monthly chunks would be 1,740 chunks — overkill for a demo. Decade chunks hit the sweet spot of ~500 tokens each with enough context for meaningful retrieval.

### `ingest/ingest_ghcn.py`

**What it does**: Downloads monthly temperature data for 6 representative US weather stations from the NOAA NCEI API, then chunks by station + decade.

**How it works**:
1. Queries the NCEI Access Data Service v1 API for 6 stations (Atlanta, New York, LA, Chicago, Anchorage, Honolulu)
2. If the API is unavailable, falls back to generating realistic sample data with a warming trend baked in
3. Parses CSV response into station/date/temperature records
4. Groups by (station_id, decade) pairs
5. Creates text chunks with station name, coordinates, state, region, average temperature, and observation count
6. Attaches rich metadata for filtering

**Output**: 48 chunks (6 stations × 8 decades from 1950s to 2020s)

**Design decision — 6 stations**: We picked one station per major US climate region (Southeast, Northeast, West, Midwest, Alaska, Hawaii). This gives geographic diversity while keeping the dataset small. The stations are major airports with long, continuous records — the most reliable GHCN data.

**Design decision — sample data fallback**: The NOAA API can be slow or return errors. Rather than failing the entire pipeline, we generate statistically plausible sample data. This ensures the demo always works. The sample data includes a realistic warming trend (~0.015°C/year) with random noise.

### `ingest/ingest_power.py`

**What it does**: Queries the NASA POWER REST API for monthly temperature data at 6 US regional coordinates, then chunks by region + decade.

**How it works**:
1. Defines 6 US regions with representative lat/lon coordinates (e.g., Southeast = Atlanta at 33.45°N, -84.39°W)
2. Calls the POWER monthly API for each region, requesting T2M (temperature at 2 meters) from 1981-2025
3. Parses the JSON response, groups monthly values by decade
4. Creates text chunks with region name, city, coordinates, average temperature, and range
5. Sleeps 2 seconds between API calls to respect rate limits (max 5 concurrent)

**Output**: 30 chunks (6 regions × 5 decades from 1980s to 2020s)

**Bug we fixed during development**: The NASA POWER monthly API expects `start=2020` (year only), not `start=198101` (year+month). The original code used the wrong format, causing HTTP 422 errors. We discovered this by testing the API directly with curl.

**Design decision — temperature only**: NASA POWER offers solar radiation (ALLSKY_SFC_SW_DWN) and precipitation (PRECTOTCORR) too. We only ingested temperature to keep chunks focused. The eval revealed this gap — queries about precipitation get honest "data not available" responses. A production system would ingest all parameters.

---

## 6. Step 5: Embedding Generation

### `ingest/embeddings.py`

**What it does**: Reads all chunk JSONL files, generates a 1024-dimensional embedding vector for each chunk's text using Amazon Titan Embeddings v2, and writes the enriched chunks back to disk.

**How it works**:
1. Iterates over the three chunk files (gistemp, ghcn, power)
2. For each chunk, calls `bedrock-runtime:InvokeModel` with the Titan Embeddings v2 model
3. Truncates text to 8,000 characters (Titan v2's input limit)
4. Appends the embedding vector to the chunk object
5. Writes to an `embedded/` subdirectory

**Output**: 93 chunks with 1024-dim float32 vectors

**Design decision — Titan Embeddings v2 over alternatives**:
- **Titan v2**: Free tier eligible (first 3 months), native Bedrock integration, 1024 dimensions, good retrieval quality
- **Cohere Embed v3**: Better benchmark scores but costs money from day one
- **OpenAI ada-002**: Requires external API key, not Bedrock-native
- For 93 chunks, embedding quality differences are negligible. Cost was the deciding factor.

**Design decision — client-side embedding**: We generate embeddings ourselves rather than using Weaviate's or Bedrock Knowledge Base's built-in vectorization. This gives us full control over the embedding model and lets us use FAISS (which requires pre-computed vectors). The trade-off is more code to maintain.

---

## 7. Step 6: Vector Index Construction

### `ingest/build_index.py`

**What it does**: Loads all embedded chunks, builds a FAISS index, and uploads both the index and metadata to S3.

**How it works**:
1. Reads all `embedded/*.jsonl` files
2. Extracts embedding vectors into a numpy array
3. Normalizes vectors (L2 normalization) so inner product = cosine similarity
4. Creates a `faiss.IndexFlatIP` (flat index with inner product search)
5. Adds all vectors to the index
6. Saves the FAISS binary index and a metadata JSONL file (text + metadata, no embeddings) to disk
7. Uploads both files to S3

**Output**: `s3://climate-rag-index-{account}/index/faiss.index` (~380KB) and `metadata.jsonl` (~150KB)

**Design decision — FAISS over managed vector databases**:

| Factor | FAISS | OpenSearch Serverless | Bedrock Knowledge Base | pgvector |
|---|---|---|---|---|
| Cost | $0 | ~$350/month (2 OCUs min) | Per-query pricing | ~$15+/month (RDS) |
| Setup | 3 lines of code | 30+ minutes | 30+ minutes | 20+ minutes |
| Our dataset | 93 vectors, 380KB | Massive overkill | Overkill | Overkill |
| Real-time updates | No (rebuild) | Yes | Yes (auto-sync) | Yes |
| Metadata filtering | Post-filter only | Native | Native | Full SQL |

For 93 vectors, FAISS loads into memory in under a second. There's no running infrastructure, no monthly cost, and no network latency. The entire index fits in a single S3 object smaller than a JPEG photo.

**When to upgrade**: If the dataset grows beyond ~100K vectors, or if you need real-time updates or complex metadata filtering, switch to OpenSearch Serverless or pgvector on Aurora Serverless v2.

**Design decision — IndexFlatIP (brute force) over approximate indexes**: FAISS offers approximate nearest neighbor indexes (IVF, HNSW) that are faster for large datasets. With 93 vectors, brute-force search takes microseconds. Approximate indexes add complexity with zero benefit at this scale.

---

## 8. Step 7: Agent Implementation

### `agent/main.py`

**What it does**: Defines the Strands Agent with its model, system prompt, and tools. Provides `handle_request()` as the main entry point for both the UI and AgentCore Runtime.

**How it works**:
1. Loads the system prompt from `prompts/system_prompt.txt`
2. Creates a `BedrockModel` pointing to Claude Sonnet 4 via inference profile
3. Registers tools: `search_climate_data`, `generate_chart`, and optionally memory tools
4. `handle_request()` snapshots the chart directory before calling the agent, then detects any new chart files after — this is how we capture chart outputs
5. Optionally saves conversation turns to AgentCore Memory

**Bug we fixed**: Claude Sonnet 4 requires an inference profile ID (`us.anthropic.claude-sonnet-4-20250514-v1:0`), not the raw model ID. The raw ID throws `ValidationException: Invocation of model ID with on-demand throughput isn't supported`. This is a Bedrock requirement for newer models.

**Design decision — Strands Agents over LangGraph/LlamaIndex**:
- **Strands**: First-class AgentCore starter toolkit support, `agentcore create/dev/deploy` workflow, built-in OTEL instrumentation, simplest deployment path
- **LangGraph**: More flexible graph-based orchestration, better for complex multi-step workflows, but more boilerplate
- **LlamaIndex**: Strong RAG primitives, but less native AgentCore integration
- We chose Strands because the AgentCore starter toolkit is built around it. Deployment is `agentcore deploy` — one command.

### `agent/tools/rag_tool.py`

**What it does**: Provides the `search_climate_data` tool that the agent calls to search the FAISS vector store.

**How it works**:
1. On first call, downloads the FAISS index and metadata from S3 (cached in memory after that)
2. Embeds the query text using Titan v2 (same model used for indexing)
3. Normalizes the query vector
4. Runs FAISS `search()` to find the top-k nearest neighbors
5. Returns results as JSON with score, text, source, region, decade, and station ID

**Design decision — lazy loading**: The index is loaded on first tool call, not at agent startup. This means the agent starts fast and only pays the S3 download cost when RAG is actually needed. For a 380KB index, this adds ~1 second on first query.

### `agent/tools/chart_tool.py`

**What it does**: Provides the `generate_chart` tool that executes Python code in AgentCore Code Interpreter to create matplotlib charts.

**How it works**:
1. Starts a Code Interpreter session
2. Sends Python code to the `executeCode` API with `language: python`
3. Reads the event stream response
4. Extracts base64-encoded PNG from stdout (the code prints `CHART_BASE64:` prefix)
5. Saves the PNG to `/tmp/climate-rag-charts/` with a unique filename
6. Returns the file path so the UI can display it

**Key discovery during development**: The Code Interpreter API uses an event stream response, not a simple JSON body. The correct invocation requires `name="executeCode"` and `arguments={"code": "...", "language": "python"}`. We discovered this through trial and error — the error messages guided us to the correct enum values.

**Design decision — file-based chart passing**: The Strands Agent consumes tool results internally and summarizes them in prose. It does NOT pass through raw base64 data to the final response. We solved this by saving charts to disk and having `handle_request()` detect new files by comparing directory snapshots before and after the agent call. This is a pragmatic workaround that avoids modifying the Strands framework.

### `agent/tools/memory_tool.py`

**What it does**: Provides tools for reading from AgentCore Memory (short-term turns and long-term semantic search). Also provides a `save_turn()` function called by `handle_request()`.

**How it works**:
1. Creates a `MemorySessionManager` connected to the AgentCore Memory resource
2. `recall_research_context`: Searches long-term memory for relevant prior findings
3. `get_recent_turns`: Retrieves the last k conversation turns from the current session
4. `save_turn`: Writes a conversation turn (user or assistant message) to memory

**Design decision — optional memory**: Memory tools are wrapped in a try/except import. If the `bedrock-agentcore` SDK isn't installed, the agent works without memory. This makes local development easier — you don't need the full AgentCore SDK just to test RAG queries.

### `agent/prompts/system_prompt.txt`

**What it does**: Defines the agent's persona, capabilities, and behavioral rules.

**Key instructions**:
- Always cite data sources (dataset name, station ID, time range)
- Note the GISTEMP 1951-1980 baseline when discussing anomalies
- Generate charts when visualization is requested
- Fall back to live API tools when vector store lacks data
- Express temperatures in both Celsius and Fahrenheit

---

## 9. Step 8: AgentCore Services Setup

### AgentCore Memory (`infra/setup_memory.py`)

**What we created**: A memory resource named `ClimateRAGMemory` with a semantic long-term memory strategy.

**Command used**:
```
agentcore memory create ClimateRAGMemory \
  --region us-east-1 \
  --strategies '[{"semanticMemoryStrategy": {...}}]' \
  --wait
```

**What it provides**:
- **Short-term memory**: Automatic storage of conversation turns within a session
- **Long-term memory**: Semantic strategy extracts factual information (researcher preferences, key findings, frequently queried stations) and makes it searchable across sessions

**Setup time**: ~3 minutes (mostly waiting for the resource to become ACTIVE)

### AgentCore Code Interpreter (`infra/setup_code_interpreter.py`)

**What we created**: A sandboxed Python execution environment named `ClimateChartInterpreter`.

**What it provides**: Isolated Python runtime with matplotlib, numpy, pandas pre-installed. The agent sends Python code, the interpreter executes it in a secure sandbox, and returns stdout/stderr.

**Design decision — Code Interpreter over local execution**: We could have the agent generate charts locally using matplotlib. But Code Interpreter provides:
- Security: sandboxed execution, no access to the agent's filesystem
- Consistency: same environment regardless of where the agent runs
- AgentCore showcase: demonstrates the Code Interpreter service

### AgentCore Gateway

**What we created**: An MCP Gateway named `ClimateDataGateway` with semantic search enabled and two Lambda targets.

**What it provides**: Converts our Lambda functions into MCP-compatible tools that the agent can discover and call. Semantic search means the agent can find relevant tools by describing what it needs.

**Auto-created resources**: The Gateway CLI automatically created:
- A Cognito User Pool for JWT-based authorization
- An IAM execution role for the Gateway
- A workload identity for the Gateway

---

## 10. Step 9: Gateway and Lambda Proxies

### `gateway/lambda_nasa_power/handler.py`

**What it does**: A Lambda function that proxies requests to the NASA POWER REST API.

**Why a proxy instead of direct API access**: AgentCore Gateway targets must be AWS resources (Lambda, API Gateway, etc.) — not arbitrary external URLs. The Lambda acts as a thin adapter that:
1. Receives structured parameters from the Gateway
2. Constructs the NASA POWER API URL
3. Makes the HTTP request
4. Normalizes the response (extracts just the parameter data, discards metadata)
5. Returns a compact JSON response

**Design decision — Lambda over API Gateway**: We could have put API Gateway in front of the external APIs and used OpenAPI specs as Gateway targets. Lambda is simpler for this use case — no API Gateway configuration, no OpenAPI spec to write, and we get request/response transformation for free in Python.

### `gateway/lambda_noaa_ncei/handler.py`

**What it does**: Same pattern as the NASA POWER proxy, but for the NOAA NCEI Access Data Service API.

**Additional feature**: Limits response size to 100 records to prevent the agent from being overwhelmed with data. The NCEI API can return thousands of records for broad queries.

---

## 11. Step 10: Streamlit UI

### `ui/app.py`

**What it does**: Provides a chat interface where researchers type questions and see text answers with inline charts.

**How it works**:
1. Loads the agent's `handle_request` function (cached with `@st.cache_resource`)
2. Maintains chat history in `st.session_state`
3. On each user message: calls `handle_request()`, renders the text response with `st.markdown()`, and renders any chart PNGs with `st.image()`
4. Charts are stored as file paths in the message history so they persist across reruns

**Design decision — Streamlit over alternatives**:
- **Streamlit**: Fastest to build, native Python, `st.chat_message` for conversation UI, `st.image` for inline charts. 80 lines of code for a complete chat+visualization app
- **Gradio**: Similar speed but less control over layout
- **React**: Better for production but would take hours to build
- **Plain HTML/JS/CSS**: No server-side Python integration without building an API layer

**HTTPS setup**: Streamlit only serves HTTP. We put nginx in front as a reverse proxy with a self-signed TLS certificate for HTTPS on port 443. The nginx config handles WebSocket upgrades (required by Streamlit's live-reload protocol).

---

## 12. Step 11: Evaluation

### `eval/eval_config.py`

**What it does**: Defines 10 benchmark queries with expected tool usage, expected data sources, and expected keywords in the response.

**Query coverage**:
- Regional trend analysis (Southeast, Midwest)
- Global trend analysis (GISTEMP)
- City comparisons (NY vs LA, Alaska vs Hawaii)
- Station-specific lookups (Chicago 1990s)
- Visualization requests (plot anomalies)
- Cross-dataset queries (NASA POWER solar radiation)
- Temporal comparisons (1950s vs 2020s)

### `eval/run_eval.py`

**What it does**: Runs all benchmark queries through the agent and scores the responses.

**Scoring method**:
- **Keyword score**: What percentage of expected keywords appear in the response
- **Source citation**: Whether the expected dataset name appears in the response

**Results**: 87% average keyword score, 100% success rate across 10 queries.

**Design decision — simple keyword eval over LLM-as-Judge**: AgentCore Evaluations supports LLM-as-Judge scoring, which would be more nuanced. We used keyword matching because:
1. It runs without deploying to AgentCore Runtime (works locally)
2. It's deterministic and fast
3. It's sufficient to catch major regressions
A production system would use AgentCore Evaluations with LLM-as-Judge for correctness, relevance, and citation accuracy.

---

## 13. Decision Trade-offs

### Architecture-level decisions

**Agentic RAG vs simple RAG chain**:
- Simple chain: query → embed → retrieve → generate. Predictable, fast, but can't decide to call live APIs or generate charts
- Agentic: the LLM decides which tools to use per query. More flexible but slower (multiple tool calls) and less predictable
- We chose agentic because the requirements demand tool selection (vector search vs live API vs chart generation)

**Single agent vs multi-agent**:
- Single agent with multiple tools: simpler, all context in one conversation
- Multi-agent (retriever agent + analyst agent + chart agent): better separation of concerns but adds latency and complexity
- We chose single agent. For 3 tools, the overhead of multi-agent orchestration isn't justified

### Data decisions

**Chunk size (~500 tokens)**:
- Smaller chunks (100-200 tokens): more precise retrieval but less context per chunk
- Larger chunks (1000+ tokens): more context but retrieval becomes less precise
- 500 tokens per decade-level chunk gives enough context for the LLM to generate a useful answer without overwhelming the context window

**Pre-computed embeddings vs query-time embedding**:
- Pre-computed: faster retrieval, but stale if data changes
- Query-time: always fresh, but slower and more expensive
- We pre-compute because climate data updates monthly at most. The 1-second embedding call per query is acceptable

### Infrastructure decisions

**AgentCore Runtime vs ECS Fargate**:
- AgentCore Runtime: serverless microVM, built-in identity/observability, `agentcore deploy` workflow
- ECS Fargate: more control, FedRAMP-authorized, but requires Docker/ECR/task definitions
- We chose AgentCore Runtime to showcase the service. For FedRAMP-High production, the mitigation plan is to move to ECS in GovCloud

**Self-signed TLS vs ACM certificate**:
- ACM: proper certificates, but requires a domain name and DNS validation
- Self-signed: works immediately, but browsers show a security warning
- For a workshop demo, self-signed is acceptable. Production would use ACM with a Route 53 domain

### Cost decisions

**Claude Sonnet 4 vs Haiku**:
- Sonnet: ~$3/1M input tokens, strong reasoning, detailed answers
- Haiku: ~$0.25/1M input tokens, faster, but less detailed analysis
- We chose Sonnet because researchers need thorough, well-reasoned answers. A production system could route simple lookups to Haiku and complex analysis to Sonnet

**FAISS on S3 vs managed vector DB**:
- FAISS: $0/month, but no real-time updates or metadata filtering
- OpenSearch Serverless: $350+/month minimum, but fully managed with filtering
- For 93 vectors, paying $350/month for a managed vector database would be like renting a warehouse to store a shoebox


---

## 14. Terraform Infrastructure as Code

### Overview

All AgentCore infrastructure can be provisioned via Terraform using the AWSCC provider (for AgentCore-specific resources) and the standard AWS provider (for S3, Lambda, IAM).

The Terraform configuration lives in `climate-rag/terraform/` and manages:

| File | Resources |
|---|---|
| `providers.tf` | AWS + AWSCC provider configuration |
| `variables.tf` | Configurable inputs (region, project name, tags) |
| `main.tf` | S3 bucket, IAM roles, Lambda functions (AWS provider) |
| `agentcore.tf` | Memory, Code Interpreter, Gateway, Gateway targets (AWSCC provider) |
| `outputs.tf` | Resource IDs and environment variables for the agent |

### Provider Split: AWS vs AWSCC

AgentCore resources use the AWSCC provider because they're based on CloudFormation resource types (`AWS::BedrockAgentCore::*`). The AWSCC provider auto-generates Terraform resources from CloudFormation schemas, so it gets new resource types as soon as CloudFormation supports them.

Standard AWS resources (S3, Lambda, IAM) use the regular AWS provider because it has better ergonomics and more mature support.

### AWSCC Resource Types Used

```
awscc_bedrockagentcore_memory                  → AgentCore Memory
awscc_bedrockagentcore_code_interpreter_custom → AgentCore Code Interpreter
awscc_bedrockagentcore_gateway                 → AgentCore Gateway
```

### Gateway Targets: The null_resource Workaround

At the time of writing, the AWSCC provider does not include `awscc_bedrockagentcore_gateway_target` as a resource type. We work around this by using `null_resource` with a `local-exec` provisioner that calls the boto3 API directly:

```hcl
resource "null_resource" "gateway_target_nasa" {
  provisioner "local-exec" {
    command = "python3 -c \"import boto3; client.create_gateway_target(...)\""
  }
}
```

This is a pragmatic workaround. When the AWSCC provider adds `gateway_target` support, the `null_resource` blocks should be replaced with proper AWSCC resources.

### Importing Existing Resources

Since we initially created resources manually (via `agentcore` CLI and boto3), we imported them into Terraform state before applying:

```bash
terraform import aws_s3_bucket.index climate-rag-index-816349677272
terraform import aws_lambda_function.nasa_power climate-rag-nasa-power
terraform import aws_lambda_function.noaa_ncei climate-rag-noaa-ncei
```

AWSCC resources (Memory, Gateway, Code Interpreter) were created fresh with `-TF` suffix names to avoid conflicts with the manually-created ones.

### IAM Propagation Timing

One issue we hit: the Gateway target creation failed because the IAM role's Lambda invoke policy hadn't propagated yet. Terraform created the IAM policy and the Gateway target in parallel, but AWS IAM is eventually consistent. The fix was to retry the target creation after a short delay. In production, you'd add an explicit `depends_on` or use a `time_sleep` resource.

### Running the Terraform

```bash
cd climate-rag/terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan

# Get environment variables for the agent
terraform output environment_variables
```

### Cleanup

```bash
terraform destroy
```

This tears down all AgentCore resources, Lambda functions, IAM roles, and the S3 bucket in the correct dependency order.

### Trade-off: Terraform vs agentcore CLI

| Factor | Terraform | agentcore CLI |
|---|---|---|
| Reproducibility | Full — declarative state | Partial — imperative commands |
| Drift detection | Built-in `terraform plan` | Manual |
| Dependency management | Automatic | Manual ordering |
| Gateway targets | Workaround needed (null_resource) | Native support |
| Speed of iteration | Slower (plan/apply cycle) | Faster for prototyping |
| Team collaboration | State locking, code review | Ad-hoc |

For production: use Terraform. For prototyping: use the `agentcore` CLI. For this project, we used the CLI first to iterate quickly, then codified everything in Terraform for reproducibility.


---

## 15. Infrastructure Teardown

### Terraform-Managed Resources

Running `terraform destroy` from the `climate-rag/terraform/` directory removes these 15 resources in dependency order:

```bash
cd /Workshop/climate-rag/terraform
terraform destroy
```

**Resources destroyed:**

| # | Resource | Type |
|---|---|---|
| 1 | `null_resource.gateway_target_nasa` | Fire-and-forget provisioner (actual target deleted with Gateway) |
| 2 | `null_resource.gateway_target_noaa` | Same as above |
| 3 | `awscc_bedrockagentcore_gateway.climate_data` | AgentCore Gateway (deleting it also deletes its targets) |
| 4 | `awscc_bedrockagentcore_memory.climate_rag` | AgentCore Memory |
| 5 | `awscc_bedrockagentcore_code_interpreter_custom.charts` | AgentCore Code Interpreter |
| 6 | `aws_lambda_function.nasa_power` | NASA POWER Lambda proxy |
| 7 | `aws_lambda_function.noaa_ncei` | NOAA NCEI Lambda proxy |
| 8 | `aws_iam_role_policy.gateway_invoke_lambda` | Gateway inline policy |
| 9 | `aws_iam_role.gateway` | Gateway IAM role |
| 10 | `aws_iam_role_policy_attachment.lambda_basic` | Lambda managed policy attachment |
| 11 | `aws_iam_role.lambda` | Lambda IAM role |
| 12 | `aws_s3_bucket_public_access_block.index` | S3 public access block |
| 13 | `aws_s3_bucket_server_side_encryption_configuration.index` | S3 encryption config |
| 14 | `aws_s3_bucket.index` | S3 bucket (force_destroy=true empties it first) |

**Important:** The S3 bucket has `force_destroy = true`, which deletes all objects (including the FAISS index) before destroying the bucket. To preserve the index:

```bash
aws s3 cp s3://climate-rag-index-816349677272/index/ ./backup/ --recursive
```

### Resources NOT Managed by Terraform (Manual Cleanup)

These were created manually before Terraform was introduced, or auto-created by the AgentCore CLI:

| Resource | Cleanup Command |
|---|---|
| Original Memory (`ClimateRAGMemory-JDJxFkEHsS`) | `agentcore memory delete ClimateRAGMemory-JDJxFkEHsS --region us-east-1` |
| Original Gateway (`climatedatagateway-apuexpkgor`) | `agentcore gateway delete-mcp-gateway --gateway-id climatedatagateway-apuexpkgor --region us-east-1` |
| Original Code Interpreter (`ClimateChartInterpreter-yKMvcYfbTO`) | `python3 -c "import boto3; boto3.client('bedrock-agentcore-control', region_name='us-east-1').delete_code_interpreter(codeInterpreterIdentifier='ClimateChartInterpreter-yKMvcYfbTO')"` |
| Manual IAM role (`ClimateRAG-Lambda-Role`) | `aws iam delete-role --role-name ClimateRAG-Lambda-Role` |
| Auto-created IAM role (`AgentCoreGatewayExecutionRole`) | `aws iam delete-role --role-name AgentCoreGatewayExecutionRole` |
| Cognito User Pool (`us-east-1_CTRz0DPc4`) | Delete via AWS Console → Cognito → User Pools |
| CloudWatch log groups (`/aws/vendedlogs/bedrock-agentcore/...`) | `aws logs delete-log-group --log-group-name <name>` |
| Security group rules (ports 443, 8501) | `aws ec2 revoke-security-group-ingress --group-id sg-0bb61b332d5d4bdc5 --protocol tcp --port 8501 --cidr 0.0.0.0/0` (repeat for 443) |
| nginx config | `sudo rm /etc/nginx/sites-enabled/climate-rag && sudo systemctl restart nginx` |
| Streamlit process | `pkill -f streamlit` |
| Local temp files | `rm -rf /tmp/climate-rag-*` |

### Recommended Teardown Order

1. **Stop running services**: Kill Streamlit, remove nginx config
2. **Backup data** (optional): Download FAISS index from S3
3. **Run `terraform destroy`**: Handles the bulk of AWS resources
4. **Clean up original manual resources**: Memory, Gateway, Code Interpreter created via CLI
5. **Clean up auto-created resources**: Cognito, CloudWatch logs, IAM roles
6. **Revert security group**: Remove port 443 and 8501 ingress rules
7. **Clean local artifacts**: `/tmp/climate-rag-*` directories

### Why Two Sets of Resources Exist

During development, we followed this workflow:
1. **Manual creation** (via `agentcore` CLI and boto3) — fast iteration, immediate testing
2. **Terraform codification** — reproducibility, team collaboration, proper IaC

The Terraform resources have a `-TF` suffix (e.g., `ClimateRAGMemoryTF`) to avoid naming conflicts with the manually-created originals. In a clean deployment, you would only use Terraform and there would be a single set of resources.

### Recreating Terraform Provider Binaries

The `.terraform/` directories containing provider binaries are excluded from the zip archive to reduce file size. After unzipping, run `terraform init` in each Terraform directory to download them:

```bash
cd terraform/
terraform init

cd ../climate-rag/terraform/
terraform init
```

The `.terraform.lock.hcl` files are included in the archive and pin exact provider versions. `terraform init` automatically detects the lock file in the current directory and downloads the matching providers — no extra flags needed. Run `terraform providers` afterward to verify the resolved versions match the lock file.
