"""ClimateRAG — Unified Golden Dataset for all evaluation suites.

Single source of truth for:
  - Retrieval ground truth (expected chunks/metadata)
  - Single-turn benchmarks (expected tools, sources, keywords)
  - Multi-turn conversation flows (context resolution, coherence)

All eval suites draw from this file. Add new test cases here.
"""

# ── Retrieval Ground Truth ────────────────────────────────────────────────────
# Used by: retrieval suite
# Each entry defines expected metadata matches for search results.

RETRIEVAL_QUERIES = [
    {
        "id": "ret_01",
        "query": "How has average temperature changed in the US Southeast over the last 50 years?",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [{"region": "Southeast"}],
    },
    {
        "id": "ret_02",
        "query": "What is the global temperature anomaly trend since 1880?",
        "expected_source": "GISTEMP_v4",
        "expected_metadata_matches": [{"region": "Global"}],
    },
    {
        "id": "ret_03",
        "query": "Compare temperature trends between New York and Los Angeles since 1950",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [
            {"station_id": "USW00094728"},
            {"station_id": "USW00023174"},
        ],
    },
    {
        "id": "ret_04",
        "query": "What was the average temperature in Chicago in the 1990s?",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [{"station_id": "USW00094846"}],
    },
    {
        "id": "ret_05",
        "query": "Show precipitation data for the Midwest from NASA POWER",
        "expected_source": "NASA_POWER",
        "expected_metadata_matches": [{"region": "Midwest"}],
    },
    {
        "id": "ret_06",
        "query": "Temperature in Alaska over the last 30 years",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [
            {"region": "Alaska"},
            {"station_id": "USW00026451"},
        ],
    },
    {
        "id": "ret_07",
        "query": "Hawaii climate data and temperature trends",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [
            {"region": "Hawaii"},
            {"station_id": "USW00022521"},
        ],
    },
    {
        "id": "ret_08",
        "query": "Warmest decades on record globally",
        "expected_source": "GISTEMP_v4",
        "expected_metadata_matches": [
            {"decade": "2010s"},
            {"decade": "2020s"},
        ],
        "top_k_override": 2,
    },
    {
        "id": "ret_09",
        "query": "Solar radiation trends in the Southeast United States",
        "expected_source": "NASA_POWER",
        "expected_metadata_matches": [{"region": "Southeast"}],
    },
    {
        "id": "ret_10",
        "query": "New York Central Park temperature history",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [{"station_id": "USW00094728"}],
    },
]

# ── Single-Turn E2E Benchmarks ────────────────────────────────────────────────
# Used by: e2e suite (LLM-as-Judge scoring)

E2E_QUERIES = [
    {
        "id": "e2e_01",
        "query": "How has average temperature changed in the US Southeast over the last 50 years?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Atlanta", "Southeast", "warming", "trend", "SOURCE"],
    },
    {
        "id": "e2e_02",
        "query": "What is the global temperature anomaly trend since 1880?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["anomaly", "baseline", "1951-1980", "SOURCE"],
    },
    {
        "id": "e2e_03",
        "query": "Compare temperature trends between New York and Los Angeles since 1950",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["New York", "Los Angeles", "compare", "SOURCE"],
    },
    {
        "id": "e2e_04",
        "query": "Show me the warmest decades on record globally",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["decade", "warmest", "2010s", "2020s"],
    },
    {
        "id": "e2e_05",
        "query": "What does NASA POWER data show for solar radiation in the Southeast?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "NASA_POWER",
        "expected_keywords": ["solar", "radiation", "Southeast"],
    },
    {
        "id": "e2e_06",
        "query": "How does Alaska's temperature trend compare to Hawaii?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Alaska", "Hawaii", "Anchorage", "Honolulu", "SOURCE"],
    },
    {
        "id": "e2e_07",
        "query": "What was the average temperature in Chicago in the 1990s?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Chicago", "1990s", "average", "SOURCE"],
    },
    {
        "id": "e2e_08",
        "query": "What is the temperature difference between the 1950s and 2020s globally?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["1950s", "2020s", "difference", "warming"],
    },
    {
        "id": "e2e_09",
        "query": "What are the temperature trends in Dallas and Houston over the last 40 years?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GHCN_v4",
        "expected_keywords": ["Dallas", "Houston", "South Central", "SOURCE"],
    },
    {
        "id": "e2e_10",
        "query": "What is the ocean surface temperature anomaly near Antarctica?",
        "expected_tools": ["search_climate_data"],
        "expected_source": "GISTEMP_v4",
        "expected_keywords": ["don't have", "insufficient", "confidence"],
    },
]

# ── Multi-Turn Conversation Flows ─────────────────────────────────────────────
# Used by: multiturn suite

MULTITURN_FLOWS = [
    {
        "id": "mt_01",
        "name": "Progressive Drill-Down",
        "description": "Region overview -> specific station -> decade detail",
        "turns": [
            {
                "prompt": "What is the temperature trend in the US Southeast?",
                "expected_behavior": "Returns Southeast GHCN data with station citations",
                "must_contain": ["Southeast", "SOURCE"],
            },
            {
                "prompt": "Which station shows the most warming in that region?",
                "expected_behavior": "References a specific station from previous results",
                "must_contain": ["USW", "warming"],
            },
            {
                "prompt": "Show me the decade-by-decade data for that station",
                "expected_behavior": "Resolves 'that station' from turn 2",
                "must_contain": ["decade", "SOURCE"],
            },
        ],
    },
    {
        "id": "mt_02",
        "name": "Comparison with Follow-Up",
        "description": "Two cities -> add third -> rank them",
        "turns": [
            {
                "prompt": "Compare New York and Los Angeles temperature trends since 1950",
                "expected_behavior": "Shows data for both NYC and LA",
                "must_contain": ["New York", "Los Angeles", "SOURCE"],
            },
            {
                "prompt": "Now add Chicago to that comparison",
                "expected_behavior": "Adds Chicago while retaining NY and LA",
                "must_contain": ["Chicago"],
            },
            {
                "prompt": "Which of the three cities has warmed the most?",
                "expected_behavior": "Ranks all three cities by warming rate",
                "must_contain": ["warming", "SOURCE"],
            },
        ],
    },
    {
        "id": "mt_03",
        "name": "Clarification and Correction",
        "description": "Ambiguous query -> temporal refinement -> comparison",
        "turns": [
            {
                "prompt": "What's the temperature in Atlanta?",
                "expected_behavior": "Returns Atlanta data",
                "must_contain": ["Atlanta", "SOURCE"],
            },
            {
                "prompt": "I meant specifically in the 1990s",
                "expected_behavior": "Narrows to 1990s for Atlanta",
                "must_contain": ["1990", "SOURCE"],
            },
            {
                "prompt": "How does that compare to the current decade?",
                "expected_behavior": "Compares 1990s to 2020s for Atlanta",
                "must_contain": ["2020", "SOURCE"],
            },
        ],
    },
    {
        "id": "mt_04",
        "name": "Cross-Dataset Query",
        "description": "GISTEMP global -> NASA POWER regional -> consistency",
        "turns": [
            {
                "prompt": "Show me global temperature anomalies for the 2010s from GISTEMP",
                "expected_behavior": "Returns GISTEMP v4 data for 2010s",
                "must_contain": ["GISTEMP", "anomal", "2010"],
            },
            {
                "prompt": "What does NASA POWER show for the Southeast in the same period?",
                "expected_behavior": "Switches to NASA POWER, same timeframe",
                "must_contain": ["NASA POWER", "Southeast"],
            },
            {
                "prompt": "Are the global and regional trends consistent?",
                "expected_behavior": "Compares both datasets",
                "must_contain": ["global", "regional"],
            },
        ],
    },
    {
        "id": "mt_05",
        "name": "Research Context Persistence",
        "description": "State topic -> query data -> compare -> summarize",
        "turns": [
            {
                "prompt": "I'm researching how Arctic amplification affects Alaska temperatures",
                "expected_behavior": "Acknowledges topic, may provide initial data",
                "must_contain": ["Alaska"],
            },
            {
                "prompt": "What temperature data do you have for Anchorage and Fairbanks?",
                "expected_behavior": "Returns Alaska station data",
                "must_contain": ["Anchorage", "SOURCE"],
            },
            {
                "prompt": "How do those Alaska warming rates compare to the Midwest?",
                "expected_behavior": "Compares Alaska vs Midwest",
                "must_contain": ["Alaska", "Midwest"],
            },
            {
                "prompt": "Summarize what we've found about my research question",
                "expected_behavior": "Summarizes Arctic amplification findings",
                "must_contain": ["Arctic", "amplification"],
            },
        ],
    },
]
