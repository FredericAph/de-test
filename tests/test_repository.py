from app.models.record import IngestedRecord, Job, Organization, Person
from app.services.history import diff_fields
from app.services.repository import (
    upsert_job,
    upsert_organization,
    upsert_person,
    upsert_records,
)


def make_record(
    first, last, middle="", email=None, phone=None, fax=None, title=None,
    job_title="Professor", job_type="Faculty", start_date=2000,
    org_name="Dept", org_vivo_uri="http://u",
):
    return IngestedRecord(
        person=Person(first_name=first, middle_name=middle, last_name=last,
                      email=email, phone=phone, fax=fax, title=title),
        organization=Organization(org_name=org_name, org_vivo_uri=org_vivo_uri),
        job=Job(job_title=job_title, job_type=job_type, start_date=start_date),
    )


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# --- dedup -----------------------------------------------------------------


def test_same_person_twice_is_deduplicated(conn) -> None:
    record = make_record("Ada", "Lovelace")

    first = upsert_records(conn, [record], "a.csv")
    second = upsert_records(conn, [record], "a.csv")

    assert _count(conn, "person") == 1
    assert first.persons_created == 1
    assert second.persons_created == 0
    assert second.persons_updated == 0


def test_same_organization_twice_is_deduplicated(conn) -> None:
    org = Organization(org_name="Dept", org_vivo_uri="http://u")

    _, created_first = upsert_organization(conn, org)
    _, created_second = upsert_organization(conn, org)

    assert created_first is True
    assert created_second is False
    assert _count(conn, "organization") == 1


def test_identical_job_twice_is_deduplicated(conn) -> None:
    record = make_record("Ada", "Lovelace")

    upsert_records(conn, [record], "a.csv")
    upsert_records(conn, [record], "a.csv")

    assert _count(conn, "job") == 1


# --- updates & history -----------------------------------------------------


def test_email_change_updates_person_and_writes_one_history_row(conn) -> None:
    upsert_records(conn, [make_record("Ada", "Lovelace", phone="111")], "first.csv")

    result = upsert_records(
        conn, [make_record("Ada", "Lovelace", email="ada@x.org", phone="111")], "second.csv"
    )

    assert result.persons_updated == 1
    assert result.history_rows_written == 1
    assert conn.execute("SELECT email FROM person").fetchone()[0] == "ada@x.org"

    rows = conn.execute(
        "SELECT field_name, old_value, new_value FROM person_history"
    ).fetchall()
    assert rows == [("email", None, "ada@x.org")]


def test_no_change_writes_no_history(conn) -> None:
    record = make_record("Ada", "Lovelace", email="ada@x.org")
    upsert_records(conn, [record], "a.csv")

    result = upsert_records(conn, [record], "a.csv")

    assert result.persons_updated == 0
    assert result.history_rows_written == 0
    assert _count(conn, "person_history") == 0


def test_existing_person_with_new_job_inserts_job(conn) -> None:
    upsert_records(conn, [make_record("Ada", "Lovelace", job_title="Professor")], "a.csv")
    jobs_before = _count(conn, "job")

    result = upsert_records(
        conn, [make_record("Ada", "Lovelace", job_title="Dean", start_date=2010)], "b.csv"
    )

    assert _count(conn, "job") == jobs_before + 1
    assert result.jobs_created == 1
    assert result.persons_created == 0
    assert _count(conn, "person") == 1


def test_version_increments_across_updates(conn) -> None:
    upsert_records(conn, [make_record("Ada", "Lovelace", email="a@x.org")], "a.csv")
    upsert_records(conn, [make_record("Ada", "Lovelace", email="b@x.org")], "b.csv")
    upsert_records(conn, [make_record("Ada", "Lovelace", email="c@x.org")], "c.csv")

    versions = [
        row[0]
        for row in conn.execute(
            "SELECT version FROM person_history ORDER BY history_id"
        ).fetchall()
    ]
    assert versions == [1, 2]


def test_history_records_old_new_and_source_file(conn) -> None:
    upsert_records(conn, [make_record("Ada", "Lovelace", phone="111")], "first.csv")
    upsert_records(conn, [make_record("Ada", "Lovelace", phone="222")], "second.csv")

    row = conn.execute(
        "SELECT field_name, old_value, new_value, source_file FROM person_history"
    ).fetchone()
    assert row == ("phone", "111", "222", "second.csv")


# --- diff_fields -----------------------------------------------------------


def test_diff_fields_reports_only_changed_fields() -> None:
    changes = diff_fields({"email": "a", "phone": "1"}, {"email": "b", "phone": "1"})
    assert changes == [("email", "a", "b")]


def test_diff_fields_none_to_value_is_change() -> None:
    assert diff_fields({"email": None}, {"email": "x"}) == [("email", None, "x")]


def test_diff_fields_value_to_none_is_change() -> None:
    assert diff_fields({"email": "x"}, {"email": None}) == [("email", "x", None)]


# --- sentinels -------------------------------------------------------------


def test_missing_optional_job_fields_use_sentinels(conn) -> None:
    record = make_record(
        "Ada", "Lovelace", job_type="", start_date=None, org_vivo_uri=""
    )

    upsert_records(conn, [record], "a.csv")

    job_row = conn.execute(
        "SELECT job_type, start_date FROM job"
    ).fetchone()
    assert job_row == ("", -1)

    org_row = conn.execute("SELECT org_vivo_uri FROM organization").fetchone()
    assert org_row == ("",)
