"""Tests for BM25 sparse search index."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from tools.bm25_search import BM25Index


class TestBM25Index:
    """Tests for the BM25Index class."""

    @pytest.fixture
    def sample_index(self):
        """Create a BM25 index with sample climate documents."""
        index = BM25Index()
        documents = [
            "Southeast United States climate data Atlanta Georgia temperature",
            "Northeast United States climate data New York temperature records",
            "Alaska United States climate data Anchorage temperature cold",
            "Global temperature anomaly GISTEMP baseline 1951 1980",
            "NASA POWER precipitation solar radiation Southeast Atlanta",
            "Midwest United States climate data Chicago Illinois temperature",
            "Hawaii United States climate data Honolulu temperature tropical",
        ]
        index.add_documents(documents)
        return index

    def test_exact_term_match(self, sample_index):
        """Should rank documents with exact term matches highest."""
        results = sample_index.search("Atlanta Southeast temperature", top_k=3)
        assert len(results) > 0
        # First result should be the Southeast/Atlanta document (index 0)
        assert results[0][0] == 0

    def test_returns_scores(self, sample_index):
        """Scores should be positive floats."""
        results = sample_index.search("temperature climate", top_k=5)
        for idx, score in results:
            assert isinstance(score, float)
            assert score > 0

    def test_top_k_limits(self, sample_index):
        """Should return at most top_k results."""
        results = sample_index.search("climate data", top_k=3)
        assert len(results) <= 3

    def test_no_match_returns_empty(self, sample_index):
        """Query with no matching terms should return empty."""
        results = sample_index.search("xyzabc qwerty", top_k=5)
        assert len(results) == 0

    def test_chicago_query(self, sample_index):
        """Chicago query should rank Midwest document highest."""
        results = sample_index.search("Chicago 1990s temperature", top_k=3)
        assert len(results) > 0
        assert results[0][0] == 5  # Midwest/Chicago doc

    def test_alaska_query(self, sample_index):
        """Alaska query should rank Alaska document highest."""
        results = sample_index.search("Alaska Anchorage cold", top_k=3)
        assert len(results) > 0
        assert results[0][0] == 2  # Alaska doc

    def test_global_gistemp_query(self, sample_index):
        """Global anomaly query should rank GISTEMP document highest."""
        results = sample_index.search("global anomaly GISTEMP", top_k=3)
        assert len(results) > 0
        assert results[0][0] == 3  # GISTEMP doc

    def test_empty_index(self):
        """Empty index should return no results."""
        index = BM25Index()
        index.add_documents([])
        results = index.search("anything", top_k=5)
        assert len(results) == 0

    def test_single_document(self):
        """Index with one document should work."""
        index = BM25Index()
        index.add_documents(["Southeast Atlanta temperature data"])
        results = index.search("Atlanta", top_k=5)
        assert len(results) == 1
        assert results[0][0] == 0


class TestBM25Tokenizer:
    """Tests for the tokenization logic."""

    def test_lowercases(self):
        """Should lowercase all tokens."""
        index = BM25Index()
        tokens = index._tokenize("ATLANTA Temperature DATA")
        assert "atlanta" in tokens
        assert "temperature" in tokens

    def test_removes_punctuation(self):
        """Should remove punctuation."""
        index = BM25Index()
        tokens = index._tokenize("Atlanta, GA. Temperature: 15.2°C")
        assert "atlanta" in tokens
        assert "," not in tokens

    def test_removes_short_tokens(self):
        """Should remove tokens with 2 or fewer characters."""
        index = BM25Index()
        tokens = index._tokenize("it is a big US city in GA")
        assert "it" not in tokens
        assert "is" not in tokens
        assert "big" in tokens
        assert "city" in tokens
