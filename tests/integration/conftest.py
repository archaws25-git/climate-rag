"""Integration test conftest — overrides the root autouse fixture.

Integration tests need REAL AWS credentials and resource IDs, so we
override the root conftest's env_defaults to preserve actual env vars.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def env_defaults(monkeypatch):
    """Preserve real AWS env vars for integration tests.

    Only sets defaults for vars that are NOT already set in the environment.
    This allows integration tests to use real Memory IDs, credentials, etc.
    """
    # Only set region if not already configured
    if not os.environ.get("AWS_REGION"):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
    if not os.environ.get("AWS_DEFAULT_REGION"):
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    # Do NOT override CLIMATE_RAG_MEMORY_ID — integration tests need the real one
    # Do NOT override AWS_PROFILE — integration tests need real credentials
