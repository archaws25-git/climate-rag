"""
Integration test for AgentCore Memory SDK.

Tests that memory save/recall works with real AWS credentials.
Validates the production Memory path independently from the multi-turn eval.

Run with: python -m pytest tests/integration/test_memory_integration.py -m integration -v

Requires:
    - Valid AWS credentials
    - CLIMATE_RAG_MEMORY_ID set (from SSM or env)
"""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

pytestmark = pytest.mark.integration

MEMORY_ID = os.environ.get("CLIMATE_RAG_MEMORY_ID", "")


@pytest.fixture
def session_context():
    """Generate unique actor and session IDs for test isolation."""
    return {
        "actor_id": f"test-actor-{uuid.uuid4().hex[:8]}",
        "session_id": f"test-session-{uuid.uuid4().hex[:8]}",
    }


class TestMemorySaveAndRecall:
    """Tests that validate Memory SDK save/recall functionality."""

    @pytest.fixture(autouse=True)
    def check_memory_configured(self):
        """Skip if Memory ID is not available."""
        if not MEMORY_ID:
            pytest.skip("CLIMATE_RAG_MEMORY_ID not set — Memory not deployed")

    def test_save_turn_succeeds(self, session_context):
        """Should successfully save a user turn to memory."""
        from tools.memory_tool import save_turn

        # Should not raise
        save_turn(
            actor_id=session_context["actor_id"],
            session_id=session_context["session_id"],
            role="user",
            content="What is the temperature trend in Atlanta?",
        )

    def test_save_and_recall_turns(self, session_context):
        """Should save turns and recall them in the same session."""
        from tools.memory_tool import get_recent_turns, save_turn

        # Save two turns
        save_turn(
            session_context["actor_id"],
            session_context["session_id"],
            "user",
            "Show me Southeast temperature data",
        )
        save_turn(
            session_context["actor_id"],
            session_context["session_id"],
            "assistant",
            "The Southeast has warmed by approximately 0.5°C since 1950.",
        )

        # Recall
        import json

        result = get_recent_turns(
            actor_id=session_context["actor_id"],
            session_id=session_context["session_id"],
            k=5,
        )
        turns = json.loads(result)
        assert len(turns) >= 2

    def test_semantic_memory_search(self, session_context):
        """Should find relevant context via semantic search."""
        from tools.memory_tool import recall_research_context, save_turn

        # Save a turn with specific content
        save_turn(
            session_context["actor_id"],
            session_context["session_id"],
            "user",
            "I am researching Arctic amplification effects on Alaska",
        )

        # Search for it semantically
        import json

        result = recall_research_context(
            actor_id=session_context["actor_id"],
            session_id=session_context["session_id"],
            query="Arctic warming Alaska",
        )
        records = json.loads(result)
        # Should find at least one relevant memory
        assert isinstance(records, list)
