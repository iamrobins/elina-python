# Elina Python SDK

Python tracing SDK for self-hosted Elina. Licensed under MIT.

## Install

```bash
python -m pip install elinaobs
```

For development from this repository:

```bash
python -m pip install -e '.[dev]'
pytest -q
```

## Public API

```python
from elinaobs import init, trace, flush, shutdown, diagnose, submit_feedback

init(api_key="...", endpoint="http://localhost:3000/v1/traces", service_name="my-agent")

@trace(name="Agent", as_type="agent")
async def run(question):
    return await your_code(question)

# The existing OTel-instrumented operations called inside run() are children.
```

Application feedback is optional. After a trace has finished, an app with a verdict can send it using the same project key. Inside a decorated function, capture the trace ID and keep it with the result:

```python
from opentelemetry import trace as otel_trace
trace_id = f"{otel_trace.get_current_span().get_span_context().trace_id:032x}"
# Later, after the traced function returns:
submit_feedback(trace_id, "bad", note="Wrong answer")  # trace_id is 32 lowercase hex characters
```

Apps without a feedback signal do not call this function. Feedback is stored separately from the dashboard's human review. Keep the project key in server-side code, not in a browser.

To send a demo trace to the local Elina server, create a project in the dashboard and copy its one-time ingestion key. Then, from this directory in PowerShell:

```powershell
$env:ELINA_WRITE_KEY = "paste-project-ingestion-key"
$env:ELINA_BASE_URL = "http://127.0.0.1:3000"
python examples/agent.py
```

The script prints the trace ID and reports whether export succeeded. Open the project’s Traces page and select that ID to inspect the three spans and their captured input/output.

Only operations that are explicitly decorated or already instrumented by a compatible OpenTelemetry instrumentation package create spans. **No framework integrations are installed, imported, or configured by Elina.**

The Elina receiver lives in the `iamrobins/elina` repository. Start it before running `examples/agent.py`. The default tests use in-memory and local HTTP receivers.

To also verify export through a real OpenTelemetry Collector, set `OTELCOL_BINARY` to the Collector executable path and run `python -m pytest -q tests/test_collector.py`. This optional test starts a local Collector with a file exporter and checks the received spans.

## What it does

- Sync + async function decorator with native OTel parent context.
- 10 span display classifications using `elinaobs.observation.type`.
- Selective export: only spans starting inside a `@trace()` scope.
- OTLP/HTTP protobuf, bearer-token auth, background batching.
- Optional bounded input/output capture, disabled by default.
- An optional `redact` callback can remove secrets from captured free text before export.
- `attribute_allowlist` and `attribute_denylist` filter span, event, and link attributes in Elina exports; the denylist wins when both contain a key.
- Exceptions automatically record OTel error status/events.
- Shares an existing OpenTelemetry SDK TracerProvider when present.
- `flush()` reports failed export batches or dropped spans. `diagnose()` returns `failed_batches`, `dropped_spans`, and `retry_attempts` without exposing credentials. Drop counts are updated after a successful processor flush; retry attempts count extra HTTP requests made for a batch.

## Non-goals for v0.1

- Framework adapters or `integrations=[...]`.
- Raw threads, multiprocessing, distributed orchestration, or generator tracing.
- Automatic patching of uninstrumented Python libraries.
- Prompt management, evaluations, or server/UI implementation.

## Known limitations before production

- SDK processor cannot modify existing OTel provider sampling or resources.
- Capture filtering uses a ContextVar marker; parent spans begun before a
  decorator scope are not exported to Elina unless also eligible.
- `as_type="event"` is a timed span category, not an OTel instant event.
- Incoming external spans from `opentelemetry-instrument` share global provider
  and may require controlling initialization order.
- Bounded batches can drop data on overload. `dropped_spans` is current only
  after `flush()` or `shutdown()`. `retry_attempts` is `None` when an OpenTelemetry
  credential-provider session is configured. Export failures remain counted
  even if later batches succeed.
- Input/output redaction is best-effort only. Explicitly inspect anything you
  opt in to collect.
- Attribute lists do not change an application's other OpenTelemetry exporters
  or resource metadata. Keys are matched exactly.
- `shutdown()` ends only Elina's processor. Do not reinitialize the SDK in
  the same interpreter after shutdown.

See [docs/LLD.md](docs/LLD.md) for the finalized architecture and build checklist.
