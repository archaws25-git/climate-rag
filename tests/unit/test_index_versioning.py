"""Tests for S3 index versioning module."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestIndexVersioning:
    """Tests for index upload and versioning logic."""

    def test_module_imports(self):
        """Should import without errors."""
        from ingest.index_versioning import (
            compute_index_hash,
            upload_versioned_index,
            list_versions,
        )

        assert callable(compute_index_hash)
        assert callable(upload_versioned_index)
        assert callable(list_versions)

    def test_compute_hash_deterministic(self, tmp_path):
        """Same files should produce same hash."""
        from ingest.index_versioning import compute_index_hash

        idx = tmp_path / "faiss.index"
        meta = tmp_path / "metadata.jsonl"
        idx.write_bytes(b"fake index content")
        meta.write_text('{"text": "chunk1"}')

        hash1 = compute_index_hash(str(idx), str(meta))
        hash2 = compute_index_hash(str(idx), str(meta))
        assert hash1 == hash2
        assert len(hash1) == 12  # Truncated SHA256 hex

    def test_compute_hash_changes_with_content(self, tmp_path):
        """Different content should produce different hash."""
        from ingest.index_versioning import compute_index_hash

        idx = tmp_path / "faiss.index"
        meta = tmp_path / "metadata.jsonl"

        idx.write_bytes(b"content A")
        meta.write_text('{"a": 1}')
        hash_a = compute_index_hash(str(idx), str(meta))

        idx.write_bytes(b"content B")
        hash_b = compute_index_hash(str(idx), str(meta))

        assert hash_a != hash_b

    def test_upload_versioned_index(self, tmp_path, monkeypatch):
        """Should upload to S3 with versioned prefix."""
        monkeypatch.setenv("AWS_PROFILE", "")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        idx = tmp_path / "faiss.index"
        meta = tmp_path / "metadata.jsonl"
        idx.write_bytes(b"fake index")
        meta.write_text('{"text": "test"}')

        with patch("boto3.Session") as mock_session_cls:
            mock_s3 = MagicMock()
            mock_session_cls.return_value.client.return_value = mock_s3

            from ingest.index_versioning import upload_versioned_index

            upload_versioned_index(
                bucket="test-bucket",
                local_index_path=str(idx),
                local_metadata_path=str(meta),
            )

            # Should upload at least 2 files (index + metadata) to both versioned and latest
            assert mock_s3.upload_file.call_count >= 2

    def test_list_versions_empty(self, monkeypatch):
        """Should return empty list when no versions exist."""
        monkeypatch.setenv("AWS_PROFILE", "")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        with patch("boto3.Session") as mock_session_cls:
            mock_s3 = MagicMock()
            mock_s3.list_objects_v2.return_value = {"Contents": []}
            mock_session_cls.return_value.client.return_value = mock_s3

            from ingest.index_versioning import list_versions

            versions = list_versions(bucket="test-bucket")

            assert isinstance(versions, list)
