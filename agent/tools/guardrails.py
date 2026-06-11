"""Bedrock Guardrails integration — input/output filtering for production safety.

Applies Bedrock Guardrails to:
  - INPUT:  User prompts before they reach the agent (blocks harmful/off-topic queries)
  - OUTPUT: Agent responses before they reach the user (blocks hallucinations/PII/harmful content)

The guardrail ID and version are read from SSM Parameter Store at startup,
falling back to environment variables.

Usage in agent/main.py:
    from tools.guardrails import apply_input_guardrail, apply_output_guardrail

    # Before agent call:
    filtered_prompt, is_blocked = apply_input_guardrail(user_prompt)
    if is_blocked:
        return {"response": filtered_prompt, ...}  # Return block message

    # After agent call:
    filtered_response, is_blocked = apply_output_guardrail(agent_response, source_context)
    if is_blocked:
        return {"response": filtered_response, ...}  # Return block message
"""

import logging
import os

import boto3

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")

# Guardrail config — read from env or SSM
_guardrail_id = None
_guardrail_version = None


def _load_guardrail_config():
    """Load guardrail ID and version from SSM or env vars."""
    global _guardrail_id, _guardrail_version

    if _guardrail_id and _guardrail_version:
        return

    # Try environment variables first
    _guardrail_id = os.environ.get("CLIMATE_RAG_GUARDRAIL_ID", "")
    _guardrail_version = os.environ.get("CLIMATE_RAG_GUARDRAIL_VERSION", "")

    if _guardrail_id and _guardrail_version:
        return

    # Fall back to SSM
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        _guardrail_id = ssm.get_parameter(Name="/climate-rag/guardrail-id")["Parameter"]["Value"]
        _guardrail_version = ssm.get_parameter(Name="/climate-rag/guardrail-version")["Parameter"]["Value"]
        # Cache in env for subsequent calls
        os.environ["CLIMATE_RAG_GUARDRAIL_ID"] = _guardrail_id
        os.environ["CLIMATE_RAG_GUARDRAIL_VERSION"] = _guardrail_version
    except Exception as e:
        logger.warning("Could not load guardrail config from SSM: %s", e)
        _guardrail_id = ""
        _guardrail_version = ""


def _get_runtime_client():
    """Get Bedrock Runtime client for ApplyGuardrail."""
    return boto3.client("bedrock-runtime", region_name=REGION)


def apply_input_guardrail(prompt: str) -> tuple[str, bool]:
    """Apply guardrail to user input before processing.

    Args:
        prompt: The user's raw input text.

    Returns:
        Tuple of (text, is_blocked):
          - If allowed: (original prompt, False)
          - If blocked: (block message from guardrail, True)
    """
    _load_guardrail_config()

    if not _guardrail_id or not _guardrail_version:
        logger.debug("Guardrails not configured — skipping input filter")
        return prompt, False

    try:
        client = _get_runtime_client()
        resp = client.apply_guardrail(
            guardrailIdentifier=_guardrail_id,
            guardrailVersion=_guardrail_version,
            source="INPUT",
            content=[{"text": {"text": prompt}}],
        )

        action = resp.get("action", "NONE")

        if action == "GUARDRAIL_INTERVENED":
            # Extract the blocked message from outputs
            outputs = resp.get("outputs", [])
            block_message = (
                outputs[0]["text"]
                if outputs
                else ("Your query was blocked by safety filters. Please ask a climate data question.")
            )
            logger.info("Input BLOCKED by guardrail: %s", prompt[:100])
            return block_message, True

        return prompt, False

    except Exception as e:
        # Fail open — if guardrail call fails, allow the request through
        # but log the error for monitoring
        logger.error("Guardrail input check failed (allowing through): %s", e)
        return prompt, False


def apply_output_guardrail(response: str, grounding_source: str = "") -> tuple[str, bool]:
    """Apply guardrail to agent output before returning to user.

    Args:
        response: The agent's generated response text.
        grounding_source: Optional context from RAG retrieval to check
                         grounding/hallucination against.

    Returns:
        Tuple of (text, is_blocked):
          - If allowed: (original response, False)
          - If blocked/modified: (filtered response, True)
    """
    _load_guardrail_config()

    if not _guardrail_id or not _guardrail_version:
        logger.debug("Guardrails not configured — skipping output filter")
        return response, False

    try:
        client = _get_runtime_client()

        content = [{"text": {"text": response}}]

        # If we have grounding source, include it for hallucination detection
        if grounding_source:
            content.append(
                {
                    "text": {
                        "text": grounding_source,
                        "qualifiers": ["grounding_source"],
                    }
                }
            )

        resp = client.apply_guardrail(
            guardrailIdentifier=_guardrail_id,
            guardrailVersion=_guardrail_version,
            source="OUTPUT",
            content=content,
        )

        action = resp.get("action", "NONE")

        if action == "GUARDRAIL_INTERVENED":
            outputs = resp.get("outputs", [])
            filtered_text = (
                outputs[0]["text"]
                if outputs
                else ("The response was filtered by safety guardrails. Please try rephrasing your question.")
            )
            logger.info("Output BLOCKED by guardrail (len=%d)", len(response))
            return filtered_text, True

        return response, False

    except Exception as e:
        # Fail open on errors — return original response
        logger.error("Guardrail output check failed (allowing through): %s", e)
        return response, False
