"""Tests for the agent main module — request handling and entry points."""

import importlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add both project root AND agent/ to sys.path
# agent/main.py uses 'from tools.rag_tool import ...' which requires
# the agent/ directory to be on sys.path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))


# The 'agent' directory is a package, so 'agent.main' resolves correctly
# only if we import it explicitly. We use importlib to handle the path.
def _import_agent_main():
    """Import agent.main module, handling the package path correctly."""
    spec = importlib.util.spec_from_file_location(
        "agent_main",
        os.path.join(os.path.dirname(__file__), "..", "..", "agent", "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    return mod, spec


class TestHandleRequest:
    """Tests for the handle_request function."""

    def test_returns_response_dict(self, monkeypatch, tmp_path):
        """Should return a dict with response, session_id, and charts."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        chart_dir = str(tmp_path / "charts")
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)

        # Mock strands Agent and BedrockModel before importing
        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = "The global temperature has risen by 1.1°C."

        with patch.dict("sys.modules", {
            "strands": MagicMock(),
            "strands.models": MagicMock(),
            "strands.models.bedrock": MagicMock(),
        }):
            with patch("builtins.__import__", wraps=__builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__):
                # Use direct function test approach
                pass

        # Simplified approach: test the lambda_handler logic directly
        from agent.main import handle_request
        with patch("agent.main.agent", mock_agent_instance):
            result = handle_request("What is the global temperature trend?")

        assert "response" in result
        assert "session_id" in result
        assert "charts" in result
        assert result["response"] == "The global temperature has risen by 1.1°C."

    def test_generates_session_id_if_none(self, monkeypatch, tmp_path):
        """Should generate a UUID session_id when none is provided."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        chart_dir = str(tmp_path / "charts")
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)

        mock_agent_instance = MagicMock(return_value="Answer")

        from agent.main import handle_request
        with patch("agent.main.agent", mock_agent_instance):
            result = handle_request("test query")
        assert len(result["session_id"]) > 0

    def test_uses_provided_session_id(self, monkeypatch, tmp_path):
        """Should use the provided session_id."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        chart_dir = str(tmp_path / "charts")
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)

        mock_agent_instance = MagicMock(return_value="Answer")

        from agent.main import handle_request
        with patch("agent.main.agent", mock_agent_instance):
            result = handle_request("test query", session_id="my-session-123")
        assert result["session_id"] == "my-session-123"

    def test_detects_new_chart_files(self, monkeypatch, tmp_path):
        """Should detect newly created chart PNG files."""
        chart_dir = str(tmp_path / "charts")
        os.makedirs(chart_dir, exist_ok=True)
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)

        def create_chart_side_effect(prompt):
            chart_path = os.path.join(chart_dir, "chart_abc123.png")
            with open(chart_path, "wb") as f:
                f.write(b"fake png content")
            return "Here is the chart."

        mock_agent_instance = MagicMock(side_effect=create_chart_side_effect)

        from agent.main import handle_request
        with patch("agent.main.agent", mock_agent_instance):
            result = handle_request("Plot temperature trends")
        assert len(result["charts"]) == 1
        assert result["charts"][0].endswith(".png")


class TestLambdaHandler:
    """Tests for the AgentCore Runtime entry point."""

    def test_parses_event_body(self, monkeypatch, tmp_path):
        """Should parse prompt from event body."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        chart_dir = str(tmp_path / "charts")
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)

        from agent.main import lambda_handler

        mock_handle = MagicMock(return_value={
            "response": "Answer", "session_id": "s1", "charts": []
        })

        with patch("agent.main.handle_request", mock_handle):
            event = {"body": json.dumps({"prompt": "What is the trend?"})}
            lambda_handler(event)

        mock_handle.assert_called_once_with("What is the trend?", None, "default")

    def test_handles_dict_body(self, monkeypatch, tmp_path):
        """Should handle event where body is already a dict (not JSON string)."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        chart_dir = str(tmp_path / "charts")
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)

        from agent.main import lambda_handler

        mock_handle = MagicMock(return_value={
            "response": "Answer", "session_id": "s1", "charts": []
        })

        with patch("agent.main.handle_request", mock_handle):
            event = {"prompt": "Direct dict prompt", "actor_id": "user-42"}
            lambda_handler(event)

        mock_handle.assert_called_once_with("Direct dict prompt", None, "user-42")

    def test_passes_session_id(self, monkeypatch, tmp_path):
        """Should pass session_id from event to handle_request."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        chart_dir = str(tmp_path / "charts")
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)

        from agent.main import lambda_handler

        mock_handle = MagicMock(return_value={
            "response": "Answer", "session_id": "existing-session", "charts": []
        })

        with patch("agent.main.handle_request", mock_handle):
            event = {"body": json.dumps({
                "prompt": "Follow up question",
                "session_id": "existing-session",
            })}
            lambda_handler(event)

        mock_handle.assert_called_once_with(
            "Follow up question", "existing-session", "default"
        )

    def test_empty_prompt(self, monkeypatch, tmp_path):
        """Should handle missing prompt gracefully."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        chart_dir = str(tmp_path / "charts")
        monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_dir)

        from agent.main import lambda_handler

        mock_handle = MagicMock(return_value={
            "response": "", "session_id": "s1", "charts": []
        })

        with patch("agent.main.handle_request", mock_handle):
            event = {"body": json.dumps({})}
            lambda_handler(event)

        mock_handle.assert_called_once_with("", None, "default")
