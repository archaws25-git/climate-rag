"""Tests for FAISS index building logic."""

import json
import os
import sys

import faiss
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ingest.build_index import load_embedded_chunks, build_faiss_index


class TestLoadEmbeddedChunks:
    """Tests for loading embedded chunks from disk."""

    def test_loads_all_chunks(self, sample_chunks_dir, monkeypatch):
        """Should load all chunks from JSONL files in the embedded/ directory."""
        monkeypatch.setenv("CHUNK_OUTPUT_DIR", sample_chunks_dir)
        # Re-import to pick up new env
        import importlib
        import ingest.build_index as mod
        importlib.reload(mod)
        mod.CHUNK_DIR = sample_chunks_dir

        chunks = mod.load_embedded_chunks()
        assert len(chunks) == 10

    def test_each_chunk_has_embedding(self, sample_chunks_dir, monkeypatch):
        """Every loaded chunk must have an embedding field."""
        import importlib
        import ingest.build_index as mod
        importlib.reload(mod)
        mod.CHUNK_DIR = sample_chunks_dir

        chunks = mod.load_embedded_chunks()
        for chunk in chunks:
            assert "embedding" in chunk
            assert len(chunk["embedding"]) == 1024

    def test_empty_directory(self, tmp_path, monkeypatch):
        """Empty embedded directory should return zero chunks."""
        embedded_dir = tmp_path / "embedded"
        embedded_dir.mkdir()

        import importlib
        import ingest.build_index as mod
        importlib.reload(mod)
        mod.CHUNK_DIR = str(tmp_path)

        chunks = mod.load_embedded_chunks()
        assert len(chunks) == 0


class TestBuildFaissIndex:
    """Tests for FAISS index construction."""

    def test_builds_index_correct_size(self, sample_chunks):
        """Index should contain the same number of vectors as input chunks."""
        index = build_faiss_index(sample_chunks)
        assert index.ntotal == len(sample_chunks)

    def test_index_dimension_matches_embeddings(self, sample_chunks):
        """Index dimension should match the embedding dimension (1024)."""
        index = build_faiss_index(sample_chunks)
        assert index.d == 1024

    def test_index_is_flat_ip(self, sample_chunks):
        """Index should be IndexFlatIP (inner product for cosine similarity)."""
        index = build_faiss_index(sample_chunks)
        assert isinstance(index, faiss.IndexFlatIP)

    def test_search_returns_results(self, sample_chunks):
        """A query vector should return nearest neighbors."""
        index = build_faiss_index(sample_chunks)

        # Use first chunk's embedding as a query
        query = np.array(sample_chunks[0]["embedding"], dtype="float32").reshape(1, -1)
        faiss.normalize_L2(query)

        scores, indices = index.search(query, 3)
        assert indices.shape == (1, 3)
        assert scores[0][0] > 0, "Top result should have positive similarity"

    def test_self_search_returns_exact_match(self, sample_chunks):
        """Searching with a chunk's own embedding should return itself as top match."""
        index = build_faiss_index(sample_chunks)

        query = np.array(sample_chunks[0]["embedding"], dtype="float32").reshape(1, -1)
        faiss.normalize_L2(query)

        scores, indices = index.search(query, 1)
        # The top result should be index 0 (itself)
        assert indices[0][0] == 0
        # Score should be very close to 1.0 (cosine similarity of identical vectors)
        assert scores[0][0] > 0.99
