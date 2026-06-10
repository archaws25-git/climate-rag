"""ClimateRAG — OpenTelemetry tracing with in-process span collection.

Provides:
  1. OTel TracerProvider with configurable exporters (console, OTLP, X-Ray)
  2. In-memory span collector for Streamlit UI latency breakdown
  3. Helper context managers for clean span creation

Usage:
    from tracing import tracer, get_request_trace

    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("key", "value")
        # ... do work ...

    # After request completes, get the breakdown:
    trace = get_request_trace()
    # Returns: [{"name": "...", "duration_ms": ..., "attributes": {...}}, ...]

Environment variables:
    OTEL_EXPORTER: "console" | "otlp" | "none" (default: "none")
    OTEL_OTLP_ENDPOINT: OTLP collector URL (for "otlp" exporter)
"""

import os
import threading
import time
from contextlib import contextmanager
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

# ── Configuration ─────────────────────────────────────────────────────────────
EXPORTER_TYPE = os.environ.get("OTEL_EXPORTER", "none")
SERVICE_NAME = "climate-rag"

# ── In-Memory Span Collector ──────────────────────────────────────────────────
# Stores completed spans for the current request so Streamlit can display them.
_request_spans: dict[str, list[dict]] = {}
_current_request_id = threading.local()


class _InMemorySpanCollector:
    """Collects completed spans into a thread-local request buffer.

    This allows the Streamlit UI to display a latency breakdown after
    each request without needing an external collector.
    """

    def export(self, spans):
        """Called by OTel SDK when spans complete."""
        req_id = getattr(_current_request_id, "value", None)
        if not req_id:
            return

        if req_id not in _request_spans:
            _request_spans[req_id] = []

        for span in spans:
            duration_ns = span.end_time - span.start_time if span.end_time else 0
            duration_ms = duration_ns / 1_000_000

            _request_spans[req_id].append({
                "name": span.name,
                "duration_ms": round(duration_ms, 1),
                "start_time": span.start_time,
                "attributes": dict(span.attributes) if span.attributes else {},
                "status": span.status.status_code.name if span.status else "UNSET",
                "parent": span.parent.span_id if span.parent else None,
            })


class _InMemoryExporter:
    """OTel-compatible exporter that routes to _InMemorySpanCollector."""

    def __init__(self):
        self._collector = _InMemorySpanCollector()

    def export(self, spans):
        self._collector.export(spans)
        return True

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=None):
        pass


# ── TracerProvider Setup ──────────────────────────────────────────────────────
_resource = Resource.create({"service.name": SERVICE_NAME})
_provider = TracerProvider(resource=_resource)

# Always add in-memory collector (for Streamlit UI)
_memory_exporter = _InMemoryExporter()
_provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))

# Optionally add console or OTLP exporter
if EXPORTER_TYPE == "console":
    _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
elif EXPORTER_TYPE == "otlp":
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        endpoint = os.environ.get("OTEL_OTLP_ENDPOINT", "http://localhost:4317")
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    except ImportError:
        pass

trace.set_tracer_provider(_provider)

# The main tracer instance used throughout the app
tracer = trace.get_tracer("climate_rag", "1.0.0")


# ── Request Lifecycle Helpers ─────────────────────────────────────────────────
def start_request_trace(request_id: str):
    """Begin collecting spans for a new request."""
    _current_request_id.value = request_id
    _request_spans[request_id] = []


def get_request_trace(request_id: Optional[str] = None) -> list[dict]:
    """Get collected spans for a request, sorted by start time.

    Returns a flat list of span dicts with name, duration_ms, and attributes.
    """
    req_id = request_id or getattr(_current_request_id, "value", None)
    if not req_id or req_id not in _request_spans:
        return []

    spans = sorted(_request_spans[req_id], key=lambda s: s.get("start_time", 0))
    return spans


def end_request_trace(request_id: Optional[str] = None):
    """Clean up spans for a completed request (call after UI displays them)."""
    req_id = request_id or getattr(_current_request_id, "value", None)
    if req_id and req_id in _request_spans:
        del _request_spans[req_id]
    _current_request_id.value = None


# ── Convenience Context Manager ───────────────────────────────────────────────
@contextmanager
def timed_span(name: str, attributes: Optional[dict] = None):
    """Create a span with automatic timing and optional attributes.

    Usage:
        with timed_span("search.embed_query", {"model": "titan-v2"}):
            embedding = embed(query)
    """
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        start = time.perf_counter()
        try:
            yield span
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("duration_ms", round(elapsed_ms, 1))
