from elinaobs.serialization import serialize


def test_unknown_object_never_calls_repr():
    class Dangerous:
        def __repr__(self):
            raise RuntimeError("must never execute")
    assert serialize(Dangerous()) == '"<Dangerous>"'


def test_secrets_and_cycles():
    obj = {"token": "not-exported", "nested": [1]}
    obj["loop"] = obj
    result = serialize(obj)
    assert "not-exported" not in result
    assert "<cycle>" in result


def test_common_credential_key_spellings():
    values = {
        "private_key": "private-value",
        "access-key": "access-value",
        "credentials": "credential-value",
        "apiKey": "api-value",
        "passphrase": "passphrase-value",
        "question": "visible",
    }
    result = serialize(values)
    assert "visible" in result
    assert all(secret not in result for secret in values.values() if secret != "visible")


def test_bounded():
    assert len(serialize("a" * 10000, max_chars=100)) <= 100
