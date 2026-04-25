"""Memory tool — AgentCore Memory integration for multi-session context."""

import os
import json

from bedrock_agentcore.memory.session import MemorySessionManager
from bedrock_agentcore.memory.constants import ConversationalMessage, MessageRole
from strands import tool

MEMORY_ID = os.environ.get("CLIMATE_RAG_MEMORY_ID", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_session(actor_id: str, session_id: str):
    mgr = MemorySessionManager(memory_id=MEMORY_ID, region_name=REGION)
    return mgr.create_memory_session(actor_id=actor_id, session_id=session_id)


@tool
def recall_research_context(actor_id: str, session_id: str, query: str) -> str:
    """Retrieve relevant long-term memory for a researcher.

    Args:
        actor_id: Researcher identifier.
        session_id: Current session identifier.
        query: What to search for in long-term memory.

    Returns:
        Relevant prior findings and preferences from long-term memory.
    """
    session = _get_session(actor_id, session_id)
    records = session.search_long_term_memories(
        query=query, namespace_prefix="/", top_k=5
    )
    return json.dumps([str(r) for r in records], indent=2)


@tool
def get_recent_turns(actor_id: str, session_id: str, k: int = 5) -> str:
    """Get recent conversation turns from short-term memory.

    Args:
        actor_id: Researcher identifier.
        session_id: Current session identifier.
        k: Number of recent turns to retrieve.

    Returns:
        Recent conversation turns.
    """
    session = _get_session(actor_id, session_id)
    turns = session.get_last_k_turns(k=k)
    return json.dumps([str(t) for t in turns], indent=2)


def save_turn(actor_id: str, session_id: str, role: str, content: str):
    """Save a conversation turn to memory (called by agent main loop)."""
    session = _get_session(actor_id, session_id)
    msg_role = MessageRole.USER if role == "user" else MessageRole.ASSISTANT
    session.add_turns(messages=[ConversationalMessage(content, msg_role)])
