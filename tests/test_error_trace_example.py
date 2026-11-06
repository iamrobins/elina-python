from examples.error_trace import run


def test_error_demo_keeps_failed_tool_inside_successful_workflow(tracer_setup):
    assert run() == "Answer prepared from fallback context"
    spans = {span.name: span for span in tracer_setup.get_finished_spans()}
    assert set(spans) == {"Error Navigation Demo", "Find answer context", "Fetch knowledge base", "Compose fallback answer"}
    assert spans["Fetch knowledge base"].status.status_code.name == "ERROR"
    assert "knowledge base timed out" in spans["Fetch knowledge base"].status.description
    assert all(span.status.status_code.name != "ERROR" for name, span in spans.items() if name != "Fetch knowledge base")
