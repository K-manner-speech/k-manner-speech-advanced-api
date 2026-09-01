from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.routers.media import stream_audio
from app.services import tts_streaming
from app.services.tts_streaming import TTSStreamRepository, iter_tts_pcm


class TrackingSession:
    def __init__(self, factory: TrackingSessionFactory) -> None:
        self._factory = factory

    def __enter__(self) -> TrackingSession:
        self._factory.active += 1
        self._factory.peak = max(self._factory.peak, self._factory.active)
        return self

    def __exit__(self, *args: object) -> None:
        self._factory.active -= 1


class TrackingSessionFactory:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    def __call__(self) -> TrackingSession:
        return TrackingSession(self)


def test_stream_target_lookup_closes_session_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = TrackingSessionFactory()
    expected = {"id": uuid4(), "processing_token": uuid4(), "generation_status": "processing"}

    def resolve(
        _repository: TTSStreamRepository, _user_id: UUID, _message_id: UUID
    ) -> dict[str, Any]:
        assert factory.active == 1
        return expected

    monkeypatch.setattr(TTSStreamRepository, "resolve", resolve)
    lookup = getattr(tts_streaming, "resolve_tts_stream_target", None)

    assert lookup is not None, "short-lived TTS target lookup helper is missing"
    assert lookup(factory, uuid4(), uuid4()) == expected
    assert factory.active == 0


def test_stream_target_lookup_closes_session_when_repository_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = TrackingSessionFactory()

    def resolve(_repository: TTSStreamRepository, _user_id: UUID, _message_id: UUID) -> None:
        assert factory.active == 1
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(TTSStreamRepository, "resolve", resolve)
    lookup = getattr(tts_streaming, "resolve_tts_stream_target", None)

    assert lookup is not None, "short-lived TTS target lookup helper is missing"
    with pytest.raises(RuntimeError, match="lookup failed"):
        lookup(factory, uuid4(), uuid4())
    assert factory.active == 0


def test_stream_route_does_not_accept_request_scoped_database_session() -> None:
    assert "session" not in inspect.signature(stream_audio).parameters


class FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def mappings(self) -> FakeResult:
        return self

    def __iter__(self) -> Iterator[dict[str, Any]]:
        assert isinstance(self._value, list)
        return iter(self._value)

    def one_or_none(self) -> dict[str, Any] | None:
        assert self._value is None or isinstance(self._value, dict)
        return self._value


class PollSession(TrackingSession):
    def __init__(
        self, factory: PollSessionFactory, poll: tuple[list[dict[str, Any]], dict[str, Any] | None]
    ) -> None:
        super().__init__(factory)
        self._poll = poll
        self._calls = 0

    def execute(self, _statement: object, parameters: dict[str, Any]) -> FakeResult:
        self._calls += 1
        self._factory.parameters.append(dict(parameters))
        return FakeResult(self._poll[0] if self._calls == 1 else self._poll[1])


class PollSessionFactory(TrackingSessionFactory):
    def __init__(self, polls: list[tuple[list[dict[str, Any]], dict[str, Any] | None]]) -> None:
        super().__init__()
        self._polls = iter(polls)
        self.opens = 0
        self.parameters: list[dict[str, Any]] = []

    def __call__(self) -> PollSession:
        self.opens += 1
        return PollSession(self, next(self._polls))


def test_pcm_iterator_releases_poll_session_before_yield() -> None:
    token = uuid4()
    factory = PollSessionFactory(
        [
            (
                [{"sequence_no": 0, "pcm": b"pcm"}],
                {"generation_status": "ready", "processing_token": token},
            )
        ]
    )
    stream = iter_tts_pcm(factory, uuid4(), token)

    assert next(stream) == b"pcm"
    assert factory.active == 0
    stream.close()
    assert factory.opens == 1


def test_pcm_iterator_switches_to_new_processing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_token = uuid4()
    new_token = uuid4()
    factory = PollSessionFactory(
        [
            ([], {"generation_status": "processing", "processing_token": new_token}),
            (
                [{"sequence_no": 0, "pcm": b"new"}],
                {"generation_status": "ready", "processing_token": new_token},
            ),
        ]
    )
    monkeypatch.setattr(tts_streaming.time, "sleep", lambda _seconds: None)

    stream = iter_tts_pcm(factory, uuid4(), old_token)

    assert next(stream) == b"new"
    assert factory.parameters[0]["token"] == old_token
    assert factory.parameters[2]["token"] == new_token
    assert factory.parameters[2]["sequence_no"] == -1
    assert factory.active == 0
    stream.close()


def test_multiple_pcm_iterators_do_not_hold_sessions_between_consumers() -> None:
    token = uuid4()
    factories = [
        PollSessionFactory(
            [
                (
                    [{"sequence_no": 0, "pcm": bytes([index])}],
                    {"generation_status": "ready", "processing_token": token},
                )
            ]
        )
        for index in range(3)
    ]
    streams = [iter_tts_pcm(factory, uuid4(), token) for factory in factories]

    assert [next(stream) for stream in streams] == [b"\x00", b"\x01", b"\x02"]
    assert all(factory.active == 0 for factory in factories)
    assert all(factory.peak == 1 for factory in factories)
    for stream in streams:
        stream.close()
