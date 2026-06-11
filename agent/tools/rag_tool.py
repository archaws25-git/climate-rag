"""RAG tool — Hybrid search (FAISS vector + BM25 keyword) with RRF fusion.

Implements a production-grade hybrid retrieval pipeline:
  1. Metadata pre-filtering (temporal + geographic hard filters)
  2. FAISS vector search (semantic similarity via Titan Embeddings v2)
  3. BM25 keyword search (exact term matching via rank_bm25)
  4. Reciprocal Rank Fusion (RRF) to merge and re-rank results

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

from tools.metadata_filter import apply_metadata_filters

S3_BUCKET = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
INDEX_PREFIX = "index/"
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Confidence thresholds — calibrated to RRF scores (range 0 to ~0.1 typically)
# These are applied to the original FAISS cosine similarity scores
# Calibrated against actual Titan Embeddings v2 score distribution for this corpus:
#   0.45+ = strong semantic match (top result for a targeted query)
#   0.35+ = partial match (related topic, different specifics)
#   0.25+ = weak match (tangentially related)
CONFIDENCE_HIGH = 0.45
CONFIDENCE_MEDIUM = 0.35
CONFIDENCE_LOW = 0.25

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
    """Get a Bedrock Runtime client using the configured profile.

    An empty AWS_PROFILE is treated as unset so boto3 falls back to the
    default credential chain (instance profile, env vars, etc.) rather
    than raising a ProfileNotFound error.
    """
    profile = os.environ.get("AWS_PROFILE") or None
    session = boto3.Session(profile_name=profile, region_name=BEDROCK_REGION)
    return session.client("bedrock-runtime")


def _embed_query(text: str) -> np.ndarray:
    """Generate embedding vector for a query using Titan Embeddings v2 (cached).

    When CLIMATE_RAG_STUB_EMBEDDINGS=1 (e.g. in CI without AWS credentials),
    returns a deterministic pseudo-random vector derived from the query text.
    This allows the full retrieval pipeline (FAISS search, BM25, RRF, metrics)
    to execute without any AWS calls — useful for structural regression checks.
    """
    if os.environ.get("CLIMATE_RAG_STUB_EMBEDDINGS") == "1":
        rng = np.random.default_rng(seed=abs(hash(text)) % (2**31))
        vec = rng.standard_normal((1, 1024)).astype("float32")
        faiss.normalize_L2(vec)
        return vec

    from tools.embedding_cache import get_cached_embedding

    client = _get_bedrock_client()
    return get_cached_embedding(client, text)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer for BM25.

    Lowercases, splits on non-alphanumeric, removes short tokens.
    """
    tokens = re.findall(r"[a-z0-9]+", text.lower())
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

    profile = os.environ.get("AWS_PROFILE") or None
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


def _vector_search(query: str, top_k: int, valid_indices: list = None) -> list[tuple[int, float]]:
    """FAISS vector search. Returns list of (doc_index, score) pairs.

    If valid_indices is provided, only those indices are considered (metadata pre-filter).
    """
    from tracing import timed_span

    with timed_span("climate_rag.search.embed_query", {"model": "titan-embed-v2"}):
        embedding = _embed_query(query)
        faiss.normalize_L2(embedding)

    # If filtering, over-fetch then filter; otherwise standard search
    fetch_k = top_k if valid_indices is None else min(top_k * 3, _index.ntotal)

    with timed_span("climate_rag.search.faiss", {"top_k": fetch_k, "index_size": _index.ntotal}):
        scores, indices = _index.search(embedding, fetch_k)

    results = []
    valid_set = set(valid_indices) if valid_indices is not None else None
    for i, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        if valid_set is not None and int(idx) not in valid_set:
            continue
        results.append((int(idx), float(scores[0][i])))
        if len(results) >= top_k:
            break
    return results


def _bm25_search(query: str, top_k: int, valid_indices: list = None) -> list[tuple[int, float]]:
    """BM25 keyword search. Returns list of (doc_index, score) pairs.

    If valid_indices is provided, only those indices are considered.
    """
    from tracing import timed_span

    if _bm25_index is None:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    with timed_span("climate_rag.search.bm25", {"query_tokens": len(query_tokens), "top_k": top_k}):
        scores = _bm25_index.get_scores(query_tokens)

        if valid_indices is not None:
            # Zero out scores for filtered-out indices
            mask = np.zeros_like(scores)
            for idx in valid_indices:
                if idx < len(mask):
                    mask[idx] = 1.0
            scores = scores * mask

        top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score > 0:
            results.append((int(idx), score))
    return results


def _hybrid_search(query: str, top_k: int) -> list[dict]:
    """Hybrid search combining FAISS vector + BM25 keyword via RRF.

    Applies metadata pre-filters (temporal + geographic) before search
    to reduce the candidate set and improve both speed and relevance.
    """
    # Apply metadata pre-filters
    valid_indices, expected_decades = apply_metadata_filters(_metadata, query)

    # Run both search backends with filtered indices
    vector_results = _vector_search(query, top_k * 2, valid_indices)
    bm25_results = _bm25_search(query, top_k * 2, valid_indices)

    # Build RRF scores
    rrf_scores = {}  # doc_index -> weighted RRF score
    vector_raw_scores = {}  # doc_index -> original FAISS cosine score (for confidence)

    # Vector RRF contribution
    for rank, (doc_idx, score) in enumerate(vector_results):
        rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + VECTOR_WEIGHT * (1.0 / (RRF_K + rank + 1))
        vector_raw_scores[doc_idx] = score

    # BM25 RRF contribution
    for rank, (doc_idx, score) in enumerate(bm25_results):
        rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + BM25_WEIGHT * (1.0 / (RRF_K + rank + 1))
        # If this doc wasn't found by vector search, estimate a low vector score
        if doc_idx not in vector_raw_scores:
            vector_raw_scores[doc_idx] = 0.3  # Below CONFIDENCE_LOW threshold

    # Sort by RRF score and take top_k
    # Apply source preference: boost GHCN station data for temperature queries
    # (both city AND region). Skip boost for solar/precipitation queries
    # where NASA POWER is the only/preferred source.
    from tools.metadata_filter import extract_geo_filter

    geo = extract_geo_filter(query)
    is_geo_query = geo is not None
    is_solar_precip = bool(re.search(r"\b(solar|radiation|precip|rainfall|rain)\b", query, re.IGNORECASE))

    if is_geo_query and not is_solar_precip:
        for doc_idx in rrf_scores:
            meta = _metadata[doc_idx]
            dataset = meta.get("metadata", {}).get("dataset", "")
            if dataset == "GHCN_v4":
                rrf_scores[doc_idx] *= 1.5  # 50% boost for station data

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

        results.append(
            {
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
            }
        )

    # Optional re-ranking pass for precision improvement
    # Only applies when CLIMATE_RAG_RERANK env var is set (adds latency)
    if os.environ.get("CLIMATE_RAG_RERANK") and len(results) > 3:
        from tools.reranker import rerank

        results = rerank(query, results, top_k=top_k)

    return results


@tool
def search_climate_data(query: str, top_k: int = 10) -> str:
    """Search climate data using hybrid vector + keyword search with metadata filtering.

    Args:
        query: Natural language climate data query. Pass verbatim, do not rephrase.
        top_k: Max results (default 10, reduced to 5 for non-comparison queries).

    Returns:
        JSON with results, confidence levels, and citations.
    """
    _load_index()

    # Multi-entity detection: if query compares two locations/entities,
    # run separate searches to ensure both are represented in results.
    comparison_pattern = re.compile(r"\b(compare|comparing|between|vs\.?|versus)\b", re.IGNORECASE)
    if comparison_pattern.search(query):
        return _multi_entity_search(query, top_k)

    # For non-comparison queries, use lower top_k to reduce context sent to LLM
    # Exception: trend/plot/history queries need more results to cover all decades
    trend_pattern = re.compile(
        r"\b(trend|plot|graph|chart|history|since|over time|all decades|anomalies)\b", re.IGNORECASE
    )
    if trend_pattern.search(query):
        effective_k = 15  # Full coverage for multi-decade trend queries
    else:
        effective_k = min(top_k, 3)  # Tight focus for specific queries
    results = _hybrid_search(query, effective_k)
    return _format_response(results)


def _multi_entity_search(query: str, top_k: int) -> str:
    """Search for multi-entity comparison queries.

    Splits the query into sub-queries for each entity mentioned,
    runs separate hybrid searches, and merges results to ensure both
    entities are represented.
    """
    # Extract entity names from comparison patterns
    between_match = re.search(r"between\s+(.+?)\s+and\s+(.+?)(?:\s+since|\s+over|\s+from|\s*$)", query, re.IGNORECASE)
    vs_match = re.search(r"(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:\s+since|\s+over|\s+from|\s*$)", query, re.IGNORECASE)
    compare_match = re.search(
        r"compare\s+(.+?)\s+(?:and|to|with)\s+(.+?)(?:\s+since|\s+over|\s+from|\s*$)", query, re.IGNORECASE
    )
    # Fallback: "X and Y temperature/trends/data"
    and_match = re.search(r"(.+?)\s+and\s+(.+?)(?:\s+temperature|\s+trends|\s+data|\s+climate)", query, re.IGNORECASE)

    match = between_match or vs_match or compare_match or and_match
    if not match:
        # Couldn't parse entities — fall back to hybrid search
        results = _hybrid_search(query, top_k)
        return _format_response(results)

    entity_a = match.group(1).strip()
    entity_b = match.group(2).strip()

    # Hybrid search for each entity separately
    # Use higher k for comparisons so we get multiple decades per entity
    per_entity_k = max(10, top_k)
    results_a = _hybrid_search(f"{entity_a} temperature climate data", per_entity_k)
    results_b = _hybrid_search(f"{entity_b} temperature climate data", per_entity_k)

    # Merge: deduplicate by chunk text prefix
    # Post-filter: keep only results that match one of the parsed entities
    entity_a_lower = entity_a.lower()
    entity_b_lower = entity_b.lower()

    seen_texts = set()
    merged = []
    for r in results_a + results_b:
        text_key = r["text"][:80]
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        # Entity relevance check: station_name or region must contain one of the entities
        station = r.get("station_name", "").lower()
        region = r.get("region", "").lower()
        if (
            entity_a_lower in station
            or entity_a_lower in region
            or entity_b_lower in station
            or entity_b_lower in region
            or r.get("source") == "GISTEMP_v4"
        ):  # Always allow global data through
            merged.append(r)

    # Determine max_results using the temporal range from the original query
    # This is deterministic — based on parsed decade count, not search results
    _, expected_decades = apply_metadata_filters(_metadata, query)
    if expected_decades > 5:
        # Need full decade coverage for both entities
        max_results = expected_decades * 2
    else:
        max_results = 10
    merged.sort(key=lambda x: x.get("rrf_score", x["score"]), reverse=True)
    merged = merged[:max_results]

    return _format_response(merged)


def _format_response(results: list) -> str:
    """Format results into JSON response for the LLM."""
    if not results:
        overall_confidence = "INSUFFICIENT"
    else:
        top_score = results[0]["score"]
        overall_confidence = _score_to_confidence(top_score)

    if overall_confidence == "INSUFFICIENT":
        return json.dumps(
            {
                "retrieval_metadata": {
                    "overall_confidence": "INSUFFICIENT",
                    "top_score": results[0]["score"] if results else 0.0,
                    "search_method": "hybrid (vector + BM25 + RRF + metadata filter)",
                    "message": ("Insufficient data found. Try live NASA POWER or NOAA NCEI API tools, or rephrase."),
                },
                "results": results,
            },
            indent=2,
        )

    return json.dumps(
        {
            "retrieval_metadata": {
                "overall_confidence": overall_confidence,
                "top_score": results[0]["score"] if results else 0.0,
                "num_results": len(results),
                "search_method": "hybrid (vector + BM25 + RRF + metadata filter)",
                "confidence_note": _confidence_note(overall_confidence),
            },
            "results": results,
        },
        indent=2,
    )


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
        "HIGH": (
            "Data IS present in the knowledge base with high relevance. "
            "Present these findings directly. Do NOT claim data is missing."
        ),
        "MEDIUM": (
            "Data IS present but coverage may be partial. Present these findings with a note about partial coverage."
        ),
        "LOW": (
            "Data relevance is low. Present with explicit uncertainty caveats. "
            "Consider trying live API tools for better data."
        ),
    }
    return notes.get(level, "")
