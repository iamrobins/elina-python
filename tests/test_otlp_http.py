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

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def test_otlp_http_endpoint_bearer_auth_and_protobuf():
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["content-length"]))
            received.append((self.path, self.headers, body))
            self.send_response(200)
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
from elinaobs import init, trace, flush
init(api_key="test-token", endpoint="http://127.0.0.1:{port}/v1/traces",
     service_name="smoke-test")
@trace(name="agent", as_type="agent")
def agent():
    with otel_trace.get_tracer("some.library").start_as_current_span("child"):
        pass
agent()
assert flush(timeout_millis=10000)
'''
        repo = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo / "src")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=20, env=env,
        )
        assert completed.returncode == 0, completed.stderr
        assert len(received) == 1
        path, headers, body = received[0]
        assert path == "/v1/traces"
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"].startswith("application/x-protobuf")
        request = ExportTraceServiceRequest()
        request.ParseFromString(body)
        names = [
            s.name
            for resource in request.resource_spans
            for scope in resource.scope_spans
            for s in scope.spans
        ]
        assert sorted(names) == ["agent", "child"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
