from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from docifer_backend.config.settings import get_settings


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata for Docifer tables."""


@lru_cache
def get_database_engine() -> Engine:
    """Create and cache the SQLAlchemy database engine."""
    settings = get_settings()

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create and cache the SQLAlchemy session factory."""

    return sessionmaker(
        bind=get_database_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session boundary for service code."""

    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_database_schema() -> None:
    """Create local development tables if they do not already exist."""

    # Import models here so their tables are registered on Base.metadata.
    import docifer_backend.ingestion.models  # noqa: F401
    import docifer_backend.retrieval.models  # noqa: F401
    import docifer_backend.retrieval.tables.models  # noqa: F401
    import docifer_backend.audit.models  # noqa: F401

    Base.metadata.create_all(bind=get_database_engine())


def check_database_connection() -> bool:
    """Return True when PostgreSQL is reachable."""
    try:
        with get_database_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
