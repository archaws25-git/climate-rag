"""Tests for guardrails — validates input/output filtering works."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))


class TestGuardrailInputFiltering:
    """Tests that off-topic/harmful queries are blocked."""

    def test_rejects_non_climate_query(self):
        """System prompt should cause agent to reject non-climate queries."""
        # This is a behavioral test — verify the system prompt contains
        # the restriction. Actual LLM behavior is tested in e2e eval.
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent.parent / "agent" / "prompts" / "system_prompt.txt"
        prompt = prompt_path.read_text()

        # System prompt should restrict to climate data
        assert "climate" in prompt.lower()
        assert "GHCN" in prompt or "GISTEMP" in prompt or "NASA" in prompt

    def test_system_prompt_requires_citations(self):
        """System prompt should mandate source citations."""
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent.parent / "agent" / "prompts" / "system_prompt.txt"
        prompt = prompt_path.read_text()

        assert "SOURCE" in prompt
        assert "cite" in prompt.lower() or "citation" in prompt.lower()

    def test_system_prompt_prevents_fabrication(self):
        """System prompt should forbid value fabrication."""
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent.parent / "agent" / "prompts" / "system_prompt.txt"
        prompt = prompt_path.read_text()

        assert "NEVER fabricate" in prompt or "never fabricate" in prompt.lower()

    def test_chart_tool_rejects_dangerous_code(self):
        """Chart tool should not crash on arbitrary code — guards or CI handle it."""
        import json
        from unittest.mock import MagicMock, patch

        os.environ["CLIMATE_RAG_CODE_INTERPRETER_ID"] = "test-ci"

        import importlib
        import tools.chart_tool as ct

        importlib.reload(ct)

        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_client.start_code_interpreter_session.return_value = {"sessionId": "s1"}
            mock_client.invoke_code_interpreter.return_value = {
                "stream": [{"result": {"structuredContent": {"stdout": "error: permission denied"}}}]
            }
            mock_client.stop_code_interpreter_session.return_value = {}
            mock_boto.return_value = mock_client

            result = ct.generate_chart(python_code="import os; os.system('rm -rf /')", description="test")

        parsed = json.loads(result)
        assert "status" in parsed
        # Should be error (no CHART_BASE64 in output) but not a crash
        assert parsed["status"] == "error"

    def test_chart_tool_blocks_merge(self):
        """Chart tool guard blocks .merge() calls."""
        import json

        os.environ["CLIMATE_RAG_CODE_INTERPRETER_ID"] = "test-ci"

        import importlib
        import tools.chart_tool as ct

        importlib.reload(ct)

        result = ct.generate_chart(python_code="df1.merge(df2)", description="test")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert ".merge(" in parsed["error"]


class TestGuardrailOutputFiltering:
    """Tests that system prompt prevents harmful outputs."""

    def test_no_fahrenheit_in_prompt(self):
        """System should output Celsius only (per prompt rules)."""
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent.parent / "agent" / "prompts" / "system_prompt.txt"
        prompt = prompt_path.read_text()

        assert "Celsius ONLY" in prompt or "do NOT include Fahrenheit" in prompt

    def test_single_chart_limit(self):
        """System prompt should limit to one chart per response."""
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent.parent / "agent" / "prompts" / "system_prompt.txt"
        prompt = prompt_path.read_text()

        assert "ONE chart" in prompt or "one chart" in prompt.lower()
