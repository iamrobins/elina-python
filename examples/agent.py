"""Send a small agent trace to a running Elina server."""
import asyncio
import os

from opentelemetry import trace as otel_trace

from elinaobs import flush, init, trace

base_url = os.getenv("ELINA_BASE_URL", "http://localhost:3000").rstrip("/")
init(
    api_key=os.environ["ELINA_WRITE_KEY"],
    endpoint=f"{base_url}/v1/traces",
    service_name="demo-agent",
    capture_input=True,
    capture_output=True,
)


@trace(name="Document Search", as_type="retriever")
async def search_documents(question: str):
    await asyncio.sleep(0.05)
    return ["Excerpt relevant to " + question]


@trace(name="Generate Answer", as_type="generation")
async def generate_answer(docs):
    await asyncio.sleep(0.08)
    return f"Summary of {len(docs)} documents"


@trace(name="Research Agent", as_type="agent")
async def research(question: str):
    trace_id = otel_trace.get_current_span().get_span_context().trace_id
    print(f"Trace ID: {trace_id:032x}")
    docs = await search_documents(question)
    return await generate_answer(docs)


if __name__ == "__main__":
    print(asyncio.run(research("How does observability work?")))
    if not flush(timeout_millis=10000):
        raise SystemExit("Trace export failed; check the server and ELINA_WRITE_KEY")
    print("Trace exported successfully")
