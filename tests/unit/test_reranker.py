"""Tests for the cross-encoder re-ranker."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from tools.reranker import rerank


class TestReranker:
    """Tests for the rerank function."""

    def test_reranks_by_relevance_score(self):
        """Should reorder candidates by LLM-assigned relevance score."""
        candidates = [
            {"text": "Irrelevant document about cooking", "score": 0.9},
            {"text": "Southeast Atlanta temperature climate data GHCN", "score": 0.5},
            {"text": "Another irrelevant document", "score": 0.8},
        ]

        # Mock LLM to give high score to climate doc, low to others
        mock_client = MagicMock()
        responses = [
            {"output": {"message": {"content": [{"text": "2"}]}}},  # cooking = 2/10
            {"output": {"message": {"content": [{"text": "9"}]}}},  # climate = 9/10
            {"output": {"message": {"content": [{"text": "1"}]}}},  # irrelevant = 1/10
        ]
        mock_client.converse.side_effect = responses

        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = mock_client
            result = rerank("Southeast temperature data", candidates, top_k=2)

        assert len(result) == 2
        # Climate doc should be ranked first after re-ranking
        assert result[0]["rerank_score"] > result[1]["rerank_score"]

    def test_returns_original_on_failure(self):
        """Should return original order if re-ranking fails."""
        candidates = [
            {"text": "Doc A", "score": 0.9},
            {"text": "Doc B", "score": 0.8},
            {"text": "Doc C", "score": 0.7},
        ]

        mock_client = MagicMock()
        mock_client.converse.side_effect = RuntimeError("Service unavailable")

        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = mock_client
            result = rerank("test query", candidates, top_k=2)

        assert len(result) == 2
        assert result[0]["text"] == "Doc A"  # Original order preserved

    def test_fewer_than_top_k_returns_all(self):
        """If fewer candidates than top_k, return all."""
        candidates = [
            {"text": "Only one doc", "score": 0.5},
        ]

        result = rerank("test", candidates, top_k=5)
        assert len(result) == 1

    def test_empty_candidates(self):
        """Empty candidate list returns empty."""
        result = rerank("test", [], top_k=5)
        assert result == []

    def test_adds_rerank_score_field(self):
        """Each result should have a rerank_score field."""
        candidates = [
            {"text": "Doc 1", "score": 0.9},
            {"text": "Doc 2", "score": 0.8},
            {"text": "Doc 3", "score": 0.7},
            {"text": "Doc 4", "score": 0.6},
            {"text": "Doc 5", "score": 0.5},
            {"text": "Doc 6", "score": 0.4},
        ]

        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "5"}]}}}

        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = mock_client
            result = rerank("test query", candidates, top_k=3)

        for r in result:
            assert "rerank_score" in r
            assert 0.0 <= r["rerank_score"] <= 1.0
