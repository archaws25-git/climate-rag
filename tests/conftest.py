"""Shared fixtures for ClimateRAG test suite."""

import json
import os
import tempfile

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def env_defaults(monkeypatch):
    """Set safe environment defaults for all tests so nothing hits real AWS."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("CLIMATE_RAG_BUCKET", "test-bucket")
    monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "test-memory-id")
    monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", "test-ci-id")
    monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "")
    monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "")
    monkeypatch.setenv("CHUNK_OUTPUT_DIR", tempfile.mkdtemp())


@pytest.fixture
def sample_chunks():
    """Return a list of sample embedded chunks for testing.

    Uses station IDs from the expanded 37-station STATIONS dict.
    """
    stations = [
        ("USW00013874", "Atlanta Hartsfield", "GA", "Southeast"),
        ("USW00094728", "New York Central Park", "NY", "Northeast"),
        ("USW00023174", "Los Angeles Intl", "CA", "West"),
        ("USW00094846", "Chicago OHare", "IL", "Midwest"),
        ("USW00026451", "Anchorage Intl", "AK", "Alaska"),
        ("USW00022521", "Honolulu Intl", "HI", "Hawaii"),
        ("USW00013960", "Dallas Fort Worth", "TX", "South Central"),
        ("USW00012839", "Miami International", "FL", "Southeast"),
        ("USW00023062", "Denver Intl", "CO", "West"),
        ("USW00014922", "Minneapolis St Paul", "MN", "Midwest"),
    ]
    chunks = []
    for i, (sid, name, state, region) in enumerate(stations):
        chunks.append({
            "chunk_id": f"ghcn_{sid}_{1950 + i * 10}s",
            "text": (
                f"NOAA GHCN v4 Monthly Temperature — {name}, {state}\n"
                f"Station: {sid} | Region: {region}\n"
                f"Decade: {1950 + i * 10}s | Period: {1950 + i * 10}-{1959 + i * 10}\n"
                f"Average temperature: {15.0 + i * 0.3:.1f}°C\n"
            ),
            "metadata": {
                "dataset": "GHCN_v4",
                "station_id": sid,
                "station_name": name,
                "state": state,
                "region": region,
                "decade": f"{1950 + i * 10}s",
                "time_range": f"{1950 + i * 10}-{1959 + i * 10}",
            },
            "embedding": np.random.randn(1024).astype("float32").tolist(),
        })
    return chunks


@pytest.fixture
def sample_chunks_dir(sample_chunks, tmp_path):
    """Write sample chunks to a temp directory and return the path."""
    embedded_dir = tmp_path / "embedded"
    embedded_dir.mkdir()
    output_path = embedded_dir / "test_chunks.jsonl"
    with open(output_path, "w") as f:
        for chunk in sample_chunks:
            f.write(json.dumps(chunk) + "\n")
    return str(tmp_path)


@pytest.fixture
def ghcn_csv_sample():
    """Return sample GHCN-format CSV text using expanded station IDs."""
    lines = [
        "STATION,DATE,TAVG,TMAX,TMIN",
        "USW00013874,1990-01-01,5.2,10.1,0.3",
        "USW00013874,1990-02-01,7.8,12.5,3.1",
        "USW00013874,1990-03-01,12.0,18.2,5.8",
        "USW00013874,1995-06-01,25.3,31.0,19.6",
        "USW00013874,1995-07-01,27.1,33.2,21.0",
        "USW00094728,2000-01-01,1.5,5.0,-2.0",
        "USW00094728,2000-02-01,3.2,7.8,-1.4",
        "USW00094728,2005-09-01,20.1,25.3,14.9",
        # South Central station
        "USW00013960,2010-03-01,16.5,22.0,11.0",
        "USW00013960,2010-04-01,20.2,26.1,14.3",
        # West station
        "USW00023062,1980-01-01,-1.2,5.3,-7.7",
        "USW00023062,1980-07-01,23.5,31.2,15.8",
    ]
    return "\n".join(lines)
