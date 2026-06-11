"""Tests for the embeddings generation module."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ingest.embeddings import get_embedding, embed_chunks


class TestGetEmbedding:
    """Tests for the get_embedding function."""

    def test_returns_list_of_floats(self):
        """Should return a list of floats from the Bedrock response."""
        fake_embedding = np.random.randn(1024).tolist()
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"embedding": fake_embedding}).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        result = get_embedding(mock_client, "test query about climate")
        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(v, float) for v in result)

    def test_invokes_correct_model(self):
        """Should call Titan Embeddings v2 model."""
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"embedding": [0.1] * 1024}).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        get_embedding(mock_client, "test text")

        mock_client.invoke_model.assert_called_once()
        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"

    def test_truncates_long_text(self):
        """Should truncate input text to 8000 chars (Titan v2 limit)."""
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"embedding": [0.1] * 1024}).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        long_text = "x" * 10000
        get_embedding(mock_client, long_text)

        call_kwargs = mock_client.invoke_model.call_args[1]
        body = json.loads(call_kwargs["body"])
        assert len(body["inputText"]) == 8000


class TestEmbedChunks:
    """Tests for the embed_chunks function."""

    def test_adds_embeddings_to_all_chunks(self, tmp_path):
        """Should add embedding field to every chunk."""
        # Write input chunks
        input_path = str(tmp_path / "input.jsonl")
        output_path = str(tmp_path / "output.jsonl")
        chunks = [
            {"text": "Chunk 1 about temperature", "metadata": {"dataset": "GHCN_v4"}},
            {"text": "Chunk 2 about precipitation", "metadata": {"dataset": "NASA_POWER"}},
        ]
        with open(input_path, "w") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

        # Mock Bedrock client
        fake_embedding = [0.5] * 1024

        with patch("boto3.Session") as mock_session_cls:
            mock_client = MagicMock()
            mock_body = MagicMock()
            mock_body.read.return_value = json.dumps({"embedding": fake_embedding}).encode()
            mock_client.invoke_model.return_value = {"body": mock_body}
            mock_session_cls.return_value.client.return_value = mock_client

            result = embed_chunks(input_path, output_path)

        assert len(result) == 2
        for chunk in result:
            assert "embedding" in chunk
            assert len(chunk["embedding"]) == 1024

        # Verify output file was written
        with open(output_path) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_preserves_original_fields(self, tmp_path):
        """Should not lose text or metadata when adding embeddings."""
        input_path = str(tmp_path / "input.jsonl")
        output_path = str(tmp_path / "output.jsonl")
        chunks = [
            {
                "text": "Temperature in Atlanta",
                "metadata": {"dataset": "GHCN_v4", "station_id": "USW00013874"},
            },
        ]
        with open(input_path, "w") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

        with patch("boto3.Session") as mock_session_cls:
            mock_client = MagicMock()
            mock_body = MagicMock()
            mock_body.read.return_value = json.dumps({"embedding": [0.1] * 1024}).encode()
            mock_client.invoke_model.return_value = {"body": mock_body}
            mock_session_cls.return_value.client.return_value = mock_client

            result = embed_chunks(input_path, output_path)

        assert result[0]["text"] == "Temperature in Atlanta"
        assert result[0]["metadata"]["station_id"] == "USW00013874"
