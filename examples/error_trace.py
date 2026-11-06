"""Send a nested trace with one failed tool for the Jump to error demo."""
import os

from opentelemetry import trace as otel_trace

from elinaobs import flush, init, trace


@trace(name="Fetch knowledge base", as_type="tool")
def fetch_context() -> str:
    raise RuntimeError("Demo tool failure: knowledge base timed out")


@trace(name="Find answer context", as_type="chain")
def find_context() -> str:
    try:
        return fetch_context()
    except RuntimeError:
        return "Fallback context"


@trace(name="Compose fallback answer", as_type="generation")
def compose_answer(context: str) -> str:
    return f"Answer prepared from {context.lower()}"


@trace(name="Error Navigation Demo", as_type="agent")
def run() -> str:
    trace_id = otel_trace.get_current_span().get_span_context().trace_id
    print(f"Trace ID: {trace_id:032x}")
    return compose_answer(find_context())


if __name__ == "__main__":
    init(
        api_key=os.environ["ELINA_WRITE_KEY"],
        endpoint=f"{os.getenv('ELINA_BASE_URL', 'http://127.0.0.1:3000').rstrip('/')}/v1/traces",
        service_name="error-navigation-demo",
    )
    print(run())
    if not flush(timeout_millis=10000):
        raise SystemExit("Trace export failed; check the server and ELINA_WRITE_KEY")
    print("Trace exported successfully. Open this trace and click Jump to error.")
