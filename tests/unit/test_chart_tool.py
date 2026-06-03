"""Tests for the chart generation tool — mocking Code Interpreter calls."""

import json
import os
import sys
import base64
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def chart_dir(tmp_path, monkeypatch):
    """Set up a temporary chart output directory."""
    chart_path = str(tmp_path / "charts")
    os.makedirs(chart_path, exist_ok=True)
    monkeypatch.setenv("CLIMATE_RAG_CHART_DIR", chart_path)
    monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "test-ci-id")
    return chart_path


class TestGenerateChart:
    """Tests for the generate_chart tool."""

    def test_no_code_interpreter_configured(self, monkeypatch):
        """Should return error when CODE_INTERPRETER_ID is not set."""
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "")

        # Need to reload module to pick up new env
        import importlib
        import agent.tools.chart_tool as chart_module
        importlib.reload(chart_module)

        result = chart_module.generate_chart(
            python_code="print('hello')",
            description="Test chart",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "not configured" in parsed["error"]

    def test_successful_chart_generation(self, chart_dir, monkeypatch):
        """Should save a PNG and return the file path on success."""
        # Create a fake base64 PNG (1x1 pixel)
        fake_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
        stdout_output = f"CHART_BASE64:{fake_png}"

        mock_client = MagicMock()
        mock_client.start_code_interpreter_session.return_value = {
            "sessionId": "test-session"
        }
        mock_client.invoke_code_interpreter.return_value = {
            "stream": [
                {"result": {"structuredContent": {"stdout": stdout_output}}}
            ]
        }
        mock_client.stop_code_interpreter_session.return_value = {}

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import agent.tools.chart_tool as chart_module
            importlib.reload(chart_module)
            chart_module.CHART_DIR = chart_dir

            result = chart_module.generate_chart(
                python_code="import matplotlib; print('CHART_BASE64:...')",
                description="Temperature trend",
            )

        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert "chart_path" in parsed
        assert parsed["description"] == "Temperature trend"
        # Verify file was actually created
        assert os.path.exists(parsed["chart_path"])

    def test_no_chart_in_output(self, chart_dir, monkeypatch):
        """Should return error when Code Interpreter output has no CHART_BASE64."""
        mock_client = MagicMock()
        mock_client.start_code_interpreter_session.return_value = {
            "sessionId": "test-session"
        }
        mock_client.invoke_code_interpreter.return_value = {
            "stream": [
                {"result": {"structuredContent": {"stdout": "No chart here"}}}
            ]
        }
        mock_client.stop_code_interpreter_session.return_value = {}

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import agent.tools.chart_tool as chart_module
            importlib.reload(chart_module)
            chart_module.CHART_DIR = chart_dir

            result = chart_module.generate_chart(
                python_code="print('hello')",
                description="Missing chart",
            )

        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "No chart in output" in parsed["error"]

    def test_code_interpreter_exception(self, chart_dir, monkeypatch):
        """Should handle exceptions from Code Interpreter gracefully."""
        mock_client = MagicMock()
        mock_client.start_code_interpreter_session.return_value = {
            "sessionId": "test-session"
        }
        mock_client.invoke_code_interpreter.side_effect = RuntimeError(
            "Code execution failed"
        )
        mock_client.stop_code_interpreter_session.return_value = {}

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import agent.tools.chart_tool as chart_module
            importlib.reload(chart_module)
            chart_module.CHART_DIR = chart_dir

            result = chart_module.generate_chart(
                python_code="bad code",
                description="Error chart",
            )

        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "Code execution failed" in parsed["error"]

    def test_session_cleanup_on_success(self, chart_dir, monkeypatch):
        """Should always call stop_code_interpreter_session in finally block."""
        fake_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
        stdout_output = f"CHART_BASE64:{fake_png}"

        mock_client = MagicMock()
        mock_client.start_code_interpreter_session.return_value = {
            "sessionId": "cleanup-session"
        }
        mock_client.invoke_code_interpreter.return_value = {
            "stream": [
                {"result": {"structuredContent": {"stdout": stdout_output}}}
            ]
        }

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import agent.tools.chart_tool as chart_module
            importlib.reload(chart_module)
            chart_module.CHART_DIR = chart_dir

            chart_module.generate_chart(
                python_code="code",
                description="Cleanup test",
            )

        mock_client.stop_code_interpreter_session.assert_called_once_with(
            codeInterpreterIdentifier="test-ci-id",
            sessionId="cleanup-session",
        )
