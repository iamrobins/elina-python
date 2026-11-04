"""Run a two-step LLM answer and inspect its nested spans in Elina."""
import os

import requests
from opentelemetry import trace as otel_trace

from elinaobs import flush, init, trace


OPENAI_MODEL = "gpt-6-luna"
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ELINA_WRITE_KEY = os.environ["ELINA_WRITE_KEY"]

init(
    api_key=ELINA_WRITE_KEY,
    endpoint=f"{os.getenv('ELINA_BASE_URL', 'http://127.0.0.1:3000').rstrip('/')}/v1/traces",
    service_name="chain-of-thoughts-demo",
    capture_input=True,
    capture_output=True,
)


def complete(prompt: str) -> str:
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": OPENAI_MODEL, "input": prompt, "reasoning": {"effort": "low"}, "max_output_tokens": 256},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    span = otel_trace.get_current_span()
    span.set_attribute("gen_ai.provider.name", "openai")
    span.set_attribute("gen_ai.request.model", OPENAI_MODEL)
    span.set_attribute("gen_ai.usage.input_tokens", data["usage"]["input_tokens"])
    span.set_attribute("gen_ai.usage.output_tokens", data["usage"]["output_tokens"])
    span.set_attribute("gen_ai.usage.cache_read.input_tokens", data["usage"].get("input_tokens_details", {}).get("cached_tokens", 0))
    if data.get("service_tier"):
        span.set_attribute("openai.response.service_tier", data["service_tier"])
    answer = "".join(
        part["text"]
        for item in data["output"] if item["type"] == "message"
        for part in item["content"] if part["type"] == "output_text"
    ).strip()
    if not answer:
        raise RuntimeError("OpenAI returned no text")
    return answer


@trace(name="Plan Answer", as_type="generation")
def plan(question: str) -> str:
    return complete(f"Give a brief, high-level outline for answering this question. Do not include private reasoning.\n\n{question}")


@trace(name="Write Answer", as_type="generation")
def answer(question: str, outline: str) -> str:
    return complete(f"Answer this question in two concise sentences using the outline.\n\nQuestion: {question}\nOutline: {outline}")


@trace(name="Question Answering", as_type="agent")
def run(question: str) -> str:
    trace_id = otel_trace.get_current_span().get_span_context().trace_id
    print(f"Trace ID: {trace_id:032x}")
    return answer(question, plan(question))


if __name__ == "__main__":
    try:
        print(run("Why are nested spans useful when debugging an LLM application?"))
    finally:
        if not flush(timeout_millis=10000):
            raise SystemExit("Trace export failed; check Elina and ELINA_WRITE_KEY")
    print("Trace exported successfully")
