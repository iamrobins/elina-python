"""Public domain types; no framework-specific types appear here."""
from typing import Literal

ObservationType = Literal[
    "span",
    "event",
    "generation",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "embedding",
    "guardrail",
]

OBSERVATION_TYPES = frozenset(
    ("span", "event", "generation", "agent", "tool", "chain",
     "retriever", "evaluator", "embedding", "guardrail")
)
