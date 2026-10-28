from dataclasses import dataclass

from app.models.record import IngestedRecord, Job, Organization, Person
from app.services.history import diff_fields, write_history


@dataclass
class IngestResult:
    persons_created: int = 0
    persons_updated: int = 0
    jobs_created: int = 0
    organizations_created: int = 0
    history_rows_written: int = 0
    format: str = ""


def upsert_organization(conn, org: Organization) -> tuple[int, bool]:
    """Return (org_id, created)."""
    row = conn.execute(
        "SELECT org_id FROM organization WHERE org_name = ? AND org_vivo_uri = ?",
        [org.org_name, org.org_vivo_uri],
    ).fetchone()
    if row is not None:
        return row[0], False

    conn.execute(
        "INSERT INTO organization (org_id, org_name, org_vivo_uri) "
        "VALUES (nextval('organization_seq'), ?, ?)",
        [org.org_name, org.org_vivo_uri],
    )
    org_id = conn.execute(
        "SELECT org_id FROM organization WHERE org_name = ? AND org_vivo_uri = ?",
        [org.org_name, org.org_vivo_uri],
    ).fetchone()[0]
    return org_id, True


def upsert_person(conn, person: Person, source_file: str) -> tuple[int, str, int]:
    """Return (person_id, status, history_rows_written) with status in {created, updated, unchanged}."""
    row = conn.execute(
        "SELECT person_id, email, phone, fax, title FROM person "
        "WHERE first_name = ? AND middle_name = ? AND last_name = ?",
        [person.first_name, person.middle_name, person.last_name],
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO person (person_id, first_name, middle_name, last_name, email, phone, fax, title) "
            "VALUES (nextval('person_seq'), ?, ?, ?, ?, ?, ?, ?)",
            [person.first_name, person.middle_name, person.last_name,
             person.email, person.phone, person.fax, person.title],
        )
        person_id = conn.execute(
            "SELECT person_id FROM person WHERE first_name = ? AND middle_name = ? AND last_name = ?",
            [person.first_name, person.middle_name, person.last_name],
        ).fetchone()[0]
        return person_id, "created", 0

    person_id, old_email, old_phone, old_fax, old_title = row
    old = {"email": old_email, "phone": old_phone, "fax": old_fax, "title": old_title}
    new = {"email": person.email, "phone": person.phone, "fax": person.fax, "title": person.title}
    changes = diff_fields(old, new)
    if not changes:
        return person_id, "unchanged", 0

    version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM person_history WHERE person_id = ?",
        [person_id],
    ).fetchone()[0]

    conn.execute(
        "UPDATE person SET email = ?, phone = ?, fax = ?, title = ? WHERE person_id = ?",
        [person.email, person.phone, person.fax, person.title, person_id],
    )
    written = write_history(conn, person_id, changes, version, source_file)
    return person_id, "updated", written


def upsert_job(conn, person_id: int, org_id: int, job: Job) -> bool:
    """Return True if a new job row was actually inserted."""
    start_date = job.start_date if job.start_date is not None else -1
    existing = conn.execute(
        "SELECT 1 FROM job WHERE person_id = ? AND org_id = ? AND job_title = ? AND job_type = ? AND start_date = ?",
        [person_id, org_id, job.job_title, job.job_type, start_date],
    ).fetchone()
    if existing is not None:
        return False

    conn.execute(
        "INSERT INTO job (job_id, person_id, org_id, job_title, job_type, start_date) "
        "VALUES (nextval('job_seq'), ?, ?, ?, ?, ?)",
        [person_id, org_id, job.job_title, job.job_type, start_date],
    )
    return True


def upsert_record(conn, record: IngestedRecord, source_file: str, result: IngestResult) -> None:
    org_id, org_created = upsert_organization(conn, record.organization)
    if org_created:
        result.organizations_created += 1

    person_id, status, history_rows = upsert_person(conn, record.person, source_file)
    if status == "created":
        result.persons_created += 1
    elif status == "updated":
        result.persons_updated += 1
    result.history_rows_written += history_rows

    if upsert_job(conn, person_id, org_id, record.job):
        result.jobs_created += 1


def upsert_records(conn, records: list[IngestedRecord], source_file: str) -> IngestResult:
    result = IngestResult()
    for record in records:
        upsert_record(conn, record, source_file, result)
    return result
