from threading import Event, Lock

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from elinaobs import diagnose, flush, runtime
from elinaobs.context import capture_active
from elinaobs.processing import ScopedSpanProcessor


def test_queue_drop_is_counted_after_flush(monkeypatch):
    class BlockingExporter(SpanExporter):
        def __init__(self):
            self.started = Event()
            self.release = Event()
            self._lock = Lock()
            self.attempted_spans = 0
            self.failed_batches = 0
            self.retry_attempts = 0

        def export(self, spans):
            self.started.set()
            assert self.release.wait(5)
            with self._lock:
                self.attempted_spans += len(spans)
            return SpanExportResult.SUCCESS

        def shutdown(self):
            pass

    exporter = BlockingExporter()
    batch = BatchSpanProcessor(exporter, max_queue_size=2, max_export_batch_size=2, schedule_delay_millis=60000)
    processor = ScopedSpanProcessor(batch)
    provider = TracerProvider()
    provider.add_span_processor(processor)
    tracer = provider.get_tracer("test")
    monkeypatch.setattr(runtime, "_exporter", exporter)
    monkeypatch.setattr(runtime, "_processor", processor)
    monkeypatch.setattr(runtime, "_dropped_spans", 0)
    token = capture_active.set(True)
    try:
        for _ in range(2):
            with tracer.start_as_current_span("first"):
                pass
        assert exporter.started.wait(5)
        for _ in range(3):
            with tracer.start_as_current_span("queued"):
                pass
        assert diagnose()["dropped_spans"] == 0
        exporter.release.set()
        assert flush(10000) is False
        assert diagnose() == {"failed_batches": 0, "dropped_spans": 1, "retry_attempts": 0}
    finally:
        capture_active.reset(token)
        exporter.release.set()
        provider.shutdown()


def test_otel_credential_provider_session_is_preserved(monkeypatch):
    sessions = []
    monkeypatch.setenv("OTEL_PYTHON_EXPORTER_OTLP_HTTP_TRACES_CREDENTIAL_PROVIDER", "custom.provider")
    monkeypatch.setattr(OTLPSpanExporter, "__init__", lambda self, **kwargs: sessions.append(kwargs["session"]))
    exporter = runtime._TrackingExporter(endpoint="http://127.0.0.1/v1/traces")
    monkeypatch.setattr(runtime, "_exporter", exporter)
    assert sessions == [None]
    assert diagnose()["retry_attempts"] is None
