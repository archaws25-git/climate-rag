"""Tests for chart_tool — sandbox guards and error handling."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))


class TestChartToolGuards:
    """Tests for dangerous pattern detection in chart code."""

    def test_rejects_merge(self, monkeypatch):
        """Should reject code containing .merge()."""
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "test-ci-id")
        from tools.chart_tool import generate_chart

        result = generate_chart(
            python_code="df1.merge(df2, on='decade')",
            description="test",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert ".merge(" in parsed["error"]

    def test_rejects_read_json(self, monkeypatch):
        """Should reject code containing pd.read_json()."""
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "test-ci-id")
        from tools.chart_tool import generate_chart

        result = generate_chart(
            python_code="df = pd.read_json('data.json')",
            description="test",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    def test_rejects_read_csv(self, monkeypatch):
        """Should reject code containing pd.read_csv()."""
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "test-ci-id")
        from tools.chart_tool import generate_chart

        result = generate_chart(
            python_code="df = pd.read_csv('file.csv')",
            description="test",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    def test_allows_valid_code(self, monkeypatch):
        """Should not reject valid inline-data chart code."""
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "test-ci-id")
        from tools.chart_tool import generate_chart

        # Valid code should pass the guard check (will fail on execution since CI isn't real)
        code = """
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64, io
decades = ['1950s', '1960s']
temps = [12.0, 12.5]
fig, ax = plt.subplots()
ax.plot(decades, temps)
buf = io.BytesIO()
fig.savefig(buf, format='png')
buf.seek(0)
print('CHART_BASE64:' + base64.b64encode(buf.read()).decode())
plt.close()
"""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_session = MagicMock()
            mock_session.__getitem__ = MagicMock(return_value="test-session")
            mock_client.start_code_interpreter_session.return_value = {"sessionId": "s1"}
            mock_client.invoke_code_interpreter.return_value = {
                "stream": [{"result": {"structuredContent": {"stdout": "CHART_BASE64:abc123"}}}]
            }
            mock_client.stop_code_interpreter_session.return_value = {}
            mock_boto.return_value = mock_client

            result = generate_chart(python_code=code, description="test chart")

        parsed = json.loads(result)
        # Will succeed or error on base64 decode — but NOT on the guard
        assert parsed["status"] in ("success", "error")
        if parsed["status"] == "error":
            assert ".merge(" not in parsed.get("error", "")

    def test_returns_error_when_ci_not_configured(self, monkeypatch):
        """Should return error when CODE_INTERPRETER_ID is empty."""
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "")
        # Need to reload module to pick up new env
        import importlib
        import tools.chart_tool as ct

        importlib.reload(ct)

        result = ct.generate_chart(
            python_code="print('hello')",
            description="test",
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "not configured" in parsed["error"]


class TestChartToolErrorHandling:
    """Tests for sandbox error detection."""

    def test_detects_attribute_error_in_stdout(self, monkeypatch):
        """Should detect AttributeError in sandbox output."""
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "test-ci-id")
        import importlib
        import tools.chart_tool as ct

        importlib.reload(ct)

        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_client.start_code_interpreter_session.return_value = {"sessionId": "s1"}
            mock_client.invoke_code_interpreter.return_value = {
                "stream": [
                    {
                        "result": {
                            "structuredContent": {
                                "stdout": "Traceback (most recent call last):\nAttributeError: 'dict' has no attribute 'merge'"
                            }
                        }
                    }
                ]
            }
            mock_client.stop_code_interpreter_session.return_value = {}
            mock_boto.return_value = mock_client

            result = ct.generate_chart(python_code="bad code", description="test")

        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "sandbox" in parsed["error"].lower() or "attribute" in parsed["error"].lower()
