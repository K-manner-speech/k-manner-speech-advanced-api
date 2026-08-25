import pytest

from app.core.config import AppSettings
from app.core.db import create_database_engine
from tests.unit.test_core_config import complete_settings


def test_database_engine_uses_only_required_postgres_url() -> None:
    settings = AppSettings.model_validate(complete_settings())

    engine = create_database_engine(settings)

    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_database_engine_rejects_non_postgres_url() -> None:
    values = complete_settings()
    values["database_url"] = "sqlite+pysqlite:///:memory:"
    settings = AppSettings.model_validate(values)

    with pytest.raises(ValueError, match="Postgres"):
        create_database_engine(settings)


def test_database_engine_normalizes_supabase_postgresql_url_to_psycopg() -> None:
    values = complete_settings()
    values["database_url"] = "postgresql://postgres:secret@localhost:5432/postgres"
    settings = AppSettings.model_validate(values)

    engine = create_database_engine(settings)

    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()
