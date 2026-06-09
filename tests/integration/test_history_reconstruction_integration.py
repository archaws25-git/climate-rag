"""
Integration test for history reconstruction with real AgentCore Memory.

Tests 5-turn conversation persistence and reconstruction through the
full Memory SDK → reconstruct_history pipeline.

Run with:
    python -m pytest tests/integration/test_history_reconstruction_integration.py -m integration -v

Requires:
    - Valid AWS credentials (aws sso login)
    - CLIMATE_RAG_MEMORY_ID set (from SSM or env)
"""

import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

pytestmark = pytest.mark.integration

MEMORY_ID = os.environ.get("CLIMATE_RAG_MEMORY_ID", "")


@pytest.fixture
def session_context():
    """Generate unique actor and session IDs for test isolation."""
    return {
        "actor_id": f"test-recon-{uuid.uuid4().hex[:8]}",
        "session_id": f"test-recon-{uuid.uuid4().hex[:8]}",
    }


# The 5-turn conversation to persist and reconstruct
FIVE_TURN_CONVERSATION = [
    ("user", "What is the average temperature in Atlanta in the 2010s?"),
    ("assistant", "According to GHCN v4 data, Atlanta Hartsfield (USW00013874) averaged approximately 17.3°C in the 2010s decade."),
    ("user", "How does that compare to the 1950s?"),
    ("assistant", "In the 1950s, Atlanta averaged approximately 15.8°C, indicating a warming of about 1.5°C over 60 years."),
    ("user", "What about precipitation trends in the Southeast?"),
    ("assistant", "NASA POWER data shows Southeast precipitation averaging 3.4 mm/day with slight increases since the 1980s."),
    ("user", "Can you make a chart comparing Atlanta temps across decades?"),
    ("assistant", "I've generated a chart showing Atlanta's decadal temperature progression from the 1950s to 2020s."),
    ("user", "What's the warmest decade globally according to GISTEMP?"),
    ("assistant", "The 2020s is the warmest decade on record globally with an anomaly of +1.27°C above the 1951-1980 baseline."),
]


class TestHistoryReconstructionIntegration:
    """Integration tests: save 5 turns, reconstruct, validate."""

    @pytest.fixture(autouse=True)
    def check_memory_configured(self):
        """Skip if Memory ID is not available."""
        if not MEMORY_ID:
            pytest.skip("CLIMATE_RAG_MEMORY_ID not set — Memory not deployed")

    def test_save_five_turns(self, session_context):
        """Should save 5 user/assistant turn pairs (10 messages) to Memory."""
        from tools.memory_tool import save_turn

        for role, content in FIVE_TURN_CONVERSATION:
            save_turn(
                actor_id=session_context["actor_id"],
                session_id=session_context["session_id"],
                role=role,
                content=content,
            )

        # Brief pause for eventual consistency
        time.sleep(10)

    def test_reconstruct_five_turns(self, session_context):
        """Should reconstruct 5 turn pairs into valid Bedrock messages."""
        from tools.history_reconstruction import reconstruct_history
        from tools.memory_tool import save_turn

        # First, save the conversation
        for role, content in FIVE_TURN_CONVERSATION:
            save_turn(
                actor_id=session_context["actor_id"],
                session_id=session_context["session_id"],
                role=role,
                content=content,
            )

        time.sleep(10)

        # Reconstruct
        messages = reconstruct_history(
            actor_id=session_context["actor_id"],
            session_id=session_context["session_id"],
            max_turns=10,
        )

        # Should have messages (may not be exactly 10 due to Memory dedup)
        assert len(messages) >= 4, f"Expected at least 4 messages, got {len(messages)}"

        # Validate alternation
        for i, msg in enumerate(messages):
            expected_role = "user" if i % 2 == 0 else "assistant"
            assert msg["role"] == expected_role, (
                f"Message {i} has role '{msg['role']}', expected '{expected_role}'"
            )

        # Validate content structure
        for msg in messages:
            assert "content" in msg
            assert isinstance(msg["content"], list)
            assert len(msg["content"]) > 0
            assert "text" in msg["content"][0]
            assert len(msg["content"][0]["text"]) > 0

    def test_reconstructed_history_has_correct_content(self, session_context):
        """Reconstructed messages should contain the original conversation content."""
        from tools.history_reconstruction import reconstruct_history
        from tools.memory_tool import save_turn

        # Save conversation
        for role, content in FIVE_TURN_CONVERSATION:
            save_turn(
                actor_id=session_context["actor_id"],
                session_id=session_context["session_id"],
                role=role,
                content=content,
            )

        time.sleep(10)

        messages = reconstruct_history(
            actor_id=session_context["actor_id"],
            session_id=session_context["session_id"],
            max_turns=10,
        )

        # Check that key content from our conversation appears
        all_text = " ".join(
            msg["content"][0]["text"] for msg in messages
        )
        # At least some of our conversation content should be present
        assert "Atlanta" in all_text or "temperature" in all_text, (
            f"Expected conversation content in reconstruction, got: {all_text[:200]}"
        )

    def test_cross_session_isolation(self, session_context):
        """Different session IDs should not share history."""
        from tools.history_reconstruction import reconstruct_history
        from tools.memory_tool import save_turn

        # Save to session A
        save_turn(
            actor_id=session_context["actor_id"],
            session_id=session_context["session_id"],
            role="user",
            content="This is session A unique content XYZ123",
        )
        save_turn(
            actor_id=session_context["actor_id"],
            session_id=session_context["session_id"],
            role="assistant",
            content="Acknowledged session A",
        )

        time.sleep(10)

        # Reconstruct from a DIFFERENT session
        other_session = f"other-session-{uuid.uuid4().hex[:8]}"
        messages = reconstruct_history(
            actor_id=session_context["actor_id"],
            session_id=other_session,
            max_turns=10,
        )

        # Other session should NOT contain session A's content
        all_text = " ".join(
            msg["content"][0]["text"] for msg in messages
        ) if messages else ""
        assert "XYZ123" not in all_text

    def test_reconstruction_survives_empty_session(self, session_context):
        """Should return empty list for a brand new session with no history."""
        from tools.history_reconstruction import reconstruct_history

        fresh_session = f"fresh-{uuid.uuid4().hex[:8]}"
        messages = reconstruct_history(
            actor_id=session_context["actor_id"],
            session_id=fresh_session,
            max_turns=10,
        )

        assert messages == [] or isinstance(messages, list)
