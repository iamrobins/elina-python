"""End-to-end OTLP/HTTP smoke test with an in-process fake receiver.

A subprocess is used because the OTel global provider is intentionally
single-assignment per Python process.
"""
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


@pytest.mark.parametrize("existing_provider", [False, True])
@pytest.mark.parametrize("retry_first", [False, True])
def test_otlp_http_endpoint_bearer_auth_and_protobuf(existing_provider, retry_first):
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["content-length"]))
            received.append((self.path, self.headers, body))
            self.send_response(503 if retry_first and len(received) == 1 else 200)
            if retry_first and len(received) == 1:
                self.send_header("Retry-After", "0")
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, port = server.server_address
        script = f'''
from opentelemetry import trace as otel_trace
from elinaobs import diagnose, init, trace, flush
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
if {existing_provider}:
    provider = TracerProvider()
    existing_exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(existing_exporter))
    otel_trace.set_tracer_provider(provider)
    with otel_trace.get_tracer("some.library").start_as_current_span("unrelated"):
        pass
init(api_key="test-token", endpoint="http://127.0.0.1:{port}/v1/traces",
     service_name="smoke-test")
init(api_key="test-token", endpoint="http://127.0.0.1:{port}/v1/traces",
     service_name="smoke-test")
try:
    init(api_key="different-token", endpoint="http://127.0.0.1:{port}/v1/traces",
         service_name="smoke-test")
except RuntimeError:
    pass
else:
    raise AssertionError("conflicting init must fail")
if {existing_provider}:
    assert otel_trace.get_tracer_provider() is provider
@trace(name="agent", as_type="agent")
def agent():
    with otel_trace.get_tracer("some.library").start_as_current_span("child") as child:
        child.set_attribute("gen_ai.request.model", "example-model")
agent()
assert flush(timeout_millis=10000)
assert diagnose() == {{"failed_batches": 0}}
if {existing_provider}:
    assert sorted(s.name for s in existing_exporter.get_finished_spans()) == ["agent", "child", "unrelated"]
'''
        repo = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo / "src")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=20, env=env,
        )
        assert completed.returncode == 0, completed.stderr
        assert len(received) == (2 if retry_first else 1)
        assert all(
            request[0] == received[0][0]
            and request[1]["Authorization"] == "Bearer test-token"
            and request[2] == received[0][2]
            for request in received
        )
        path, headers, body = received[-1]
        assert path == "/v1/traces"
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"].startswith("application/x-protobuf")
        request = ExportTraceServiceRequest()
        request.ParseFromString(body)
        spans = [
            span
            for resource in request.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        assert sorted(span.name for span in spans) == ["agent", "child"]
        child = next(span for span in spans if span.name == "child")
        assert any(
            attr.key == "gen_ai.request.model" and attr.value.string_value == "example-model"
            for attr in child.attributes
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_failed_export_is_reported():
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = f'''
from elinaobs import diagnose, flush, init, trace
init(api_key="test-token", endpoint="http://127.0.0.1:{server.server_port}/v1/traces")
@trace
def agent():
    pass
agent()
assert flush(timeout_millis=10000) is False
assert diagnose() == {{"failed_batches": 1}}
assert "test-token" not in repr(diagnose())
'''
        completed = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
