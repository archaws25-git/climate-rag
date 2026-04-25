"""Evaluation configuration — benchmark queries and expected behaviors."""

BENCHMARK_QUERIES = [
    {
        "id": "eval_01",
        "query": "How has average temperature changed in the US Southeast over the last 50 years?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Atlanta", "Southeast", "warming", "trend"],
    },
    {
        "id": "eval_02",
        "query": "What is the global temperature anomaly trend since 1880?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["anomaly", "baseline", "1951-1980"],
    },
    {
        "id": "eval_03",
        "query": "Compare temperature trends between New York and Los Angeles since 1950",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["New York", "Los Angeles", "compare"],
    },
    {
        "id": "eval_04",
        "query": "Show me the warmest decades on record globally",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["decade", "warmest", "2010s", "2020s"],
    },
    {
        "id": "eval_05",
        "query": "What does NASA POWER data show for solar radiation in the Southeast?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "NASA_POWER",
        "expected_keywords": ["solar", "radiation", "Southeast"],
    },
    {
        "id": "eval_06",
        "query": "Plot annual global temperature anomalies from 1950 to 2025",
        "expected_tools": ["search_climate_data", "generate_chart"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["chart", "plot", "time series"],
    },
    {
        "id": "eval_07",
        "query": "How does Alaska's temperature trend compare to Hawaii?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Alaska", "Hawaii", "Anchorage", "Honolulu"],
    },
    {
        "id": "eval_08",
        "query": "What was the average temperature in Chicago in the 1990s?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Chicago", "1990s", "average"],
    },
    {
        "id": "eval_09",
        "query": "Show precipitation data for the Midwest from NASA POWER",
        "expected_tools": ["search_climate_data"],
        "expected_source": "NASA_POWER",
        "expected_keywords": ["precipitation", "Midwest"],
    },
    {
        "id": "eval_10",
        "query": "What is the temperature difference between the 1950s and 2020s globally?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["1950s", "2020s", "difference", "warming"],
    },
]
