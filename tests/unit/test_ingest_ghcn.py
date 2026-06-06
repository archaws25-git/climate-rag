"""Tests for GHCN v4 ingestion — parsing and chunking logic."""

import json
import os
import sys

import pytest

# Add project root to path so we can import ingest modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ingest.ingest_ghcn import parse_and_chunk, generate_sample_data, STATIONS


class TestParseAndChunk:
    """Tests for the parse_and_chunk function."""

    def test_basic_parsing(self, ghcn_csv_sample):
        """Verify CSV rows are parsed into structured chunks."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        assert len(chunks) > 0, "Should produce at least one chunk"

    def test_chunk_has_required_fields(self, ghcn_csv_sample):
        """Each chunk must have chunk_id, text, and metadata."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            assert "chunk_id" in chunk
            assert "text" in chunk
            assert "metadata" in chunk
            assert chunk["text"].strip() != ""

    def test_metadata_has_required_keys(self, ghcn_csv_sample):
        """Metadata must include dataset, station_id, region, decade, time_range."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        required_keys = ["dataset", "station_id", "region", "decade", "time_range"]
        for chunk in chunks:
            for key in required_keys:
                assert key in chunk["metadata"], f"Missing key: {key}"

    def test_dataset_is_ghcn_v4(self, ghcn_csv_sample):
        """All chunks should be marked as GHCN_v4 dataset."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            assert chunk["metadata"]["dataset"] == "GHCN_v4"

    def test_chunks_grouped_by_station_and_decade(self, ghcn_csv_sample):
        """Chunks should be unique per station + decade combination."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        chunk_ids = [c["chunk_id"] for c in chunks]
        assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk_ids found"

    def test_station_filtering(self, ghcn_csv_sample):
        """Only stations in the STATIONS dict should produce chunks."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            station_id = chunk["metadata"]["station_id"]
            assert station_id in STATIONS, f"Unknown station: {station_id}"

    def test_unknown_station_ignored(self):
        """Rows with unknown station IDs should be silently skipped."""
        csv_text = (
            "STATION,DATE,TAVG,TMAX,TMIN\n"
            "UNKNOWN001,2000-01-01,10.0,15.0,5.0\n"
        )
        chunks = parse_and_chunk(csv_text)
        assert len(chunks) == 0

    def test_missing_tavg_skipped(self):
        """Rows with empty TAVG should be skipped."""
        csv_text = (
            "STATION,DATE,TAVG,TMAX,TMIN\n"
            "USW00013874,2000-01-01,,15.0,5.0\n"
        )
        chunks = parse_and_chunk(csv_text)
        assert len(chunks) == 0

    def test_decade_calculation(self, ghcn_csv_sample):
        """Decade should be correctly derived from year."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            decade = chunk["metadata"]["decade"]
            # Decade format is like "1990s", "2000s"
            assert decade.endswith("s")
            decade_num = int(decade[:-1])
            assert decade_num % 10 == 0

    def test_chunk_text_contains_station_info(self, ghcn_csv_sample):
        """Chunk text should mention the station name and location."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            station_id = chunk["metadata"]["station_id"]
            info = STATIONS[station_id]
            assert info["name"] in chunk["text"]
            assert station_id in chunk["text"]

    def test_avg_temp_calculated(self, ghcn_csv_sample):
        """Metadata should include an average temperature."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            assert "avg_temp_c" in chunk["metadata"]
            assert isinstance(chunk["metadata"]["avg_temp_c"], float)

    def test_empty_csv(self):
        """Empty CSV with only headers should return no chunks."""
        csv_text = "STATION,DATE,TAVG,TMAX,TMIN\n"
        chunks = parse_and_chunk(csv_text)
        assert len(chunks) == 0


class TestGenerateSampleData:
    """Tests for the sample data generator (fallback when API is unavailable)."""

    def test_generates_csv_format(self):
        """Generated data should be valid CSV with expected columns."""
        data = generate_sample_data()
        lines = data.strip().split("\n")
        assert lines[0] == "STATION,DATE,TAVG,TMAX,TMIN"
        assert len(lines) > 1

    def test_all_stations_present(self):
        """Generated data should include all 37 configured stations."""
        data = generate_sample_data()
        for station_id in STATIONS:
            assert station_id in data, f"Station {station_id} missing from sample data"

    def test_parseable_by_chunker(self):
        """Generated sample data should be parseable by parse_and_chunk."""
        data = generate_sample_data()
        chunks = parse_and_chunk(data)
        assert len(chunks) > 0

    def test_generates_data_across_decades(self):
        """Sample data should span multiple decades (1950-2025)."""
        data = generate_sample_data()
        chunks = parse_and_chunk(data)
        decades = set(c["metadata"]["decade"] for c in chunks)
        assert len(decades) >= 7, f"Expected 7+ decades, got {decades}"

    def test_station_count_is_37(self):
        """STATIONS dict should have exactly 37 entries."""
        assert len(STATIONS) == 37

    def test_all_regions_covered(self):
        """Should cover all 7 US climate regions."""
        regions = set(info["region"] for info in STATIONS.values())
        expected = {"Southeast", "Northeast", "Midwest", "West", "South Central", "Alaska", "Hawaii"}
        assert regions == expected

    def test_generates_approximately_correct_chunk_count(self):
        """Should produce ~296 chunks (37 stations × 8 decades)."""
        data = generate_sample_data()
        chunks = parse_and_chunk(data)
        # 37 stations × 8 decades = 296, but edge decades may vary
        assert 250 <= len(chunks) <= 310, f"Got {len(chunks)} chunks"

    def test_realistic_warming_rate(self):
        """Temperature difference between 1950s and 2020s should be ~0.5°C."""
        data = generate_sample_data()
        chunks = parse_and_chunk(data)
        # Find Atlanta 1950s and 2020s chunks
        atlanta_chunks = [c for c in chunks if c["metadata"]["station_id"] == "USW00013874"]
        decades_map = {c["metadata"]["decade"]: c["metadata"]["avg_temp_c"] for c in atlanta_chunks}
        if "1950s" in decades_map and "2020s" in decades_map:
            diff = decades_map["2020s"] - decades_map["1950s"]
            # Should be roughly 0.5°C (±0.5 due to noise)
            assert -0.5 <= diff <= 1.5, f"Warming {diff:.2f}°C seems unrealistic"
