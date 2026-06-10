"""ClimateRAG — Unified metrics module for all eval suites.

Contains:
  - IR metrics: Recall@K, Precision@K, MRR, NDCG@K
  - Generation metrics: composite score from LLM-as-Judge dimensions
  - Latency metrics: P50, P95, P99 computation
"""

import math
from typing import Optional


# ── IR Metrics (Retrieval Suite) ──────────────────────────────────────────────

def is_relevant(result: dict, ground_truth: dict) -> bool:
    """Check if a retrieved result matches any expected metadata."""
    if result.get("source") != ground_truth["expected_source"]:
        return False
    for expected in ground_truth["expected_metadata_matches"]:
        if all(result.get(k, "") == v for k, v in expected.items()):
            return True
    return False


def recall_at_k(results: list, ground_truth: dict, k: int) -> float:
    """Recall@K: fraction of expected relevant items found in top-K."""
    top_k = results[:k]
    total_relevant = len(ground_truth["expected_metadata_matches"])
    if total_relevant == 0:
        return 0.0

    found = 0
    for expected in ground_truth["expected_metadata_matches"]:
        for r in top_k:
            if r.get("source") != ground_truth["expected_source"]:
                continue
            if all(r.get(key, "") == value for key, value in expected.items()):
                found += 1
                break
    return found / total_relevant


def precision_at_k(results: list, ground_truth: dict, k: int) -> float:
    """Precision@K: fraction of top-K results that are relevant."""
    top_k = results[:k]
    if not top_k:
        return 0.0
    relevant_count = sum(1 for r in top_k if is_relevant(r, ground_truth))
    return min(relevant_count / len(top_k), 1.0)


def reciprocal_rank(results: list, ground_truth: dict) -> float:
    """MRR: 1/rank of the first relevant result."""
    for i, r in enumerate(results):
        if is_relevant(r, ground_truth):
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(results: list, ground_truth: dict, k: int) -> float:
    """NDCG@K: normalized discounted cumulative gain."""
    top_k = results[:k]
    num_relevant = len(ground_truth["expected_metadata_matches"])

    dcg = 0.0
    relevant_found = 0
    for i, r in enumerate(top_k):
        if is_relevant(r, ground_truth) and relevant_found < num_relevant:
            dcg += 1.0 / math.log2(i + 2)
            relevant_found += 1

    ideal_k = min(num_relevant, k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_k))

    return dcg / idcg if idcg > 0 else 0.0


# ── Generation Metrics (E2E Suite) ────────────────────────────────────────────

def composite_score(scores: dict) -> float:
    """Weighted composite score from LLM-as-Judge dimensions, normalized to [0, 1].

    Weights:
      correctness 30%, relevance 20%, source_attribution 20%,
      confidence_appropriate 15%, citation 10%, tool_use 5%
    """
    weights = {
        "correctness": 0.30,
        "relevance": 0.20,
        "source_attribution": 0.20,
        "confidence_appropriate": 0.15,
        "citation": 0.10,
        "tool_use": 0.05,
    }
    raw = sum(scores.get(dim, 0) * w for dim, w in weights.items())
    return (raw - 1.0) / 4.0


# ── Latency Metrics ───────────────────────────────────────────────────────────

def percentile(data: list[float], pct: float) -> float:
    """Compute percentile using nearest-rank interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


def latency_summary(latencies_ms: list[float]) -> dict:
    """Compute P50, P95, P99 from a list of latency values in ms."""
    if not latencies_ms:
        return {"p50": 0, "p95": 0, "p99": 0, "mean": 0, "count": 0}
    return {
        "p50": round(percentile(latencies_ms, 50), 0),
        "p95": round(percentile(latencies_ms, 95), 0),
        "p99": round(percentile(latencies_ms, 99), 0),
        "mean": round(sum(latencies_ms) / len(latencies_ms), 0),
        "count": len(latencies_ms),
    }
