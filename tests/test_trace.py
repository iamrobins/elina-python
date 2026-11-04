import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
import requests
from opentelemetry import trace as otel_trace
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from elinaobs import trace
from elinaobs import runtime


def test_parent_child_and_unrelated_span_are_filtered(tracer_setup):
    raw = otel_trace.get_tracer("another.library")
    with raw.start_as_current_span("unrelated"):
        pass

    @trace(name="outer", as_type="agent")
    def outer():
        with raw.start_as_current_span("instrumented-child"):
            pass
        return inner()

    @trace(name="inner", as_type="tool")
    def inner():
        return 42

    assert outer() == 42
    spans = tracer_setup.get_finished_spans()
    assert {s.name for s in spans} == {"outer", "inner", "instrumented-child"}
    by_name = {s.name: s for s in spans}
    outer_id = by_name["outer"].context.span_id
    assert by_name["inner"].parent.span_id == outer_id
    assert by_name["instrumented-child"].parent.span_id == outer_id
    assert by_name["outer"].attributes["elinaobs.observation.type"] == "agent"


@pytest.mark.asyncio
async def test_async_tasks_inherit_parent(tracer_setup):
    @trace(name="task", as_type="tool")
    async def task(i):
        await asyncio.sleep(0)
        return i

    @trace(name="root", as_type="agent")
    async def root():
        return await asyncio.gather(task(1), task(2))

    assert await root() == [1, 2]
    spans = tracer_setup.get_finished_spans()
    root_span = next(s for s in spans if s.name == "root")
    children = [s for s in spans if s.name == "task"]
    assert len(children) == 2
    assert all(s.parent.span_id == root_span.context.span_id for s in children)


def test_uncaught_exception_records_failure(tracer_setup):
    @trace
    def broken():
        raise ValueError("test failure")

    with pytest.raises(ValueError):
        broken()
    span = tracer_setup.get_finished_spans()[0]
    assert span.status.status_code.name == "ERROR"
    assert any(e.name == "exception" for e in span.events)


def test_capture_disabled_by_default(tracer_setup):
    @trace(name="private")
    def fn(password: str):
        return password

    fn("password-123")
    assert "elinaobs.input" not in tracer_setup.get_finished_spans()[0].attributes
    assert "elinaobs.output" not in tracer_setup.get_finished_spans()[0].attributes


def test_capture_can_be_enabled(tracer_setup, monkeypatch):
    monkeypatch.setattr(runtime, "_config", runtime.Config(
        api_key="test", capture_input=True, capture_output=True
    ))

    @trace
    def fn(password: str, question: str):
        return "ok"

    fn("secret", "hi")
    span = tracer_setup.get_finished_spans()[0]
    assert "<redacted>" in span.attributes["elinaobs.input"]
    assert "hi" in span.attributes["elinaobs.input"]
    assert span.attributes["elinaobs.output"] == '"ok"'


def test_reject_generator_functions():
    with pytest.raises(TypeError):
        @trace
        def stream():
            yield "token"


@pytest.mark.parametrize("capture_input", [False, True])
def test_builtin_without_signature_can_be_traced(tracer_setup, monkeypatch, capture_input):
    monkeypatch.setattr(runtime, "_config", runtime.Config(api_key="test", capture_input=capture_input))
    traced_max = trace(max)
    assert traced_max(1, 2) == 2
    span = tracer_setup.get_finished_spans()[0]
    assert span.name == "max"
    assert "elinaobs.input" not in span.attributes


def test_existing_requests_instrumentation_is_captured(tracer_setup):
    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    instrumentor = RequestsInstrumentor()
    instrumentor.instrument()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        requests.get(url, timeout=2).raise_for_status()

        @trace(name="agent")
        def agent():
            requests.get(url, timeout=2).raise_for_status()

        agent()
        spans = tracer_setup.get_finished_spans()
        assert len(spans) == 2
        root = next(span for span in spans if span.name == "agent")
        child = next(span for span in spans if span.name != "agent")
        assert child.parent.span_id == root.context.span_id
        assert child.context.trace_id == root.context.trace_id
    finally:
        instrumentor.uninstrument()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
