"""
Integration tests that verify real AWS service connectivity.

These tests require valid AWS credentials and access to:
- Amazon S3 (list/read from the climate-rag bucket)
- Amazon Bedrock Runtime (invoke Titan Embeddings v2)
- Amazon Bedrock AgentCore Control Plane (list memories, code interpreters)
- AWS SSM Parameter Store (read /climate-rag/* parameters)

Run with: python -m pytest tests/integration -m integration
Skip with: python -m pytest -m "not integration"
"""

import json
import os

import boto3
import pytest

REGION = os.environ.get("AWS_REGION", "us-east-1")


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestS3Connectivity:
    """Verify S3 bucket access for the FAISS index."""

    def test_bucket_exists_and_accessible(self):
        """The climate-rag index bucket should exist and be accessible."""
        bucket = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
        s3 = boto3.client("s3", region_name=REGION)

        response = s3.head_bucket(Bucket=bucket)
        # head_bucket returns 200 on success; raises ClientError otherwise
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    def test_faiss_index_exists_in_s3(self):
        """The FAISS index file should exist in the bucket."""
        bucket = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
        s3 = boto3.client("s3", region_name=REGION)

        response = s3.head_object(Bucket=bucket, Key="index/faiss.index")
        # File exists if no exception is raised
        assert response["ContentLength"] > 0

    def test_metadata_jsonl_exists_in_s3(self):
        """The metadata.jsonl file should exist alongside the index."""
        bucket = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
        s3 = boto3.client("s3", region_name=REGION)

        response = s3.head_object(Bucket=bucket, Key="index/metadata.jsonl")
        assert response["ContentLength"] > 0


class TestBedrockEmbeddings:
    """Verify Bedrock Titan Embeddings v2 is accessible."""

    def test_titan_embeddings_invocation(self):
        """Should successfully generate an embedding vector from Titan v2."""
        client = boto3.client("bedrock-runtime", region_name=REGION)

        response = client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=json.dumps({"inputText": "What is the global temperature trend?"}),
        )

        result = json.loads(response["body"].read())
        assert "embedding" in result
        assert len(result["embedding"]) == 1024
        assert all(isinstance(v, float) for v in result["embedding"])

    def test_embedding_dimension_consistency(self):
        """Two different texts should produce same-dimension embeddings."""
        client = boto3.client("bedrock-runtime", region_name=REGION)

        texts = [
            "Temperature trends in the Southeast US",
            "Precipitation data from NASA POWER satellite observations",
        ]

        embeddings = []
        for text in texts:
            response = client.invoke_model(
                modelId="amazon.titan-embed-text-v2:0",
                body=json.dumps({"inputText": text}),
            )
            result = json.loads(response["body"].read())
            embeddings.append(result["embedding"])

        assert len(embeddings[0]) == len(embeddings[1]) == 1024


class TestAgentCoreControlPlane:
    """Verify AgentCore control plane API access."""

    def test_list_memories(self):
        """Should be able to list AgentCore memories without error."""
        client = boto3.client("bedrock-agentcore-control", region_name=REGION)

        response = client.list_memories()
        # Should return a list (may be empty if nothing deployed)
        assert "memorySummaries" in response
        assert isinstance(response["memorySummaries"], list)

    def test_list_code_interpreters(self):
        """Should be able to list AgentCore code interpreters without error."""
        client = boto3.client("bedrock-agentcore-control", region_name=REGION)

        response = client.list_code_interpreters()
        assert "codeInterpreterSummaries" in response
        assert isinstance(response["codeInterpreterSummaries"], list)

    def test_list_gateways(self):
        """Should be able to list AgentCore gateways without error."""
        client = boto3.client("bedrock-agentcore-control", region_name=REGION)

        response = client.list_gateways()
        assert "gatewaySummaries" in response
        assert isinstance(response["gatewaySummaries"], list)


class TestSSMParameters:
    """Verify SSM parameters are accessible (if stack is deployed)."""

    def test_can_read_ssm_parameter(self):
        """Should be able to call GetParameter (even if it doesn't exist yet)."""
        ssm = boto3.client("ssm", region_name=REGION)

        # Try to read one of our parameters — it may or may not exist
        try:
            response = ssm.get_parameter(Name="/climate-rag/memory-id")
            # If it exists, it should have a value
            assert response["Parameter"]["Value"] != ""
        except ssm.exceptions.ParameterNotFound:
            # Parameter not found is acceptable — stack may not be deployed yet
            # The test passes because we confirmed SSM API connectivity
            pass


class TestSTSIdentity:
    """Verify basic AWS credential validity."""

    def test_get_caller_identity(self):
        """AWS credentials should be valid and return account info."""
        sts = boto3.client("sts", region_name=REGION)
        response = sts.get_caller_identity()

        assert "Account" in response
        assert "Arn" in response
        assert len(response["Account"]) == 12  # AWS account IDs are 12 digits
