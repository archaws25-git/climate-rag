"""Run on-demand evaluation of ClimateRAG agent."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from eval_config import BENCHMARK_QUERIES
from main import handle_request


def run_evaluation():
    """Run all benchmark queries and score results."""
    results = []

    for bench in BENCHMARK_QUERIES:
        print(f"\n{'='*60}")
        print(f"Running: {bench['id']} — {bench['query'][:60]}...")

        try:
            response = handle_request(bench["query"])
            answer = response["response"]

            # Simple keyword-based scoring
            keywords_found = sum(
                1 for kw in bench["expected_keywords"]
                if kw.lower() in answer.lower()
            )
            keyword_score = keywords_found / len(bench["expected_keywords"])

            # Check if expected source is mentioned
            source_mentioned = bench["expected_source"].lower() in answer.lower()

            results.append({
                "id": bench["id"],
                "query": bench["query"],
                "keyword_score": keyword_score,
                "source_cited": source_mentioned,
                "answer_length": len(answer),
                "status": "success",
            })

            print(f"  Keyword score: {keyword_score:.0%}")
            print(f"  Source cited: {source_mentioned}")

        except Exception as e:
            results.append({
                "id": bench["id"],
                "query": bench["query"],
                "status": "error",
                "error": str(e),
            })
            print(f"  ERROR: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("EVALUATION SUMMARY")
    print(f"{'='*60}")

    successful = [r for r in results if r["status"] == "success"]
    if successful:
        avg_keyword = sum(r["keyword_score"] for r in successful) / len(successful)
        source_rate = sum(1 for r in successful if r["source_cited"]) / len(successful)
        print(f"Queries run: {len(results)}")
        print(f"Successful: {len(successful)}")
        print(f"Avg keyword score: {avg_keyword:.0%}")
        print(f"Source citation rate: {source_rate:.0%}")

    # Save results
    output_path = "/tmp/climate-rag-eval-results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to {output_path}")


if __name__ == "__main__":
    run_evaluation()
