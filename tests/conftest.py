import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from elinaobs import runtime
from elinaobs.processing import ScopedSpanProcessor


@pytest.fixture(scope="session")
def tracer_setup():
    provider = TracerProvider()
    otel_trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(ScopedSpanProcessor(SimpleSpanProcessor(exporter)))
    return exporter


@pytest.fixture(autouse=True)
def configured(tracer_setup, monkeypatch):
    tracer_setup.clear()
    monkeypatch.setattr(runtime, "_config", runtime.Config(api_key="test"))
    monkeypatch.setattr(runtime, "_closed", False)
    yield
    tracer_setup.clear()
