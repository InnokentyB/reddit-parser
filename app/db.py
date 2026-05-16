from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def create_engine_and_sessionmaker(
    testing: bool = False,
    database_url: str | None = None,
) -> tuple[object, sessionmaker]:
    if testing:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        if database_url is None:
            raise ValueError("database_url is required when testing is False")
        engine = create_engine(
            database_url,
            future=True,
        )

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, session_factory


def ensure_runtime_schema(engine) -> None:
    inspector = inspect(engine)
    if "search_jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("search_jobs")}
    statements: list[str] = []
    if "source" not in columns:
        statements.append("ALTER TABLE search_jobs ADD COLUMN source VARCHAR(32) DEFAULT 'reddit'")
        statements.append("UPDATE search_jobs SET source = 'reddit' WHERE source IS NULL")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
