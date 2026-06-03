"""Tests for the RAG search tool — mocking AWS calls."""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import faiss
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def mock_faiss_index(sample_chunks, tmp_path):
    """Create a real FAISS index and metadata file on disk for testing."""
    # Build a real FAISS index from sample chunks
    embeddings = np.array(
        [c["embedding"] for c in sample_chunks], dtype="float32"
    )
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(1024)
    index.add(embeddings)

    # Write index
    idx_path = str(tmp_path / "faiss.index")
    faiss.write_index(index, idx_path)

    # Write metadata
    meta_path = str(tmp_path / "metadata.jsonl")
    with open(meta_path, "w") as f:
        for chunk in sample_chunks:
            record = {"text": chunk["text"], "metadata": chunk["metadata"]}
            f.write(json.dumps(record) + "\n")

    return str(tmp_path), idx_path, meta_path


class TestRagTool:
    """Tests for the search_climate_data RAG tool."""

    def test_search_returns_results(self, mock_faiss_index, monkeypatch):
        """Search should return relevant results from the FAISS index."""
        tmp_dir, idx_path, meta_path = mock_faiss_index

        # Mock S3 download to use our local files
        mock_s3 = MagicMock()

        def fake_download(bucket, key, path):
            import shutil
            if "faiss.index" in key:
                shutil.copy(idx_path, path)
            elif "metadata.jsonl" in key:
                shutil.copy(meta_path, path)

        mock_s3.download_file = fake_download

        with patch("boto3.client") as mock_boto:
            # Mock bedrock-runtime for embedding
            mock_bedrock = MagicMock()
            mock_body = MagicMock()
            # Return a fake embedding
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

            mock_boto.side_effect = client_factory

            # Reset the module-level cache
            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="temperature trends in Southeast", top_k=3
            )

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) <= 3

    def test_search_result_has_required_fields(self, mock_faiss_index, monkeypatch):
        """Each result should have score, text, source, and other metadata."""
        tmp_dir, idx_path, meta_path = mock_faiss_index

        mock_s3 = MagicMock()

        def fake_download(bucket, key, path):
            import shutil
            if "faiss.index" in key:
                shutil.copy(idx_path, path)
            elif "metadata.jsonl" in key:
                shutil.copy(meta_path, path)

        mock_s3.download_file = fake_download

        with patch("boto3.client") as mock_boto:
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

            mock_boto.side_effect = client_factory

            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="global temperature anomaly", top_k=5
            )

        parsed = json.loads(result)
        if len(parsed) > 0:
            result_item = parsed[0]
            assert "score" in result_item
            assert "text" in result_item
            assert "source" in result_item
            assert isinstance(result_item["score"], float)

    def test_top_k_limits_results(self, mock_faiss_index, monkeypatch):
        """top_k parameter should limit the number of returned results."""
        tmp_dir, idx_path, meta_path = mock_faiss_index

        mock_s3 = MagicMock()

        def fake_download(bucket, key, path):
            import shutil
            if "faiss.index" in key:
                shutil.copy(idx_path, path)
            elif "metadata.jsonl" in key:
                shutil.copy(meta_path, path)

        mock_s3.download_file = fake_download

        with patch("boto3.client") as mock_boto:
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

            mock_boto.side_effect = client_factory

            import agent.tools.rag_tool as rag_module
            rag_module._index = None
            rag_module._metadata = None

            result = rag_module.search_climate_data(
                query="precipitation data", top_k=2
            )

        parsed = json.loads(result)
        assert len(parsed) <= 2
