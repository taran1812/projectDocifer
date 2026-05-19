from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from docifer_backend.config.settings import get_settings


@lru_cache
def get_database_engine() -> Engine:
    """Create and cache the SQLAlchemy database engine."""
    settings = get_settings()

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
    )


def check_database_connection() -> bool:
    """Return True when PostgreSQL is reachable."""
    try:
        with get_database_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
