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
    monkeypatch.setenv("CHUNK_OUTPUT_DIR", tempfile.mkdtemp())


@pytest.fixture
def sample_chunks():
    """Return a list of sample embedded chunks for testing."""
    chunks = []
    for i in range(10):
        chunks.append({
            "chunk_id": f"test_chunk_{i}",
            "text": f"Sample climate data chunk {i} about temperature trends in region {i}.",
            "metadata": {
                "dataset": "GHCN_v4" if i % 2 == 0 else "GISTEMP_v4",
                "station_id": f"USW0001{i:04d}",
                "station_name": f"Test Station {i}",
                "state": "GA",
                "region": "Southeast",
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
    """Return sample GHCN-format CSV text for parsing tests."""
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
    ]
    return "\n".join(lines)
