"""Additional tests for ingest_ghcn — covers download_ghcn and main."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ingest.ingest_ghcn import download_ghcn, main


class TestDownloadGhcn:
    """Tests for the download_ghcn function."""

    def test_successful_download(self):
        """Should return CSV text from the API on success."""
        fake_csv = "STATION,DATE,TAVG,TMAX,TMIN\nUSW00013874,2020-01-01,5.0,10.0,0.0"

        mock_response = MagicMock()
        mock_response.read.return_value = fake_csv.encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = download_ghcn()

        assert "STATION" in result
        assert "USW00013874" in result

    def test_fallback_to_sample_on_error(self):
        """Should generate sample data when API download fails."""
        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("Network timeout"),
        ):
            result = download_ghcn()

        # Should still return valid CSV from the sample generator
        assert "STATION,DATE,TAVG,TMAX,TMIN" in result
        assert "USW00013874" in result


class TestMain:
    """Tests for the main orchestration function."""

    def test_main_creates_output_file(self, tmp_path, monkeypatch):
        """main() should create a ghcn_chunks.jsonl output file."""
        monkeypatch.setattr("ingest.ingest_ghcn.OUTPUT_DIR", str(tmp_path))

        # Mock the download to return simple CSV
        fake_csv = (
            "STATION,DATE,TAVG,TMAX,TMIN\nUSW00013874,1990-01-01,5.2,10.1,0.3\nUSW00013874,1990-02-01,7.8,12.5,3.1\n"
        )
        with patch("ingest.ingest_ghcn.download_ghcn", return_value=fake_csv):
            main()

        output_path = tmp_path / "ghcn_chunks.jsonl"
        assert output_path.exists()

        with open(output_path) as f:
            lines = f.readlines()
        assert len(lines) >= 1

        # Verify valid JSON per line
        chunk = json.loads(lines[0])
        assert "chunk_id" in chunk
        assert "text" in chunk
        assert "metadata" in chunk

    def test_main_creates_output_directory(self, tmp_path, monkeypatch):
        """main() should create the output directory if it doesn't exist."""
        output_dir = str(tmp_path / "new_dir")
        monkeypatch.setattr("ingest.ingest_ghcn.OUTPUT_DIR", output_dir)

        fake_csv = "STATION,DATE,TAVG,TMAX,TMIN\nUSW00013874,2000-05-01,20.0,25.0,15.0\n"
        with patch("ingest.ingest_ghcn.download_ghcn", return_value=fake_csv):
            main()

        assert os.path.isdir(output_dir)
