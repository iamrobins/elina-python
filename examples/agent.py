"""Example. Requires a compatible OTLP receiver at the configured endpoint."""
import asyncio

from elinaobs import flush, init, trace

init(api_key="dev-key", endpoint="http://localhost:3000/v1/traces", service_name="demo-agent")


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
    docs = await search_documents(question)
    return await generate_answer(docs)


if __name__ == "__main__":
    print(asyncio.run(research("How does observability work?")))
    flush()
