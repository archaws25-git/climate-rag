# ClimateRAG — Data Flow & Integration Specification

**Date:** 2026-03-26 | **Version:** 1.0

---

## 1. Ingestion Flow (One-Time)

### 1.1 GISTEMP v4

```
Download CSV from data.giss.nasa.gov/gistemp/
  → Parse rows (year, month, anomaly by latitude band)
  → Chunk by decade + latitude band (~500 tokens each)
  → Generate embeddings via Bedrock Titan v2
  → Add to FAISS index
```

### 1.2 GHCN v4

```
Download from NCEI (US stations, 1950-present)
  → Parse station metadata + monthly temperature values
  → Chunk by station + decade (~500 tokens each)
  → Generate embeddings via Bedrock Titan v2
  → Add to FAISS index
```

### 1.3 NASA POWER

```
Query NASA POWER API for 6 US regions
  Parameters: T2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN
  → Chunk by region + year (~500 tokens each)
  → Generate embeddings via Bedrock Titan v2
  → Add to FAISS index
```

### 1.4 Index Build

```
Merge all chunks + embeddings
  → Build FAISS IndexFlatIP (cosine similarity)
  → Upload index + metadata JSON to S3
```

## 2. Runtime Query Flow

```
1. Researcher types query in Streamlit
2. Streamlit calls InvokeAgentRuntime via boto3
3. Strands Agent receives query
4. Agent retrieves last-k turns from Memory (short-term)
5. Agent searches long-term memory for researcher preferences
6. Agent performs FAISS vector search
7. If live data needed: Agent calls Gateway MCP tools
8. Agent assembles context → Claude Sonnet generates answer
9. If chart needed: Agent sends code to Code Interpreter
10. Agent writes turn to Memory
11. Response (text + optional chart) streamed to Streamlit
12. OTEL trace emitted to CloudWatch
```

## 3. External API Integration

### 3.1 NASA POWER API

- Base URL: `https://power.larc.nasa.gov/api/temporal/daily/point`
- Parameters: `T2M`, `T2M_MAX`, `T2M_MIN`, `PRECTOTCORR`, `ALLSKY_SFC_SW_DWN`
- Community: `RE` (Renewable Energy) or `AG` (Agroclimatology)
- Format: JSON or CSV
- Rate limit: max 5 concurrent requests
- Auth: none required

### 3.2 NOAA NCEI Access Data Service

- Base URL: `https://www.ncei.noaa.gov/access/services/data/v1`
- Datasets: `global-summary-of-the-month`, `daily-summaries`
- Parameters: `TAVG`, `TMAX`, `TMIN`, `PRCP`
- Format: JSON or CSV
- Auth: free API token from `ncdc.noaa.gov/cdo-web/webservices/v2`

## 4. Data Schema

### 4.1 Chunk Document Schema

```json
{
  "chunk_id": "gistemp_1970_1979_northern_hemisphere",
  "source": "GISTEMP_v4",
  "text": "Northern Hemisphere temperature anomalies 1970-1979...",
  "metadata": {
    "dataset": "GISTEMP_v4",
    "decade": "1970s",
    "region": "Northern Hemisphere",
    "lat_band": "24N-90N",
    "time_range": "1970-1979",
    "unit": "degrees_C_anomaly",
    "baseline": "1951-1980"
  },
  "embedding": [0.012, -0.034, ...]
}
```

### 4.2 S3 Bucket Structure

```
s3://climate-rag-index-{account_id}/
├── index/
│   ├── faiss.index          # FAISS binary index
│   └── metadata.jsonl       # Chunk metadata (one JSON per line)
├── raw/
│   ├── gistemp/             # Raw GISTEMP CSVs
│   ├── ghcn/                # Raw GHCN data
│   └── power/               # Raw NASA POWER JSONs
└── chunks/
    └── all_chunks.jsonl      # All chunks with text + metadata
```
