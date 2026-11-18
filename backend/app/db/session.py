"""Database engine and session factory (SQLite for development, PostgreSQL e.g. Neon)."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base


def normalize_url(url: str) -> str:
    """Use the psycopg 3 driver for plain postgres:// or postgresql:// URLs (e.g. from Neon)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def is_postgres(url: str) -> bool:
    return normalize_url(url).startswith("postgresql")


class Database:
    def __init__(self, url: str) -> None:
        url = normalize_url(url)
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool  # one shared in-memory database (tests)
        elif is_postgres(url):
            kwargs.update(
                # Serverless databases drop idle connections: recycle them before that happens
                # (a pre-ping would cost an extra network round trip on every request).
                pool_recycle=240,
                pool_size=5,
                max_overflow=5,
                connect_args={
                    "connect_timeout": 20,
                    # PgBouncer-style poolers (Neon "-pooler" hosts) cannot keep server-side
                    # prepared statements across transactions.
                    "prepare_threshold": None,
                },
            )
        self.url = url
        self.engine: Engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self.session: sessionmaker[Session] = sessionmaker(self.engine, expire_on_commit=False)
        # Read-only queries in autocommit mode: no BEGIN/ROLLBACK round trips per request.
        self.read_session: sessionmaker[Session] = sessionmaker(
            self.engine.execution_options(isolation_level="AUTOCOMMIT"), expire_on_commit=False
        )

    @property
    def remote(self) -> bool:
        return not self.url.startswith("sqlite")

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()
