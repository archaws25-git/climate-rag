"""
Multi-turn conversation evaluation for ClimateRAG.

Tests 5 conversation flows (3-5 turns each) to validate:
  - Context resolution: Does "that station" resolve correctly?
  - Session coherence: Are answers consistent across turns?
  - Progressive quality: Does more context improve answers?
  - Memory persistence: Can turn N reference information from turn 1?

Approach: Option C — same Agent instance, messages accumulate naturally.
Agent.messages is reset between flows to isolate them.

Usage:
    python eval/run_multiturn_eval.py
    python eval/run_multiturn_eval.py --flow mt_01

Prerequisites:
    - AWS credentials (Bedrock for LLM + embeddings)
    - FAISS index in local CHUNK_OUTPUT_DIR or S3
    - Memory disabled (uses in-process conversation history)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Load config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import boto3
import config  # noqa: E402, F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

# Disable memory for multi-turn eval — uses agent's in-process messages instead
os.environ["CLIMATE_RAG_MEMORY_ID"] = ""
os.environ.pop("CLIMATE_RAG_MEMORY_ID", None)

# ── Configuration ─────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-east-1")
JUDGE_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
OUTPUT_DIR = os.environ.get("EVAL_OUTPUT_DIR", "eval/results")

# ── Multi-Turn Conversation Flows ─────────────────────────────────────────────

MULTI_TURN_FLOWS = [
    {
        "id": "mt_01",
        "name": "Progressive Drill-Down",
        "description": "Region overview → specific station → decade detail",
        "turns": [
            {
                "prompt": "What is the temperature trend in the US Southeast?",
                "expected_behavior": "Returns Southeast GHCN data with station citations",
                "must_contain": ["Southeast", "SOURCE"],
            },
            {
                "prompt": "Which station shows the most warming in that region?",
                "expected_behavior": "References a specific station from previous results",
                "must_contain": ["USW", "warming"],
                "context_check": "Must reference a Southeast station, not change region",
            },
            {
                "prompt": "Show me the decade-by-decade data for that station",
                "expected_behavior": "Resolves 'that station' from turn 2, presents decadal data",
                "must_contain": ["decade", "SOURCE"],
                "context_check": "Station must match turn 2 recommendation",
            },
        ],
    },
    {
        "id": "mt_02",
        "name": "Comparison with Follow-Up",
        "description": "Two cities → add third → plot all",
        "turns": [
            {
                "prompt": "Compare New York and Los Angeles temperature trends since 1950",
                "expected_behavior": "Shows data for both NYC and LA with citations",
                "must_contain": ["New York", "Los Angeles", "SOURCE"],
            },
            {
                "prompt": "Now add Chicago to that comparison",
                "expected_behavior": "Adds Chicago data while retaining NY and LA context",
                "must_contain": ["Chicago"],
                "context_check": "Must include all three cities, not just Chicago alone",
            },
            {
                "prompt": "Which of the three cities has warmed the most?",
                "expected_behavior": "Compares warming rates across all three previously discussed cities",
                "must_contain": ["warming", "SOURCE"],
                "context_check": "Must reference all three cities from prior turns",
            },
        ],
    },
    {
        "id": "mt_03",
        "name": "Clarification and Correction",
        "description": "Ambiguous query → temporal refinement → comparison",
        "turns": [
            {
                "prompt": "What's the temperature in Atlanta?",
                "expected_behavior": "Returns Atlanta temperature data (may ask for time period)",
                "must_contain": ["Atlanta", "SOURCE"],
            },
            {
                "prompt": "I meant specifically in the 1990s",
                "expected_behavior": "Narrows to 1990s decade for Atlanta",
                "must_contain": ["1990", "SOURCE"],
                "context_check": "Must stay on Atlanta, not switch cities",
            },
            {
                "prompt": "How does that compare to the current decade?",
                "expected_behavior": "Compares 1990s to 2020s for Atlanta",
                "must_contain": ["2020", "SOURCE"],
                "context_check": "Must compare two time periods for the SAME station",
            },
        ],
    },
    {
        "id": "mt_04",
        "name": "Cross-Dataset Query",
        "description": "GISTEMP global → NASA POWER regional → consistency",
        "turns": [
            {
                "prompt": "Show me global temperature anomalies for the 2010s from GISTEMP",
                "expected_behavior": "Returns GISTEMP v4 data for 2010s decade",
                "must_contain": ["GISTEMP", "anomal", "2010"],
            },
            {
                "prompt": "What does NASA POWER show for the Southeast in the same period?",
                "expected_behavior": "Switches to NASA POWER data, same time period",
                "must_contain": ["NASA POWER", "Southeast"],
                "context_check": "Must use 2010s timeframe from turn 1",
            },
            {
                "prompt": "Are the global and regional trends consistent?",
                "expected_behavior": "Compares GISTEMP global vs NASA POWER regional",
                "must_contain": ["global", "regional"],
                "context_check": "Must reference both datasets discussed in turns 1 and 2",
            },
        ],
    },
    {
        "id": "mt_05",
        "name": "Research Context Persistence",
        "description": "State topic → query data → summarize session",
        "turns": [
            {
                "prompt": "I'm researching how Arctic amplification affects Alaska temperatures compared to the lower 48 states",
                "expected_behavior": "Acknowledges research topic, may provide initial data",
                "must_contain": ["Alaska"],
            },
            {
                "prompt": "What temperature data do you have for Anchorage and Fairbanks?",
                "expected_behavior": "Returns Alaska station data with citations",
                "must_contain": ["Anchorage", "SOURCE"],
            },
            {
                "prompt": "How do those Alaska warming rates compare to the Midwest?",
                "expected_behavior": "Compares Alaska vs Midwest warming rates",
                "must_contain": ["Alaska", "Midwest"],
                "context_check": "Should reference Arctic amplification from turn 1",
            },
            {
                "prompt": "Summarize what we've found about my research question",
                "expected_behavior": "Summarizes Arctic amplification findings from entire session",
                "must_contain": ["Arctic", "amplification"],
                "context_check": "Must recall research topic from turn 1 and data from turns 2-3",
            },
        ],
    },
]


# ── Judge Prompt ──────────────────────────────────────────────────────────────

MULTITURN_JUDGE_SYSTEM = """You are evaluating a multi-turn conversation with a climate data assistant.
You will receive the FULL conversation (all turns) and must score it on four dimensions.
Return ONLY a JSON object — no preamble, no markdown fences.

Scoring scale: 1 = very poor, 3 = acceptable, 5 = excellent.

{
  "per_turn_correctness": <float 1-5, average across turns>,
  "context_resolution": <float 1-5, how well does the system resolve references like "that station", "same period">,
  "session_coherence": <float 1-5, are answers consistent with no contradictions across turns>,
  "progressive_quality": <float 1-5, does context improve answer quality over the session>,
  "reasoning": "<one sentence per dimension separated by |>"
}

Definitions:
- per_turn_correctness: Each individual answer is factually accurate for climate data
- context_resolution: Pronouns and references ("that", "same", "those") resolve to the correct entity from prior turns
- session_coherence: No contradictions between turns (e.g., stating 1.2°C warming in turn 1, then 0.5°C in turn 3 for same station)
- progressive_quality: Later turns benefit from earlier context (turn 3 answer is better/more specific than turn 1)
"""

MULTITURN_JUDGE_USER_TMPL = """### Conversation Flow: {flow_name}

{conversation_text}

### Expected Behaviors:
{expected_behaviors}

Score this conversation now."""


# ── Core Functions ────────────────────────────────────────────────────────────

def run_conversation_flow(flow: dict) -> dict:
    """Run a single multi-turn conversation flow using the same Agent instance."""
    from main import agent, handle_request

    # Reset agent messages to isolate this flow
    agent.messages = []

    turns_data = []

    for i, turn in enumerate(flow["turns"]):
        t0 = time.time()
        result = handle_request(turn["prompt"])
        latency = time.time() - t0

        response_text = result["response"]

        # Check must_contain keywords
        keywords_found = sum(
            1 for kw in turn.get("must_contain", [])
            if kw.lower() in response_text.lower()
        )
        keyword_total = len(turn.get("must_contain", []))
        keyword_score = keywords_found / keyword_total if keyword_total > 0 else 1.0

        turns_data.append({
            "turn": i + 1,
            "prompt": turn["prompt"],
            "response": response_text[:500],  # Truncate for storage
            "response_full_length": len(response_text),
            "latency_s": round(latency, 2),
            "keyword_score": round(keyword_score, 2),
            "tools_called": result.get("tools_called", []),
        })

        print(f"    Turn {i+1}: keyword_score={keyword_score:.0%}, latency={latency:.1f}s")

    return {
        "flow_id": flow["id"],
        "flow_name": flow["name"],
        "turns": turns_data,
    }


def judge_conversation(flow: dict, turns_data: list) -> dict:
    """Use LLM-as-Judge to score the full conversation."""
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    # Build conversation text
    conversation_lines = []
    for td in turns_data:
        conversation_lines.append(f"USER (Turn {td['turn']}): {td['prompt']}")
        conversation_lines.append(f"ASSISTANT (Turn {td['turn']}): {td['response']}")
        conversation_lines.append("")

    # Build expected behaviors
    expected_lines = []
    for i, turn in enumerate(flow["turns"]):
        expected_lines.append(f"Turn {i+1}: {turn['expected_behavior']}")
        if "context_check" in turn:
            expected_lines.append(f"  Context check: {turn['context_check']}")

    user_msg = MULTITURN_JUDGE_USER_TMPL.format(
        flow_name=flow["name"],
        conversation_text="\n".join(conversation_lines),
        expected_behaviors="\n".join(expected_lines),
    )

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": MULTITURN_JUDGE_SYSTEM,
        "messages": [{"role": "user", "content": user_msg}],
    }

    try:
        resp = bedrock.invoke_model(
            modelId=JUDGE_MODEL,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload),
        )
        body = json.loads(resp["body"].read())
        raw = body["content"][0]["text"].strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        scores = json.loads(raw)
        return scores

    except Exception as e:
        return {
            "per_turn_correctness": 0,
            "context_resolution": 0,
            "session_coherence": 0,
            "progressive_quality": 0,
            "reasoning": f"JUDGE_ERROR: {e}",
        }


# ── Main ──────────────────────────────────────────────────────────────────────

def run_multiturn_eval(flow_ids: list = None):
    """Run multi-turn evaluation."""
    flows = MULTI_TURN_FLOWS
    if flow_ids:
        flows = [f for f in flows if f["id"] in flow_ids]

    print("\n🔄 ClimateRAG Multi-Turn Evaluation")
    print(f"   Flows: {len(flows)}")
    print(f"   Judge: {JUDGE_MODEL}")
    print(f"   Timestamp: {datetime.now(timezone.utc).isoformat()}")

    all_results = []

    for flow in flows:
        print(f"\n{'=' * 60}")
        print(f"  [{flow['id']}] {flow['name']}")
        print(f"  {flow['description']}")
        print(f"  Turns: {len(flow['turns'])}")

        # Run the conversation
        flow_result = run_conversation_flow(flow)

        # Judge the conversation
        print("  Judging conversation...")
        scores = judge_conversation(flow, flow_result["turns"])

        flow_result["scores"] = scores
        all_results.append(flow_result)

        # Print scores
        if scores.get("per_turn_correctness", 0) > 0:
            print(f"    ✅ Per-turn correctness:  {scores['per_turn_correctness']}/5")
            print(f"    ✅ Context resolution:    {scores['context_resolution']}/5")
            print(f"    ✅ Session coherence:     {scores['session_coherence']}/5")
            print(f"    ✅ Progressive quality:   {scores['progressive_quality']}/5")
            print(f"    💬 Reasoning: {scores.get('reasoning', 'N/A')}")
        else:
            print(f"    ❌ Judge error: {scores.get('reasoning', 'Unknown')}")

        time.sleep(2)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("📊 MULTI-TURN EVALUATION SUMMARY")
    print(f"{'=' * 60}")

    successful = [r for r in all_results if r["scores"].get("per_turn_correctness", 0) > 0]

    if successful:
        avg_correctness = sum(r["scores"]["per_turn_correctness"] for r in successful) / len(successful)
        avg_context = sum(r["scores"]["context_resolution"] for r in successful) / len(successful)
        avg_coherence = sum(r["scores"]["session_coherence"] for r in successful) / len(successful)
        avg_progressive = sum(r["scores"]["progressive_quality"] for r in successful) / len(successful)

        print(f"  Flows evaluated:        {len(all_results)}")
        print(f"  Successful:             {len(successful)}")
        print(f"  Avg correctness:        {avg_correctness:.2f}/5 (threshold: 4.0)")
        print(f"  Avg context resolution: {avg_context:.2f}/5 (threshold: 4.0)")
        print(f"  Avg session coherence:  {avg_coherence:.2f}/5 (threshold: 4.0)")
        print(f"  Avg progressive quality:{avg_progressive:.2f}/5 (threshold: 4.0)")

    # Save results
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"multiturn_eval_{timestamp}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "judge_model": JUDGE_MODEL,
                "total_flows": len(all_results),
                "successful": len(successful) if successful else 0,
            },
            "results": all_results,
        }, f, indent=2)

    print(f"\n📄 Results saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ClimateRAG Multi-Turn Evaluation")
    parser.add_argument(
        "--flow", nargs="+", default=None,
        help="Run specific flow IDs (e.g. --flow mt_01 mt_03)",
    )
    args = parser.parse_args()
    run_multiturn_eval(flow_ids=args.flow)
