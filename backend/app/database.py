"""SQLAlchemy engine / session.

SQLite for local dev (default). Any SQLAlchemy URL works, e.g.
postgresql://user:pass@host:5432/aisystem for cloud deployment -- the
models use no SQLite-specific features, so switching is a config change.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    # Ensure the parent dir for a file-based SQLite DB exists.
    path = settings.database_url.replace("sqlite:///", "")
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
