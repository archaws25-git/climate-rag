# ClimateRAG

Production-grade RAG pipeline for historical climate trend analysis, built on Amazon Bedrock AgentCore.

## Quick Start

```bash
# 1. Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r agent/requirements.txt

# 2. Infrastructure
python infra/setup_memory.py
python infra/setup_gateway.py
python infra/setup_code_interpreter.py
python infra/setup_observability.py

# 3. Ingest data
python ingest/ingest_gistemp.py
python ingest/ingest_ghcn.py
python ingest/ingest_power.py
python ingest/embeddings.py
python ingest/build_index.py

# 4. Test locally
cd agent && agentcore dev
# In another terminal:
agentcore invoke --dev '{"prompt": "Global temperature trend?"}'

# 5. Deploy
bash infra/deploy.sh

# 6. Run UI
streamlit run ui/app.py

# 7. Evaluate
python eval/run_eval.py
```

## AgentCore Services Used

| Service | Purpose |
|---|---|
| Runtime | Serverless agent hosting (microVM) |
| Memory | Multi-session researcher context |
| Gateway | NASA POWER + NOAA NCEI as MCP tools |
| Identity | Workload identity + IAM auth |
| Code Interpreter | Chart generation (matplotlib/plotly) |
| Browser | (Stretch) Latest data checks |
| Observability | OTEL traces → CloudWatch |
| Evaluations | Answer quality assessment |
| Policy | Cedar policies on Gateway |

## Datasets

- NOAA GHCN v4 — US station monthly temperatures (1950-present)
- NASA GISTEMP v4 — Global surface temperature anomalies (1880-present)
- NASA POWER — Solar, temperature, precipitation (1981-present)

## Documentation

See [docs/README.md](docs/README.md) for full architecture documentation.
