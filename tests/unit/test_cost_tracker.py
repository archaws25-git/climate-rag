"""Tests for the cost tracking module."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from tools.cost_tracker import CostTracker, RequestCost


class TestRequestCost:
    """Tests for RequestCost dataclass."""

    def test_empty_cost_is_zero(self):
        """Empty request should have zero cost."""
        cost = RequestCost()
        assert cost.total_cost_usd == 0.0
        assert cost.total_tokens == 0

    def test_llm_tokens_cost(self):
        """Should calculate LLM cost correctly."""
        cost = RequestCost(llm_input_tokens=1000, llm_output_tokens=500)
        # 1000 input: 1000/1M * $3 = $0.003
        # 500 output: 500/1M * $15 = $0.0075
        expected = 0.003 + 0.0075
        assert abs(cost.total_cost_usd - expected) < 0.0001

    def test_embedding_tokens_cost(self):
        """Should calculate embedding cost correctly."""
        cost = RequestCost(embedding_tokens=10000)
        # 10000/1M * $0.02 = $0.0002
        assert abs(cost.total_cost_usd - 0.0002) < 0.00001

    def test_total_tokens(self):
        """Should sum all token types."""
        cost = RequestCost(
            llm_input_tokens=100,
            llm_output_tokens=200,
            embedding_tokens=50,
            reranker_input_tokens=30,
            reranker_output_tokens=10,
            planner_input_tokens=20,
            planner_output_tokens=5,
        )
        assert cost.total_tokens == 415

    def test_to_dict(self):
        """Should serialize to dict with expected keys."""
        cost = RequestCost(llm_input_tokens=100, llm_output_tokens=50)
        d = cost.to_dict()
        assert "llm_input_tokens" in d
        assert "llm_output_tokens" in d
        assert "total_tokens" in d
        assert "estimated_cost_usd" in d
        assert d["total_tokens"] == 150


class TestCostTracker:
    """Tests for the CostTracker singleton."""

    def test_track_request(self):
        """Should track tokens for a single request."""
        tracker = CostTracker()
        tracker.reset_request()
        tracker.add_llm_tokens(500, 200)
        tracker.add_embedding_tokens(100)
        result = tracker.finish_request()

        assert result.llm_input_tokens == 500
        assert result.llm_output_tokens == 200
        assert result.embedding_tokens == 100

    def test_session_accumulates(self):
        """Session total should accumulate across requests."""
        tracker = CostTracker()

        tracker.reset_request()
        tracker.add_llm_tokens(100, 50)
        tracker.finish_request()

        tracker.reset_request()
        tracker.add_llm_tokens(200, 100)
        tracker.finish_request()

        assert tracker.session_cost.llm_input_tokens == 300
        assert tracker.session_cost.llm_output_tokens == 150
        assert tracker.request_count == 2

    def test_get_summary(self):
        """Should return a valid summary dict."""
        tracker = CostTracker()
        tracker.reset_request()
        tracker.add_llm_tokens(1000, 500)
        tracker.finish_request()

        summary = tracker.get_summary()
        assert summary["requests"] == 1
        assert summary["session_total"]["total_tokens"] == 1500
        assert summary["avg_cost_per_request"] > 0

    def test_thread_safety(self):
        """Should handle concurrent access without errors."""
        import threading

        tracker = CostTracker()
        errors = []

        def add_tokens():
            try:
                for _ in range(100):
                    tracker.add_llm_tokens(10, 5)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_tokens) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert tracker.session_cost.llm_input_tokens == 5000  # 5 threads × 100 × 10
