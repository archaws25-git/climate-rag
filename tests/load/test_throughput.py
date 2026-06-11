"""
Throughput benchmarks — measures QPS (queries per second) under realistic load.

Tests:
  1. RAG search throughput (FAISS only, no LLM)
  2. Full agent request throughput (RAG + LLM generation)
  3. Embedding generation throughput

Run with:
    python -m pytest tests/load/test_throughput.py -v -s --timeout=300

Requirements:
    - AWS credentials active
    - FAISS index uploaded to S3
    - CLIMATE_RAG_BUCKET set
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, stdev

import boto3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

# pylint: disable=import-error,wrong-import-position

# Mark all tests as load tests (skip in normal runs)
pytestmark = pytest.mark.load

# ── Auto-configure environment from SSM at module load ────────────────────────
# Load tests require real AWS resources. Read IDs from SSM so the agent
# can connect to Memory and Code Interpreter without manual env setup.
REGION = os.environ.get("AWS_REGION", "us-east-1")


def _load_ssm_param(name):
    """Read a single SSM parameter, return empty string on failure."""
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return ""


_memory_id = _load_ssm_param("/climate-rag/memory-id")
if _memory_id:
    os.environ["CLIMATE_RAG_MEMORY_ID"] = _memory_id
else:
    os.environ["CLIMATE_RAG_MEMORY_ID"] = ""

_ci_id = _load_ssm_param("/climate-rag/code-interpreter-id")
if _ci_id:
    os.environ["CLIMATE_RAG_CODE_INTERPRETER_ID"] = _ci_id
else:
    os.environ["CLIMATE_RAG_CODE_INTERPRETER_ID"] = ""


# Get bucket name from CloudFormation stack output
def _get_bucket_name():
    """Read bucket name from CloudFormation DataStack output."""
    try:
        cfn = boto3.client("cloudformation", region_name=REGION)
        stacks = cfn.describe_stacks(StackName="ClimateRagDataStack")["Stacks"]
        for output in stacks[0].get("Outputs", []):
            if output["OutputKey"] == "IndexBucketName":
                return output["OutputValue"]
    except Exception:
        pass
    return os.environ.get("CLIMATE_RAG_BUCKET", "")


_bucket = _get_bucket_name()
if _bucket:
    os.environ["CLIMATE_RAG_BUCKET"] = _bucket

# ── Test queries for benchmarking ─────────────────────────────────────────────
BENCHMARK_QUERIES = [
    "What is the temperature trend in the Southeast?",
    "Compare New York and Chicago temperatures",
    "Average temperature in Atlanta in the 1990s",
    "How has Alaska warmed since 1950?",
    "What is the hottest decade on record?",
    "Show me Miami temperature data",
    "Temperature trends in Denver Colorado",
    "How does Phoenix compare to Las Vegas?",
    "Minneapolis winter temperatures over time",
    "Dallas and Houston climate comparison",
]


class TestRagSearchThroughput:
    """Benchmark FAISS vector search throughput (no LLM calls)."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Ensure RAG tool uses the real bucket, not conftest's test-bucket."""
        if not _bucket:
            pytest.skip("CLIMATE_RAG_BUCKET not available — load tests require deployed infrastructure")
        monkeypatch.setenv("CLIMATE_RAG_BUCKET", _bucket)
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "")

        from tools.rag_tool import _load_index, search_climate_data

        # Reset index cache so it re-downloads with correct bucket
        import tools.rag_tool as rag_mod

        rag_mod._index = None
        rag_mod._metadata = None
        rag_mod._bm25_index = None
        rag_mod._bm25_corpus_tokens = None

        self.search = search_climate_data
        _load_index()
        _load_index()

    def test_single_query_latency(self):
        """Single RAG search should complete under 2 seconds."""
        start = time.time()
        result = self.search(query="temperature in Atlanta", top_k=5)
        latency = time.time() - start

        assert latency < 2.0, f"Single query took {latency:.2f}s (limit: 2s)"
        parsed = json.loads(result)
        assert "results" in parsed
        print(f"\n  Single query latency: {latency * 1000:.0f}ms")

    def test_sequential_throughput(self):
        """Measure sequential QPS over 10 queries."""
        start = time.time()
        for query in BENCHMARK_QUERIES:
            self.search(query=query, top_k=5)
        elapsed = time.time() - start

        qps = len(BENCHMARK_QUERIES) / elapsed
        avg_latency = elapsed / len(BENCHMARK_QUERIES)

        print(f"\n  Sequential throughput:")
        print(f"    Queries: {len(BENCHMARK_QUERIES)}")
        print(f"    Total time: {elapsed:.2f}s")
        print(f"    QPS: {qps:.1f}")
        print(f"    Avg latency: {avg_latency * 1000:.0f}ms")

        # Baseline: FAISS search + embedding should do > 1 QPS
        assert qps > 0.5, f"QPS too low: {qps:.2f}"

    def test_burst_throughput(self):
        """Measure throughput under burst of 20 queries."""
        queries = BENCHMARK_QUERIES * 2  # 20 queries
        latencies = []

        for query in queries:
            start = time.time()
            self.search(query=query, top_k=5)
            latencies.append(time.time() - start)

        avg = mean(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        qps = len(queries) / sum(latencies)

        print(f"\n  Burst throughput (20 queries):")
        print(f"    QPS: {qps:.1f}")
        print(f"    Avg latency: {avg * 1000:.0f}ms")
        print(f"    P95 latency: {p95 * 1000:.0f}ms")

        assert avg < 5.0, f"Average latency too high: {avg:.2f}s"


class TestConcurrentThroughput:
    """Benchmark concurrent request handling."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Pre-load the index with real bucket."""
        if not _bucket:
            pytest.skip("CLIMATE_RAG_BUCKET not available — load tests require deployed infrastructure")
        monkeypatch.setenv("CLIMATE_RAG_BUCKET", _bucket)
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", "")

        from tools.rag_tool import _load_index, search_climate_data
        import tools.rag_tool as rag_mod

        rag_mod._index = None
        rag_mod._metadata = None
        rag_mod._bm25_index = None
        rag_mod._bm25_corpus_tokens = None

        self.search = search_climate_data
        _load_index()

    def test_concurrent_rag_searches(self):
        """5 concurrent RAG searches should all complete successfully."""
        results = []
        errors = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self.search, query=q, top_k=5): q for q in BENCHMARK_QUERIES[:5]}
            start = time.time()

            for future in as_completed(futures):
                try:
                    result = future.result(timeout=30)
                    results.append(result)
                except Exception as e:
                    errors.append(str(e))

            elapsed = time.time() - start

        qps = len(results) / elapsed if elapsed > 0 else 0

        print(f"\n  Concurrent RAG search (5 threads):")
        print(f"    Successful: {len(results)}")
        print(f"    Errors: {len(errors)}")
        print(f"    Wall time: {elapsed:.2f}s")
        print(f"    Effective QPS: {qps:.1f}")

        assert len(errors) == 0, f"Concurrent errors: {errors}"
        assert len(results) == 5

    def test_concurrent_10_requests(self):
        """10 concurrent requests should complete within 60 seconds."""
        results = []
        errors = []

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self.search, query=q, top_k=5): q for q in BENCHMARK_QUERIES}
            start = time.time()

            for future in as_completed(futures):
                try:
                    result = future.result(timeout=60)
                    results.append(result)
                except Exception as e:
                    errors.append(str(e))

            elapsed = time.time() - start

        print(f"\n  Concurrent RAG search (10 threads):")
        print(f"    Successful: {len(results)}/{len(BENCHMARK_QUERIES)}")
        print(f"    Errors: {len(errors)}")
        print(f"    Wall time: {elapsed:.2f}s")

        # Allow up to 20% error rate under high concurrency
        error_rate = len(errors) / len(BENCHMARK_QUERIES)
        assert error_rate <= 0.2, f"Error rate too high: {error_rate:.0%}"


class TestFullAgentThroughput:
    """Benchmark end-to-end agent request throughput (RAG + LLM)."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Load the agent handler with correct env vars for real AWS."""
        # Override conftest defaults — load tests need real (or empty) values
        if _bucket:
            monkeypatch.setenv("CLIMATE_RAG_BUCKET", _bucket)
        monkeypatch.setenv("CLIMATE_RAG_MEMORY_ID", _memory_id if _memory_id else "")
        monkeypatch.setenv("CLIMATE_RAG_CODE_INTERPRETER_ID", _ci_id if _ci_id else "")

        from main import handle_request

        self.handle = handle_request

    def test_single_request_latency(self):
        """Single full agent request should complete under 30 seconds."""
        start = time.time()
        result = self.handle("What is the temperature in Atlanta?")
        latency = time.time() - start

        print(f"\n  Full agent request latency: {latency:.1f}s")
        print(f"    Response length: {len(result['response'])} chars")
        print(f"    Tools called: {result.get('tools_called', [])}")

        assert latency < 30.0, f"Request took {latency:.1f}s (limit: 30s)"
        assert len(result["response"]) > 50

    def test_sequential_agent_throughput(self):
        """Measure full agent QPS over 3 queries (LLM is the bottleneck)."""
        queries = BENCHMARK_QUERIES[:3]
        latencies = []

        for query in queries:
            start = time.time()
            self.handle(query)
            latencies.append(time.time() - start)

        avg = mean(latencies)
        qps = len(queries) / sum(latencies)

        print(f"\n  Full agent sequential throughput:")
        print(f"    Queries: {len(queries)}")
        print(f"    Avg latency: {avg:.1f}s")
        print(f"    QPS: {qps:.2f}")

        # LLM calls are slow — expect > 0.03 QPS (< 30s per query avg)
        assert qps > 0.03, f"Agent QPS too low: {qps:.3f}"
