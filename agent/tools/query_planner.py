"""LLM-based query planning — replaces regex entity detection.

Uses the LLM to decompose complex queries into sub-queries.
Handles:
  - Multi-entity comparisons ("Compare NY and LA")
  - Temporal refinements ("in the 1990s")
  - Dataset routing ("from NASA POWER")
"""

import json
import logging
import os

import boto3

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")
PLANNER_MODEL = os.environ.get(
    "CLIMATE_RAG_PLANNER_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

PLANNER_PROMPT = """You are a query planner for a climate data retrieval system.
Given a user query, determine if it should be split into multiple sub-queries.

Rules:
- If the query mentions TWO or more distinct locations/stations, split into one sub-query per location.
- If the query is about a single topic, return it as-is (one sub-query).
- Each sub-query should be a self-contained search query.
- Add "temperature climate data" to each sub-query for better retrieval.

Return ONLY a JSON object:
{
  "is_multi_entity": true/false,
  "sub_queries": ["query1", "query2", ...]
}

Examples:
- "Compare New York and Los Angeles" → {"is_multi_entity": true, "sub_queries": ["New York temperature climate data", "Los Angeles temperature climate data"]}
- "Temperature in Alaska" → {"is_multi_entity": false, "sub_queries": ["Temperature in Alaska"]}
- "How does Denver compare to Phoenix?" → {"is_multi_entity": true, "sub_queries": ["Denver temperature climate data", "Phoenix temperature climate data"]}
"""


def plan_query(query: str) -> dict:
    """Decompose a query into sub-queries using LLM reasoning.

    Args:
        query: The user's natural language query.

    Returns:
        Dict with:
          - is_multi_entity: bool
          - sub_queries: list of search strings
    """
    try:
        profile = os.environ.get("AWS_PROFILE")
        session = boto3.Session(profile_name=profile, region_name=REGION)
        client = session.client("bedrock-runtime")

        response = client.converse(
            modelId=PLANNER_MODEL,
            system=[{"text": PLANNER_PROMPT}],
            messages=[{"role": "user", "content": [{"text": query}]}],
            inferenceConfig={"maxTokens": 200, "temperature": 0.0},
        )

        raw = response["output"]["message"]["content"][0]["text"].strip()

        # Parse JSON response
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        plan = json.loads(raw)

        # Validate structure
        if "is_multi_entity" not in plan or "sub_queries" not in plan:
            raise ValueError("Invalid plan structure")

        if not plan["sub_queries"]:
            plan["sub_queries"] = [query]

        logger.info("Query plan: multi=%s, sub_queries=%d", plan["is_multi_entity"], len(plan["sub_queries"]))
        return plan

    except Exception as e:
        # Fallback: return query as-is (no decomposition)
        logger.warning("Query planning failed, using original query: %s", e)
        return {"is_multi_entity": False, "sub_queries": [query]}
