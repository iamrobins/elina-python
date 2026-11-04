"""Bounded host-to-Compose ingestion and acknowledgment check."""

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def main():
    base = os.environ["ELINA_BASE_URL"]
    admin = {"Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}"}
    project = requests.post(f"{base}/api/projects", headers=admin, json={"name": "load-check", "retentionDays": 1}, timeout=10)
    project.raise_for_status()
    project_id = project.json()["project"]["id"]
    key = project.json()["writeKey"]
    prefix = f"{time.time_ns() & ((1 << 64) - 1):016x}"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/x-protobuf"}
    print(f"project={project_id} prefix={prefix}", flush=True)

    def send(index):
        request = ExportTraceServiceRequest()
        span = request.resource_spans.add().scope_spans.add().spans.add()
        span.trace_id = bytes.fromhex(f"{prefix}{index:016x}")
        span.span_id = index.to_bytes(8, "big")
        span.name = "load-check"
        span.start_time_unix_nano = 1_000_000_000
        span.end_time_unix_nano = 2_000_000_000
        try:
            response = requests.post(f"{base}/v1/traces", headers=headers, data=request.SerializeToString(), timeout=20)
            return response.status_code
        except requests.RequestException as error:
            return type(error).__name__

    outcomes = {}
    for start in range(1, 1001, 200):
        with ThreadPoolExecutor(max_workers=32) as pool:
            outcomes.update(zip(range(start, start + 200), pool.map(send, range(start, start + 200))))
        # A delayed commit after a client timeout is allowed; a 200 without its row is not.
        rows = subprocess.check_output([
            "wsl.exe", "-u", "root", "--", "docker", "compose", "exec", "-T", "postgres",
            "psql", "-U", "elina", "-d", "elina", "-At", "-c",
            f"SELECT trace_id FROM spans WHERE project_id = '{project_id}' AND trace_id LIKE '{prefix}%';",
        ], cwd=os.environ["ELINA_SERVER_DIR"], text=True).splitlines()
        stored = {int(row[16:], 16) for row in rows}
        acknowledged = {index for index, status in outcomes.items() if status == 200}
        missing = sorted(acknowledged - stored)
        counts = {str(status): list(outcomes.values()).count(status) for status in set(outcomes.values())}
        print(f"through={start + 199} responses={counts} stored={len(stored)} false_ack={missing}", flush=True)
        assert not missing, "HTTP 200 acknowledged an absent trace"
    assert all(status == 200 for status in outcomes.values()), "load check had non-200 responses or timeouts"
    assert len(stored) == 1000, "load check lost a span"


if __name__ == "__main__":
    main()
