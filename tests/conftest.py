import pytest

from app.db import connect


@pytest.fixture
def conn():
    """A fresh in-memory DuckDB connection with the schema applied."""
    c = connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def client(conn):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(conn=conn)
    with TestClient(app) as test_client:
        yield test_client
