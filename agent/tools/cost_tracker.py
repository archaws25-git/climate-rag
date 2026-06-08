"""Cost tracking for ClimateRAG — token counts and estimated costs per request.

Tracks:
  - Input/output tokens per LLM call
  - Embedding tokens per RAG search
  - Re-ranker tokens per call
  - Cumulative session cost

Pricing (us-east-1, as of 2026-06):
  - Claude Sonnet: $3.00/M input, $15.00/M output tokens
  - Titan Embeddings v2: $0.02/M input tokens
  - Re-ranker (Sonnet): same as Claude Sonnet
"""

import threading
from dataclasses import dataclass, field


# Pricing per million tokens (USD)
PRICING = {
    "claude-sonnet-input": 3.00,
    "claude-sonnet-output": 15.00,
    "titan-embed-input": 0.02,
    "reranker-input": 3.00,
    "reranker-output": 15.00,
    "query-planner-input": 3.00,
    "query-planner-output": 15.00,
}


@dataclass
class RequestCost:
    """Cost breakdown for a single request."""

    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    embedding_tokens: int = 0
    reranker_input_tokens: int = 0
    reranker_output_tokens: int = 0
    planner_input_tokens: int = 0
    planner_output_tokens: int = 0

    @property
    def total_cost_usd(self) -> float:
        """Calculate total estimated cost in USD."""
        cost = 0.0
        cost += (self.llm_input_tokens / 1_000_000) * PRICING["claude-sonnet-input"]
        cost += (self.llm_output_tokens / 1_000_000) * PRICING["claude-sonnet-output"]
        cost += (self.embedding_tokens / 1_000_000) * PRICING["titan-embed-input"]
        cost += (self.reranker_input_tokens / 1_000_000) * PRICING["reranker-input"]
        cost += (self.reranker_output_tokens / 1_000_000) * PRICING["reranker-output"]
        cost += (self.planner_input_tokens / 1_000_000) * PRICING["query-planner-input"]
        cost += (self.planner_output_tokens / 1_000_000) * PRICING["query-planner-output"]
        return round(cost, 6)

    @property
    def total_tokens(self) -> int:
        """Total tokens across all services."""
        return (
            self.llm_input_tokens
            + self.llm_output_tokens
            + self.embedding_tokens
            + self.reranker_input_tokens
            + self.reranker_output_tokens
            + self.planner_input_tokens
            + self.planner_output_tokens
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "embedding_tokens": self.embedding_tokens,
            "reranker_tokens": self.reranker_input_tokens + self.reranker_output_tokens,
            "planner_tokens": self.planner_input_tokens + self.planner_output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.total_cost_usd,
        }


class CostTracker:
    """Thread-safe cost tracker for accumulating request costs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._current_request = RequestCost()
        self._session_total = RequestCost()
        self._request_count = 0

    def reset_request(self):
        """Start tracking a new request."""
        with self._lock:
            self._current_request = RequestCost()

    def add_llm_tokens(self, input_tokens: int, output_tokens: int):
        """Record LLM token usage."""
        with self._lock:
            self._current_request.llm_input_tokens += input_tokens
            self._current_request.llm_output_tokens += output_tokens
            self._session_total.llm_input_tokens += input_tokens
            self._session_total.llm_output_tokens += output_tokens

    def add_embedding_tokens(self, tokens: int):
        """Record embedding token usage."""
        with self._lock:
            self._current_request.embedding_tokens += tokens
            self._session_total.embedding_tokens += tokens

    def add_reranker_tokens(self, input_tokens: int, output_tokens: int):
        """Record re-ranker token usage."""
        with self._lock:
            self._current_request.reranker_input_tokens += input_tokens
            self._current_request.reranker_output_tokens += output_tokens
            self._session_total.reranker_input_tokens += input_tokens
            self._session_total.reranker_output_tokens += output_tokens

    def add_planner_tokens(self, input_tokens: int, output_tokens: int):
        """Record query planner token usage."""
        with self._lock:
            self._current_request.planner_input_tokens += input_tokens
            self._current_request.planner_output_tokens += output_tokens
            self._session_total.planner_input_tokens += input_tokens
            self._session_total.planner_output_tokens += output_tokens

    def finish_request(self) -> RequestCost:
        """Finalize current request and return its cost breakdown."""
        with self._lock:
            self._request_count += 1
            return self._current_request

    @property
    def session_cost(self) -> RequestCost:
        """Get cumulative session cost."""
        return self._session_total

    @property
    def request_count(self) -> int:
        """Number of requests tracked this session."""
        return self._request_count

    def get_summary(self) -> dict:
        """Get full session cost summary."""
        return {
            "requests": self._request_count,
            "session_total": self._session_total.to_dict(),
            "avg_cost_per_request": (
                round(self._session_total.total_cost_usd / self._request_count, 6)
                if self._request_count > 0
                else 0.0
            ),
        }


# Global singleton tracker
tracker = CostTracker()
