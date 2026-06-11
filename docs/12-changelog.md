# ClimateRAG — Changelog

## 2026-06-11 — Performance, Precision & Eval Consolidation

### Hybrid Search
- **BM25 keyword search** added alongside FAISS vector search with Reciprocal Rank Fusion (RRF)
- **Metadata pre-filtering**: Temporal (decade range) + geographic (50-mile radius or region match) applied BEFORE search
- **Word-boundary regex** for city matching: "LA" no longer matches inside "Alaska"
- **GHCN source boost** (1.5x) for temperature queries on both city AND region queries
- **Solar/precipitation bypass**: No GHCN boost for solar/radiation/precip queries (NASA POWER preferred)
- **Dynamic top_k**: 3 for focused queries, 10 for general, 15 for trend/plot queries
- **Entity post-filter**: Multi-entity comparison results filtered to only matching stations
- **Deterministic decade cap**: Multi-entity merge uses temporal range to set result limit (e.g., 8 decades × 2 = 16)

### Data Ingestion
- **GHCN precipitation (PRCP)** added to ingestion pipeline (station-level ground truth)
- **NASA POWER reduced to solar-only** (removed temp/precip — GHCN is more accurate for those)
- **City aliases** in GHCN chunks (NYC, LA, SF, etc.) for BM25 keyword matching
- **City field** added to all 37 stations for proper embedding text

### Performance
- **System prompt trimmed**: 80 lines → 15 lines (-600 tokens)
- **Celsius only**: No duplicate Fahrenheit conversions
- **One chart max**: Only generated when explicitly asked ("plot", "chart", "graph")
- **Bedrock timeout**: 120s read timeout via BotocoreConfig
- **Skip memory reconstruction on first turn**: Saves 1-2s on initial query
- **Streaming**: Token-by-token via Strands `stream_async` with async→sync bridge
- **TTFT progress indicator**: "🔍 Searching climate data..." shown until first token

### Latency Metrics
- P50: 25.7s → **12.5s** (51% improvement)
- P95: 39.7s → **21.5s** (46% improvement)
- Error rate: 20% → **0%** (orphan recovery)

### Memory & History
- **History reconstruction from AgentCore Memory**: Rebuilds Bedrock messages on restart
- **EventMessage handling**: Correctly parses SDK's `EventMessage` objects (not plain dicts)
- **Orphan tool_use recovery**: Both streaming and non-streaming paths clear + retry
- **Conversation sanitizer**: Trims trailing orphaned messages while preserving valid history

### Evaluation Framework
- **Consolidated eval runner** (`eval/run.py`): Single entry point for all 4 suites
- **Golden dataset** (`eval/golden_dataset.py`): Unified test data (retrieval + E2E + multiturn)
- **Shared judge module** (`eval/judge.py`): LLM-as-Judge for both single and multi-turn
- **Metrics module** (`eval/metrics.py`): IR + composite + latency percentile computation
- **Eval dashboard**: Streamlit page with metric cards, tables, bar charts, and trend lines

### Testing
- **243 unit tests** (up from 136), 78% coverage
- **5 integration tests** for Memory reconstruction (5-turn round-trip)
- **Fixed boto3 mocking**: All tests use `patch("boto3.Session")` matching actual code
- **Metadata filter tests**: 20 tests covering temporal, geo, haversine, combined filters
- **Chart tool guard tests**: 6 tests for sandbox error detection
- **Latency tracker tests**: 14 tests for timing, TTFT, percentiles

### Infrastructure
- **provision_agentcore.py**: Correct API response keys (`items` not `gatewaySummaries`, `memories` not `memorySummaries`)
- **Teardown wait loop**: Polls targets until removed before deleting gateway
- **Multi-strategy resource lookup**: list → SSM → CloudFormation → manual ID
- **CLI overrides**: `--memory-id`, `--gateway-id`, `--code-interpreter-id` flags

### CI/CD
- **Ruff only** (flake8 removed): Single linter, faster CI
- **Coverage threshold**: 78% enforced
- **Load test workflow**: Manual dispatch with OIDC AWS credentials

---

## 2026-06-10 — Gateway Teardown Reliability

### Infrastructure
- **Gateway teardown wait loop**: `_teardown_gateway` now polls (up to 60s) for targets to be fully removed before deleting the gateway, preventing ConflictException errors
- **Idempotent target deletion**: Handles `ResourceNotFoundException` gracefully when targets are already deleted

---

## 2026-06-06 — Retrieval Quality & Evaluation Improvements

### Retrieval Architecture
- **Multi-entity search**: RAG tool detects comparison queries ("compare X and Y", "between", "vs") and splits into separate sub-queries per entity, merging results to ensure both are represented
- **Confidence scoring**: Every search result includes confidence level (HIGH/MEDIUM/LOW/INSUFFICIENT) with appropriate response guidance
- **Source citations**: Each result includes formatted `[SOURCE: Dataset | Station/Region | Period]` citation strings
- **"I don't know" fallback**: When confidence is INSUFFICIENT, system advises user to try live APIs or rephrase

### Chunk Text Optimization (Embedding Quality)
- **Region synonyms**: GHCN chunks include "Southeast (US Southeast, Southeastern US)" for all 7 regions
- **City name prominence**: Added explicit "City: Chicago" to improve city-specific query matching
- **GISTEMP warmth annotations**: Recent decades (2000s+) include "warmest decades on record globally" in text
- **NASA POWER leading keywords**: Chunks lead with "precipitation, solar radiation, and climate data"
- **37-station expansion**: Expanded from 6 to 37 stations across all major US climate regions

### Synthetic Data Calibration
- **Arctic amplification**: Alaska warms at 0.015°C/yr (2x US average), Hawaii at 0.004°C/yr
- **GISTEMP verified values**: Decadal anomalies calibrated to NASA GISS published data
- **NASA POWER verified values**: Temperatures from NOAA Normals, solar from NREL NSRDB
- **Explicit warning**: Scripts print prominent ⚠️ warning when using synthetic vs. live data

### Data Pipeline
- **Cleanup script** (`ingest/cleanup.py`): Removes local chunks, embeddings, index, AND stale S3 data
- **Unified pipeline** (`ingest/ingest_all.py`): Single command for full rebuild with verification
- **Verification step**: Pipeline exits with error if any embedded file is missing after Titan v2 call
- **Profile-aware boto3**: All AWS calls use `boto3.Session(profile_name=...)` for SSO compatibility

### Evaluation Improvements
- **Retrieval eval uses local index**: Bypasses S3 to always test against latest rebuilt index
- **NDCG fixed**: Now correctly bounded to [0, 1] (was exceeding 1.0 due to counting bug)
- **Precision fixed**: Standard `relevant/K` capped at 1.0
- **Per-query top_k_override**: Queries with < K relevant docs use reduced K to avoid precision penalty
- **LLM-as-Judge dimensions expanded**: Added `confidence_appropriate` and `source_attribution`
- **Memory disabled during eval**: Prevents ExpiredTokenException from crashing eval runs
- **All thresholds at 90%**: Recall, Precision, MRR, NDCG all require ≥ 0.9

### Configuration & Security
- **Centralized config** (`config.py`): Auto-loads .env, detects AWS profile, reads SSM/CloudFormation
- **`.env` file**: Template provided (`.env.example`), actual `.env` in `.gitignore`
- **Memory resilience**: `save_turn()` wrapped in try/except — never crashes the agent request
- **Guardrails fail-open**: Guardrail service outage doesn't block user requests
- **Bandit clean**: 0 medium/high severity findings

### CDK Infrastructure
- **Async polling pattern**: `on_event` + `is_complete` with 40-min total timeout
- **Idempotent creates**: Checks for existing resources before creating (handles rollback orphans)
- **READY status support**: Code Interpreter returns "READY" not "ACTIVE" — both accepted
- **Gateway targets in is_complete**: Created after gateway reaches ACTIVE using props from event
- **IAM retry**: Gateway creation retries on AccessDeniedException (IAM propagation delay)

### CI/CD
- **GitHub Actions workflow** (`.github/workflows/ci.yml`): ruff lint, unit tests, bandit, CDK synth
- **ruff configured**: Import sorting, line length 120, Python 3.12 target
- **pytest-timeout**: Added for load test time limits

---

## 2026-06-03 — Initial Test Suite & Infrastructure

- Created 71 unit tests across 9 test modules
- Overall coverage: 87%+
- CDK stack fixes: dispatch keys, boto3 endpoint, response paths, required parameters
- Bedrock Guardrails integration (input/output filtering)
- System prompt with citation rules and confidence levels
- Integration tests for AWS connectivity verification
