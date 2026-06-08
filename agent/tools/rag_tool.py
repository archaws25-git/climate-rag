"""RAG tool — Hybrid search (FAISS vector + BM25 keyword) with RRF fusion.

Implements a production-grade hybrid retrieval pipeline:
  1. FAISS vector search (semantic similarity via Titan Embeddings v2)
  2. BM25 keyword search (exact term matching via rank_bm25)
  3. Reciprocal Rank Fusion (RRF) to merge and re-rank results

This ensures queries like "NYC", "LA", or abbreviations match via keyword
even when embeddings don't capture the alias relationship.
"""

import json
import os
import re
import tempfile

import boto3
import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from strands import tool

S3_BUCKET = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
INDEX_PREFIX = "index/"
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Confidence thresholds — calibrated to RRF scores (range 0 to ~0.1 typically)
# These are applied to the original FAISS cosine similarity scores
CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.55
CONFIDENCE_LOW = 0.40

# Hybrid search weighting: how much to favor vector vs keyword results
# Higher alpha = more weight on vector (semantic), lower = more on BM25 (keyword)
VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4

# RRF constant (standard value from the RRF paper)
RRF_K = 60

_index = None
_metadata = None
_bm25_index = None
_bm25_corpus_tokens = None


def _get_bedrock_client():
    """Get a Bedrock Runtime client using the configured profile."""
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=BEDROCK_REGION)
    return session.client("bedrock-runtime")


def _embed_query(text: str) -> np.ndarray:
    """Generate embedding vector for a query using Titan Embeddings v2."""
    client = _get_bedrock_client()
    resp = client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text}),
    )
    vec = json.loads(resp["body"].read())["embedding"]
    return np.array(vec, dtype="float32").reshape(1, -1)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer for BM25.

    Lowercases, splits on non-alphanumeric, removes short tokens.
    """
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    return [t for t in tokens if len(t) > 1]


def _build_bm25_index():
    """Build the BM25 index from loaded metadata texts."""
    global _bm25_index, _bm25_corpus_tokens

    if _metadata is None:
        return

    _bm25_corpus_tokens = [_tokenize(doc["text"]) for doc in _metadata]
    _bm25_index = BM25Okapi(_bm25_corpus_tokens)


def _load_index():
    """Load FAISS index + metadata, then build BM25 index on top."""
    global _index, _metadata
    if _index is not None:
        return

    # Try LOCAL index first (fastest, always up-to-date after ingest_all.py)
    chunk_dir = os.environ.get("CHUNK_OUTPUT_DIR", "")
    local_idx = os.path.join(chunk_dir, "index", "faiss.index") if chunk_dir else ""
    local_meta = os.path.join(chunk_dir, "index", "metadata.jsonl") if chunk_dir else ""

    if local_idx and os.path.exists(local_idx) and os.path.exists(local_meta):
        _index = faiss.read_index(local_idx)
        _metadata = []
        with open(local_meta, encoding="utf-8") as f:
            for line in f:
                _metadata.append(json.loads(line))
        _build_bm25_index()
        return

    # Fallback: download from S3
    if not S3_BUCKET:
        raise RuntimeError(
            "No FAISS index available. Either set CHUNK_OUTPUT_DIR with a local index, "
            "or set CLIMATE_RAG_BUCKET and upload the index to S3."
        )

    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=BEDROCK_REGION)
    s3 = session.client("s3")
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

    _build_bm25_index()


def _score_to_confidence(score: float) -> str:
    """Convert cosine similarity score to a human-readable confidence level."""
    if score >= CONFIDENCE_HIGH:
        return "HIGH"
    if score >= CONFIDENCE_MEDIUM:
        return "MEDIUM"
    if score >= CONFIDENCE_LOW:
        return "LOW"
    return "INSUFFICIENT"


def _vector_search(query: str, top_k: int) -> list[tuple[int, float]]:
    """FAISS vector search. Returns list of (doc_index, score) pairs."""
    embedding = _embed_query(query)
    faiss.normalize_L2(embedding)
    scores, indices = _index.search(embedding, top_k)

    results = []
    for i, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        results.append((int(idx), float(scores[0][i])))
    return results


def _bm25_search(query: str, top_k: int) -> list[tuple[int, float]]:
    """BM25 keyword search. Returns list of (doc_index, score) pairs."""
    if _bm25_index is None:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scores = _bm25_index.get_scores(query_tokens)

    # Get top-k indices by score
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score > 0:
            results.append((int(idx), score))
    return results


def _hybrid_search(query: str, top_k: int) -> list[dict]:
    """Hybrid search combining FAISS vector + BM25 keyword via RRF.

    Reciprocal Rank Fusion (RRF) formula:
        rrf_score(doc) = sum( 1 / (k + rank_i(doc)) ) for each retriever i

    We weight the retrievers:
        final_score = VECTOR_WEIGHT * rrf_vector + BM25_WEIGHT * rrf_bm25
    """
    # Run both search backends
    vector_results = _vector_search(query, top_k * 2)  # Over-fetch for better fusion
    bm25_results = _bm25_search(query, top_k * 2)

    # Build RRF scores
    rrf_scores = {}  # doc_index -> weighted RRF score
    vector_raw_scores = {}  # doc_index -> original FAISS cosine score (for confidence)

    # Vector RRF contribution
    for rank, (doc_idx, score) in enumerate(vector_results):
        rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + \
            VECTOR_WEIGHT * (1.0 / (RRF_K + rank + 1))
        vector_raw_scores[doc_idx] = score

    # BM25 RRF contribution
    for rank, (doc_idx, score) in enumerate(bm25_results):
        rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + \
            BM25_WEIGHT * (1.0 / (RRF_K + rank + 1))
        # If this doc wasn't found by vector search, estimate a low vector score
        if doc_idx not in vector_raw_scores:
            vector_raw_scores[doc_idx] = 0.3  # Below CONFIDENCE_LOW threshold

    # Sort by RRF score and take top_k
    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    # Build result dicts
    results = []
    for doc_idx, rrf_score in ranked:
        meta = _metadata[doc_idx]
        # Use the vector similarity score for confidence assessment
        # (more meaningful than RRF score for threshold comparison)
        vector_score = vector_raw_scores.get(doc_idx, 0.3)
        confidence = _score_to_confidence(vector_score)
        metadata = meta.get("metadata", {})
        citation = _build_citation(metadata)

        results.append({
            "score": vector_score,
            "rrf_score": rrf_score,
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


@tool
def search_climate_data(query: str, top_k: int = 5) -> str:
    """Search the climate data vector store for relevant information.

    Uses hybrid search (vector + BM25 keyword) with Reciprocal Rank Fusion
    to combine semantic similarity with exact keyword matching.

    Args:
        query: Natural language query about climate data.
        top_k: Number of results to return (default 5).

    Returns:
        JSON with retrieval results including:
        - confidence_level: HIGH/MEDIUM/LOW/INSUFFICIENT for each result
        - citation: formatted source attribution string
        - retrieval_metadata: overall confidence assessment and search method
    """
    _load_index()

    # Multi-entity detection: if query compares two locations/entities,
    # run separate searches to ensure both are represented in results.
    comparison_pattern = re.compile(
        r'\b(compare|comparing|between|vs\.?|versus)\b', re.IGNORECASE
    )
    if comparison_pattern.search(query):
        return _multi_entity_search(query, top_k)

    results = _hybrid_search(query, top_k)
    return _format_response(results)


def _multi_entity_search(query: str, top_k: int) -> str:
    """Search for multi-entity comparison queries.

    Splits the query into sub-queries for each entity mentioned,
    runs separate hybrid searches, and merges results to ensure both
    entities are represented.
    """
    # Extract entity names from comparison patterns
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
        # Couldn't parse entities — fall back to hybrid search
        results = _hybrid_search(query, top_k)
        return _format_response(results)

    entity_a = match.group(1).strip()
    entity_b = match.group(2).strip()

    # Hybrid search for each entity separately
    per_entity_k = max(5, top_k)
    results_a = _hybrid_search(f"{entity_a} temperature climate data", per_entity_k)
    results_b = _hybrid_search(f"{entity_b} temperature climate data", per_entity_k)

    # Merge: deduplicate by chunk text prefix
    seen_texts = set()
    merged = []
    for r in results_a + results_b:
        text_key = r["text"][:80]
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            merged.append(r)

    # Sort by RRF score descending and limit to top_k
    merged.sort(key=lambda x: x.get("rrf_score", x["score"]), reverse=True)
    merged = merged[:top_k]

    return _format_response(merged)


def _format_response(results: list) -> str:
    """Format results list into the standard JSON response."""
    if not results:
        overall_confidence = "INSUFFICIENT"
    else:
        top_score = results[0]["score"]
        overall_confidence = _score_to_confidence(top_score)

    if overall_confidence == "INSUFFICIENT":
        return json.dumps({
            "retrieval_metadata": {
                "overall_confidence": "INSUFFICIENT",
                "top_score": results[0]["score"] if results else 0.0,
                "search_method": "hybrid (vector + BM25 + RRF)",
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
            "search_method": "hybrid (vector + BM25 + RRF)",
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
