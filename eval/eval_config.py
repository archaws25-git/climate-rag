"""Evaluation configuration — benchmark queries and expected behaviors.

Covers all 7 US climate regions with the expanded 37-station dataset.
Each query tests a different aspect of the RAG system.
"""

BENCHMARK_QUERIES = [
    # ── Southeast ─────────────────────────────────────────────────────────────
    {
        "id": "eval_01",
        "query": "How has average temperature changed in the US Southeast over the last 50 years?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Atlanta", "Southeast", "warming", "trend", "SOURCE"],
    },
    # ── Global (GISTEMP) ──────────────────────────────────────────────────────
    {
        "id": "eval_02",
        "query": "What is the global temperature anomaly trend since 1880?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["anomaly", "baseline", "1951-1980", "SOURCE"],
    },
    # ── Multi-station comparison ──────────────────────────────────────────────
    {
        "id": "eval_03",
        "query": "Compare temperature trends between New York and Los Angeles since 1950",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["New York", "Los Angeles", "compare", "SOURCE"],
    },
    # ── Global decades ────────────────────────────────────────────────────────
    {
        "id": "eval_04",
        "query": "Show me the warmest decades on record globally",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["decade", "warmest", "2010s", "2020s"],
    },
    # ── NASA POWER ────────────────────────────────────────────────────────────
    {
        "id": "eval_05",
        "query": "What does NASA POWER data show for solar radiation in the Southeast?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "NASA_POWER",
        "expected_keywords": ["solar", "radiation", "Southeast"],
    },
    # ── Chart generation ──────────────────────────────────────────────────────
    {
        "id": "eval_06",
        "query": "Plot annual global temperature anomalies from 1950 to 2025",
        "expected_tools": ["search_climate_data", "generate_chart"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["chart", "plot", "time series"],
    },
    # ── Alaska vs Hawaii (multi-region) ───────────────────────────────────────
    {
        "id": "eval_07",
        "query": "How does Alaska's temperature trend compare to Hawaii?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Alaska", "Hawaii", "Anchorage", "Honolulu", "SOURCE"],
    },
    # ── Specific station + decade ─────────────────────────────────────────────
    {
        "id": "eval_08",
        "query": "What was the average temperature in Chicago in the 1990s?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Chicago", "1990s", "average", "SOURCE"],
    },
    # ── NASA POWER Midwest ────────────────────────────────────────────────────
    {
        "id": "eval_09",
        "query": "Show precipitation data for the Midwest from NASA POWER",
        "expected_tools": ["search_climate_data"],
        "expected_source": "NASA_POWER",
        "expected_keywords": ["precipitation", "Midwest"],
    },
    # ── Temporal comparison ───────────────────────────────────────────────────
    {
        "id": "eval_10",
        "query": "What is the temperature difference between the 1950s and 2020s globally?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["1950s", "2020s", "difference", "warming"],
    },
    # ── South Central region (tests expanded 37-station coverage) ─────────────
    {
        "id": "eval_11",
        "query": "What are the temperature trends in Dallas and Houston over the last 40 years?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Dallas", "Houston", "South Central", "SOURCE"],
    },
    # ── West region multi-station ─────────────────────────────────────────────
    {
        "id": "eval_12",
        "query": "Compare climate between Denver and Phoenix",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Denver", "Phoenix", "West", "SOURCE"],
    },
    # ── Confidence / "I don't know" test ──────────────────────────────────────
    {
        "id": "eval_13",
        "query": "What is the ocean surface temperature anomaly near Antarctica?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["don't have", "insufficient", "confidence", "rephrase"],
    },
    # ── Citation format test ──────────────────────────────────────────────────
    {
        "id": "eval_14",
        "query": "What is the average temperature at Miami International Airport?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Miami", "SOURCE", "GHCN", "USW00012839"],
    },
    # ── Minneapolis (Midwest expansion) ───────────────────────────────────────
    {
        "id": "eval_15",
        "query": "How cold are winters in Minneapolis compared to Boston?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Minneapolis", "Boston", "winter", "SOURCE"],
    },
]
