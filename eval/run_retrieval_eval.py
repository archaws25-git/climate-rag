"""
Retrieval quality evaluation for ClimateRAG.

Measures retrieval-specific metrics that are independent of the LLM generation:
  - Recall@K      — are the relevant chunks actually being retrieved?
  - Precision@K   — of what's retrieved, how much is actually relevant?
  - MRR           — how highly are correct chunks ranked?
  - NDCG@K        — normalized ranking quality score
  - Confidence    — average retrieval confidence level

Also includes:
  - Index integrity checks (vector count, dimension, search health)
  - Confidence threshold validation

Usage:
    python eval/run_retrieval_eval.py
    python eval/run_retrieval_eval.py --top-k 10
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

# Load all environment variables from .env + SSM
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402, F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

# ── Retrieval Ground Truth ────────────────────────────────────────────────────
# Each query has expected relevant chunks identified by dataset + metadata matches.
# A retrieved chunk is "relevant" if it matches the expected_source AND any of the
# expected_metadata_matches (station, region, or decade).

RETRIEVAL_GROUND_TRUTH = [
    {
        "id": "ret_01",
        "query": "How has average temperature changed in the US Southeast over the last 50 years?",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [
            {"region": "Southeast"},
        ],
    },
    {
        "id": "ret_02",
        "query": "What is the global temperature anomaly trend since 1880?",
        "expected_source": "GISTEMP_v4",
        "expected_metadata_matches": [
            {"region": "Global"},
        ],
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
        "expected_metadata_matches": [
            {"station_id": "USW00094846"},
        ],
    },
    {
        "id": "ret_05",
        "query": "Show precipitation data for the Midwest from NASA POWER",
        "expected_source": "NASA_POWER",
        "expected_metadata_matches": [
            {"region": "Midwest"},
        ],
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
        "top_k_override": 2,  # Only 2 relevant docs exist; avoid precision penalty from irrelevant fill
    },
    {
        "id": "ret_09",
        "query": "Solar radiation trends in the Southeast United States",
        "expected_source": "NASA_POWER",
        "expected_metadata_matches": [
            {"region": "Southeast"},
        ],
    },
    {
        "id": "ret_10",
        "query": "New York Central Park temperature history",
        "expected_source": "GHCN_v4",
        "expected_metadata_matches": [
            {"station_id": "USW00094728"},
        ],
    },
]


# ── Retrieval Metrics ─────────────────────────────────────────────────────────

def is_relevant(result: dict, ground_truth: dict) -> bool:
    """Check if a retrieved result matches any expected metadata."""
    # Source must match
    if result.get("source") != ground_truth["expected_source"]:
        return False

    # Check if any metadata criterion matches
    for expected in ground_truth["expected_metadata_matches"]:
        matches_all = True
        for key, value in expected.items():
            if result.get(key, "") != value:
                matches_all = False
                break
        if matches_all:
            return True

    return False


def recall_at_k(results: list, ground_truth: dict, k: int) -> float:
    """Recall@K: fraction of expected relevant items found in top-K.

    Measures how many of the expected metadata matches appear in the
    retrieved results. For scientific accuracy, each expected match
    criterion must be found independently.
    """
    top_k = results[:k]
    total_relevant = len(ground_truth["expected_metadata_matches"])
    if total_relevant == 0:
        return 0.0

    # Count how many distinct expected criteria are satisfied
    found = 0
    for expected in ground_truth["expected_metadata_matches"]:
        for r in top_k:
            if r.get("source") != ground_truth["expected_source"]:
                continue
            matches_all = True
            for key, value in expected.items():
                if r.get(key, "") != value:
                    matches_all = False
                    break
            if matches_all:
                found += 1
                break  # This criterion is satisfied, move to next

    return found / total_relevant


def precision_at_k(results: list, ground_truth: dict, k: int) -> float:
    """Precision@K: fraction of top-K results that are relevant.

    Standard IR precision: relevant_found / K.
    Capped at 1.0 — if all results are relevant, precision = 1.0.
    """
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
    """NDCG@K: normalized discounted cumulative gain.

    Returns a value in [0, 1]. 1.0 means all relevant items are ranked
    at the top positions. The score accounts for ranking quality.
    """
    top_k = results[:k]
    num_relevant = len(ground_truth["expected_metadata_matches"])

    # DCG: sum of relevance / log2(rank+1), capped at num_relevant hits
    dcg = 0.0
    relevant_found = 0
    for i, r in enumerate(top_k):
        if is_relevant(r, ground_truth) and relevant_found < num_relevant:
            dcg += 1.0 / math.log2(i + 2)  # +2 because rank starts at 1
            relevant_found += 1

    # Ideal DCG: all relevant items at the very top positions
    ideal_k = min(num_relevant, k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_k))

    return dcg / idcg if idcg > 0 else 0.0


# ── Index Integrity Checks ────────────────────────────────────────────────────

def check_index_integrity():
    """Validate FAISS index health and properties.

    Uses whatever index is currently loaded in the rag_module.
    Does NOT call _load_index() — the caller is responsible for loading.
    """
    import tools.rag_tool as rag_module

    print("\n📐 Index Integrity Checks")
    print("-" * 40)

    # If not yet loaded, load now (will use S3 as fallback)
    if rag_module._index is None:
        from tools.rag_tool import _load_index
        _load_index()

    index = rag_module._index
    metadata = rag_module._metadata

    # Vector count
    print(f"  Total vectors:  {index.ntotal}")
    assert index.ntotal > 0, "Index is empty!"

    # Dimension
    print(f"  Dimension:      {index.d}")
    assert index.d == 1024, f"Expected 1024 dimensions, got {index.d}"

    # Metadata count matches index
    print(f"  Metadata count: {len(metadata)}")
    assert len(metadata) == index.ntotal, (
        f"Metadata count ({len(metadata)}) != index vectors ({index.ntotal})"
    )

    # Each metadata entry has required fields
    required_fields = ["text", "metadata"]
    for i, m in enumerate(metadata[:5]):  # Check first 5
        for field in required_fields:
            assert field in m, f"Chunk {i} missing field: {field}"

    # Search health: a random query should return results
    import numpy as np
    random_vec = np.random.randn(1, 1024).astype("float32")
    faiss_module = __import__("faiss")
    faiss_module.normalize_L2(random_vec)
    scores, indices_result = index.search(random_vec, 3)
    assert indices_result[0][0] != -1, "Search returned no results for random vector"
    print(f"  Search health:  ✅ (random query returned {(indices_result[0] != -1).sum()} results)")

    # Dataset distribution
    datasets = {}
    for m in metadata:
        ds = m.get("metadata", {}).get("dataset", "unknown")
        datasets[ds] = datasets.get(ds, 0) + 1
    print(f"  Dataset distribution:")
    for ds, count in sorted(datasets.items()):
        print(f"    {ds}: {count} chunks")

    print("  ✅ All integrity checks passed\n")
    return True


# ── Main Evaluation ───────────────────────────────────────────────────────────

def run_retrieval_eval(top_k: int = 5):
    """Run retrieval evaluation against ground truth."""
    import importlib

    import tools.rag_tool as rag_module

    # Reload to clear any stale state from previous imports
    importlib.reload(rag_module)
    rag_module._index = None
    rag_module._metadata = None

    # Load LOCAL index directly — bypasses S3 entirely.
    # This ensures we always test against the LATEST rebuilt index.
    chunk_dir = os.environ.get("CHUNK_OUTPUT_DIR", "")
    local_index_path = os.path.join(chunk_dir, "index", "faiss.index") if chunk_dir else ""
    local_meta_path = os.path.join(chunk_dir, "index", "metadata.jsonl") if chunk_dir else ""

    if local_index_path and os.path.exists(local_index_path) and os.path.exists(local_meta_path):
        import faiss
        print(f"   Using LOCAL index: {local_index_path}")
        rag_module._index = faiss.read_index(local_index_path)
        rag_module._metadata = []
        with open(local_meta_path, encoding="utf-8") as f:
            for line in f:
                rag_module._metadata.append(json.loads(line))
        print(f"   Loaded {rag_module._index.ntotal} vectors from local index")

        # Verify the index has the new chunk format (region-forward text)
        sample = rag_module._metadata[0]["text"] if rag_module._metadata else ""
        if sample.startswith("NOAA GHCN"):
            print("\n   ⚠️  WARNING: Index contains OLD chunk text format!")
            print("   ⚠️  Run 'python ingest/cleanup.py && python ingest/ingest_all.py' to rebuild.")
            print("   ⚠️  The new format starts with region name, not 'NOAA GHCN'.\n")
    else:
        print("   ⚠️  No local index found — will download from S3")
        print(f"   ⚠️  Looked for: {local_index_path}")

    # Use rag_module.search_climate_data directly (NOT a `from` import)
    # to ensure it uses the _index we just set on the module.
    search_fn = rag_module.search_climate_data

    print(f"\n📊 ClimateRAG Retrieval Evaluation")
    print(f"   Top-K: {top_k}")
    print(f"   Queries: {len(RETRIEVAL_GROUND_TRUTH)}")
    print(f"   Timestamp: {datetime.now(timezone.utc).isoformat()}")

    # Run index integrity checks first
    try:
        check_index_integrity()
    except Exception as e:
        print(f"\n❌ Index integrity check failed: {e}")
        print("   Fix the index before running retrieval eval.")
        sys.exit(1)

    results_all = []

    for gt in RETRIEVAL_GROUND_TRUTH:
        print(f"\n{'=' * 50}")
        print(f"[{gt['id']}] {gt['query'][:50]}...")

        # Call the search tool (use per-query top_k override if specified)
        query_top_k = gt.get("top_k_override", top_k)
        raw = search_fn(query=gt["query"], top_k=query_top_k)
        parsed = json.loads(raw)

        # Extract results (handle both old format and new format with retrieval_metadata)
        if "results" in parsed:
            search_results = parsed["results"]
            confidence = parsed.get("retrieval_metadata", {}).get("overall_confidence", "N/A")
        else:
            search_results = parsed if isinstance(parsed, list) else []
            confidence = "N/A"

        # Compute metrics
        recall = recall_at_k(search_results, gt, query_top_k)
        precision = precision_at_k(search_results, gt, query_top_k)
        mrr = reciprocal_rank(search_results, gt)
        ndcg = ndcg_at_k(search_results, gt, query_top_k)

        results_all.append({
            "id": gt["id"],
            "query": gt["query"],
            "recall_at_k": round(recall, 3),
            "precision_at_k": round(precision, 3),
            "mrr": round(mrr, 3),
            "ndcg_at_k": round(ndcg, 3),
            "confidence": confidence,
            "num_results": len(search_results),
            "top_score": search_results[0]["score"] if search_results else 0.0,
        })

        status = "✅" if recall > 0.5 else "⚠️"
        print(f"  {status} Recall@{top_k}: {recall:.0%} | Precision@{top_k}: {precision:.0%}")
        print(f"     MRR: {mrr:.3f} | NDCG@{top_k}: {ndcg:.3f} | Confidence: {confidence}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 50}")
    print("📊 RETRIEVAL EVALUATION SUMMARY")
    print(f"{'=' * 50}")

    avg_recall = sum(r["recall_at_k"] for r in results_all) / len(results_all)
    avg_precision = sum(r["precision_at_k"] for r in results_all) / len(results_all)
    avg_mrr = sum(r["mrr"] for r in results_all) / len(results_all)
    avg_ndcg = sum(r["ndcg_at_k"] for r in results_all) / len(results_all)

    recall_status = "✅" if avg_recall >= 0.9 else "❌"
    precision_status = "✅" if avg_precision >= 0.9 else "❌"
    mrr_status = "✅" if avg_mrr >= 0.9 else "❌"
    ndcg_status = "✅" if avg_ndcg >= 0.9 else "❌"

    print(f"  {recall_status} Avg Recall@{top_k}:    {avg_recall:.0%} (threshold: 90%)")
    print(f"  {precision_status} Avg Precision@{top_k}: {avg_precision:.0%} (threshold: 90%)")
    print(f"  {mrr_status} Avg MRR:            {avg_mrr:.3f} (threshold: 0.9)")
    print(f"  {ndcg_status} Avg NDCG@{top_k}:      {avg_ndcg:.3f} (threshold: 0.9)")

    # Confidence distribution
    confidences = [r["confidence"] for r in results_all]
    print(f"\n  Confidence distribution:")
    for level in ["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"]:
        count = confidences.count(level)
        if count > 0:
            print(f"    {level}: {count}/{len(results_all)}")

    # ── Save Results ──────────────────────────────────────────────────────────
    output_dir = os.environ.get("EVAL_OUTPUT_DIR", "eval/results")
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"retrieval_eval_{timestamp}.json")

    report = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "top_k": top_k,
            "total_queries": len(results_all),
        },
        "summary": {
            "avg_recall_at_k": round(avg_recall, 3),
            "avg_precision_at_k": round(avg_precision, 3),
            "avg_mrr": round(avg_mrr, 3),
            "avg_ndcg_at_k": round(avg_ndcg, 3),
        },
        "results": results_all,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Results saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClimateRAG Retrieval Evaluation")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K for retrieval (default: 5)")
    args = parser.parse_args()

    run_retrieval_eval(top_k=args.top_k)
