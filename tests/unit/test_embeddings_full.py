"""Additional tests for embeddings — covers main() orchestration."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestEmbeddingsMain:
    """Tests for the main orchestration function."""

    def test_main_processes_all_chunk_files(self, tmp_path, monkeypatch):
        """main() should embed all *_chunks.jsonl files in CHUNK_DIR."""
        import importlib
        import ingest.embeddings as mod
        importlib.reload(mod)

        chunk_dir = str(tmp_path)
        monkeypatch.setenv("CHUNK_OUTPUT_DIR", chunk_dir)
        mod.CHUNK_DIR = chunk_dir

        # Create sample chunk files
        for name in ["ghcn_chunks.jsonl", "gistemp_chunks.jsonl"]:
            path = tmp_path / name
            with open(path, "w") as f:
                f.write(json.dumps({"text": f"Sample from {name}", "metadata": {}}) + "\n")
                f.write(json.dumps({"text": f"Another from {name}", "metadata": {}}) + "\n")

        embedded_dir = tmp_path / "embedded"
        embedded_dir.mkdir()

        with patch("boto3.Session") as mock_session_cls:
            mock_client = MagicMock()
            mock_body = MagicMock()
            mock_body.read.return_value = json.dumps(
                {"embedding": [0.1] * 1024}
            ).encode()
            mock_client.invoke_model.return_value = {"body": mock_body}
            mock_session_cls.return_value.client.return_value = mock_client

            mod.main()

        # Should have created embedded output files
        output_files = list(embedded_dir.iterdir())
        assert len(output_files) == 2

    def test_main_skips_missing_files(self, tmp_path, monkeypatch):
        """main() should skip chunk files that don't exist without error."""
        import importlib
        import ingest.embeddings as mod
        importlib.reload(mod)

        chunk_dir = str(tmp_path)
        monkeypatch.setenv("CHUNK_OUTPUT_DIR", chunk_dir)
        mod.CHUNK_DIR = chunk_dir

        # Create only one of the expected files
        ghcn_path = tmp_path / "ghcn_chunks.jsonl"
        with open(ghcn_path, "w") as f:
            f.write(json.dumps({"text": "Test chunk", "metadata": {}}) + "\n")

        embedded_dir = tmp_path / "embedded"
        embedded_dir.mkdir()

        with patch("boto3.Session") as mock_session_cls:
            mock_client = MagicMock()
            mock_body = MagicMock()
            mock_body.read.return_value = json.dumps(
                {"embedding": [0.2] * 1024}
            ).encode()
            mock_client.invoke_model.return_value = {"body": mock_body}
            mock_session_cls.return_value.client.return_value = mock_client

            # Should not raise even though gistemp_chunks.jsonl and power_chunks.jsonl are missing
            mod.main()

        output_files = list(embedded_dir.iterdir())
        assert len(output_files) == 1
