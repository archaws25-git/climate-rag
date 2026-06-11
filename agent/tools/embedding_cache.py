"""Embedding cache — LRU cache for Titan Embeddings v2 queries.

Avoids re-embedding identical queries (saves ~500ms and $0.0001 per hit).
Cache is in-memory, scoped to the process lifetime.

Usage:
    from tools.embedding_cache import get_cached_embedding

    embedding = get_cached_embedding(client, "temperature in Atlanta")
"""

import hashlib
import json
import logging
from collections import OrderedDict

import numpy as np

logger = logging.getLogger(__name__)

# LRU cache with max 512 entries (~2MB at 1024 floats × 4 bytes each)
_MAX_CACHE_SIZE = 512
_cache: OrderedDict[str, np.ndarray] = OrderedDict()
_hits = 0
_misses = 0

MODEL_ID = "amazon.titan-embed-text-v2:0"


def _cache_key(text: str) -> str:
    """Generate a deterministic cache key from query text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def get_cached_embedding(client, text: str) -> np.ndarray:
    """Get embedding from cache or generate via Bedrock.

    Args:
        client: boto3 bedrock-runtime client.
        text: Text to embed.

    Returns:
        numpy array of shape (1, 1024).
    """
    global _hits, _misses

    key = _cache_key(text)

    if key in _cache:
        _hits += 1
        # Move to end (most recently used)
        _cache.move_to_end(key)
        return _cache[key].copy()

    # Cache miss — call Bedrock
    _misses += 1
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({"inputText": text[:8000]}),
    )
    vec = json.loads(resp["body"].read())["embedding"]
    embedding = np.array(vec, dtype="float32").reshape(1, -1)

    # Store in cache
    _cache[key] = embedding.copy()

    # Evict oldest if over capacity
    if len(_cache) > _MAX_CACHE_SIZE:
        _cache.popitem(last=False)

    return embedding


def cache_stats() -> dict:
    """Return cache hit/miss statistics."""
    total = _hits + _misses
    return {
        "hits": _hits,
        "misses": _misses,
        "hit_rate": round(_hits / total, 2) if total > 0 else 0.0,
        "size": len(_cache),
        "max_size": _MAX_CACHE_SIZE,
    }


def clear_cache():
    """Clear the embedding cache (useful for testing)."""
    global _hits, _misses
    _cache.clear()
    _hits = 0
    _misses = 0
