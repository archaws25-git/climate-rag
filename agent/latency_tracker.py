"""ClimateRAG — Lightweight latency tracker for Streamlit UI.

Records per-stage timing during a request and exposes results for
the sidebar widget. Uses time.perf_counter() internally and OTel
spans when available.

This is a non-invasive wrapper — it patches into handle_request_streaming
via the UI layer without modifying the agent core files.

Usage (in Streamlit):
    from latency_tracker import LatencyTracker

    tracker = LatencyTracker()
    tracker.start("e2e")
    # ... run request ...
    tracker.stop("e2e")
    breakdown = tracker.get_breakdown()
"""

import time
from collections import OrderedDict
from typing import Optional

try:
    from tracing import start_request_trace  # noqa: F401

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


class LatencyTracker:
    """Records per-stage timing for a single request lifecycle."""

    # Class-level accumulator for percentile computation across requests
    _history: list[dict] = []

    def __init__(self, request_id: Optional[str] = None):
        self._timers: OrderedDict[str, dict] = OrderedDict()
        self._request_id = request_id or str(time.time())
        self._first_token_time: Optional[float] = None
        self._stream_start_time: Optional[float] = None
        self._token_count: int = 0
        self._input_tokens: int = 0
        self._output_tokens: int = 0

        if OTEL_AVAILABLE:
            start_request_trace(self._request_id)

    def start(self, stage: str):
        """Start timing a stage."""
        self._timers[stage] = {"start": time.perf_counter(), "end": None, "duration_ms": None}

    def stop(self, stage: str):
        """Stop timing a stage."""
        if stage in self._timers and self._timers[stage]["end"] is None:
            end = time.perf_counter()
            self._timers[stage]["end"] = end
            self._timers[stage]["duration_ms"] = round((end - self._timers[stage]["start"]) * 1000, 1)

    def record_first_token(self):
        """Record when the first streaming token arrives."""
        if self._first_token_time is None:
            self._first_token_time = time.perf_counter()

    def record_stream_start(self):
        """Record when streaming begins (before first token)."""
        self._stream_start_time = time.perf_counter()

    def increment_tokens(self, count: int = 1):
        """Increment token counter."""
        self._token_count += count

    def set_token_usage(self, input_tokens: int, output_tokens: int):
        """Set token usage from response metadata."""
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    @property
    def ttft_ms(self) -> Optional[float]:
        """Time to First Token in milliseconds."""
        if self._first_token_time and self._stream_start_time:
            return round((self._first_token_time - self._stream_start_time) * 1000, 1)
        return None

    def get_breakdown(self) -> list[dict]:
        """Get the full latency breakdown as a list of stage dicts.

        Returns:
            [{"stage": "e2e", "duration_ms": 14230.5}, ...]
        """
        breakdown = []
        for stage, timer in self._timers.items():
            duration = timer.get("duration_ms")
            if duration is not None:
                breakdown.append(
                    {
                        "stage": stage,
                        "duration_ms": duration,
                    }
                )

        # Add TTFT if available
        if self.ttft_ms is not None:
            breakdown.append(
                {
                    "stage": "ttft (time to first token)",
                    "duration_ms": self.ttft_ms,
                }
            )

        return breakdown

    def get_summary(self) -> dict:
        """Get a summary dict for the metadata expander."""
        e2e = self._timers.get("e2e", {}).get("duration_ms")
        return {
            "e2e_ms": e2e,
            "ttft_ms": self.ttft_ms,
            "token_chunks": self._token_count,
            "stages": {s: t.get("duration_ms") for s, t in self._timers.items() if t.get("duration_ms")},
        }

    def format_for_sidebar(self) -> str:
        """Format latency data as a readable string for Streamlit sidebar."""
        lines = []
        e2e = self._timers.get("e2e", {}).get("duration_ms")
        if e2e:
            lines.append(f"**Total:** {e2e:,.0f}ms ({e2e / 1000:.1f}s)")

        if self.ttft_ms:
            lines.append(f"**TTFT:** {self.ttft_ms:,.0f}ms")

        lines.append("")
        lines.append("**Stage Breakdown:**")

        for stage, timer in self._timers.items():
            if stage == "e2e":
                continue
            duration = timer.get("duration_ms")
            if duration is not None:
                # Calculate percentage of E2E
                pct = f" ({duration / e2e * 100:.0f}%)" if e2e and e2e > 0 else ""
                lines.append(f"- {stage}: {duration:,.0f}ms{pct}")

        if self._token_count:
            lines.append(f"\n**Tokens streamed:** {self._token_count}")

        # Add percentile stats if we have history
        percentiles = self._compute_percentiles()
        if percentiles:
            lines.append("")
            lines.append("**Session Percentiles (across queries):**")
            lines.append(
                f"- E2E — P50: {percentiles['e2e_p50']:.0f}ms | "
                f"P95: {percentiles['e2e_p95']:.0f}ms | "
                f"P99: {percentiles['e2e_p99']:.0f}ms"
            )
            lines.append(
                f"- TTFT — P50: {percentiles['ttft_p50']:.0f}ms | "
                f"P95: {percentiles['ttft_p95']:.0f}ms | "
                f"P99: {percentiles['ttft_p99']:.0f}ms"
            )
            lines.append(f"- Queries in session: {percentiles['count']}")

        return "\n".join(lines)

    def finalize(self):
        """Finalize this request and add metrics to history for percentile computation."""
        entry = {
            "e2e_ms": self._timers.get("e2e", {}).get("duration_ms", 0),
            "ttft_ms": self.ttft_ms or 0,
            "token_count": self._token_count,
        }
        LatencyTracker._history.append(entry)

    def _compute_percentiles(self) -> Optional[dict]:
        """Compute P50/P95/P99 from session history."""
        history = LatencyTracker._history
        if len(history) < 2:
            return None

        e2e_values = sorted(h["e2e_ms"] for h in history if h["e2e_ms"] > 0)
        ttft_values = sorted(h["ttft_ms"] for h in history if h["ttft_ms"] > 0)

        if not e2e_values or not ttft_values:
            return None

        def percentile(data, pct):
            """Compute percentile using nearest-rank method."""
            if not data:
                return 0
            k = (len(data) - 1) * (pct / 100)
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            d = k - f
            return data[f] + d * (data[c] - data[f])

        return {
            "e2e_p50": percentile(e2e_values, 50),
            "e2e_p95": percentile(e2e_values, 95),
            "e2e_p99": percentile(e2e_values, 99),
            "ttft_p50": percentile(ttft_values, 50),
            "ttft_p95": percentile(ttft_values, 95),
            "ttft_p99": percentile(ttft_values, 99),
            "count": len(history),
        }
