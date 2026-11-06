from unittest.mock import Mock

import pytest

from elinaobs import submit_feedback
from elinaobs import runtime


def test_feedback_is_optional_and_uses_the_project_key(monkeypatch):
    sent = Mock(return_value=Mock())
    monkeypatch.setattr(runtime, "put", sent)
    monkeypatch.setattr(runtime, "flush", lambda: True)

    submit_feedback("a" * 32, "bad", "  Wrong answer  ")

    sent.assert_called_once_with(
        f"http://localhost:3000/v1/traces/{'a' * 32}/feedback",
        headers={"Authorization": "Bearer test"},
        json={"verdict": "bad", "note": "Wrong answer"},
        timeout=5,
    )
    sent.return_value.raise_for_status.assert_called_once()
    sent.reset_mock()
    submit_feedback("a" * 32, "good")
    assert sent.call_args.kwargs["json"] == {"verdict": "good", "note": None}


def test_feedback_rejects_invalid_values_before_sending(monkeypatch):
    sent = Mock()
    monkeypatch.setattr(runtime, "put", sent)
    with pytest.raises(ValueError):
        submit_feedback("bad-id", "good")
    with pytest.raises(ValueError):
        submit_feedback("a" * 32, "maybe")
    with pytest.raises(ValueError):
        submit_feedback("a" * 32, "good", "x" * 2001)
    sent.assert_not_called()


def test_feedback_waits_for_trace_export(monkeypatch):
    sent = Mock()
    monkeypatch.setattr(runtime, "put", sent)
    monkeypatch.setattr(runtime, "flush", lambda: False)
    with pytest.raises(RuntimeError, match="Trace export failed"):
        submit_feedback("a" * 32, "good")
    sent.assert_not_called()
