from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def _upload(client, path: Path):
    content = path.read_bytes()
    content_type = "text/csv" if path.suffix == ".csv" else "application/octet-stream"
    return client.post("/upload", files={"file": (path.name, content, content_type)})


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _q(conn, sql: str, *params):
    return conn.execute(sql, list(params)).fetchone()


def test_full_use_case(client, conn) -> None:
    """Reproduce the full use-case: load data_1.csv + data_2.xlsx (tronc commun), then
    data_3.xlsx + data_4.xlsx (subsidiaire) which update existing persons' contact details,
    insert new jobs, and record field-level history. No duplicate persons are ever created."""
    # 1. data_1.csv
    response = _upload(client, DATA / "data_1.csv")
    assert response.status_code == 200
    body = response.json()
    assert body["persons_created"] == 16
    assert body["organizations_created"] == 1
    assert body["jobs_created"] == 16
    assert body["persons_updated"] == 0
    assert body["history_rows_written"] == 0

    # 2. data_2.xlsx
    response = _upload(client, DATA / "data_2.xlsx")
    assert response.status_code == 200
    body = response.json()
    assert body["persons_created"] == 24
    assert body["organizations_created"] == 1
    assert body["jobs_created"] == 24
    assert body["persons_updated"] == 0

    # 3. data_3.xlsx
    response = _upload(client, DATA / "data_3.xlsx")
    assert response.status_code == 200
    body = response.json()
    assert body["persons_created"] == 0
    assert body["persons_updated"] == 8
    assert body["jobs_created"] == 10
    assert body["organizations_created"] == 2
    assert body["history_rows_written"] == 14

    # 4. data_4.xlsx
    response = _upload(client, DATA / "data_4.xlsx")
    assert response.status_code == 200
    body = response.json()
    assert body["persons_created"] == 0
    assert body["persons_updated"] == 4
    assert body["jobs_created"] == 5
    assert body["organizations_created"] == 0
    assert body["history_rows_written"] == 9

    # 5. Final row counts — no duplicate persons despite 4 uploads.
    assert _count(conn, "person") == 40
    assert _count(conn, "organization") == 4
    assert _count(conn, "job") == 55
    assert _count(conn, "person_history") == 23

    # 6. "latest wins": data_4 values overwrote data_3 values for Kimberly Mullins.
    assert _q(
        conn,
        "SELECT phone, fax, title FROM person "
        "WHERE first_name='Kimberly' AND middle_name='' AND last_name='Mullins'",
    ) == ("963.555.5471x8999", "963.777.1111", "Curate")

    # 7. Angelina Sims contact details updated.
    assert _q(
        conn,
        "SELECT phone, fax FROM person "
        "WHERE first_name='Angelina' AND middle_name='' AND last_name='Sims'",
    ) == ("963.555.8856", "963.777.4465")

    # 8. Updated persons gained new jobs.
    assert _q(
        conn,
        "SELECT count(*) FROM job j JOIN person p ON p.person_id=j.person_id "
        "WHERE p.first_name='Andrea' AND p.last_name='Pate'",
    )[0] == 3
    assert _q(
        conn,
        "SELECT count(*) FROM job j JOIN person p ON p.person_id=j.person_id "
        "WHERE p.first_name='Kimberly' AND p.last_name='Mullins'",
    )[0] == 3

    # 9. History rows reference the correct source file.
    assert _q(
        conn, "SELECT count(*) FROM person_history WHERE source_file='data_3.xlsx'"
    )[0] == 14
    assert _q(
        conn, "SELECT count(*) FROM person_history WHERE source_file='data_4.xlsx'"
    )[0] == 9
