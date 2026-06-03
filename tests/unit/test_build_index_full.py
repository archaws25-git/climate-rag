"""Additional tests for build_index — covers save_and_upload and main."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import faiss
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestSaveAndUpload:
    """Tests for save_and_upload — local file writing and S3 upload."""

    def test_saves_index_and_metadata_locally(self, sample_chunks, tmp_path, monkeypatch):
        """Should write faiss.index and metadata.jsonl to local disk."""
        import importlib
        import ingest.build_index as mod
        importlib.reload(mod)
        mod.CHUNK_DIR = str(tmp_path)

        index = mod.build_faiss_index(sample_chunks)

        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3
            mod.save_and_upload(index, sample_chunks)

        index_dir = tmp_path / "index"
        assert (index_dir / "faiss.index").exists()
        assert (index_dir / "metadata.jsonl").exists()

        # Verify metadata content
        with open(index_dir / "metadata.jsonl") as f:
            lines = f.readlines()
        assert len(lines) == len(sample_chunks)

        # Each line should have text + metadata but NOT embedding
        first = json.loads(lines[0])
        assert "text" in first
        assert "metadata" in first
        assert "embedding" not in first

    def test_uploads_to_s3(self, sample_chunks, tmp_path, monkeypatch):
        """Should call s3.upload_file for both index and metadata."""
        import importlib
        import ingest.build_index as mod
        importlib.reload(mod)
        mod.CHUNK_DIR = str(tmp_path)
        mod.S3_BUCKET = "test-bucket"

        index = mod.build_faiss_index(sample_chunks)

        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3
            mod.save_and_upload(index, sample_chunks)

        assert mock_s3.upload_file.call_count == 2
        upload_calls = mock_s3.upload_file.call_args_list
        uploaded_keys = [call[0][2] for call in upload_calls]
        assert "index/faiss.index" in uploaded_keys
        assert "index/metadata.jsonl" in uploaded_keys

    def test_uploaded_index_is_readable(self, sample_chunks, tmp_path, monkeypatch):
        """The saved FAISS index should be loadable and searchable."""
        import importlib
        import ingest.build_index as mod
        importlib.reload(mod)
        mod.CHUNK_DIR = str(tmp_path)

        index = mod.build_faiss_index(sample_chunks)

        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3
            mod.save_and_upload(index, sample_chunks)

        # Reload the saved index
        saved_path = str(tmp_path / "index" / "faiss.index")
        loaded_index = faiss.read_index(saved_path)
        assert loaded_index.ntotal == len(sample_chunks)


class TestMain:
    """Tests for the main orchestration function."""

    def test_main_orchestrates_full_pipeline(self, sample_chunks_dir, monkeypatch):
        """main() should load chunks, build index, and upload."""
        import importlib
        import ingest.build_index as mod
        importlib.reload(mod)
        mod.CHUNK_DIR = sample_chunks_dir

        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3
            mod.main()

        # Should have uploaded 2 files
        assert mock_s3.upload_file.call_count == 2
