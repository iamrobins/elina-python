"""Opt-in SDK to backend check against the local Compose stack."""

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

import requests
from opentelemetry import trace as otel_trace
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest, ExportTraceServiceResponse

from elinaobs import diagnose, flush, init, trace


def test_sdk_batch_and_concurrent_ingestion():
    base = os.environ["ELINA_BASE_URL"]
    admin = {"Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}"}
    project = requests.post(f"{base}/api/projects", headers=admin, json={"name": "sdk-live-check", "retentionDays": 1}, timeout=10)
    project.raise_for_status()
    project_id = project.json()["project"]["id"]
    key = project.json()["writeKey"]
    captured = []
    original_request = requests.Session.request

    def capture(self, method, url, **kwargs):
        response = original_request(self, method, url, **kwargs)
        if url == f"{base}/v1/traces":
            captured.append((kwargs["data"], response))
        return response

    with patch.object(requests.Session, "request", capture):
        init(api_key=key, endpoint=f"{base}/v1/traces", service_name="sdk-live-check")

        @trace(name="agent", as_type="agent")
        def agent():
            with otel_trace.get_tracer("sdk-live-check").start_as_current_span("child") as child:
                child.set_attribute("gen_ai.request.model", "check-model")

        agent()
        assert flush(timeout_millis=10000)
    assert diagnose() == {"failed_batches": 0, "dropped_spans": 0, "retry_attempts": 0}
    assert len(captured) == 1
    body, response = captured[0]
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/x-protobuf")
    ExportTraceServiceResponse().ParseFromString(response.content)
    batch = ExportTraceServiceRequest.FromString(body)
    spans = [span for resource in batch.resource_spans for scope in resource.scope_spans for span in scope.spans]
    assert sorted(span.name for span in spans) == ["agent", "child"]
    root = next(span for span in spans if span.name == "agent")
    child = next(span for span in spans if span.name == "child")
    assert child.parent_span_id == root.span_id
    assert all(span.end_time_unix_nano >= span.start_time_unix_nano > 0 for span in spans)

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/x-protobuf"}
    detail = requests.get(f"{base}/api/traces/{root.trace_id.hex()}", headers=admin, params={"projectId": project_id}, timeout=10)
    detail.raise_for_status()
    stored = detail.json()["spans"]
    assert len(stored) == 2
    stored_child = next(span for span in stored if span["name"] == "child")
    assert stored_child["parentSpanId"] == root.span_id.hex()
    assert stored_child["attributes"]["gen_ai.request.model"] == {"stringValue": "check-model"}
    assert stored_child["resourceAttributes"]["service.name"] == {"stringValue": "sdk-live-check"}
    assert stored_child["scope"]["name"]
    assert requests.post(f"{base}/v1/traces", headers=headers, data=body, timeout=10).status_code == 200

    def send(index):
        duplicate = deepcopy(batch)
        trace_id = index.to_bytes(16, "big")
        for resource in duplicate.resource_spans:
            for scope in resource.scope_spans:
                for span in scope.spans:
                    span.trace_id = trace_id
        return requests.post(f"{base}/v1/traces", headers=headers, data=duplicate.SerializeToString(), timeout=20).status_code

    with ThreadPoolExecutor(max_workers=32) as pool:
        statuses = list(pool.map(send, range(1, 101)))
    assert statuses == [200] * 100
    metrics = requests.get(f"{base}/api/metrics/summary", headers=admin, params={"projectId": project_id}, timeout=10)
    metrics.raise_for_status()
    assert metrics.json()["traceCount"] == 101
    assert metrics.json()["inputTokens"] == "0"


if __name__ == "__main__":
    test_sdk_batch_and_concurrent_ingestion()
    print("SDK batch, stored fields, duplicate replay, and 100 traces at 32 workers passed")
