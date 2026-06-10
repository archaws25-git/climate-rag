"""ClimateRAG — Unified Evaluation Runner.

Single entry point for all eval suites:
  - retrieval: Search quality (Recall, Precision, MRR, NDCG)
  - e2e: End-to-end generation quality (LLM-as-Judge, 6 dimensions)
  - multiturn: Conversation coherence (4 dimensions)
  - latency: Performance (E2E P50/P95/P99, TTFT)

Usage:
    python eval/run.py                    # All suites
    python eval/run.py --suite retrieval  # Retrieval only (fast, no LLM gen)
    python eval/run.py --suite e2e        # Single-turn E2E
    python eval/run.py --suite multiturn  # Multi-turn flows
    python eval/run.py --suite latency    # Performance benchmarks
    python eval/run.py --suite retrieval e2e  # Multiple suites
    python eval/run.py --id e2e_01 e2e_03    # Specific query IDs

Prerequisites:
    - AWS credentials configured
    - FAISS index available (local or S3)
    - For e2e/multiturn: Bedrock model access
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# ── Setup ─────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402, F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

# Disable memory during eval
os.environ["CLIMATE_RAG_MEMORY_ID"] = ""
os.environ.pop("CLIMATE_RAG_MEMORY_ID", None)

from golden_dataset import E2E_QUERIES, MULTITURN_FLOWS, RETRIEVAL_QUERIES
from judge import judge_multiturn, judge_single_turn
from metrics import (
    composite_score,
    latency_summary,
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

REGION = os.environ.get("AWS_REGION", "us-east-1")
OUTPUT_DIR = os.environ.get("EVAL_OUTPUT_DIR", "eval/results")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "us.anthropic.claude-sonnet-4-6")


# ── Suite: Retrieval ──────────────────────────────────────────────────────────

def run_retrieval_suite(top_k: int = 5) -> dict:
    """Run retrieval quality evaluation. No LLM generation needed."""
    import importlib
    import tools.rag_tool as rag_module

    importlib.reload(rag_module)
    rag_module._index = None
    rag_module._metadata = None
    rag_module._bm25_index = None
    rag_module._bm25_corpus_tokens = None

    print("\n📊 Suite: RETRIEVAL")
    print(f"   Queries: {len(RETRIEVAL_QUERIES)} | Top-K: {top_k}")

    results = []
    for gt in RETRIEVAL_QUERIES:
        query_k = gt.get("top_k_override", top_k)
        raw = rag_module.search_climate_data(query=gt["query"], top_k=query_k)
        parsed = json.loads(raw)
        search_results = parsed.get("results", [])

        r = recall_at_k(search_results, gt, query_k)
        p = precision_at_k(search_results, gt, query_k)
        mrr = reciprocal_rank(search_results, gt)
        ndcg = ndcg_at_k(search_results, gt, query_k)

        results.append({
            "id": gt["id"],
            "recall": round(r, 3),
            "precision": round(p, 3),
            "mrr": round(mrr, 3),
            "ndcg": round(ndcg, 3),
        })

        status = "✅" if r >= 0.5 else "⚠️"
        print(f"  {status} [{gt['id']}] R={r:.0%} P={p:.0%} MRR={mrr:.2f} NDCG={ndcg:.2f}")

    avg = lambda key: sum(r[key] for r in results) / len(results)
    summary = {
        "avg_recall": round(avg("recall"), 3),
        "avg_precision": round(avg("precision"), 3),
        "avg_mrr": round(avg("mrr"), 3),
        "avg_ndcg": round(avg("ndcg"), 3),
    }
    print(f"\n  Summary: Recall={summary['avg_recall']:.0%} "
          f"Precision={summary['avg_precision']:.0%} "
          f"MRR={summary['avg_mrr']:.2f} NDCG={summary['avg_ndcg']:.2f}")

    return {"suite": "retrieval", "summary": summary, "results": results}


# ── Suite: E2E ────────────────────────────────────────────────────────────────

def run_e2e_suite(query_ids: list = None) -> dict:
    """Run end-to-end LLM-as-Judge evaluation."""
    from main import handle_request
    import main as main_module
    main_module._memory_available = False

    queries = E2E_QUERIES
    if query_ids:
        queries = [q for q in queries if q["id"] in query_ids]

    print(f"\n📊 Suite: E2E (LLM-as-Judge)")
    print(f"   Queries: {len(queries)} | Judge: {JUDGE_MODEL}")

    results = []
    latencies = []

    for bench in queries:
        print(f"\n  [{bench['id']}] {bench['query'][:50]}...")
        try:
            t0 = time.time()
            response = handle_request(bench["query"])
            latency_s = time.time() - t0
            latencies.append(latency_s * 1000)

            scores = judge_single_turn(
                query=bench["query"],
                answer=response["response"],
                expected_tools=bench["expected_tools"],
                expected_source=bench["expected_source"],
                expected_keywords=bench["expected_keywords"],
                tools_called=response.get("tools_called", []),
                judge_model=JUDGE_MODEL,
            )
            comp = composite_score(scores)

            results.append({
                "id": bench["id"],
                "status": "success",
                "latency_s": round(latency_s, 2),
                "composite": round(comp, 3),
                "scores": scores,
            })

            status = "✅" if comp >= 0.9 else "⚠️"
            print(f"    {status} composite={comp:.0%} latency={latency_s:.1f}s")

        except Exception as exc:
            results.append({"id": bench["id"], "status": "error", "error": str(exc)})
            print(f"    ❌ {exc}")

        time.sleep(2)

    successful = [r for r in results if r["status"] == "success"]
    summary = {}
    if successful:
        summary = {
            "avg_composite": round(sum(r["composite"] for r in successful) / len(successful), 3),
            "avg_latency_s": round(sum(r["latency_s"] for r in successful) / len(successful), 1),
            "latency": latency_summary(latencies),
            "pass_rate": round(sum(1 for r in successful if r["composite"] >= 0.9) / len(successful), 2),
        }
        print(f"\n  Summary: composite={summary['avg_composite']:.0%} "
              f"pass_rate={summary['pass_rate']:.0%} "
              f"latency_p50={summary['latency']['p50']:.0f}ms")

    return {"suite": "e2e", "summary": summary, "results": results}


# ── Suite: Multi-Turn ─────────────────────────────────────────────────────────

def run_multiturn_suite(flow_ids: list = None) -> dict:
    """Run multi-turn conversation evaluation."""
    from main import agent, handle_request
    import main as main_module
    main_module._memory_available = False

    flows = MULTITURN_FLOWS
    if flow_ids:
        flows = [f for f in flows if f["id"] in flow_ids]

    print(f"\n📊 Suite: MULTI-TURN")
    print(f"   Flows: {len(flows)} | Judge: {JUDGE_MODEL}")

    results = []

    for flow in flows:
        print(f"\n  [{flow['id']}] {flow['name']} ({len(flow['turns'])} turns)")
        agent.messages = []

        turns_data = []
        for i, turn in enumerate(flow["turns"]):
            t0 = time.time()
            result = handle_request(turn["prompt"])
            latency = time.time() - t0

            keywords_found = sum(
                1 for kw in turn.get("must_contain", [])
                if kw.lower() in result["response"].lower()
            )
            keyword_total = len(turn.get("must_contain", []))

            turns_data.append({
                "turn": i + 1,
                "prompt": turn["prompt"],
                "response": result["response"][:500],
                "latency_s": round(latency, 2),
                "keyword_score": round(keywords_found / keyword_total, 2) if keyword_total else 1.0,
            })
            print(f"    Turn {i+1}: kw={keywords_found}/{keyword_total} latency={latency:.1f}s")

        # Judge the full conversation
        scores = judge_multiturn(flow["name"], turns_data, flow["turns"], JUDGE_MODEL)
        results.append({
            "flow_id": flow["id"],
            "flow_name": flow["name"],
            "scores": scores,
            "turns": turns_data,
        })

        if scores.get("context_resolution", 0) > 0:
            print(f"    Judge: context={scores['context_resolution']}/5 "
                  f"coherence={scores['session_coherence']}/5")

        time.sleep(2)

    successful = [r for r in results if r["scores"].get("context_resolution", 0) > 0]
    summary = {}
    if successful:
        summary = {
            "avg_context_resolution": round(
                sum(r["scores"]["context_resolution"] for r in successful) / len(successful), 2),
            "avg_session_coherence": round(
                sum(r["scores"]["session_coherence"] for r in successful) / len(successful), 2),
            "avg_progressive_quality": round(
                sum(r["scores"]["progressive_quality"] for r in successful) / len(successful), 2),
        }
        print(f"\n  Summary: context={summary['avg_context_resolution']:.1f}/5 "
              f"coherence={summary['avg_session_coherence']:.1f}/5")

    return {"suite": "multiturn", "summary": summary, "results": results}


# ── Suite: Latency ────────────────────────────────────────────────────────────

def run_latency_suite(num_queries: int = 5) -> dict:
    """Run latency benchmark. Measures E2E and TTFT across N queries."""
    from main import handle_request
    import main as main_module
    main_module._memory_available = False

    # Use a mix of query types
    test_queries = [
        "What is the temperature trend in the US Southeast?",
        "Show me the warmest decades on record globally",
        "Compare New York and Los Angeles temperature trends",
        "What was the average temperature in Chicago in the 1990s?",
        "What does NASA POWER show for solar radiation in the Southeast?",
    ][:num_queries]

    print(f"\n📊 Suite: LATENCY")
    print(f"   Queries: {len(test_queries)}")

    e2e_latencies = []
    results = []

    for i, query in enumerate(test_queries):
        print(f"  [{i+1}/{len(test_queries)}] {query[:45]}...", end=" ")
        t0 = time.time()
        try:
            response = handle_request(query)
            latency_ms = (time.time() - t0) * 1000
            e2e_latencies.append(latency_ms)
            results.append({"query": query, "e2e_ms": round(latency_ms, 0), "status": "ok"})
            print(f"{latency_ms:.0f}ms")
        except Exception as exc:
            results.append({"query": query, "status": "error", "error": str(exc)})
            print(f"ERROR: {exc}")

        time.sleep(1)

    summary = {
        "e2e": latency_summary(e2e_latencies),
    }

    print(f"\n  E2E: P50={summary['e2e']['p50']:.0f}ms "
          f"P95={summary['e2e']['p95']:.0f}ms "
          f"P99={summary['e2e']['p99']:.0f}ms")

    return {"suite": "latency", "summary": summary, "results": results}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ClimateRAG Unified Evaluation")
    parser.add_argument(
        "--suite", nargs="+", default=["all"],
        choices=["all", "retrieval", "e2e", "multiturn", "latency"],
        help="Which suite(s) to run (default: all)",
    )
    parser.add_argument("--id", nargs="+", help="Specific query/flow IDs to run")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K for retrieval")
    args = parser.parse_args()

    suites = args.suite
    if "all" in suites:
        suites = ["retrieval", "e2e", "multiturn", "latency"]

    print("=" * 60)
    print("🌍 ClimateRAG — Unified Evaluation")
    print(f"   Suites: {', '.join(suites)}")
    print(f"   Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    report = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "suites": suites,
            "judge_model": JUDGE_MODEL,
        },
        "suites": {},
    }

    if "retrieval" in suites:
        report["suites"]["retrieval"] = run_retrieval_suite(top_k=args.top_k)

    if "e2e" in suites:
        report["suites"]["e2e"] = run_e2e_suite(query_ids=args.id)

    if "multiturn" in suites:
        report["suites"]["multiturn"] = run_multiturn_suite(flow_ids=args.id)

    if "latency" in suites:
        report["suites"]["latency"] = run_latency_suite()

    # Save unified report
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"eval_{timestamp}.json")

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"📄 Report saved: {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
