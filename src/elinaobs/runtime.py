"""SDK lifecycle and standard OTLP export configuration."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from threading import Lock, RLock
from typing import Callable, Literal

from requests import Session, put
from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
from opentelemetry.trace import ProxyTracerProvider

from .processing import ScopedSpanProcessor


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    endpoint: str = "http://localhost:3000/v1/traces"
    service_name: str = "python-app"
    capture_input: bool = False
    capture_output: bool = False
    max_content_chars: int = 4000
    redact: Callable[[str], str] | None = field(default=None, repr=False)
    attribute_allowlist: tuple[str, ...] | None = None
    attribute_denylist: tuple[str, ...] = ()


class _AttributeView:
    def __init__(self, original, attributes) -> None:
        self._original = original
        self.attributes = attributes

    def __getattr__(self, name):
        return getattr(self._original, name)


class _CountingSession(Session):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def request(self, *args, **kwargs):
        self.attempts += 1
        return super().request(*args, **kwargs)


class _TrackingExporter(OTLPSpanExporter):
    def __init__(self, *, attribute_allowlist=None, attribute_denylist=(), **kwargs) -> None:
        # Preserve an OTel credential-provider session when the application configured one.
        self._counting_session = (
            None if os.getenv("OTEL_PYTHON_EXPORTER_OTLP_HTTP_TRACES_CREDENTIAL_PROVIDER") else _CountingSession()
        )
        super().__init__(session=self._counting_session, **kwargs)
        self._lock = Lock()
        self.failed_batches = 0
        self.attempted_spans = 0
        self.retry_attempts = None if self._counting_session is None else 0
        self._allowlist = None if attribute_allowlist is None else set(attribute_allowlist)
        self._denylist = set(attribute_denylist)

    def _filter(self, value):
        return _AttributeView(value, {
            key: item for key, item in (value.attributes or {}).items()
            if (self._allowlist is None or key in self._allowlist) and key not in self._denylist
        })

    def export(self, spans):
        with self._lock:
            self.attempted_spans += len(spans)
        before = self._counting_session.attempts if self._counting_session is not None else 0
        try:
            if self._allowlist is not None or self._denylist:
                filtered = []
                for span in spans:
                    view = self._filter(span)
                    view.events = tuple(self._filter(event) for event in span.events)
                    view.links = tuple(self._filter(link) for link in span.links)
                    filtered.append(view)
                spans = filtered
            result = super().export(spans)
        except Exception:
            with self._lock:
                self.failed_batches += 1
            raise
        finally:
            if self._counting_session is not None:
                with self._lock:
                    self.retry_attempts += max(0, self._counting_session.attempts - before - 1)
        if result != SpanExportResult.SUCCESS:
            with self._lock:
                self.failed_batches += 1
        return result


_lock = RLock()
_config: Config | None = None
_processor: ScopedSpanProcessor | None = None
_exporter: _TrackingExporter | None = None
_owned_provider: TracerProvider | None = None
_closed = False
# shortcut: drop counts update only after flush, use processor metrics when supported across OTel versions.
_dropped_spans = 0


def get_config() -> Config:
    if _config is None:
        raise RuntimeError("Elina is not initialized. Call elinaobs.init(...) before executing @trace functions.")
    if _closed:
        raise RuntimeError("Elina has been shut down; restart the process before using it again.")
    return _config


def init(
    *,
    api_key: str,
    endpoint: str = "http://localhost:3000/v1/traces",
    service_name: str = "python-app",
    capture_input: bool = False,
    capture_output: bool = False,
    max_content_chars: int = 4000,
    redact: Callable[[str], str] | None = None,
    attribute_allowlist: tuple[str, ...] | None = None,
    attribute_denylist: tuple[str, ...] = (),
) -> None:
    """Register a selective OTel processor, preserving existing exporters.

    The endpoint is the full OTLP/HTTP traces URL, not just the server base.
    """
    global _config, _processor, _exporter, _owned_provider
    if not api_key or not api_key.strip():
        raise ValueError("api_key must not be empty")
    if not endpoint.startswith(("https://", "http://")):
        raise ValueError("endpoint must be an HTTP(S) URL")
    if max_content_chars < 100:
        raise ValueError("max_content_chars must be >= 100")
    if redact is not None and not callable(redact):
        raise ValueError("redact must be callable")
    if isinstance(attribute_allowlist, str) or isinstance(attribute_denylist, str):
        raise ValueError("attribute lists must contain nonempty strings")
    allowlist = None if attribute_allowlist is None else tuple(attribute_allowlist)
    denylist = tuple(attribute_denylist)
    for keys in (allowlist, denylist):
        if keys is not None and any(not isinstance(key, str) or not key for key in keys):
            raise ValueError("attribute lists must contain nonempty strings")
    config = Config(
        api_key, endpoint, service_name, capture_input, capture_output, max_content_chars,
        redact, allowlist, denylist,
    )
    with _lock:
        if _closed:
            raise RuntimeError("Elina was shut down. A fresh process is required for reinitialization.")
        if _config is not None:
            if _config == config:
                return  # idempotent init
            raise RuntimeError("Elina has already been initialized with different settings")
        provider = otel_trace.get_tracer_provider()
        if isinstance(provider, ProxyTracerProvider):
            owned = TracerProvider(resource=Resource.create({"service.name": service_name}))
            otel_trace.set_tracer_provider(owned)
            provider = otel_trace.get_tracer_provider()
            if provider is not owned:
                raise RuntimeError("Could not register Elina tracer provider: another provider was installed")
            _owned_provider = owned
        if not isinstance(provider, TracerProvider):
            raise RuntimeError(
                "Existing global OTel provider does not support SDK span processors. "
                "Use an OpenTelemetry SDK TracerProvider before elinaobs.init()."
            )
        exporter = _TrackingExporter(
            endpoint=endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
            attribute_allowlist=config.attribute_allowlist,
            attribute_denylist=config.attribute_denylist,
        )
        batch = BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=256,
            schedule_delay_millis=1000,
        )
        processor = ScopedSpanProcessor(batch)
        provider.add_span_processor(processor)
        _exporter = exporter
        _processor = processor
        _config = config


def flush(timeout_millis: int = 5000) -> bool:
    """Flush Elina's exporter; report failed batches or dropped spans."""
    global _dropped_spans
    processor = _processor
    if processor is None:
        return True
    if not processor.force_flush(timeout_millis):
        return False
    exporter = _exporter
    assert exporter is not None
    with _lock, exporter._lock:
        _dropped_spans = max(_dropped_spans, processor.flushed_spans - exporter.attempted_spans)
        return exporter.failed_batches == 0 and _dropped_spans == 0


def submit_feedback(trace_id: str, verdict: Literal["good", "bad"], note: str | None = None) -> None:
    """Optionally attach application feedback to an exported trace."""
    config = get_config()
    if not isinstance(trace_id, str) or not re.fullmatch(r"[0-9a-f]{32}", trace_id):
        raise ValueError("trace_id must be 32 lowercase hex characters")
    if verdict not in ("good", "bad"):
        raise ValueError("verdict must be 'good' or 'bad'")
    if note is not None and (not isinstance(note, str) or len(note.strip()) > 2000):
        raise ValueError("note must be at most 2000 characters")
    if not flush():
        raise RuntimeError("Trace export failed; feedback was not sent")
    response = put(
        f"{config.endpoint.rstrip('/')}/{trace_id}/feedback",
        headers={"Authorization": f"Bearer {config.api_key}"},
        json={"verdict": verdict, "note": note.strip() or None if note is not None else None},
        timeout=5,
    )
    response.raise_for_status()


def diagnose() -> dict[str, int | None]:
    """Return failure and last-flush drop counts without credentials."""
    exporter = _exporter
    if exporter is None:
        return {"failed_batches": 0, "dropped_spans": 0, "retry_attempts": 0}
    with _lock, exporter._lock:
        return {
            "failed_batches": exporter.failed_batches,
            "dropped_spans": _dropped_spans,
            "retry_attempts": exporter.retry_attempts,
        }


def shutdown() -> None:
    """Close only our processor, not an existing third-party global provider."""
    global _closed
    with _lock:
        if _closed:
            return
        processor = _processor
        if processor is not None:
            flush(timeout_millis=5000)
            processor.shutdown()
        _closed = True
