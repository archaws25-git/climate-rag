"""Tests for the LLM-based query planner."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from tools.query_planner import plan_query


class TestQueryPlanner:
    """Tests for the plan_query function."""

    def test_single_entity_query(self):
        """Single-entity query should return one sub-query."""
        mock_response = {
            "output": {"message": {"content": [{"text": json.dumps({
                "is_multi_entity": False,
                "sub_queries": ["Temperature in Alaska"]
            })}]}}
        }

        mock_client = MagicMock()
        mock_client.converse.return_value = mock_response

        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = mock_client
            result = plan_query("Temperature in Alaska")

        assert result["is_multi_entity"] is False
        assert len(result["sub_queries"]) == 1

    def test_multi_entity_query(self):
        """Comparison query should be split into sub-queries."""
        mock_response = {
            "output": {"message": {"content": [{"text": json.dumps({
                "is_multi_entity": True,
                "sub_queries": [
                    "New York temperature climate data",
                    "Los Angeles temperature climate data",
                ]
            })}]}}
        }

        mock_client = MagicMock()
        mock_client.converse.return_value = mock_response

        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = mock_client
            result = plan_query("Compare New York and Los Angeles")

        assert result["is_multi_entity"] is True
        assert len(result["sub_queries"]) == 2

    def test_fallback_on_error(self):
        """Should return original query on LLM failure."""
        mock_client = MagicMock()
        mock_client.converse.side_effect = RuntimeError("API error")

        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = mock_client
            result = plan_query("Some query about climate")

        assert result["is_multi_entity"] is False
        assert result["sub_queries"] == ["Some query about climate"]

    def test_invalid_json_fallback(self):
        """Should fallback when LLM returns invalid JSON."""
        mock_response = {
            "output": {"message": {"content": [{"text": "Not valid JSON at all"}]}}
        }

        mock_client = MagicMock()
        mock_client.converse.return_value = mock_response

        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = mock_client
            result = plan_query("Test query")

        assert result["is_multi_entity"] is False
        assert result["sub_queries"] == ["Test query"]
