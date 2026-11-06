"""Send one simulated workflow showing every Elina observation type."""
import os
import time

from opentelemetry import trace as otel_trace

from elinaobs import flush, init, trace


STEPS = (
    ("event", "Question received", "What is Elina?"),
    ("guardrail", "Check request safety", "allowed"),
    ("embedding", "Embed question", "vector ready"),
    ("retriever", "Find documentation", "one relevant document"),
    ("chain", "Build answer context", "context ready"),
    ("tool", "Read project metadata", "project found"),
    ("generation", "Draft answer", "Elina shows how a workflow ran."),
    ("evaluator", "Score answer", "relevant"),
    ("span", "Prepare response", "answer ready"),
)


def step(output: str) -> str:
    time.sleep(0.02)
    return output


@trace(name="Observation Types Demo", as_type="agent")
def run() -> str:
    trace_id = otel_trace.get_current_span().get_span_context().trace_id
    print(f"Trace ID: {trace_id:032x}")
    result = ""
    for as_type, name, output in STEPS:
        result = trace(name=name, as_type=as_type)(step)(output)
    return result


if __name__ == "__main__":
    init(
        api_key=os.environ["ELINA_WRITE_KEY"],
        endpoint=f"{os.getenv('ELINA_BASE_URL', 'http://127.0.0.1:3000').rstrip('/')}/v1/traces",
        service_name="observation-types-demo",
        capture_input=True,
        capture_output=True,
    )
    print(run())
    if not flush(timeout_millis=10000):
        raise SystemExit("Trace export failed; check the server and ELINA_WRITE_KEY")
    print("Trace exported successfully")
