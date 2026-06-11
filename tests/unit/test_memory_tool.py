"""Tests for the memory tool — mocking AgentCore Memory SDK."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def mock_memory_session():
    """Create a mock MemorySessionManager and session."""
    mock_session = MagicMock()
    mock_session.search_long_term_memories.return_value = [
        "Previous finding: Global avg temp rose 1.1°C since pre-industrial",
        "User prefers Celsius and time-series charts",
    ]
    mock_session.get_last_k_turns.return_value = [
        "User: What is the temperature trend?",
        "Assistant: The global temperature has risen by approximately 1.1°C.",
    ]
    return mock_session


class TestRecallResearchContext:
    """Tests for the recall_research_context tool."""

    def test_returns_memory_results(self, mock_memory_session, monkeypatch):
        """Should return search results from long-term memory."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        with patch(
            "agent.tools.memory_tool._get_session",
            return_value=mock_memory_session,
        ):
            from agent.tools.memory_tool import recall_research_context

            result = recall_research_context(
                actor_id="researcher-1",
                session_id="session-abc",
                query="temperature trends",
            )

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert "1.1°C" in parsed[0]

    def test_calls_search_with_query(self, mock_memory_session, monkeypatch):
        """Should pass the query and correct parameters to search."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        with patch(
            "agent.tools.memory_tool._get_session",
            return_value=mock_memory_session,
        ):
            from agent.tools.memory_tool import recall_research_context

            recall_research_context(
                actor_id="researcher-1",
                session_id="session-abc",
                query="solar radiation data",
            )

        mock_memory_session.search_long_term_memories.assert_called_once_with(
            query="solar radiation data", namespace_prefix="/", top_k=5
        )


class TestGetRecentTurns:
    """Tests for the get_recent_turns tool."""

    def test_returns_recent_turns(self, mock_memory_session, monkeypatch):
        """Should return last k conversation turns."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        with patch(
            "agent.tools.memory_tool._get_session",
            return_value=mock_memory_session,
        ):
            from agent.tools.memory_tool import get_recent_turns

            result = get_recent_turns(
                actor_id="researcher-1",
                session_id="session-abc",
                k=5,
            )

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_calls_get_last_k_with_parameter(self, mock_memory_session, monkeypatch):
        """Should pass k parameter to the session manager."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        with patch(
            "agent.tools.memory_tool._get_session",
            return_value=mock_memory_session,
        ):
            from agent.tools.memory_tool import get_recent_turns

            get_recent_turns(
                actor_id="researcher-1",
                session_id="session-abc",
                k=3,
            )

        mock_memory_session.get_last_k_turns.assert_called_once_with(k=3)


class TestSaveTurn:
    """Tests for the save_turn function."""

    def test_saves_user_turn(self, mock_memory_session, monkeypatch):
        """Should save a user turn with correct role."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        with patch(
            "agent.tools.memory_tool._get_session",
            return_value=mock_memory_session,
        ):
            from agent.tools.memory_tool import save_turn

            save_turn(
                actor_id="researcher-1",
                session_id="session-abc",
                role="user",
                content="What is the temperature in Atlanta?",
            )

        mock_memory_session.add_turns.assert_called_once()

    def test_saves_assistant_turn(self, mock_memory_session, monkeypatch):
        """Should save an assistant turn with correct role."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        with patch(
            "agent.tools.memory_tool._get_session",
            return_value=mock_memory_session,
        ):
            from agent.tools.memory_tool import save_turn

            save_turn(
                actor_id="researcher-1",
                session_id="session-abc",
                role="assistant",
                content="Atlanta's average temperature has risen 1.2°C since 1950.",
            )

        mock_memory_session.add_turns.assert_called_once()
