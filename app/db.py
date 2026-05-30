from __future__ import annotations

import re

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def _normalize_schema_name(schema_name: str | None) -> str | None:
    if schema_name is None:
        return None

    normalized = schema_name.strip().lower()
    if not normalized:
        return None
    if not re.match(r"^[a-z_][a-z0-9_]*$", normalized):
        raise ValueError(f"Invalid Postgres schema name: {schema_name}")
    return normalized


def _configure_postgres_search_path(engine, schema_name: str | None) -> str | None:
    normalized = _normalize_schema_name(schema_name)
    if normalized is None or engine.dialect.name == "sqlite":
        return normalized

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{normalized}"')
            cursor.execute(f'SET search_path TO "{normalized}", public')
        finally:
            cursor.close()

    return normalized


def create_engine_and_sessionmaker(
    testing: bool = False,
    database_url: str | None = None,
    database_schema: str | None = None,
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
        _configure_postgres_search_path(engine, database_schema)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, session_factory


def initialize_database(engine, schema_name: str | None = None) -> None:
    normalized = _normalize_schema_name(schema_name)
    if engine.dialect.name != "sqlite" and normalized is not None:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{normalized}"'))

    Base.metadata.create_all(engine)
    ensure_runtime_schema(engine)


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
