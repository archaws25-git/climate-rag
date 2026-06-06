"""
Run on-demand LLM-as-Judge evaluation of ClimateRAG agent.

Uses Claude Sonnet as judge to score agent responses across four dimensions:
  - correctness   : Is the answer factually accurate for a climate data query?
  - relevance     : Does the answer actually address what was asked?
  - tool_use      : Did the agent call the right tool(s) for the query?
  - citation      : Did the agent cite the expected data source?

Each dimension is scored 1-5. Results are written to JSON and summarised
on stdout.

Usage:
    cd climate-rag
    .venv\\Scripts\\Activate.ps1
    python eval/run_eval.py

    # Run a single query by ID:
    python eval/run_eval.py --id eval_01

    # Run with a different judge model:
    python eval/run_eval.py --judge-model anthropic.claude-sonnet-4-6

Prerequisites:
    - AWS credentials configured
    - CLIMATE_RAG_BUCKET set (FAISS index uploaded)
    - Agent dependencies installed
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Load all environment variables from .env + SSM
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402, F401

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from eval_config import BENCHMARK_QUERIES
from main import handle_request

# ── Configuration ─────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-east-1")
DEFAULT_JUDGE_MODEL = "us.anthropic.claude-sonnet-4-6"
OUTPUT_DIR = os.environ.get("EVAL_OUTPUT_DIR", "eval/results")

# ── Scoring thresholds (from requirements: correctness >= 80%, relevance >= 85%)
# On a 1-5 scale: 80% -> 4.0, 85% -> 4.25, 90% -> 4.5
THRESHOLDS = {
    "correctness": 4.5,            # >= 90%
    "relevance": 4.5,              # >= 90%
    "tool_use": 4.5,               # >= 90%
    "citation": 4.5,               # >= 90%
    "confidence_appropriate": 4.5, # >= 90%
    "source_attribution": 4.5,     # >= 90%
    "composite": 0.9,              # Overall pass threshold
}


# ── Judge Prompt Templates ────────────────────────────────────────────────────

JUDGE_SYSTEM = """You are an expert evaluator for a climate-data RAG system.
You will receive a user question, the agent's answer, and metadata about what
tools and data sources were expected. Your job is to score the answer on six
dimensions and return ONLY a JSON object — no preamble, no markdown fences.

Scoring scale for every dimension: 1 = very poor, 3 = acceptable, 5 = excellent.

Return exactly this JSON shape:
{
  "correctness": <int 1-5>,
  "relevance": <int 1-5>,
  "tool_use": <int 1-5>,
  "citation": <int 1-5>,
  "confidence_appropriate": <int 1-5>,
  "source_attribution": <int 1-5>,
  "reasoning": "<one concise sentence per dimension separated by | >"
}

Dimension definitions
---------------------
correctness  — Is the factual content of the answer accurate and consistent with
               known climate science? Penalise hallucinated figures, wrong baselines,
               or made-up station data.
relevance    — Does the answer directly address the user's question without
               excessive padding or off-topic content?
tool_use     — Given the expected tools listed, did the answer reflect that the
               right retrieval path was taken? (Infer from citations/phrasing if
               tool names are not explicit.)
citation     — Did the answer explicitly reference the expected data source
               (e.g. GHCN v4, GISTEMP v4, NASA POWER)?
confidence_appropriate — Did the answer appropriately express confidence or
               uncertainty? High-confidence claims should be well-supported by data.
               Low-confidence situations should include hedging language or "I don't
               know" fallbacks. Penalise overconfident answers without data backing.
source_attribution — Does the answer include inline source citations in the format
               [SOURCE: Dataset | Station/Region | Period]? Every factual claim
               should trace back to a specific document.
"""

JUDGE_USER_TMPL = """### User question
{query}

### Agent answer
{answer}

### Tools actually called by agent
{tools_called}

### Expected tool(s)
{expected_tools}

### Expected data source
{expected_source}

### Expected keywords (for context, not strict requirements)
{expected_keywords}

Score the answer now."""


# ── Core Judge Function ───────────────────────────────────────────────────────

def judge(query: str, answer: str, expected_tools: list,
          expected_source: str, expected_keywords: list,
          tools_called: list = None,
          judge_model: str = DEFAULT_JUDGE_MODEL) -> dict:
    """
    Call Claude Sonnet as judge. Returns a dict with keys:
      correctness, relevance, tool_use, citation (all int 1-5)
      reasoning (str)
    On failure returns all scores = 0 and error string in reasoning.
    """
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    tools_called_str = ", ".join(tools_called) if tools_called else "(not captured)"

    user_msg = JUDGE_USER_TMPL.format(
        query=query,
        answer=answer,
        tools_called=tools_called_str,
        expected_tools=", ".join(expected_tools),
        expected_source=expected_source,
        expected_keywords=", ".join(expected_keywords),
    )

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": JUDGE_SYSTEM,
        "messages": [{"role": "user", "content": user_msg}],
    }

    try:
        resp = bedrock.invoke_model(
            modelId=judge_model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload),
        )
        body = json.loads(resp["body"].read())
        raw = body["content"][0]["text"].strip()

        # Strip accidental markdown fences if the model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        scores = json.loads(raw)

        # Validate expected keys and types
        required = {"correctness", "relevance", "tool_use", "citation",
                    "confidence_appropriate", "source_attribution", "reasoning"}
        if not required.issubset(scores.keys()):
            raise ValueError(f"Missing keys in judge response: {scores.keys()}")
        for dim in ("correctness", "relevance", "tool_use", "citation",
                    "confidence_appropriate", "source_attribution"):
            scores[dim] = int(scores[dim])
            if not 1 <= scores[dim] <= 5:
                raise ValueError(f"{dim} score out of range: {scores[dim]}")

        return scores

    except Exception as exc:
        return {
            "correctness": 0,
            "relevance": 0,
            "tool_use": 0,
            "citation": 0,
            "confidence_appropriate": 0,
            "source_attribution": 0,
            "reasoning": f"JUDGE_ERROR: {exc}",
        }


# ── Composite Score ───────────────────────────────────────────────────────────

def composite(scores: dict) -> float:
    """
    Weighted average of six dimensions, normalized to [0, 1].
    Weights reflect production RAG priorities:
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
    raw = sum(scores[dim] * w for dim, w in weights.items())
    # Normalize: min possible weighted = 1.0, max = 5.0
    return (raw - 1.0) / 4.0


# ── Main Evaluation Loop ─────────────────────────────────────────────────────

def run_evaluation(query_ids: list = None, judge_model: str = DEFAULT_JUDGE_MODEL):
    """Run evaluation on benchmark queries.

    Args:
        query_ids: Optional list of specific eval IDs to run (e.g. ["eval_01"]).
                   If None, runs all benchmark queries.
        judge_model: Bedrock model ID for the judge.
    """
    queries = BENCHMARK_QUERIES
    if query_ids:
        queries = [q for q in queries if q["id"] in query_ids]
        if not queries:
            print(f"ERROR: No matching queries for IDs: {query_ids}")
            sys.exit(1)

    results = []
    print(f"\n🌍 ClimateRAG Evaluation — LLM-as-Judge")
    print(f"   Judge model: {judge_model}")
    print(f"   Queries: {len(queries)}")
    print(f"   Timestamp: {datetime.now(timezone.utc).isoformat()}")

    for bench in queries:
        print(f"\n{'=' * 60}")
        print(f"[{bench['id']}] {bench['query'][:55]}...")

        try:
            # Run the agent
            t0 = time.time()
            response = handle_request(bench["query"])
            latency = time.time() - t0
            answer = response["response"]

            # LLM-as-Judge scoring
            scores = judge(
                query=bench["query"],
                answer=answer,
                expected_tools=bench["expected_tools"],
                expected_source=bench["expected_source"],
                expected_keywords=bench["expected_keywords"],
                tools_called=response.get("tools_called", []),
                judge_model=judge_model,
            )

            comp = composite(scores)

            results.append({
                "id": bench["id"],
                "query": bench["query"],
                "status": "success",
                "latency_s": round(latency, 2),
                "answer_length": len(answer),
                "scores": scores,
                "composite": round(comp, 3),
            })

            # Print per-query results
            status = "✅" if comp >= THRESHOLDS["composite"] else "⚠️"
            print(f"  {status} Composite: {comp:.0%}")
            print(f"     Correctness      : {scores['correctness']}/5")
            print(f"     Relevance        : {scores['relevance']}/5")
            print(f"     Tool use         : {scores['tool_use']}/5")
            print(f"     Citation         : {scores['citation']}/5")
            print(f"     Confidence       : {scores['confidence_appropriate']}/5")
            print(f"     Source attrib.   : {scores['source_attribution']}/5")
            print(f"     Latency          : {latency:.1f}s")
            print(f"     Reasoning        : {scores['reasoning']}")

        except Exception as exc:
            results.append({
                "id": bench["id"],
                "query": bench["query"],
                "status": "error",
                "error": str(exc),
            })
            print(f"  ❌ ERROR: {exc}")

        # Polite pause to avoid Bedrock throttling
        time.sleep(2)

    # ── Summary ───────────────────────────────────────────────────────────────
    _print_summary(results)
    _save_results(results, judge_model)


def _print_summary(results: list):
    """Print evaluation summary with pass/fail against thresholds."""
    print(f"\n{'=' * 60}")
    print("📊 EVALUATION SUMMARY")
    print(f"{'=' * 60}")

    successful = [r for r in results if r["status"] == "success"]
    errors = [r for r in results if r["status"] == "error"]

    if not successful:
        print("No successful evaluations.")
        return

    def avg_dim(dim):
        return sum(r["scores"][dim] for r in successful) / len(successful)

    avg_comp = sum(r["composite"] for r in successful) / len(successful)
    avg_latency = sum(r["latency_s"] for r in successful) / len(successful)

    print(f"  Queries run      : {len(results)}")
    print(f"  Successful       : {len(successful)}")
    print(f"  Errors           : {len(errors)}")
    print(f"  Avg latency      : {avg_latency:.1f}s")
    print()

    # Dimension averages with pass/fail indicators
    dims = ["correctness", "relevance", "tool_use", "citation",
            "confidence_appropriate", "source_attribution"]
    for dim in dims:
        avg = avg_dim(dim)
        threshold = THRESHOLDS[dim]
        status = "✅" if avg >= threshold else "❌"
        print(f"  {status} Avg {dim:<13}: {avg:.2f}/5 (threshold: {threshold})")

    comp_status = "✅" if avg_comp >= THRESHOLDS["composite"] else "❌"
    print(f"\n  {comp_status} Overall composite : {avg_comp:.0%} (threshold: {THRESHOLDS['composite']:.0%})")

    # Flag failing queries
    failures = [
        r for r in successful
        if r["composite"] < THRESHOLDS["composite"]
    ]
    if failures:
        print(f"\n  ⚠️  Queries below threshold ({len(failures)}):")
        for r in failures:
            print(f"     {r['id']} — composite={r['composite']:.0%} "
                  f"correctness={r['scores']['correctness']} "
                  f"relevance={r['scores']['relevance']}")


def _save_results(results: list, judge_model: str):
    """Save evaluation results to JSON file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"eval_{timestamp}.json")

    successful = [r for r in results if r["status"] == "success"]

    report = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "judge_model": judge_model,
            "total_queries": len(results),
            "successful": len(successful),
            "thresholds": THRESHOLDS,
        },
        "summary": {
            "avg_composite": round(
                sum(r["composite"] for r in successful) / len(successful), 3
            ) if successful else None,
            "avg_correctness": round(
                sum(r["scores"]["correctness"] for r in successful) / len(successful), 2
            ) if successful else None,
            "avg_relevance": round(
                sum(r["scores"]["relevance"] for r in successful) / len(successful), 2
            ) if successful else None,
            "avg_tool_use": round(
                sum(r["scores"]["tool_use"] for r in successful) / len(successful), 2
            ) if successful else None,
            "avg_citation": round(
                sum(r["scores"]["citation"] for r in successful) / len(successful), 2
            ) if successful else None,
        },
        "results": results,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Results saved to: {output_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClimateRAG LLM-as-Judge Evaluation")
    parser.add_argument(
        "--id", nargs="+", default=None,
        help="Run specific eval IDs (e.g. --id eval_01 eval_03)",
    )
    parser.add_argument(
        "--judge-model", default=DEFAULT_JUDGE_MODEL,
        help=f"Bedrock model ID for the judge (default: {DEFAULT_JUDGE_MODEL})",
    )
    args = parser.parse_args()

    run_evaluation(query_ids=args.id, judge_model=args.judge_model)
