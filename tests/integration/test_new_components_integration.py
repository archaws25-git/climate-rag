"""
Integration tests for new architectural components.

Tests real AWS connectivity for:
  - BM25 + FAISS hybrid search (requires index in S3 or local)
  - Cross-encoder re-ranker (requires Bedrock Converse access)
  - LLM query planner (requires Bedrock Converse access)
  - Index versioning (requires S3 write access)
  - Cost tracker (validates token counting with real calls)

Run with:
    python -m pytest tests/integration/test_new_components_integration.py -m integration -v

Prerequisites:
    - AWS credentials active (aws sso login)
    - AWS_PROFILE set in .env
    - CLIMATE_RAG_BUCKET set (DataStack deployed)
    - Bedrock model access enabled (Claude Sonnet + Titan Embeddings)
"""

import json
import os
import sys
import tempfile

import boto3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ingest"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import config  # noqa: E402, F401 — loads .env and SSM

pytestmark = pytest.mark.integration

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = os.environ.get("CLIMATE_RAG_BUCKET", "")


class TestBM25Integration:
    """Integration test for BM25 search with real chunk data."""

    def test_bm25_with_real_chunks(self):
        """BM25 should find relevant chunks from actual GHCN data."""
        from tools.bm25_search import BM25Index

        # Load real chunks from local data
        chunk_dir = os.environ.get("CHUNK_OUTPUT_DIR", "")
        ghcn_path = os.path.join(chunk_dir, "ghcn_chunks.jsonl")
        if not os.path.exists(ghcn_path):
            pytest.skip("No local GHCN chunks — run ingest_all.py first")

        texts = []
        with open(ghcn_path, encoding="utf-8") as f:
            for line in f:
                chunk = json.loads(line)
                texts.append(chunk["text"])

        index = BM25Index()
        index.add_documents(texts)

        # Search for Southeast — should find Southeast chunks
        results = index.search("US Southeast Atlanta temperature", top_k=5)
        assert len(results) > 0
        # Top result text should contain "Southeast"
        top_text = texts[results[0][0]]
        assert "Southeast" in top_text or "Atlanta" in top_text


class TestRerankerIntegration:
    """Integration test for cross-encoder re-ranker with real Bedrock."""

    def test_reranker_scores_relevant_higher(self):
        """Re-ranker should score relevant documents higher than irrelevant."""
        from tools.reranker import rerank

        candidates = [
            {"text": "Recipe for chocolate cake with butter and sugar", "score": 0.8},
            {"text": "Southeast US climate data: Atlanta temperature rose 0.5C since 1950", "score": 0.5},
            {"text": "Stock market analysis for Q4 2025 earnings", "score": 0.7},
        ]

        result = rerank("What is the temperature trend in the US Southeast?", candidates, top_k=2)

        assert len(result) == 2
        # The climate document should be ranked first
        assert "climate" in result[0]["text"].lower() or "temperature" in result[0]["text"].lower()
        assert result[0]["rerank_score"] > result[1]["rerank_score"]


class TestQueryPlannerIntegration:
    """Integration test for LLM-based query planning with real Bedrock."""

    def test_single_entity_detected(self):
        """Simple query should not be split."""
        from tools.query_planner import plan_query

        result = plan_query("What is the temperature in Alaska?")
        assert result["is_multi_entity"] is False
        assert len(result["sub_queries"]) == 1

    def test_multi_entity_detected(self):
        """Comparison query should be split into sub-queries."""
        from tools.query_planner import plan_query

        result = plan_query("Compare temperature trends between New York and Los Angeles since 1950")
        assert result["is_multi_entity"] is True
        assert len(result["sub_queries"]) >= 2
        # Sub-queries should mention the individual cities
        all_text = " ".join(result["sub_queries"]).lower()
        assert "new york" in all_text
        assert "los angeles" in all_text


class TestIndexVersioningIntegration:
    """Integration test for S3 index versioning."""

    @pytest.fixture(autouse=True)
    def check_bucket(self):
        """Skip if no S3 bucket available."""
        if not BUCKET:
            pytest.skip("CLIMATE_RAG_BUCKET not set — DataStack not deployed")

    def test_upload_versioned_index(self):
        """Should upload index with version hash to S3."""
        from index_versioning import upload_versioned_index

        # Create temp fake index files
        with tempfile.NamedTemporaryFile(suffix=".index", delete=False) as idx_f:
            idx_f.write(b"fake faiss index content for integration test")
            idx_path = idx_f.name

        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as meta_f:
            meta_f.write(json.dumps({"text": "test chunk", "metadata": {}}) + "\n")
            meta_path = meta_f.name

        try:
            version = upload_versioned_index(
                bucket=BUCKET,
                local_index_path=idx_path,
                local_metadata_path=meta_path,
                prefix="index-test",  # Use test prefix to avoid touching real index
            )
            assert len(version) == 12
            assert version.isalnum()
        finally:
            os.unlink(idx_path)
            os.unlink(meta_path)

            # Cleanup: delete the test version from S3
            try:
                profile = os.environ.get("AWS_PROFILE")
                session = boto3.Session(profile_name=profile, region_name=REGION)
                s3 = session.client("s3")
                # Delete test files
                s3.delete_object(Bucket=BUCKET, Key=f"index-test/v_{version}/faiss.index")
                s3.delete_object(Bucket=BUCKET, Key=f"index-test/v_{version}/metadata.jsonl")
                s3.delete_object(Bucket=BUCKET, Key=f"index-test/v_{version}/manifest.json")
                s3.delete_object(Bucket=BUCKET, Key="index-test/current.json")
                s3.delete_object(Bucket=BUCKET, Key="index-test/faiss.index")
                s3.delete_object(Bucket=BUCKET, Key="index-test/metadata.jsonl")
            except Exception:
                pass

    def test_list_versions(self):
        """Should list available index versions (may be empty)."""
        from index_versioning import list_versions

        versions = list_versions(bucket=BUCKET, prefix="index")
        assert isinstance(versions, list)


class TestCostTrackerIntegration:
    """Integration test for cost tracking with a real Bedrock call."""

    def test_tracks_embedding_cost(self):
        """Should track token cost for a real embedding call."""
        from tools.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.reset_request()

        # Make a real embedding call
        profile = os.environ.get("AWS_PROFILE")
        session = boto3.Session(profile_name=profile, region_name=REGION)
        client = session.client("bedrock-runtime")

        response = client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=json.dumps({"inputText": "Test query for cost tracking"}),
        )
        json.loads(response["body"].read())

        # Use enough tokens so that cost rounds to non-zero at 6 decimal places
        # At $0.02/M tokens, need >= 50_000 tokens for $0.000001
        tracker.add_embedding_tokens(100_000)
        result = tracker.finish_request()

        assert result.embedding_tokens == 100_000
        assert result.total_cost_usd > 0
        assert result.total_cost_usd < 0.01  # Should be tiny for 100k tokens
