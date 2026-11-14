"""Database setup: SQLite by default, Postgres through DATABASE_URL."""

import logging
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL
from app.models import Base

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_SQLITE_URL = f"sqlite:///{DATA_DIR / 'reports.db'}"


def _build_url() -> str:
    url = (DATABASE_URL or "").strip()
    if not url:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DEFAULT_SQLITE_URL
    # Render/Heroku hand out postgres:// which SQLAlchemy no longer accepts.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


ENGINE_URL = _build_url()
_is_sqlite = ENGINE_URL.startswith("sqlite")

engine = create_engine(
    ENGINE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they do not exist yet, and add new columns to old DBs."""
    Base.metadata.create_all(bind=engine)

    # Runs created before the title feature need the new column added in place.
    columns = {column["name"] for column in inspect(engine).get_columns("runs")}
    if "title" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE runs ADD COLUMN title VARCHAR(200)"))
        logger.info("Added runs.title column")

    if "word_count" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE runs ADD COLUMN word_count INTEGER DEFAULT 0"))
        logger.info("Added runs.word_count column")

    logger.info("Database ready at %s", ENGINE_URL.split("@")[-1])


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
