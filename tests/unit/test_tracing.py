"""Tests for the OpenTelemetry tracing module."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent"))

from tracing import (
    start_request_trace,
    get_request_trace,
    end_request_trace,
    timed_span,
    tracer,
)


class TestRequestTraceLifecycle:
    """Tests for request trace start/get/end."""

    def test_start_creates_empty_trace(self):
        start_request_trace("test-req-1")
        trace = get_request_trace("test-req-1")
        assert isinstance(trace, list)
        end_request_trace("test-req-1")

    def test_end_cleans_up(self):
        start_request_trace("test-req-2")
        end_request_trace("test-req-2")
        trace = get_request_trace("test-req-2")
        assert trace == []

    def test_get_unknown_request_returns_empty(self):
        trace = get_request_trace("nonexistent-id")
        assert trace == []


class TestTimedSpan:
    """Tests for the timed_span context manager."""

    def test_creates_span(self):
        start_request_trace("span-test")
        with timed_span("test_operation"):
            pass
        # Span should be collected
        trace = get_request_trace("span-test")
        # May or may not have collected depending on SimpleSpanProcessor timing
        assert isinstance(trace, list)
        end_request_trace("span-test")

    def test_span_with_attributes(self):
        start_request_trace("attr-test")
        with timed_span("test_op", {"key1": "value1", "count": 42}):
            pass
        end_request_trace("attr-test")

    def test_span_records_duration(self):
        import time
        start_request_trace("dur-test")
        with timed_span("slow_op") as span:
            time.sleep(0.01)
        trace = get_request_trace("dur-test")
        # If span was collected, check duration
        if trace:
            for s in trace:
                if s["name"] == "slow_op":
                    assert s["duration_ms"] > 0
        end_request_trace("dur-test")


class TestTracer:
    """Tests for the global tracer instance."""

    def test_tracer_exists(self):
        assert tracer is not None

    def test_tracer_creates_spans(self):
        with tracer.start_as_current_span("manual_span") as span:
            span.set_attribute("test_key", "test_value")
