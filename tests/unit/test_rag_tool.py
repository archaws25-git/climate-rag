"""Tests for the RAG search tool — hybrid search (vector + BM25), confidence, citations."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import faiss
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def mock_faiss_index(sample_chunks, tmp_path):
    """Create a real FAISS index and metadata file on disk for testing."""
    embeddings = np.array(
        [c["embedding"] for c in sample_chunks], dtype="float32"
    )
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(1024)
    index.add(embeddings)

    idx_path = str(tmp_path / "faiss.index")
    faiss.write_index(index, idx_path)

    meta_path = str(tmp_path / "metadata.jsonl")
    with open(meta_path, "w") as f:
        for chunk in sample_chunks:
            record = {"text": chunk["text"], "metadata": chunk["metadata"]}
            f.write(json.dumps(record) + "\n")

    return str(tmp_path), idx_path, meta_path


def _setup_mocked_rag(mock_faiss_index, monkeypatch=None):
    """Helper to set up mocked environment for RAG tests.

    Sets CHUNK_OUTPUT_DIR to point at the local test index so the module
    loads from disk (no S3/boto3 needed for index loading). Only the
    embedding call needs mocking.
    """
    tmp_dir, idx_path, meta_path = mock_faiss_index

    # Create the expected index/ subdirectory structure
    import shutil
    index_dir = os.path.join(tmp_dir, "index")
    os.makedirs(index_dir, exist_ok=True)
    shutil.copy(idx_path, os.path.join(index_dir, "faiss.index"))
    shutil.copy(meta_path, os.path.join(index_dir, "metadata.jsonl"))

    # Set env var so _load_index uses local path (no S3)
    os.environ["CHUNK_OUTPUT_DIR"] = tmp_dir

    # Mock only the Bedrock embedding call
    mock_bedrock = MagicMock()
    mock_body = MagicMock()
    fake_embedding = np.random.randn(1024).tolist()
    mock_body.read.return_value = json.dumps(
        {"embedding": fake_embedding}
    ).encode()
    mock_bedrock.invoke_model.return_value = {"body": mock_body}

    mock_session = MagicMock()
    mock_session.client.return_value = mock_bedrock

    return mock_session


def _reset_rag_module():
    """Reset the RAG module's cached state (FAISS + BM25 indices)."""
    import agent.tools.rag_tool as rag_module
    rag_module._index = None
    rag_module._metadata = None
    rag_module._bm25_index = None
    rag_module._bm25_corpus_tokens = None
    return rag_module


class TestHybridSearch:
    """Tests for hybrid search (vector + BM25 + RRF fusion)."""

    def test_response_has_retrieval_metadata(self, mock_faiss_index):
        """Response should include retrieval_metadata with confidence."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="temperature trends in Southeast", top_k=3
            )

        parsed = json.loads(result)
        assert "retrieval_metadata" in parsed
        assert "overall_confidence" in parsed["retrieval_metadata"]
        assert parsed["retrieval_metadata"]["overall_confidence"] in (
            "HIGH", "MEDIUM", "LOW", "INSUFFICIENT"
        )

    def test_response_includes_search_method(self, mock_faiss_index):
        """Response metadata should report hybrid search method."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="Atlanta climate data", top_k=5
            )

        parsed = json.loads(result)
        assert "search_method" in parsed["retrieval_metadata"]
        assert "hybrid" in parsed["retrieval_metadata"]["search_method"]
        assert "BM25" in parsed["retrieval_metadata"]["search_method"]

    def test_response_has_results_list(self, mock_faiss_index):
        """Response should contain a results array."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="Atlanta climate data", top_k=5
            )

        parsed = json.loads(result)
        assert "results" in parsed
        assert isinstance(parsed["results"], list)
        assert len(parsed["results"]) <= 5

    def test_each_result_has_confidence_level(self, mock_faiss_index):
        """Each result should have a confidence_level field."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="temperature data", top_k=3
            )

        parsed = json.loads(result)
        for r in parsed["results"]:
            assert "confidence_level" in r
            assert r["confidence_level"] in ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT")

    def test_each_result_has_rrf_score(self, mock_faiss_index):
        """Each result should have an rrf_score from fusion."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="Chicago temperature", top_k=3
            )

        parsed = json.loads(result)
        for r in parsed["results"]:
            assert "rrf_score" in r
            assert r["rrf_score"] > 0

    def test_each_result_has_citation(self, mock_faiss_index):
        """Each result should have a formatted citation string."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="Chicago temperature", top_k=3
            )

        parsed = json.loads(result)
        for r in parsed["results"]:
            assert "citation" in r
            assert "[GHCN_v4]" in r["citation"] or "[" in r["citation"]

    def test_top_k_limits_results(self, mock_faiss_index):
        """top_k should limit the number of returned results."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="precipitation data", top_k=2
            )

        parsed = json.loads(result)
        assert len(parsed["results"]) <= 2

    def test_results_include_station_name(self, mock_faiss_index):
        """Results should include station_name for attribution."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="weather station data", top_k=5
            )

        parsed = json.loads(result)
        for r in parsed["results"]:
            assert "station_name" in r

    def test_retrieval_metadata_has_top_score(self, mock_faiss_index):
        """Retrieval metadata should report the top similarity score."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="any query", top_k=3
            )

        parsed = json.loads(result)
        assert "top_score" in parsed["retrieval_metadata"]
        assert isinstance(parsed["retrieval_metadata"]["top_score"], float)

    def test_bm25_boosts_keyword_matches(self, mock_faiss_index):
        """BM25 should boost results that contain exact query keywords."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="Atlanta", top_k=5
            )

        parsed = json.loads(result)
        texts = [r["text"] for r in parsed["results"]]
        has_atlanta = any("Atlanta" in t for t in texts)
        assert has_atlanta, f"Expected Atlanta in results, got: {texts}"

    def test_bm25_index_built_on_load(self, mock_faiss_index, monkeypatch):
        """BM25 index should be built when FAISS index is loaded."""
        _setup_mocked_rag(mock_faiss_index)
        rag_module = _reset_rag_module()
        rag_module._load_index()

        assert rag_module._bm25_index is not None
        assert rag_module._bm25_corpus_tokens is not None
        assert len(rag_module._bm25_corpus_tokens) == len(rag_module._metadata)


class TestMultiEntitySearch:
    """Tests for multi-entity comparison queries."""

    def test_compare_query_triggers_multi_search(self, mock_faiss_index):
        """Queries with 'compare' should use multi-entity search."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="Compare Atlanta and Chicago temperatures", top_k=5
            )

        parsed = json.loads(result)
        assert "results" in parsed
        assert len(parsed["results"]) > 0

    def test_vs_query_triggers_multi_search(self, mock_faiss_index):
        """Queries with 'vs' should use multi-entity search."""
        mock_session = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.Session", return_value=mock_session):
            rag_module = _reset_rag_module()
            result = rag_module.search_climate_data(
                query="New York vs Los Angeles trends", top_k=5
            )

        parsed = json.loads(result)
        assert "results" in parsed
        assert len(parsed["results"]) > 0


class TestConfidenceScoring:
    """Tests for the confidence threshold logic."""

    def test_score_to_confidence_high(self):
        """Score >= 0.45 should be HIGH."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.50) == "HIGH"
        assert _score_to_confidence(0.45) == "HIGH"

    def test_score_to_confidence_medium(self):
        """Score >= 0.35 and < 0.45 should be MEDIUM."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.40) == "MEDIUM"
        assert _score_to_confidence(0.35) == "MEDIUM"

    def test_score_to_confidence_low(self):
        """Score >= 0.25 and < 0.35 should be LOW."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.30) == "LOW"
        assert _score_to_confidence(0.25) == "LOW"

    def test_score_to_confidence_insufficient(self):
        """Score < 0.25 should be INSUFFICIENT."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.24) == "INSUFFICIENT"
        assert _score_to_confidence(0.10) == "INSUFFICIENT"
        assert _score_to_confidence(0.0) == "INSUFFICIENT"


class TestCitationBuilder:
    """Tests for the citation string builder."""

    def test_builds_full_citation(self):
        """Should build citation with dataset, station, and period."""
        from agent.tools.rag_tool import _build_citation
        meta = {
            "dataset": "GHCN_v4",
            "station_id": "USW00013874",
            "station_name": "Atlanta Hartsfield",
            "region": "Southeast",
            "time_range": "1990-1999",
        }
        citation = _build_citation(meta)
        assert "[GHCN_v4]" in citation
        assert "Atlanta Hartsfield" in citation
        assert "1990-1999" in citation

    def test_builds_citation_with_region_only(self):
        """Should use region when station is not available."""
        from agent.tools.rag_tool import _build_citation
        meta = {
            "dataset": "NASA_POWER",
            "region": "Midwest",
            "decade": "2000s",
        }
        citation = _build_citation(meta)
        assert "[NASA_POWER]" in citation
        assert "Midwest" in citation

    def test_builds_citation_with_decade(self):
        """Should include decade when time_range is not available."""
        from agent.tools.rag_tool import _build_citation
        meta = {
            "dataset": "GISTEMP_v4",
            "region": "Global",
            "decade": "2010s",
        }
        citation = _build_citation(meta)
        assert "2010s" in citation


class TestTokenizer:
    """Tests for the BM25 tokenizer."""

    def test_tokenize_basic(self):
        """Should lowercase and split on non-alphanumeric."""
        from agent.tools.rag_tool import _tokenize
        tokens = _tokenize("New York City, NY Temperature")
        assert "new" in tokens
        assert "york" in tokens
        assert "city" in tokens
        assert "temperature" in tokens

    def test_tokenize_removes_short_tokens(self):
        """Should remove single-character tokens."""
        from agent.tools.rag_tool import _tokenize
        tokens = _tokenize("a b c hello world")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_handles_numbers(self):
        """Should preserve numeric tokens."""
        from agent.tools.rag_tool import _tokenize
        tokens = _tokenize("1950s decade 2020")
        assert "1950s" in tokens
        assert "decade" in tokens
        assert "2020" in tokens
