# ElinaObs Python SDK v0.1 — Low-Level Design (Locked)

## Scope

Decorate arbitrary sync and async Python code. Every OTel-instrumented span
started while that code executes can be exported as a nested span. Do not
implement vendor/framework-specific integrations. Do not design server/UI.

## Public API

```python
init(api_key, endpoint, service_name, capture_input=False,
     capture_output=False, max_content_chars=4000, redact=None,
     attribute_allowlist=None, attribute_denylist=())
@trace
@trace()
@trace(name='Research Agent', as_type='agent')
flush(timeout_millis=5000) -> bool
diagnose() -> dict[str, int | None]
shutdown() -> None
```

Types: `span`, `event`, `generation`, `agent`, `tool`, `chain`, `retriever`,
`evaluator`, `embedding`, `guardrail`.

## Ownership

- OpenTelemetry: span IDs, trace IDs, parentage, context propagation,
  exception events, span timestamps and status.
- ElinaObs: ergonomic decorator, semantic type attribute, optional bounded
  payload capture, selection of exported spans, OTLP exporter configuration.
- Existing instrumentation (when installed by the application): model/tool
  details and LLM-specific GenAI semantic conventions.

## Lifecycle

1. `init()` registers a `ScopedSpanProcessor` wrapping OTel `BatchSpanProcessor`.
2. `@trace` reads runtime config and enables a `ContextVar` capture scope.
3. The OTel tracer creates an `INTERNAL` span with `elinaobs.observation.type`.
4. OTel makes the span active and handles hierarchy of nested spans.
5. `ScopedSpanProcessor.on_start` remembers eligible span IDs while the marker
   is enabled. This captures compatible third-party OTel spans as well.
6. Function completes; optional output is stored; OTel handles exception and
   status automatically; scope is restored in `finally`.
7. Processor receives `on_end` and queues eligible spans into the batch export.
8. OTLP/HTTP protobuf exporter transmits to the configured full traces URL.

## Existing global providers

- When global OTel provider is still a proxy, ElinaObs installs a SDK provider.
- When it is an OpenTelemetry SDK TracerProvider, ElinaObs adds a processor.
- When it is incompatible, fail with a clear error and do not overwrite it.
- `init()` is idempotent for matching settings, rejects conflicting settings.
- The selective exporter does not govern an application's other exporters.

## Semantic mapping

- `elinaobs.observation.type` always holds the application's semantic type.
- `SpanKind.INTERNAL` is used for decorated Python functions, regardless of
  their semantic type; the type is not an OTel SpanKind.
- `elinaobs.input` / `elinaobs.output` are optional truncated JSON string attrs.
- Preserve other OTel attributes, including existing `gen_ai.*` metadata.
- `as_type='event'` remains a duration-based span in v0.1.

## Testable invariants

- An unrelated global OTel span is not sent to ElinaObs.
- Decorated root and child spans share one trace ID, correct parent IDs.
- Sync recursion and async gather create correct independent child spans.
- Exceptions re-raise and mark span ERROR.
- Input/output contents never export unless explicitly opted in.
- Unknown objects are not introspected by default.
- Span activation/restoration is correct on success and failure.
- `init` never silently replaces a compatible existing SDK provider.
- Short-lived scripts may call `flush()`.

## What to build next in the SDK (before production)

1. `diagnose()` exposes final exporter batch failures, flush-time queue drops,
   and HTTP retry attempts without logging credentials. Retry counting uses
   the exporter's public session hook; it is unavailable when an application
   configures an OpenTelemetry credential-provider session.
2. In-process receiver tests verify endpoint, headers, protobuf shape and retry
   behavior. An optional test also verifies receipt through a real Collector.
3. Test with standard third-party OTel instrumentation already registered.
4. Add privacy controls (attribute allow/deny list, stronger redaction hooks).
5. Test multiple Python versions and supported OTel releases, including
   global-provider bootstrap order.
6. Adopt OpenTelemetry `gen_ai.*` attributes from upstream instrumentation
   without requiring frameworks in ElinaObs itself.

The above are engineering-hardening tasks, not invitations to add product
features or framework-specific integration code.
