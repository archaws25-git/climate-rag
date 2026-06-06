"""Tests for the Bedrock Guardrails integration module."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))


class TestApplyInputGuardrail:
    """Tests for the input guardrail (pre-processing user prompts)."""

    def test_skips_when_not_configured(self, monkeypatch):
        """Should pass through when guardrail ID is empty."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "")

        import importlib
        import tools.guardrails as mod
        importlib.reload(mod)
        mod._guardrail_id = None
        mod._guardrail_version = None

        text, blocked = mod.apply_input_guardrail("What is the temperature?")
        assert blocked is False
        assert text == "What is the temperature?"

    def test_allows_safe_input(self, monkeypatch):
        """Should allow through a safe climate question."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-guardrail")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = {
            "action": "NONE",
            "outputs": [],
        }

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-guardrail"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_input_guardrail("Temperature in Atlanta?")

        assert blocked is False
        assert text == "Temperature in Atlanta?"

    def test_blocks_harmful_input(self, monkeypatch):
        """Should block input that triggers the guardrail."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-guardrail")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "This query is blocked by safety filters."}],
        }

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-guardrail"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_input_guardrail("How to hack a weather station?")

        assert blocked is True
        assert "blocked" in text.lower()

    def test_fails_open_on_error(self, monkeypatch):
        """Should allow through on API error (fail-open)."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-guardrail")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.side_effect = RuntimeError("API error")

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-guardrail"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_input_guardrail("Safe question")

        assert blocked is False
        assert text == "Safe question"


class TestApplyOutputGuardrail:
    """Tests for the output guardrail (post-processing agent responses)."""

    def test_skips_when_not_configured(self, monkeypatch):
        """Should pass through when guardrail not configured."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "")

        import importlib
        import tools.guardrails as mod
        importlib.reload(mod)
        mod._guardrail_id = None
        mod._guardrail_version = None

        text, blocked = mod.apply_output_guardrail("The temperature is 15°C.")
        assert blocked is False
        assert text == "The temperature is 15°C."

    def test_allows_safe_output(self, monkeypatch):
        """Should allow safe agent output through."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-guardrail")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = {
            "action": "NONE",
            "outputs": [],
        }

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-guardrail"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_output_guardrail("Atlanta avg temp: 17.5°C")

        assert blocked is False

    def test_blocks_pii_in_output(self, monkeypatch):
        """Should block output containing PII."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-guardrail")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.return_value = {
            "action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "Response filtered due to PII."}],
        }

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-guardrail"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_output_guardrail(
                "Call me at 555-123-4567 for results."
            )

        assert blocked is True
        assert "filtered" in text.lower() or "PII" in text
