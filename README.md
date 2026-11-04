# ElinaObs Python SDK (v0.1 starter)

An **implementation starter**, not a released SDK. Name `elinaobs` is a placeholder. License is intentionally not selected yet.

## Install

```bash
python -m pip install -e '.[dev]'
pytest -q
```

## Public API

```python
from elinaobs import init, trace, flush, shutdown, diagnose

init(api_key="...", endpoint="http://localhost:3000/v1/traces", service_name="my-agent")

@trace(name="Agent", as_type="agent")
async def run(question):
    return await your_code(question)

# The existing OTel-instrumented operations called inside run() are children.
```

Only operations that are explicitly decorated or already instrumented by a compatible OpenTelemetry instrumentation package create spans. **No framework integrations are installed, imported, or configured by ElinaObs.**

The OTLP receiver is not supplied in this repo; `examples/agent.py` will attempt to send to `localhost:3000/v1/traces` and fail to deliver until a compatible receiver is running. The tests use an in-memory exporter and require no server.

## What it does

- Sync + async function decorator with native OTel parent context.
- 10 span display classifications using `elinaobs.observation.type`.
- Selective export: only spans starting inside a `@trace()` scope.
- OTLP/HTTP protobuf, bearer-token auth, background batching.
- Optional bounded input/output capture, disabled by default.
- An optional `redact` callback can remove secrets from captured free text before export.
- Exceptions automatically record OTel error status/events.
- Shares an existing OpenTelemetry SDK TracerProvider when present.
- `flush()` reports failed export batches; `diagnose()["failed_batches"]` counts final batch failures without exposing credentials. Successful retries are not counted; queue drops are not currently measurable through the batch processor's public API.

## Non-goals for v0.1

- Framework adapters or `integrations=[...]`.
- Raw threads, multiprocessing, distributed orchestration, or generator tracing.
- Automatic patching of uninstrumented Python libraries.
- Prompt management, evaluations, or server/UI implementation.

## Known limitations before production

- SDK processor cannot modify existing OTel provider sampling or resources.
- Capture filtering uses a ContextVar marker; parent spans begun before a
  decorator scope are not exported to ElinaObs unless also eligible.
- `as_type="event"` is a timed span category, not an OTel instant event.
- Incoming external spans from `opentelemetry-instrument` share global provider
  and may require controlling initialization order.
- Bounded batches can drop data on overload; drop and retry counters are not
  exposed yet. Export failures remain counted even if later batches succeed.
- Input/output redaction is best-effort only. Explicitly inspect anything you
  opt in to collect.
- `shutdown()` ends only ElinaObs's processor. Do not reinitialize the SDK in
  the same interpreter after shutdown.

See [docs/LLD.md](docs/LLD.md) for the finalized architecture and build checklist.
