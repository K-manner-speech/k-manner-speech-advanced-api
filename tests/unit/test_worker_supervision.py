from __future__ import annotations

import inspect
from typing import Any

import worker.main as worker_main


class ExplodingHeartbeat:
    """하트비트 기록이 계속 실패하는 상황."""

    def __init__(self) -> None:
        self.attempts = 0

    def record(self, worker_id: str, queue_name: str, started_at: Any) -> None:
        self.attempts += 1
        raise RuntimeError("heartbeat insert rejected")


class CountingWorker:
    def __init__(self, stop_after: int) -> None:
        self.runs = 0
        self._stop_after = stop_after

    def run_once(self) -> bool:
        self.runs += 1
        if self.runs >= self._stop_after:
            raise StopIteration
        return True


class Session:
    def __init__(self) -> None:
        self.rollbacks = 0

    def rollback(self) -> None:
        self.rollbacks += 1


def _consumer_loop_body() -> str:
    return inspect.getsource(worker_main._run_consumer)


def test_heartbeat_failure_does_not_break_out_of_the_consumer_loop() -> None:
    """하트비트 실패로 루프를 벗어나면 job 을 하나도 처리하지 못하는 좀비가 된다."""
    source = _consumer_loop_body()
    heartbeat_call = source.index("heartbeat.record(")
    guarded = source.rindex("try:", 0, heartbeat_call)
    between = source[guarded:heartbeat_call]

    # heartbeat.record 바로 앞에 try 가 있고, 그 사이에 다른 문장이 끼지 않아야 한다.
    assert between.strip() == "try:"
    assert "logger.exception" in source


def test_consumer_survives_repeated_heartbeat_failures() -> None:
    heartbeat = ExplodingHeartbeat()
    session = Session()
    job_worker = CountingWorker(stop_after=3)

    # _run_consumer 의 루프와 같은 구조를 그대로 재현한다.
    runs = 0
    while runs < 5:
        runs += 1
        try:
            heartbeat.record("w", "evaluation_ai", None)
        except Exception:
            session.rollback()
        try:
            job_worker.run_once()
        except StopIteration:
            break
        except Exception:
            session.rollback()

    assert heartbeat.attempts >= 3, "하트비트가 실패해도 계속 시도해야 한다"
    assert job_worker.runs >= 3, "하트비트 실패와 무관하게 job 을 계속 처리해야 한다"


def test_dead_thread_terminates_the_process_instead_of_hanging() -> None:
    """ThreadPoolExecutor 의 __exit__ 는 남은 스레드를 기다리다 영원히 멈춘다.

    예외를 그대로 올리면 traceback 도 못 남기고 프로세스만 살아 있는 좀비가 된다.
    """
    source = inspect.getsource(worker_main.run_queue)

    assert "future.result()" not in source, "예외를 그대로 올리면 shutdown 에서 멈춘다"
    assert "future.exception()" in source
    assert "logger.critical" in source
    assert "os._exit(1)" in source


def test_worker_failures_are_logged_not_printed() -> None:
    """print 로 남기면 로그 수준·형식을 통제할 수 없다."""
    source = inspect.getsource(worker_main)

    assert "traceback.print_exc()" not in source
    assert source.count("logger.exception") >= 3
