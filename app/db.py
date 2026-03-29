from __future__ import annotations

from sqlalchemy import create_engine
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
            connect_args={"check_same_thread": False},
        )

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, session_factory
