from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings
from app.core.db import create_database_engine, create_session_factory
from app.core.errors import ApiError
from app.core.readiness import DatabaseReadinessChecker, ReadinessReport


@lru_cache
def get_settings() -> AppSettings:
    try:
        return AppSettings()
    except ValidationError as error:
        raise ApiError(
            503,
            "CONFIG_NOT_READY",
            "필수 서버 설정이 준비되지 않았습니다.",
            retryable=True,
        ) from error


@lru_cache
def get_engine() -> Engine:
    return create_database_engine(get_settings())


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_engine())


def get_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


class ApplicationReadinessChecker:
    async def check(self) -> ReadinessReport:
        try:
            settings = get_settings()
            checker = DatabaseReadinessChecker(
                get_engine(),
                settings.queue_names,
                settings.worker_heartbeat_ttl_seconds,
            )
        except ApiError:
            return ReadinessReport.all_failed()
        return await checker.check()
