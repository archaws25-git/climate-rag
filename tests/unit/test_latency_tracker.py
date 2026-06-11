"""Tests for the latency tracker module."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from latency_tracker import LatencyTracker


class TestLatencyTrackerBasic:
    """Tests for basic timing functionality."""

    def test_start_and_stop(self):
        tracker = LatencyTracker()
        tracker.start("test_stage")
        time.sleep(0.01)
        tracker.stop("test_stage")

        breakdown = tracker.get_breakdown()
        assert len(breakdown) >= 1
        assert breakdown[0]["stage"] == "test_stage"
        assert breakdown[0]["duration_ms"] > 0

    def test_multiple_stages(self):
        tracker = LatencyTracker()
        tracker.start("stage_a")
        time.sleep(0.01)
        tracker.stop("stage_a")
        tracker.start("stage_b")
        time.sleep(0.01)
        tracker.stop("stage_b")

        breakdown = tracker.get_breakdown()
        stages = [b["stage"] for b in breakdown]
        assert "stage_a" in stages
        assert "stage_b" in stages

    def test_ttft_recording(self):
        tracker = LatencyTracker()
        tracker.record_stream_start()
        time.sleep(0.01)
        tracker.record_first_token()

        assert tracker.ttft_ms is not None
        assert tracker.ttft_ms > 0

    def test_ttft_none_when_not_recorded(self):
        tracker = LatencyTracker()
        assert tracker.ttft_ms is None

    def test_token_counting(self):
        tracker = LatencyTracker()
        tracker.increment_tokens()
        tracker.increment_tokens()
        tracker.increment_tokens(5)

        assert tracker._token_count == 7

    def test_first_token_only_recorded_once(self):
        tracker = LatencyTracker()
        tracker.record_stream_start()
        time.sleep(0.01)
        tracker.record_first_token()
        first_ttft = tracker.ttft_ms
        time.sleep(0.01)
        tracker.record_first_token()  # Should not update
        assert tracker.ttft_ms == first_ttft


class TestLatencyTrackerFormatting:
    """Tests for the format_for_sidebar output."""

    def test_format_includes_total(self):
        tracker = LatencyTracker()
        tracker.start("e2e")
        time.sleep(0.01)
        tracker.stop("e2e")

        output = tracker.format_for_sidebar()
        assert "Total:" in output

    def test_format_includes_ttft(self):
        tracker = LatencyTracker()
        tracker.start("e2e")
        tracker.record_stream_start()
        time.sleep(0.01)
        tracker.record_first_token()
        tracker.stop("e2e")

        output = tracker.format_for_sidebar()
        assert "TTFT:" in output

    def test_format_includes_tokens(self):
        tracker = LatencyTracker()
        tracker.start("e2e")
        tracker.increment_tokens(42)
        tracker.stop("e2e")

        output = tracker.format_for_sidebar()
        assert "42" in output

    def test_format_includes_stage_breakdown(self):
        tracker = LatencyTracker()
        tracker.start("e2e")
        tracker.start("search")
        time.sleep(0.01)
        tracker.stop("search")
        tracker.stop("e2e")

        output = tracker.format_for_sidebar()
        assert "search:" in output


class TestLatencyTrackerPercentiles:
    """Tests for session-level percentile computation."""

    def test_no_percentiles_with_single_request(self):
        tracker = LatencyTracker()
        tracker.start("e2e")
        tracker.record_stream_start()
        tracker.record_first_token()
        tracker.stop("e2e")
        tracker.finalize()

        output = tracker.format_for_sidebar()
        # Should NOT include percentiles with only 1 data point
        assert "P50" not in output

    def test_percentiles_after_multiple_requests(self):
        # Simulate multiple requests
        LatencyTracker._history = []

        for _ in range(3):
            t = LatencyTracker()
            t.start("e2e")
            t.record_stream_start()
            time.sleep(0.005)
            t.record_first_token()
            t.stop("e2e")
            t.finalize()

        # The last tracker should show percentiles
        output = t.format_for_sidebar()
        assert "P50" in output
        assert "P95" in output
        assert "P99" in output

        # Cleanup
        LatencyTracker._history = []

    def test_finalize_adds_to_history(self):
        LatencyTracker._history = []

        tracker = LatencyTracker()
        tracker.start("e2e")
        tracker.stop("e2e")
        tracker.finalize()

        assert len(LatencyTracker._history) == 1
        assert "e2e_ms" in LatencyTracker._history[0]

        # Cleanup
        LatencyTracker._history = []


class TestLatencyTrackerSummary:
    """Tests for get_summary and get_breakdown."""

    def test_get_summary_structure(self):
        tracker = LatencyTracker()
        tracker.start("e2e")
        tracker.record_stream_start()
        time.sleep(0.01)
        tracker.record_first_token()
        tracker.increment_tokens(10)
        tracker.stop("e2e")

        summary = tracker.get_summary()
        assert "e2e_ms" in summary
        assert "ttft_ms" in summary
        assert "token_chunks" in summary
        assert "stages" in summary
        assert summary["token_chunks"] == 10

    def test_get_breakdown_empty_for_unstopped(self):
        tracker = LatencyTracker()
        tracker.start("running")
        # Don't stop it

        breakdown = tracker.get_breakdown()
        # Should not include unstoppped stage
        stages = [b["stage"] for b in breakdown]
        assert "running" not in stages
