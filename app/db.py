from pathlib import Path

import duckdb

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "schema.sql"


def apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Apply schema.sql idempotently to the given connection."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    for stmt in sql.split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)


def connect(db_path: str) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection and ensure the schema exists."""
    conn = duckdb.connect(db_path)
    apply_schema(conn)
    return conn
