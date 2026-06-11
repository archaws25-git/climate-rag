"""Load test conftest — overrides root autouse fixture.

Load tests need real AWS credentials and resources. We override the root
conftest's env_defaults to preserve actual env vars (same pattern as
integration tests).
"""

import os

import pytest


@pytest.fixture(autouse=True)
def env_defaults(monkeypatch):
    """Preserve real AWS env vars for load tests.

    Only sets defaults for vars that are NOT already set in the environment.
    This allows load tests to use real buckets, credentials, etc.
    """
    if not os.environ.get("AWS_REGION"):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
    if not os.environ.get("AWS_DEFAULT_REGION"):
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    # Do NOT override CLIMATE_RAG_BUCKET — load tests need the real one
    # Do NOT override AWS_PROFILE — load tests need real credentials
