from examples.observation_types import run
from elinaobs.types import OBSERVATION_TYPES


def test_demo_emits_every_observation_type_in_one_trace(tracer_setup):
    assert run() == "answer ready"
    spans = tracer_setup.get_finished_spans()
    assert len(spans) == len(OBSERVATION_TYPES)
    assert {span.attributes["elinaobs.observation.type"] for span in spans} == OBSERVATION_TYPES
    root = next(span for span in spans if span.parent is None)
    assert all(span.context.trace_id == root.context.trace_id for span in spans)
    assert all(span.parent.span_id == root.context.span_id for span in spans if span is not root)
