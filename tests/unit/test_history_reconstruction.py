"""Unit tests for history reconstruction from AgentCore Memory."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))


class FakeTurn:
    """Mimics a ConversationalMessage from AgentCore Memory."""

    def __init__(self, text: str, role):
        self.text = text
        self.role = role


class FakeRole:
    """Mimics MessageRole enum."""

    def __init__(self, value: str):
        self.value = value


USER = FakeRole("USER")
ASSISTANT = FakeRole("ASSISTANT")


class TestConvertTurnsToMessages:
    """Tests for _convert_turns_to_messages."""

    def test_converts_user_turn(self):
        """Should convert a user turn in list-of-lists format."""
        from tools.history_reconstruction import _convert_turns_to_messages

        turns = [[{"content": {"text": "Hello"}, "role": "USER"}]]
        result = _convert_turns_to_messages(turns)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == [{"text": "Hello"}]

    def test_converts_assistant_turn(self):
        """Should convert an assistant turn."""
        from tools.history_reconstruction import _convert_turns_to_messages

        turns = [[{"content": {"text": "The temperature is 15C"}, "role": "ASSISTANT"}]]
        result = _convert_turns_to_messages(turns)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == [{"text": "The temperature is 15C"}]

    def test_converts_multiple_turns_in_reverse_order(self):
        """Should reverse turns from newest-first to chronological."""
        from tools.history_reconstruction import _convert_turns_to_messages

        # API returns newest first
        turns = [
            [{"content": {"text": "It has warmed by 0.5C."}, "role": "ASSISTANT"}],
            [{"content": {"text": "How about since 1950?"}, "role": "USER"}],
            [{"content": {"text": "Atlanta averages 17C."}, "role": "ASSISTANT"}],
            [{"content": {"text": "What is the temp in Atlanta?"}, "role": "USER"}],
        ]
        result = _convert_turns_to_messages(turns)

        assert len(result) == 4
        # After reversal: user, assistant, user, assistant (chronological)
        assert result[0]["role"] == "user"
        assert "Atlanta" in result[0]["content"][0]["text"]
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"
        assert result[3]["role"] == "assistant"

    def test_skips_empty_text(self):
        """Should skip turns with empty text."""
        from tools.history_reconstruction import _convert_turns_to_messages

        turns = [
            [{"content": {"text": "Valid response"}, "role": "ASSISTANT"}],
            [{"content": {"text": ""}, "role": "USER"}],
            [{"content": {"text": "Hello"}, "role": "USER"}],
        ]
        result = _convert_turns_to_messages(turns)

        assert len(result) == 2

    def test_handles_flat_dict_turns(self):
        """Should handle turns that are plain dicts (not wrapped in list)."""
        from tools.history_reconstruction import _convert_turns_to_messages

        # Flat dicts also get reversed (API returns newest first)
        turns = [
            {"content": {"text": "Hi there"}, "role": "ASSISTANT"},
            {"content": {"text": "Hello"}, "role": "USER"},
        ]
        result = _convert_turns_to_messages(turns)

        assert len(result) == 2
        # After reversal: user first, then assistant
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_skips_corrupted_turns(self):
        """Should skip turns that can't be parsed without crashing."""
        from tools.history_reconstruction import _convert_turns_to_messages

        turns = [
            [{"content": {"text": "Good turn"}, "role": "USER"}],
            None,  # Corrupted
            [{"content": {"text": "Another good turn"}, "role": "ASSISTANT"}],
        ]
        result = _convert_turns_to_messages(turns)

        assert len(result) == 2


class TestValidateMessageSequence:
    """Tests for _validate_message_sequence."""

    def test_valid_alternating_sequence(self):
        """Should pass through a valid alternating sequence."""
        from tools.history_reconstruction import _validate_message_sequence

        messages = [
            {"role": "user", "content": [{"text": "Q1"}]},
            {"role": "assistant", "content": [{"text": "A1"}]},
            {"role": "user", "content": [{"text": "Q2"}]},
            {"role": "assistant", "content": [{"text": "A2"}]},
        ]
        result = _validate_message_sequence(messages)

        assert len(result) == 4

    def test_removes_consecutive_same_role(self):
        """Should skip messages that break alternation."""
        from tools.history_reconstruction import _validate_message_sequence

        messages = [
            {"role": "user", "content": [{"text": "Q1"}]},
            {"role": "user", "content": [{"text": "Q2"}]},  # Duplicate user
            {"role": "assistant", "content": [{"text": "A1"}]},
        ]
        result = _validate_message_sequence(messages)

        assert len(result) == 2
        assert result[0]["content"] == [{"text": "Q1"}]
        assert result[1]["content"] == [{"text": "A1"}]

    def test_must_start_with_user(self):
        """Should skip leading assistant messages."""
        from tools.history_reconstruction import _validate_message_sequence

        messages = [
            {"role": "assistant", "content": [{"text": "A0"}]},
            {"role": "user", "content": [{"text": "Q1"}]},
            {"role": "assistant", "content": [{"text": "A1"}]},
        ]
        result = _validate_message_sequence(messages)

        assert len(result) == 2
        assert result[0]["role"] == "user"

    def test_drops_trailing_user_message(self):
        """Should drop trailing user message (new prompt will be appended)."""
        from tools.history_reconstruction import _validate_message_sequence

        messages = [
            {"role": "user", "content": [{"text": "Q1"}]},
            {"role": "assistant", "content": [{"text": "A1"}]},
            {"role": "user", "content": [{"text": "Q2"}]},
        ]
        result = _validate_message_sequence(messages)

        assert len(result) == 2
        assert result[-1]["role"] == "assistant"

    def test_empty_input(self):
        """Should return empty list for empty input."""
        from tools.history_reconstruction import _validate_message_sequence

        assert _validate_message_sequence([]) == []


class TestReconstructHistory:
    """Tests for the full reconstruct_history function."""

    def test_returns_empty_when_no_memory_id(self, monkeypatch):
        """Should return empty list when CLIMATE_RAG_MEMORY_ID is not set."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "")
        from tools.history_reconstruction import reconstruct_history

        result = reconstruct_history("actor1", "session1")
        assert result == []

    def test_returns_empty_on_memory_failure(self, monkeypatch):
        """Should return empty list when Memory SDK throws."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        with patch("tools.history_reconstruction.MemorySessionManager") as mock_mgr:
            mock_mgr.side_effect = RuntimeError("Connection failed")
            from tools.history_reconstruction import reconstruct_history

            result = reconstruct_history("actor1", "session1")
            assert result == []

    def test_reconstructs_valid_history(self, monkeypatch):
        """Should reconstruct valid Bedrock messages from Memory turns."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        mock_session = MagicMock()
        # Real format: list of lists, newest first
        mock_session.get_last_k_turns.return_value = [
            [{"content": {"text": "It has warmed by 0.5C."}, "role": "ASSISTANT"}],
            [{"content": {"text": "How about since 1950?"}, "role": "USER"}],
            [{"content": {"text": "Atlanta averages 17C."}, "role": "ASSISTANT"}],
            [{"content": {"text": "What is the temp in Atlanta?"}, "role": "USER"}],
        ]

        mock_mgr_instance = MagicMock()
        mock_mgr_instance.create_memory_session.return_value = mock_session

        with patch(
            "tools.history_reconstruction.MemorySessionManager",
            return_value=mock_mgr_instance,
        ):
            from tools.history_reconstruction import reconstruct_history

            result = reconstruct_history("actor1", "session1", max_turns=10)

        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"
        assert result[3]["role"] == "assistant"
        assert "Atlanta" in result[0]["content"][0]["text"]

    def test_handles_corrupted_turn_in_middle(self, monkeypatch):
        """Should skip corrupted turns and still return valid history."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        mock_session = MagicMock()
        # Includes an empty-text turn and a None
        mock_session.get_last_k_turns.return_value = [
            [{"content": {"text": "A2"}, "role": "ASSISTANT"}],
            [{"content": {"text": "Q2"}, "role": "USER"}],
            [{"content": {"text": ""}, "role": "USER"}],  # Empty — will be skipped
            [{"content": {"text": "A1"}, "role": "ASSISTANT"}],
            [{"content": {"text": "Q1"}, "role": "USER"}],
        ]

        mock_mgr_instance = MagicMock()
        mock_mgr_instance.create_memory_session.return_value = mock_session

        with patch(
            "tools.history_reconstruction.MemorySessionManager",
            return_value=mock_mgr_instance,
        ):
            from tools.history_reconstruction import reconstruct_history

            result = reconstruct_history("actor1", "session1")

        # After reversal: Q1, A1, (empty skipped), Q2, A2
        # Validation: user(Q1), assistant(A1), user(Q2), assistant(A2)
        assert len(result) == 4

    def test_returns_empty_for_no_turns(self, monkeypatch):
        """Should return empty when Memory has no turns for session."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        mock_session = MagicMock()
        mock_session.get_last_k_turns.return_value = []

        mock_mgr_instance = MagicMock()
        mock_mgr_instance.create_memory_session.return_value = mock_session

        with patch(
            "tools.history_reconstruction.MemorySessionManager",
            return_value=mock_mgr_instance,
        ):
            from tools.history_reconstruction import reconstruct_history

            result = reconstruct_history("actor1", "session1")

        assert result == []

    def test_respects_max_turns(self, monkeypatch):
        """Should pass max_turns to Memory SDK."""
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")

        mock_session = MagicMock()
        mock_session.get_last_k_turns.return_value = []

        mock_mgr_instance = MagicMock()
        mock_mgr_instance.create_memory_session.return_value = mock_session

        with patch(
            "tools.history_reconstruction.MemorySessionManager",
            return_value=mock_mgr_instance,
        ):
            from tools.history_reconstruction import reconstruct_history

            reconstruct_history("actor1", "session1", max_turns=5)

        mock_session.get_last_k_turns.assert_called_once_with(k=5)
