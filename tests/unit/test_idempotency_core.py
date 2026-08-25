from app.services.idempotency import request_fingerprint


def test_request_fingerprint_is_canonical_and_opaque() -> None:
    first = request_fingerprint({"content": "비밀", "nested": {"a": 1, "b": 2}})
    second = request_fingerprint({"nested": {"b": 2, "a": 1}, "content": "비밀"})
    changed = request_fingerprint({"content": "다름", "nested": {"a": 1, "b": 2}})

    assert first == second
    assert first != changed
    assert isinstance(first, bytes)
    assert len(first) == 32
    assert "비밀" not in first.hex()
