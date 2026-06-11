"""Tests for GHCN ingestion — parse_and_chunk function."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ingest.ingest_ghcn import parse_and_chunk, STATIONS


class TestParseAndChunk:
    """Tests for the CSV parser and chunking logic."""

    def test_basic_parsing(self, ghcn_csv_sample):
        """Should parse CSV and produce chunks."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        assert len(chunks) > 0

    def test_chunk_has_required_fields(self, ghcn_csv_sample):
        """Each chunk should have chunk_id, text, and metadata."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            assert "chunk_id" in chunk
            assert "text" in chunk
            assert "metadata" in chunk

    def test_metadata_has_required_keys(self, ghcn_csv_sample):
        """Metadata should contain dataset, station_id, region, decade."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            meta = chunk["metadata"]
            assert meta["dataset"] == "GHCN_v4"
            assert "station_id" in meta
            assert "region" in meta
            assert "decade" in meta
            assert "station_name" in meta
            assert "time_range" in meta

    def test_groups_by_station_and_decade(self, ghcn_csv_sample):
        """Should create one chunk per station × decade combination."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        keys = set()
        for chunk in chunks:
            key = (chunk["metadata"]["station_id"], chunk["metadata"]["decade"])
            assert key not in keys, f"Duplicate chunk for {key}"
            keys.add(key)

    def test_chunk_text_contains_city(self, ghcn_csv_sample):
        """Chunk text should include the city name for BM25 matching."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        # Find Atlanta chunk
        atlanta_chunks = [c for c in chunks if c["metadata"]["station_id"] == "USW00013874"]
        assert len(atlanta_chunks) > 0
        assert "Atlanta" in atlanta_chunks[0]["text"]

    def test_chunk_text_contains_aliases(self, ghcn_csv_sample):
        """Chunk text should include aliases for keyword search."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        # Find NY chunk
        ny_chunks = [c for c in chunks if c["metadata"]["station_id"] == "USW00094728"]
        if ny_chunks:
            assert "NYC" in ny_chunks[0]["text"] or "New York City" in ny_chunks[0]["text"]

    def test_chunk_text_contains_temperature(self, ghcn_csv_sample):
        """Chunk text should include average temperature value."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            assert "Average temperature:" in chunk["text"]
            assert "°C" in chunk["text"]

    def test_handles_empty_csv(self):
        """Should return empty list for CSV with only headers."""
        chunks = parse_and_chunk("STATION,DATE,TAVG,TMAX,TMIN\n")
        assert chunks == []

    def test_skips_unknown_stations(self):
        """Should skip rows with station IDs not in STATIONS dict."""
        csv = "STATION,DATE,TAVG,TMAX,TMIN\nXXX99999,2000-01-01,10.0,15.0,5.0\n"
        chunks = parse_and_chunk(csv)
        assert chunks == []

    def test_skips_rows_without_tavg(self):
        """Should skip rows where TAVG is empty."""
        csv = "STATION,DATE,TAVG,TMAX,TMIN\nUSW00013874,2000-01-01,,15.0,5.0\n"
        chunks = parse_and_chunk(csv)
        assert chunks == []

    def test_avg_temp_in_metadata(self, ghcn_csv_sample):
        """Metadata should include avg_temp_c as a float."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            assert "avg_temp_c" in chunk["metadata"]
            assert isinstance(chunk["metadata"]["avg_temp_c"], float)

    def test_lat_lon_in_metadata(self, ghcn_csv_sample):
        """Metadata should include lat/lon coordinates."""
        chunks = parse_and_chunk(ghcn_csv_sample)
        for chunk in chunks:
            assert "lat" in chunk["metadata"]
            assert "lon" in chunk["metadata"]


class TestStationsDict:
    """Tests for the STATIONS configuration."""

    def test_has_37_stations(self):
        """Should have exactly 37 stations configured."""
        assert len(STATIONS) == 37

    def test_all_stations_have_required_fields(self):
        """Each station should have name, state, region, lat, lon, city."""
        for sid, info in STATIONS.items():
            assert "name" in info, f"{sid} missing name"
            assert "state" in info, f"{sid} missing state"
            assert "region" in info, f"{sid} missing region"
            assert "lat" in info, f"{sid} missing lat"
            assert "lon" in info, f"{sid} missing lon"
            assert "city" in info, f"{sid} missing city"

    def test_all_regions_covered(self):
        """Should cover all 7 climate regions."""
        regions = set(info["region"] for info in STATIONS.values())
        expected = {"Southeast", "Northeast", "Midwest", "West", "South Central", "Alaska", "Hawaii"}
        assert regions == expected

    def test_station_ids_are_valid_format(self):
        """Station IDs should match USW##### format."""
        for sid in STATIONS:
            assert sid.startswith("USW"), f"Invalid station ID: {sid}"
            assert len(sid) == 11, f"Invalid station ID length: {sid}"
