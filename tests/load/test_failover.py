"""
Failover testing — graceful degradation when components are unavailable.

Verifies the system behaves correctly when:
  1. Vector DB (FAISS/S3) is unavailable
  2. Embedding model (Bedrock Titan) is unavailable
  3. LLM (Claude Sonnet) is unavailable
  4. Guardrail service is unavailable

Each test simulates a component failure and verifies the system degrades
gracefully — returning meaningful error messages rather than crashing.

Run with:
    python -m pytest tests/load/test_failover.py -v -s

These tests mock AWS services so no real credentials are needed.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Mark as load tests
pytestmark = pytest.mark.load


def _make_client_error(code, message="Service unavailable"):
    """Create a botocore ClientError."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "TestOperation",
    )


class TestVectorDBFailover:
    """Test behavior when FAISS index in S3 is unavailable."""

    def test_s3_connection_failure(self):
        """Should raise clear error when S3 is unreachable."""
        import importlib
        import agent.tools.rag_tool as rag_module
        importlib.reload(rag_module)
        rag_module._index = None
        rag_module._metadata = None

        mock_s3 = MagicMock()
        mock_s3.download_file.side_effect = EndpointConnectionError(
            endpoint_url="https://s3.us-east-1.amazonaws.com"
        )

        with patch("boto3.client") as mock_boto:
            def client_factory(service, **kwargs):
                if service == "s3":
                    return mock_s3
                return MagicMock()
            mock_boto.side_effect = client_factory

            with pytest.raises(Exception) as exc_info:
                rag_module.search_climate_data(query="test", top_k=3)

            # Should be a connection-related error, not a crash
            assert "endpoint" in str(exc_info.value).lower() or "connect" in str(exc_info.value).lower()

    def test_s3_bucket_not_found(self):
        """Should raise clear error when bucket doesn't exist."""
        import importlib
        import agent.tools.rag_tool as rag_module
        importlib.reload(rag_module)
        rag_module._index = None
        rag_module._metadata = None

        mock_s3 = MagicMock()
        mock_s3.download_file.side_effect = _make_client_error(
            "NoSuchBucket", "The specified bucket does not exist"
        )

        with patch("boto3.client") as mock_boto:
            def client_factory(service, **kwargs):
                if service == "s3":
                    return mock_s3
                return MagicMock()
            mock_boto.side_effect = client_factory

            with pytest.raises(ClientError) as exc_info:
                rag_module.search_climate_data(query="test", top_k=3)

            assert "NoSuchBucket" in str(exc_info.value)

    def test_s3_index_file_missing(self):
        """Should raise error when faiss.index doesn't exist in bucket."""
        import importlib
        import agent.tools.rag_tool as rag_module
        importlib.reload(rag_module)
        rag_module._index = None
        rag_module._metadata = None

        mock_s3 = MagicMock()
        mock_s3.download_file.side_effect = _make_client_error(
            "404", "Not Found"
        )

        with patch("boto3.client") as mock_boto:
            def client_factory(service, **kwargs):
                if service == "s3":
                    return mock_s3
                return MagicMock()
            mock_boto.side_effect = client_factory

            with pytest.raises(ClientError):
                rag_module.search_climate_data(query="test", top_k=3)


class TestEmbeddingModelFailover:
    """Test behavior when Bedrock Titan embedding model is unavailable."""

    def test_embedding_throttled(self, sample_chunks, tmp_path):
        """Should propagate throttling error clearly."""
        import importlib
        import faiss
        import numpy as np
        import agent.tools.rag_tool as rag_module
        importlib.reload(rag_module)

        # Pre-load a real index so S3 succeeds
        embeddings = np.array(
            [c["embedding"] for c in sample_chunks], dtype="float32"
        )
        faiss.normalize_L2(embeddings)
        index = faiss.IndexFlatIP(1024)
        index.add(embeddings)
        rag_module._index = index
        rag_module._metadata = [
            {"text": c["text"], "metadata": c["metadata"]} for c in sample_chunks
        ]

        # Mock embedding call to fail with throttling
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.side_effect = _make_client_error(
            "ThrottlingException", "Rate exceeded"
        )

        with patch("boto3.client") as mock_boto:
            def client_factory(service, **kwargs):
                if service == "bedrock-runtime":
                    return mock_bedrock
                return MagicMock()
            mock_boto.side_effect = client_factory

            with pytest.raises(ClientError) as exc_info:
                rag_module.search_climate_data(query="test query", top_k=3)

            assert "ThrottlingException" in str(exc_info.value)

    def test_embedding_model_not_found(self, sample_chunks):
        """Should raise error when embedding model is not available."""
        import importlib
        import faiss
        import numpy as np
        import agent.tools.rag_tool as rag_module
        importlib.reload(rag_module)

        embeddings = np.array(
            [c["embedding"] for c in sample_chunks], dtype="float32"
        )
        faiss.normalize_L2(embeddings)
        index = faiss.IndexFlatIP(1024)
        index.add(embeddings)
        rag_module._index = index
        rag_module._metadata = [
            {"text": c["text"], "metadata": c["metadata"]} for c in sample_chunks
        ]

        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.side_effect = _make_client_error(
            "ModelNotReadyException", "Model is not available"
        )

        with patch("boto3.client") as mock_boto:
            def client_factory(service, **kwargs):
                if service == "bedrock-runtime":
                    return mock_bedrock
                return MagicMock()
            mock_boto.side_effect = client_factory

            with pytest.raises(ClientError) as exc_info:
                rag_module.search_climate_data(query="test", top_k=3)

            assert "ModelNotReadyException" in str(exc_info.value)


class TestGuardrailFailover:
    """Test behavior when Bedrock Guardrails are unavailable."""

    def test_guardrail_service_down_input(self, monkeypatch):
        """Input guardrail should fail-open when service is unreachable."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-id")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.side_effect = EndpointConnectionError(
            endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com"
        )

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-id"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_input_guardrail("Safe climate question")

        # Should fail-open: allow through, don't block
        assert blocked is False
        assert text == "Safe climate question"

    def test_guardrail_service_down_output(self, monkeypatch):
        """Output guardrail should fail-open when service is unreachable."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-id")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.side_effect = _make_client_error(
            "ServiceUnavailableException", "Service is temporarily unavailable"
        )

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-id"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_output_guardrail("Temperature is 15°C")

        # Should fail-open
        assert blocked is False
        assert text == "Temperature is 15°C"

    def test_guardrail_throttled(self, monkeypatch):
        """Throttled guardrail should fail-open gracefully."""
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "test-id")
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_VERSION", "1")

        mock_client = MagicMock()
        mock_client.apply_guardrail.side_effect = _make_client_error(
            "ThrottlingException", "Rate exceeded"
        )

        with patch("boto3.client", return_value=mock_client):
            import importlib
            import tools.guardrails as mod
            importlib.reload(mod)
            mod._guardrail_id = "test-id"
            mod._guardrail_version = "1"

            text, blocked = mod.apply_input_guardrail("Normal question")

        assert blocked is False


class TestLLMFailover:
    """Test behavior when the LLM (Claude) is unavailable.

    These tests patch the agent at the module level BEFORE calling handle_request,
    and disable memory to avoid real AWS calls.
    """

    def test_agent_handles_llm_timeout(self, monkeypatch):
        """Agent should propagate LLM timeout as a clear exception."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "")

        import importlib
        import agent.main as main_module
        importlib.reload(main_module)

        # Patch the agent object directly on the reloaded module
        mock_agent = MagicMock()
        mock_agent.side_effect = _make_client_error(
            "ModelTimeoutException", "Model invocation timed out"
        )
        main_module.agent = mock_agent

        with pytest.raises(ClientError) as exc_info:
            main_module.handle_request("What is the temperature?")

        assert "ModelTimeoutException" in str(exc_info.value)

    def test_agent_handles_llm_throttling(self, monkeypatch):
        """Agent should propagate LLM throttling as a clear exception."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "")

        import importlib
        import agent.main as main_module
        importlib.reload(main_module)

        mock_agent = MagicMock()
        mock_agent.side_effect = _make_client_error(
            "ThrottlingException", "Too many requests"
        )
        main_module.agent = mock_agent

        with pytest.raises(ClientError) as exc_info:
            main_module.handle_request("Climate question")

        assert "ThrottlingException" in str(exc_info.value)

    def test_agent_handles_model_not_available(self, monkeypatch):
        """Agent should propagate access denied as a clear exception."""
        monkeypatch.delenv("CLIMATE_RAG_MEMORY_ID", raising=False)
        monkeypatch.setenv("CLIMATE_RAG_GUARDRAIL_ID", "")

        import importlib
        import agent.main as main_module
        importlib.reload(main_module)

        mock_agent = MagicMock()
        mock_agent.side_effect = _make_client_error(
            "AccessDeniedException", "Model access not enabled"
        )
        main_module.agent = mock_agent

        with pytest.raises(ClientError) as exc_info:
            main_module.handle_request("Simple question")

        assert "AccessDeniedException" in str(exc_info.value)
