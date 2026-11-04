"""SDK lifecycle and standard OTLP export configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, RLock

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


class _TrackingExporter(OTLPSpanExporter):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lock = Lock()
        self.failed_batches = 0

    def export(self, spans):
        try:
            result = super().export(spans)
        except Exception:
            with self._lock:
                self.failed_batches += 1
            raise
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


def get_config() -> Config:
    if _config is None:
        raise RuntimeError("ElinaObs is not initialized. Call elinaobs.init(...) before executing @trace functions.")
    if _closed:
        raise RuntimeError("ElinaObs has been shut down; restart the process before using it again.")
    return _config


def init(
    *,
    api_key: str,
    endpoint: str = "http://localhost:3000/v1/traces",
    service_name: str = "python-app",
    capture_input: bool = False,
    capture_output: bool = False,
    max_content_chars: int = 4000,
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
    config = Config(api_key, endpoint, service_name, capture_input, capture_output, max_content_chars)
    with _lock:
        if _closed:
            raise RuntimeError("ElinaObs was shut down. A fresh process is required for reinitialization.")
        if _config is not None:
            if _config == config:
                return  # idempotent init
            raise RuntimeError("ElinaObs has already been initialized with different settings")
        provider = otel_trace.get_tracer_provider()
        if isinstance(provider, ProxyTracerProvider):
            owned = TracerProvider(resource=Resource.create({"service.name": service_name}))
            otel_trace.set_tracer_provider(owned)
            provider = otel_trace.get_tracer_provider()
            if provider is not owned:
                raise RuntimeError("Could not register ElinaObs tracer provider: another provider was installed")
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
    """Flush ElinaObs's exporter; report any failed batch since initialization."""
    processor = _processor
    if processor is None:
        return True
    return processor.force_flush(timeout_millis) and diagnose()["failed_batches"] == 0


def diagnose() -> dict[str, int]:
    """Return export failure counts without endpoint or credential details."""
    exporter = _exporter
    if exporter is None:
        return {"failed_batches": 0}
    with exporter._lock:
        return {"failed_batches": exporter.failed_batches}


def shutdown() -> None:
    """Close only our processor, not an existing third-party global provider."""
    global _closed
    with _lock:
        if _closed:
            return
        processor = _processor
        if processor is not None:
            processor.force_flush(timeout_millis=5000)
            processor.shutdown()
        _closed = True
