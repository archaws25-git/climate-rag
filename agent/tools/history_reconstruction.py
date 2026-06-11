"""History reconstruction — Rebuild Bedrock-compatible message history from AgentCore Memory.

Converts stored conversation turns (from AgentCore Memory short-term storage)
into the Bedrock Converse API message format. Handles:
  - Role alternation validation (user/assistant must alternate)
  - Corrupted turn filtering (skips turns that would break Bedrock's schema)
  - Token budget awareness (keeps only the most recent N turns)

This enables multi-turn conversations to survive process restarts and
orphaned tool_use recovery without losing context.
"""

import logging
import os
from typing import Optional

from bedrock_agentcore.memory.session import MemorySessionManager

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")

# Maximum turns to reconstruct (keeps context manageable)
MAX_RECONSTRUCTION_TURNS = 10


def _get_memory_id() -> str:
    """Read memory ID lazily."""
    return os.environ.get("CLIMATE_RAG_MEMORY_ID", "")


def reconstruct_history(
    actor_id: str,
    session_id: str,
    max_turns: int = MAX_RECONSTRUCTION_TURNS,
) -> list[dict]:
    """Rebuild Bedrock-compatible message history from AgentCore Memory.

    Retrieves the last `max_turns` conversation turns from Memory and
    converts them into the Bedrock Converse API message format:
        [{"role": "user", "content": [{"text": "..."}]}, ...]

    Validates role alternation and filters corrupted entries.

    Args:
        actor_id: Actor/researcher identifier.
        session_id: Session identifier.
        max_turns: Maximum number of turns to retrieve.

    Returns:
        List of Bedrock-compatible message dicts, ready to assign to
        agent.messages. Returns empty list on any failure.
    """
    memory_id = _get_memory_id()
    if not memory_id:
        return []

    try:
        mgr = MemorySessionManager(memory_id=memory_id, region_name=REGION)
        session = mgr.create_memory_session(actor_id=actor_id, session_id=session_id)
        turns = session.get_last_k_turns(k=max_turns)
    except Exception as e:
        logger.warning(f"Memory recall failed, starting fresh: {e}")
        return []

    if not turns:
        logger.info(f"No turns found for actor={actor_id} session={session_id}")
        return []

    logger.info(f"Retrieved {len(turns)} turns from Memory")
    # Debug: log the raw structure of the first turn
    if turns:
        logger.info(f"First turn type: {type(turns[0]).__name__}, repr: {repr(turns[0])[:300]}")

    # Convert Memory turns to Bedrock message format
    raw_messages = _convert_turns_to_messages(turns)
    logger.info(f"Converted to {len(raw_messages)} raw messages")

    # Validate and repair the message list
    valid_messages = _validate_message_sequence(raw_messages)
    logger.info(f"Validated to {len(valid_messages)} messages")

    return valid_messages


def _convert_turns_to_messages(turns) -> list[dict]:
    """Convert AgentCore Memory turns to Bedrock message dicts.

    AgentCore Memory's get_last_k_turns returns a list of "turns", where
    each turn is itself a list of message dicts:
        [[{'content': {'text': '...'}, 'role': 'USER'}], ...]

    They arrive in reverse chronological order (newest first).
    We flatten, reverse, and convert to Bedrock format:
        {"role": "user"|"assistant", "content": [{"text": "..."}]}
    """
    messages = []

    # Flatten: each turn is a list containing one or more EventMessage objects
    # EventMessage has .content (dict with 'text'), .role (str), and supports dict()
    flat_messages = []
    for turn in turns:
        if isinstance(turn, list):
            for msg in turn:
                if isinstance(msg, dict):
                    flat_messages.append(msg)
                elif hasattr(msg, "content") and hasattr(msg, "role"):
                    # EventMessage object — convert to dict
                    flat_messages.append({"content": msg.content, "role": msg.role})
                else:
                    try:
                        flat_messages.append(dict(msg))
                    except (TypeError, ValueError):
                        continue
        elif isinstance(turn, dict):
            flat_messages.append(turn)
        elif hasattr(turn, "content") and hasattr(turn, "role"):
            flat_messages.append({"content": turn.content, "role": turn.role})
        else:
            continue

    # Reverse to chronological order (API returns newest first)
    flat_messages.reverse()

    logger.info(f"Flattened to {len(flat_messages)} messages. First: {flat_messages[0] if flat_messages else 'EMPTY'}")

    for msg in flat_messages:
        try:
            # Extract role
            role_raw = msg.get("role", "")
            if not role_raw:
                continue
            role_str = role_raw.lower() if isinstance(role_raw, str) else str(role_raw).lower()

            if "user" in role_str:
                bedrock_role = "user"
            elif "assistant" in role_str:
                bedrock_role = "assistant"
            else:
                continue

            # Extract text — handles both {"content": {"text": "..."}} and {"text": "..."}
            content = msg.get("content", {})
            if isinstance(content, dict):
                text_val = content.get("text", "")
            elif isinstance(content, str):
                text_val = content
            else:
                text_val = msg.get("text", str(msg))

            if not text_val or not text_val.strip():
                continue

            messages.append(
                {
                    "role": bedrock_role,
                    "content": [{"text": text_val.strip()}],
                }
            )
        except Exception as e:
            logger.warning(f"Skipping corrupted turn: {e}")
            continue

    return messages


def _validate_message_sequence(messages: list[dict]) -> list[dict]:
    """Validate and repair Bedrock message sequence.

    Bedrock requires:
    1. Roles must alternate (user → assistant → user → ...)
    2. No consecutive same-role messages
    3. First message must be "user" role

    Strategy: find the first "user" message, start from there,
    then enforce alternation. Drop trailing user message since
    we'll append a new one.
    """
    if not messages:
        return []

    # Find first user message to start from
    start_idx = 0
    for i, msg in enumerate(messages):
        if msg["role"] == "user":
            start_idx = i
            break
    else:
        # No user messages at all
        return []

    validated = []
    expected_role: Optional[str] = "user"

    for msg in messages[start_idx:]:
        role = msg["role"]

        if role == expected_role:
            validated.append(msg)
            expected_role = "assistant" if role == "user" else "user"
        else:
            # Skip this message — it breaks alternation
            logger.debug(f"Skipping out-of-order {role} message (expected {expected_role})")
            continue

    # Drop trailing user message (new user prompt will be appended after)
    if validated and validated[-1]["role"] == "user":
        validated.pop()

    return validated
