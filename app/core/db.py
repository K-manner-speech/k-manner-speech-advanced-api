from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings


def create_database_engine(settings: AppSettings) -> Engine:
    database_url = settings.database_url.get_secret_value()
    parsed_url = make_url(database_url)
    if not parsed_url.drivername.startswith("postgresql"):
        raise ValueError("DATABASE_URL must use Postgres")
    sync_url = parsed_url.set(drivername="postgresql+psycopg")
    return create_engine(
        sync_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=1,
        connect_args={"prepare_threshold": None},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
