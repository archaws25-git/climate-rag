"""RAG tool — FAISS vector search with confidence scoring and source attribution."""

import json
import os
import tempfile

import boto3
import faiss
import numpy as np
from strands import tool

S3_BUCKET = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
INDEX_PREFIX = "index/"
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Confidence thresholds — calibrated to cosine similarity scores from FAISS
# Scores are inner product after L2 normalization (range 0 to 1)
CONFIDENCE_HIGH = 0.75       # Strong match — high confidence in answer
CONFIDENCE_MEDIUM = 0.55     # Partial match — moderate confidence
CONFIDENCE_LOW = 0.40        # Weak match — low confidence, flag uncertainty
# Below LOW: "I don't know" fallback triggered

_index = None
_metadata = None


def _get_bedrock_client():
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=BEDROCK_REGION)
    return session.client("bedrock-runtime")


def _embed_query(text: str) -> np.ndarray:
    client = _get_bedrock_client()
    resp = client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text}),
    )
    vec = json.loads(resp["body"].read())["embedding"]
    return np.array(vec, dtype="float32").reshape(1, -1)


def _load_index():
    global _index, _metadata
    if _index is not None:
        return

    s3 = boto3.client("s3", region_name=BEDROCK_REGION)
    tmpdir = tempfile.mkdtemp()

    idx_path = os.path.join(tmpdir, "faiss.index")
    meta_path = os.path.join(tmpdir, "metadata.jsonl")

    s3.download_file(S3_BUCKET, f"{INDEX_PREFIX}faiss.index", idx_path)
    s3.download_file(S3_BUCKET, f"{INDEX_PREFIX}metadata.jsonl", meta_path)

    _index = faiss.read_index(idx_path)

    _metadata = []
    with open(meta_path, encoding="utf-8") as f:
        for line in f:
            _metadata.append(json.loads(line))


def _score_to_confidence(score: float) -> str:
    """Convert cosine similarity score to a human-readable confidence level."""
    if score >= CONFIDENCE_HIGH:
        return "HIGH"
    if score >= CONFIDENCE_MEDIUM:
        return "MEDIUM"
    if score >= CONFIDENCE_LOW:
        return "LOW"
    return "INSUFFICIENT"


@tool
def search_climate_data(query: str, top_k: int = 5) -> str:
    """Search the climate data vector store for relevant information.

    Returns results with confidence levels and source citations.
    If confidence is INSUFFICIENT, returns an "I don't know" message
    advising the user to try live API tools or rephrase.

    Args:
        query: Natural language query about climate data.
        top_k: Number of results to return (default 5).

    Returns:
        JSON with retrieval results including:
        - confidence_level: HIGH/MEDIUM/LOW/INSUFFICIENT for each result
        - citation: formatted source attribution string
        - retrieval_metadata: overall confidence assessment
    """
    _load_index()

    # Multi-entity detection: if query compares two locations/entities,
    # run separate searches to ensure both are represented in results.
    import re
    comparison_pattern = re.compile(
        r'\b(compare|comparing|between|vs\.?|versus)\b', re.IGNORECASE
    )
    if comparison_pattern.search(query):
        return _multi_entity_search(query, top_k)

    return _single_search(query, top_k)


def _single_search(query: str, top_k: int) -> str:
    """Standard single-vector search."""
    embedding = _embed_query(query)
    faiss.normalize_L2(embedding)
    scores, indices = _index.search(embedding, top_k)

    results = []
    for i, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        meta = _metadata[idx]
        score = float(scores[0][i])
        confidence = _score_to_confidence(score)
        metadata = meta.get("metadata", {})

        citation = _build_citation(metadata)

        results.append({
            "score": score,
            "confidence_level": confidence,
            "citation": citation,
            "text": meta["text"],
            "source": metadata.get("dataset", "unknown"),
            "region": metadata.get("region", ""),
            "decade": metadata.get("decade", ""),
            "station_id": metadata.get("station_id", ""),
            "station_name": metadata.get("station_name", ""),
            "time_range": metadata.get("time_range", ""),
        })

    return _format_response(results)


def _multi_entity_search(query: str, top_k: int) -> str:
    """Search for multi-entity comparison queries.

    Splits the query into sub-queries for each entity mentioned,
    runs separate searches, and merges results to ensure both
    entities are represented.
    """
    import re

    # Extract entity names from comparison patterns
    # Handles: "between X and Y", "X vs Y", "X compared to Y"
    between_match = re.search(
        r'between\s+(.+?)\s+and\s+(.+?)(?:\s+since|\s+over|\s+from|\s*$)',
        query, re.IGNORECASE
    )
    vs_match = re.search(
        r'(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:\s+since|\s+over|\s+from|\s*$)',
        query, re.IGNORECASE
    )
    compare_match = re.search(
        r'compare\s+(?:climate\s+)?(?:between\s+)?(.+?)\s+(?:and|to|with)\s+(.+?)(?:\s+since|\s+over|\s+from|\s*$)',
        query, re.IGNORECASE
    )

    match = between_match or vs_match or compare_match
    if not match:
        # Couldn't parse entities — fall back to single search
        return _single_search(query, top_k)

    entity_a = match.group(1).strip()
    entity_b = match.group(2).strip()

    # Search for each entity separately, allocating enough results per entity
    per_entity_k = max(5, top_k)

    results_a = _search_raw(f"{entity_a} temperature climate data", per_entity_k)
    results_b = _search_raw(f"{entity_b} temperature climate data", per_entity_k)

    # Merge: interleave results, deduplicate by chunk text
    seen_texts = set()
    merged = []
    for r in results_a + results_b:
        text_key = r["text"][:80]
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            merged.append(r)

    # Sort by score descending and limit to top_k
    merged.sort(key=lambda x: x["score"], reverse=True)
    merged = merged[:top_k]

    return _format_response(merged)


def _search_raw(query: str, top_k: int) -> list:
    """Raw search returning list of result dicts (no JSON formatting)."""
    embedding = _embed_query(query)
    faiss.normalize_L2(embedding)
    scores, indices = _index.search(embedding, top_k)

    results = []
    for i, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        meta = _metadata[idx]
        score = float(scores[0][i])
        confidence = _score_to_confidence(score)
        metadata = meta.get("metadata", {})
        citation = _build_citation(metadata)

        results.append({
            "score": score,
            "confidence_level": confidence,
            "citation": citation,
            "text": meta["text"],
            "source": metadata.get("dataset", "unknown"),
            "region": metadata.get("region", ""),
            "decade": metadata.get("decade", ""),
            "station_id": metadata.get("station_id", ""),
            "station_name": metadata.get("station_name", ""),
            "time_range": metadata.get("time_range", ""),
        })

    return results


def _format_response(results: list) -> str:
    """Format results list into the standard JSON response."""
    # Compute overall retrieval confidence
    if not results:
        overall_confidence = "INSUFFICIENT"
    else:
        top_score = results[0]["score"]
        overall_confidence = _score_to_confidence(top_score)

    # If confidence is INSUFFICIENT, return a clear "I don't know" signal
    if overall_confidence == "INSUFFICIENT":
        return json.dumps({
            "retrieval_metadata": {
                "overall_confidence": "INSUFFICIENT",
                "top_score": results[0]["score"] if results else 0.0,
                "message": (
                    "I could not find sufficiently relevant data in the vector store "
                    "for this query. Confidence is below the minimum threshold. "
                    "Consider: (1) trying the live NASA POWER or NOAA NCEI API tools, "
                    "(2) rephrasing your question, or (3) acknowledging the data gap."
                ),
            },
            "results": results,
        }, indent=2)

    return json.dumps({
        "retrieval_metadata": {
            "overall_confidence": overall_confidence,
            "top_score": results[0]["score"] if results else 0.0,
            "num_results": len(results),
            "confidence_note": _confidence_note(overall_confidence),
        },
        "results": results,
    }, indent=2)


def _build_citation(metadata: dict) -> str:
    """Build a human-readable citation string from chunk metadata."""
    dataset = metadata.get("dataset", "Unknown")
    station_id = metadata.get("station_id", "")
    station_name = metadata.get("station_name", "")
    region = metadata.get("region", "")
    time_range = metadata.get("time_range", "")
    decade = metadata.get("decade", "")

    parts = [f"[{dataset}]"]
    if station_name:
        parts.append(f"Station: {station_name} ({station_id})")
    elif region:
        parts.append(f"Region: {region}")
    if time_range:
        parts.append(f"Period: {time_range}")
    elif decade:
        parts.append(f"Decade: {decade}")

    return " | ".join(parts)


def _confidence_note(level: str) -> str:
    """Return guidance for the agent based on confidence level."""
    notes = {
        "HIGH": "Data is highly relevant. Present findings with confidence and cite sources.",
        "MEDIUM": (
            "Data is moderately relevant. Present findings but note that coverage "
            "may be partial. Consider supplementing with live API data."
        ),
        "LOW": (
            "Data relevance is low. Present with explicit uncertainty caveats. "
            "Strongly recommend trying live API tools for more relevant data. "
            "State: 'Based on limited available data...' in your response."
        ),
    }
    return notes.get(level, "")
