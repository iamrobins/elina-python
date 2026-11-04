"""Selectively forward spans created inside @trace scope to an OTel processor."""
from __future__ import annotations

from threading import Lock

from opentelemetry.sdk.trace import SpanProcessor

from .context import capture_active


class ScopedSpanProcessor(SpanProcessor):
    """Keep our exporter from sending unrelated global OTel spans.

    on_start runs synchronously while the calling ContextVar is available.
    on_end may run after the capture scope has exited, so eligibility is
    remembered by the pair (trace_id, span_id), not re-checked on end.
    """

    def __init__(self, downstream: SpanProcessor) -> None:
        self._downstream = downstream
        self._eligible: set[tuple[int, int]] = set()
        self._lock = Lock()
        self.ended_spans = 0
        self.flushed_spans = 0

    @staticmethod
    def _key(span) -> tuple[int, int]:
        ctx = span.get_span_context()
        return (ctx.trace_id, ctx.span_id)

    def on_start(self, span, parent_context=None) -> None:
        if not capture_active.get():
            return
        key = self._key(span)
        with self._lock:
            self._eligible.add(key)
        self._downstream.on_start(span, parent_context=parent_context)

    def on_end(self, span) -> None:
        key = self._key(span)
        with self._lock:
            if key not in self._eligible:
                return
            self._eligible.remove(key)
            if span.context.trace_flags.sampled:
                self.ended_spans += 1
            self._downstream.on_end(span)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        with self._lock:
            result = self._downstream.force_flush(timeout_millis=timeout_millis)
            if result:
                self.flushed_spans = self.ended_spans
            return result

    def shutdown(self) -> None:
        self._downstream.shutdown()
