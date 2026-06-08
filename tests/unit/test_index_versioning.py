"""Tests for index versioning module."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ingest"))

from index_versioning import compute_index_hash


class TestIndexVersioning:
    """Tests for index versioning utilities."""

    def test_compute_hash_deterministic(self, tmp_path):
        """Same files should produce same hash."""
        idx_file = tmp_path / "faiss.index"
        meta_file = tmp_path / "metadata.jsonl"
        idx_file.write_bytes(b"fake index content")
        meta_file.write_text('{"text": "chunk1"}\n')

        hash1 = compute_index_hash(str(idx_file), str(meta_file))
        hash2 = compute_index_hash(str(idx_file), str(meta_file))
        assert hash1 == hash2

    def test_different_content_different_hash(self, tmp_path):
        """Different files should produce different hashes."""
        idx1 = tmp_path / "idx1.bin"
        idx2 = tmp_path / "idx2.bin"
        meta = tmp_path / "meta.jsonl"

        idx1.write_bytes(b"content A")
        idx2.write_bytes(b"content B")
        meta.write_text('{"text": "chunk"}\n')

        hash1 = compute_index_hash(str(idx1), str(meta))
        hash2 = compute_index_hash(str(idx2), str(meta))
        assert hash1 != hash2

    def test_hash_is_12_chars(self, tmp_path):
        """Hash should be exactly 12 characters (short SHA256)."""
        idx_file = tmp_path / "faiss.index"
        meta_file = tmp_path / "metadata.jsonl"
        idx_file.write_bytes(b"test content")
        meta_file.write_text('{"data": true}\n')

        result = compute_index_hash(str(idx_file), str(meta_file))
        assert len(result) == 12
        assert result.isalnum()
