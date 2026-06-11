"""Cross-encoder re-ranker for improving retrieval precision.

Takes top-N candidates from hybrid search and re-ranks them using
a more expensive but accurate cross-encoder scoring approach.
Uses Bedrock's Converse API to score query-document relevance.
"""

import logging
import os

import boto3

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")
# Use a fast model for re-ranking — needs to be quick per-candidate
RERANK_MODEL = os.environ.get("CLIMATE_RAG_RERANK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")


def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Re-rank candidates using cross-encoder scoring via LLM.

    Args:
        query: The user's original query.
        candidates: List of result dicts from hybrid search (must have 'text' field).
        top_k: Number of results to return after re-ranking.

    Returns:
        Re-ranked list of candidates (top_k), with added 'rerank_score' field.
    """
    if not candidates or len(candidates) <= top_k:
        return candidates

    try:
        profile = os.environ.get("AWS_PROFILE")
        session = boto3.Session(profile_name=profile, region_name=REGION)
        client = session.client("bedrock-runtime")

        # Score each candidate's relevance to the query
        scored = []
        for candidate in candidates[:10]:  # Limit to top-10 for cost
            score = _score_relevance(client, query, candidate["text"])
            candidate_copy = dict(candidate)
            candidate_copy["rerank_score"] = score
            scored.append(candidate_copy)

        # Sort by rerank score descending
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_k]

    except Exception as e:
        logger.warning("Re-ranker failed, returning original order: %s", e)
        return candidates[:top_k]


def _score_relevance(client, query: str, document: str) -> float:
    """Score how relevant a document is to a query (0-1 scale).

    Uses a lightweight LLM call to assess relevance. Returns a float
    between 0 and 1 where 1 = highly relevant.
    """
    prompt = (
        f"On a scale of 0 to 10, how relevant is this document to the query?\n\n"
        f"Query: {query}\n\n"
        f"Document: {document[:500]}\n\n"
        f"Reply with ONLY a single number (0-10), nothing else."
    )

    try:
        response = client.converse(
            modelId=RERANK_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 5, "temperature": 0.0},
        )

        raw = response["output"]["message"]["content"][0]["text"].strip()
        # Extract number from response
        score = float(raw.split()[0])
        return min(max(score / 10.0, 0.0), 1.0)  # Normalize to 0-1

    except Exception:
        return 0.5  # Default mid-score on failure
