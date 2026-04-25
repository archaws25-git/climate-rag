# ClimateRAG — Implementation Plan

**Date:** 2026-03-26 | **Version:** 1.0

---

## 1. Timeline (8 Hours)

| Hour | Phase | Tasks | Deliverables |
|---|---|---|---|
| 0-1 | Scaffolding | Project structure, venv, dependencies, infra setup scripts | `climate-rag/` directory, `requirements.txt`, setup scripts |
| 1-3 | Data Ingestion | Download GISTEMP + GHCN + POWER, chunk, embed, build FAISS | S3 bucket with FAISS index + metadata |
| 3-5 | Agent Core | Strands Agent with RAG tool, Gateway MCP tools, Memory, Code Interpreter | Working agent testable via `agentcore dev` |
| 5-6 | UI | Streamlit chat with inline chart rendering | `app.py` running locally |
| 6-7 | Deploy + Test | `agentcore launch`, end-to-end testing, fix issues | Agent deployed to AgentCore Runtime |
| 7-8 | Production | Evaluations, observability verification, README | Eval results, CloudWatch dashboard, docs |

## 2. Project Structure

```
climate-rag/
├── docs/                        # This documentation folder
├── agent/
│   ├── main.py                  # Strands Agent definition + tools
│   ├── tools/
│   │   ├── rag_tool.py          # FAISS vector search
│   │   ├── memory_tool.py       # AgentCore Memory integration
│   │   └── chart_tool.py        # Code Interpreter chart generation
│   ├── prompts/
│   │   └── system_prompt.txt    # Climate analyst system prompt
│   └── requirements.txt
├── gateway/
│   ├── lambda_nasa_power/
│   │   └── handler.py           # Lambda proxy for NASA POWER API
│   ├── lambda_noaa_ncei/
│   │   └── handler.py           # Lambda proxy for NOAA NCEI API
│   └── gateway_config.py        # Gateway + target creation script
├── ingest/
│   ├── ingest_gistemp.py        # GISTEMP v4 download + chunking
│   ├── ingest_ghcn.py           # GHCN v4 download + chunking
│   ├── ingest_power.py          # NASA POWER API download + chunking
│   ├── embeddings.py            # Bedrock Titan embedding generation
│   └── build_index.py           # FAISS index builder + S3 upload
├── eval/
│   ├── eval_config.py           # Evaluation setup + test cases
│   └── run_eval.py              # On-demand evaluation runner
├── ui/
│   └── app.py                   # Streamlit chat + visualization app
├── infra/
│   ├── setup_memory.py          # AgentCore Memory creation
│   ├── setup_gateway.py         # Gateway + targets + Cedar policies
│   ├── setup_code_interpreter.py
│   ├── setup_observability.py   # CloudWatch Transaction Search
│   └── deploy.sh                # agentcore launch wrapper
├── .bedrock_agentcore.yaml
└── README.md
```

## 3. Dependencies

```
# Core
bedrock-agentcore
bedrock-agentcore-starter-toolkit
strands-agents

# Data processing
pandas
numpy
faiss-cpu
requests

# Embeddings + LLM
boto3

# Visualization
matplotlib
plotly

# UI
streamlit
```

## 4. Prerequisites Checklist

- [ ] AWS account with credentials configured (`aws configure`)
- [ ] Python 3.10+ installed
- [ ] Bedrock model access enabled: Claude Sonnet + Titan Embeddings v2
- [ ] AgentCore permissions (see Runtime permissions docs)
- [ ] NOAA CDO API token (free, from ncdc.noaa.gov/cdo-web/webservices/v2)
- [ ] S3 bucket created: `climate-rag-index-{account_id}`

## 5. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NASA/NOAA API downtime during ingestion | Low | High | Cache raw data locally; retry logic |
| FAISS index too large for microVM memory | Low | High | Filter to US-only stations; reduce chunk count |
| AgentCore Runtime cold start too slow | Medium | Medium | Pre-warm with initial invocation |
| Claude Sonnet rate limits | Low | Medium | Implement exponential backoff |
| 8-hour timeline too tight | Medium | High | Prioritize P0 requirements; defer Browser (P1) |
