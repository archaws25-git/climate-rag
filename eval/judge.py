"""ClimateRAG — Shared LLM-as-Judge module.

Provides judge functions for both single-turn and multi-turn evaluation.
Uses Claude Sonnet as the judge model via Bedrock Converse API.
"""

import json
import os

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
DEFAULT_JUDGE_MODEL = "us.anthropic.claude-sonnet-4-6"

# ── Single-Turn Judge ─────────────────────────────────────────────────────────

SINGLE_TURN_SYSTEM = """You are an expert evaluator for a climate-data RAG system.
Score the agent's answer on six dimensions. Return ONLY a JSON object.

Scoring: 1 = very poor, 3 = acceptable, 5 = excellent.

{
  "correctness": <int 1-5>,
  "relevance": <int 1-5>,
  "tool_use": <int 1-5>,
  "citation": <int 1-5>,
  "confidence_appropriate": <int 1-5>,
  "source_attribution": <int 1-5>,
  "reasoning": "<one sentence per dimension separated by |>"
}

Dimensions:
- correctness: Factual accuracy for climate data
- relevance: Directly addresses the question
- tool_use: Right retrieval path taken
- citation: References expected data source
- confidence_appropriate: Proper hedging/certainty
- source_attribution: Inline [SOURCE: ...] citations present
"""

SINGLE_TURN_USER = """### User question
{query}

### Agent answer
{answer}

### Tools called
{tools_called}

### Expected tool(s): {expected_tools}
### Expected source: {expected_source}
### Expected keywords: {expected_keywords}

Score now."""


def judge_single_turn(
    query: str,
    answer: str,
    expected_tools: list,
    expected_source: str,
    expected_keywords: list,
    tools_called: list = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> dict:
    """Score a single-turn response. Returns dict with 6 dimension scores."""
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    user_msg = SINGLE_TURN_USER.format(
        query=query,
        answer=answer,
        tools_called=", ".join(tools_called) if tools_called else "(not captured)",
        expected_tools=", ".join(expected_tools),
        expected_source=expected_source,
        expected_keywords=", ".join(expected_keywords),
    )

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": SINGLE_TURN_SYSTEM,
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

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        scores = json.loads(raw)
        for dim in ("correctness", "relevance", "tool_use", "citation",
                    "confidence_appropriate", "source_attribution"):
            scores[dim] = max(1, min(5, int(scores.get(dim, 0))))
        return scores

    except Exception as exc:
        return {
            "correctness": 0, "relevance": 0, "tool_use": 0,
            "citation": 0, "confidence_appropriate": 0, "source_attribution": 0,
            "reasoning": f"JUDGE_ERROR: {exc}",
        }


# ── Multi-Turn Judge ──────────────────────────────────────────────────────────

MULTITURN_SYSTEM = """You are evaluating a multi-turn conversation with a climate data assistant.
Score the FULL conversation on four dimensions. Return ONLY a JSON object.

Scoring: 1 = very poor, 3 = acceptable, 5 = excellent.

{
  "per_turn_correctness": <float 1-5>,
  "context_resolution": <float 1-5>,
  "session_coherence": <float 1-5>,
  "progressive_quality": <float 1-5>,
  "reasoning": "<one sentence per dimension separated by |>"
}

Dimensions:
- per_turn_correctness: Each answer is factually accurate
- context_resolution: References like "that station" resolve correctly
- session_coherence: No contradictions across turns
- progressive_quality: Later turns benefit from earlier context
"""

MULTITURN_USER = """### Conversation: {flow_name}

{conversation_text}

### Expected Behaviors:
{expected_behaviors}

Score now."""


def judge_multiturn(flow_name: str, turns_data: list, flow_turns: list,
                    judge_model: str = DEFAULT_JUDGE_MODEL) -> dict:
    """Score a multi-turn conversation flow."""
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    conversation_lines = []
    for td in turns_data:
        conversation_lines.append(f"USER (Turn {td['turn']}): {td['prompt']}")
        conversation_lines.append(f"ASSISTANT (Turn {td['turn']}): {td['response']}")

    expected_lines = []
    for i, turn in enumerate(flow_turns):
        expected_lines.append(f"Turn {i+1}: {turn['expected_behavior']}")

    user_msg = MULTITURN_USER.format(
        flow_name=flow_name,
        conversation_text="\n".join(conversation_lines),
        expected_behaviors="\n".join(expected_lines),
    )

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": MULTITURN_SYSTEM,
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

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        return json.loads(raw)

    except Exception as exc:
        return {
            "per_turn_correctness": 0, "context_resolution": 0,
            "session_coherence": 0, "progressive_quality": 0,
            "reasoning": f"JUDGE_ERROR: {exc}",
        }
