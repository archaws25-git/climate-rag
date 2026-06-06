"""Tests for retrieval evaluation metrics (Recall@K, Precision@K, MRR, NDCG)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "eval"))

from run_retrieval_eval import (
    is_relevant,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


# ── Test data ─────────────────────────────────────────────────────────────────

GROUND_TRUTH = {
    "expected_source": "GHCN_v4",
    "expected_metadata_matches": [
        {"region": "Southeast"},
        {"station_id": "USW00013874"},
    ],
}

RESULTS_PERFECT = [
    {"source": "GHCN_v4", "region": "Southeast", "station_id": "USW00013874"},
    {"source": "GHCN_v4", "region": "Southeast", "station_id": "USW00012839"},
    {"source": "GHCN_v4", "region": "Northeast", "station_id": "USW00094728"},
]

RESULTS_PARTIAL = [
    {"source": "GHCN_v4", "region": "Northeast", "station_id": "USW00094728"},
    {"source": "GHCN_v4", "region": "Southeast", "station_id": "USW00013874"},
    {"source": "NASA_POWER", "region": "Southeast", "station_id": ""},
]

RESULTS_NONE = [
    {"source": "NASA_POWER", "region": "West", "station_id": ""},
    {"source": "GISTEMP_v4", "region": "Global", "station_id": ""},
]


class TestIsRelevant:
    """Tests for the relevance matching function."""

    def test_matches_region(self):
        """Should match on region when source matches."""
        result = {"source": "GHCN_v4", "region": "Southeast", "station_id": "USW00012839"}
        assert is_relevant(result, GROUND_TRUTH) is True

    def test_matches_station_id(self):
        """Should match on station_id when source matches."""
        result = {"source": "GHCN_v4", "region": "Other", "station_id": "USW00013874"}
        assert is_relevant(result, GROUND_TRUTH) is True

    def test_wrong_source(self):
        """Should not match when source doesn't match."""
        result = {"source": "NASA_POWER", "region": "Southeast", "station_id": "USW00013874"}
        assert is_relevant(result, GROUND_TRUTH) is False

    def test_no_metadata_match(self):
        """Should not match when neither region nor station matches."""
        result = {"source": "GHCN_v4", "region": "West", "station_id": "USW00023174"}
        assert is_relevant(result, GROUND_TRUTH) is False


class TestRecallAtK:
    """Tests for Recall@K metric."""

    def test_perfect_recall(self):
        """All relevant items found should give recall = 1.0."""
        recall = recall_at_k(RESULTS_PERFECT, GROUND_TRUTH, k=3)
        assert recall == 1.0

    def test_partial_recall(self):
        """Finding one of two relevant criteria should give partial recall."""
        recall = recall_at_k(RESULTS_PARTIAL, GROUND_TRUTH, k=3)
        assert 0.0 < recall <= 1.0

    def test_zero_recall(self):
        """No relevant items should give recall = 0."""
        recall = recall_at_k(RESULTS_NONE, GROUND_TRUTH, k=2)
        assert recall == 0.0

    def test_k_limits_search(self):
        """Should only look at top-K results."""
        # First result is not relevant, second is — but k=1 only checks first
        recall = recall_at_k(RESULTS_PARTIAL, GROUND_TRUTH, k=1)
        assert recall == 0.0


class TestPrecisionAtK:
    """Tests for Precision@K metric."""

    def test_all_relevant(self):
        """When all top-K are relevant, precision = 1.0."""
        precision = precision_at_k(RESULTS_PERFECT[:2], GROUND_TRUTH, k=2)
        assert precision == 1.0

    def test_mixed_results(self):
        """Mix of relevant and irrelevant should give partial precision."""
        precision = precision_at_k(RESULTS_PERFECT, GROUND_TRUTH, k=3)
        # 2 out of 3 are relevant (Southeast matches)
        assert 0.0 < precision <= 1.0

    def test_none_relevant(self):
        """No relevant results should give precision = 0."""
        precision = precision_at_k(RESULTS_NONE, GROUND_TRUTH, k=2)
        assert precision == 0.0

    def test_empty_results(self):
        """Empty results list should give precision = 0."""
        precision = precision_at_k([], GROUND_TRUTH, k=5)
        assert precision == 0.0


class TestReciprocalRank:
    """Tests for Mean Reciprocal Rank (MRR)."""

    def test_first_result_relevant(self):
        """First result relevant should give RR = 1.0."""
        rr = reciprocal_rank(RESULTS_PERFECT, GROUND_TRUTH)
        assert rr == 1.0

    def test_second_result_relevant(self):
        """Second result relevant should give RR = 0.5."""
        rr = reciprocal_rank(RESULTS_PARTIAL, GROUND_TRUTH)
        assert rr == 0.5

    def test_no_relevant_results(self):
        """No relevant results should give RR = 0."""
        rr = reciprocal_rank(RESULTS_NONE, GROUND_TRUTH)
        assert rr == 0.0


class TestNDCG:
    """Tests for Normalized Discounted Cumulative Gain."""

    def test_perfect_ranking(self):
        """Relevant items at top should give NDCG = 1.0."""
        ndcg = ndcg_at_k(RESULTS_PERFECT, GROUND_TRUTH, k=3)
        assert ndcg == 1.0  # Both relevant items at positions 1 and 2

    def test_imperfect_ranking(self):
        """Relevant item not at top should give lower NDCG."""
        ndcg = ndcg_at_k(RESULTS_PARTIAL, GROUND_TRUTH, k=3)
        assert 0.0 < ndcg < 1.0

    def test_no_relevant_items(self):
        """No relevant items should give NDCG = 0."""
        ndcg = ndcg_at_k(RESULTS_NONE, GROUND_TRUTH, k=2)
        assert ndcg == 0.0

    def test_ndcg_bounded(self):
        """NDCG should always be between 0 and 1."""
        for results in [RESULTS_PERFECT, RESULTS_PARTIAL, RESULTS_NONE]:
            ndcg = ndcg_at_k(results, GROUND_TRUTH, k=3)
            assert 0.0 <= ndcg <= 1.0
