"""Optional smoke test against a real OpenTelemetry Collector binary."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


def test_real_collector_accepts_otlp_http():
    binary = os.environ.get("OTELCOL_BINARY")
    if not binary:
        pytest.skip("set OTELCOL_BINARY to run the real Collector test")

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "traces.json"
        config = Path(directory) / "collector.yaml"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        config.write_text(f"""
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:{port}
exporters:
  file:
    path: {output.as_posix()}
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [file]
""", encoding="utf-8")
        collector = subprocess.Popen(
            [binary, "--config", str(config)], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        try:
            for _ in range(50):
                if collector.poll() is not None:
                    raise AssertionError(f"Collector exited: {collector.stdout.read()}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Collector did not start")

            script = f'''
from elinaobs import init, trace, flush
from opentelemetry import trace as otel_trace
init(api_key="test-token", endpoint="http://127.0.0.1:{port}/v1/traces")
@trace(name="agent", as_type="agent")
def agent():
    with otel_trace.get_tracer("some.library").start_as_current_span("child"):
        pass
agent()
assert flush(timeout_millis=10000)
'''
            result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
            assert result.returncode == 0, result.stderr
            for _ in range(50):
                if output.exists() and output.stat().st_size:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Collector did not export the trace")
            batches = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            names = [
                span["name"] for batch in batches for resource in batch["resourceSpans"]
                for scope in resource["scopeSpans"] for span in scope["spans"]
            ]
            assert sorted(names) == ["agent", "child"]
        finally:
            collector.terminate()
            collector.communicate(timeout=5)
