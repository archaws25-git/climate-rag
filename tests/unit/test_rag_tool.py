"""Tests for the RAG search tool — confidence scoring, citations, mocked AWS."""

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


def _setup_mocked_rag(mock_faiss_index):
    """Helper to set up mocked boto3 clients for RAG tests."""
    tmp_dir, idx_path, meta_path = mock_faiss_index

    mock_s3 = MagicMock()

    def fake_download(bucket, key, path):
        import shutil
        if "faiss.index" in key:
            shutil.copy(idx_path, path)
        elif "metadata.jsonl" in key:
            shutil.copy(meta_path, path)

    mock_s3.download_file = fake_download

    mock_bedrock = MagicMock()
    mock_body = MagicMock()
    fake_embedding = np.random.randn(1024).tolist()
    mock_body.read.return_value = json.dumps(
        {"embedding": fake_embedding}
    ).encode()
    mock_bedrock.invoke_model.return_value = {"body": mock_body}

    def client_factory(service, **kwargs):
        if service == "s3":
            return mock_s3
        elif service == "bedrock-runtime":
            return mock_bedrock
        return MagicMock()

    return client_factory


class TestRagToolResponseFormat:
    """Tests for the new response format with confidence and citations."""

    def test_response_has_retrieval_metadata(self, mock_faiss_index):
        """Response should include retrieval_metadata with confidence."""
        client_factory = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.client", side_effect=client_factory):
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="temperature trends in Southeast", top_k=3
            )

        parsed = json.loads(result)
        assert "retrieval_metadata" in parsed
        assert "overall_confidence" in parsed["retrieval_metadata"]
        assert parsed["retrieval_metadata"]["overall_confidence"] in (
            "HIGH", "MEDIUM", "LOW", "INSUFFICIENT"
        )

    def test_response_has_results_list(self, mock_faiss_index):
        """Response should contain a results array."""
        client_factory = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.client", side_effect=client_factory):
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="Atlanta climate data", top_k=5
            )

        parsed = json.loads(result)
        assert "results" in parsed
        assert isinstance(parsed["results"], list)
        assert len(parsed["results"]) <= 5

    def test_each_result_has_confidence_level(self, mock_faiss_index):
        """Each result should have a confidence_level field."""
        client_factory = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.client", side_effect=client_factory):
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="temperature data", top_k=3
            )

        parsed = json.loads(result)
        for r in parsed["results"]:
            assert "confidence_level" in r
            assert r["confidence_level"] in ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT")

    def test_each_result_has_citation(self, mock_faiss_index):
        """Each result should have a formatted citation string."""
        client_factory = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.client", side_effect=client_factory):
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="Chicago temperature", top_k=3
            )

        parsed = json.loads(result)
        for r in parsed["results"]:
            assert "citation" in r
            assert "[GHCN_v4]" in r["citation"] or "[" in r["citation"]

    def test_top_k_limits_results(self, mock_faiss_index):
        """top_k should limit the number of returned results."""
        client_factory = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.client", side_effect=client_factory):
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="precipitation data", top_k=2
            )

        parsed = json.loads(result)
        assert len(parsed["results"]) <= 2

    def test_results_include_station_name(self, mock_faiss_index):
        """Results should include station_name for attribution."""
        client_factory = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.client", side_effect=client_factory):
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="weather station data", top_k=5
            )

        parsed = json.loads(result)
        for r in parsed["results"]:
            assert "station_name" in r

    def test_retrieval_metadata_has_top_score(self, mock_faiss_index):
        """Retrieval metadata should report the top similarity score."""
        client_factory = _setup_mocked_rag(mock_faiss_index)

        with patch("boto3.client", side_effect=client_factory):
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="any query", top_k=3
            )

        parsed = json.loads(result)
        assert "top_score" in parsed["retrieval_metadata"]
        assert isinstance(parsed["retrieval_metadata"]["top_score"], float)


class TestConfidenceScoring:
    """Tests for the confidence threshold logic."""

    def test_score_to_confidence_high(self):
        """Score >= 0.75 should be HIGH."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.80) == "HIGH"
        assert _score_to_confidence(0.75) == "HIGH"

    def test_score_to_confidence_medium(self):
        """Score >= 0.55 and < 0.75 should be MEDIUM."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.60) == "MEDIUM"
        assert _score_to_confidence(0.55) == "MEDIUM"

    def test_score_to_confidence_low(self):
        """Score >= 0.40 and < 0.55 should be LOW."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.45) == "LOW"
        assert _score_to_confidence(0.40) == "LOW"

    def test_score_to_confidence_insufficient(self):
        """Score < 0.40 should be INSUFFICIENT."""
        from agent.tools.rag_tool import _score_to_confidence
        assert _score_to_confidence(0.39) == "INSUFFICIENT"
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
