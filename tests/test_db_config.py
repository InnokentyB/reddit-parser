from unittest.mock import Mock, patch

from app.db import create_engine_and_sessionmaker


def test_postgres_connections_pin_parser_search_path_before_pool_checkout():
    engine = Mock()
    with patch("app.db.create_engine", return_value=engine) as create_engine, patch(
        "app.db._configure_postgres_search_path"
    ):
        create_engine_and_sessionmaker(
            database_url="postgresql+psycopg2://example.invalid/parser",
            database_schema="parser",
        )

    assert create_engine.call_args.kwargs["connect_args"] == {
        "options": "-csearch_path=parser,public"
    }
