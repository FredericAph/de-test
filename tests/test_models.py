import pytest
from pydantic import ValidationError

from app.models import IngestedRecord, Job, Organization, Person


def _minimal_record() -> IngestedRecord:
    return IngestedRecord(
        person=Person(first_name="Ada", last_name="Lovelace"),
        organization=Organization(org_name="Analytical Engines Ltd"),
        job=Job(job_title="Mathematician"),
    )


def test_minimal_record_builds_with_defaults() -> None:
    record = _minimal_record()

    assert record.person.first_name == "Ada"
    assert record.person.last_name == "Lovelace"
    assert record.person.middle_name == ""
    assert record.person.email is None
    assert record.person.phone is None
    assert record.person.fax is None
    assert record.person.title is None
    assert record.person.person_id is None

    assert record.organization.org_name == "Analytical Engines Ltd"
    assert record.organization.org_vivo_uri == ""
    assert record.organization.org_id is None

    assert record.job.job_title == "Mathematician"
    assert record.job.job_type == ""
    assert record.job.start_date is None
    assert record.job.job_id is None


def test_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        Person(last_name="Lovelace")  # type: ignore[call-arg]


def test_job_start_date_accepts_int() -> None:
    assert Job(job_title="Engineer", start_date=2001).start_date == 2001


def test_job_start_date_coerces_numeric_string() -> None:
    assert Job(job_title="Engineer", start_date="2001").start_date == 2001


def test_job_start_date_rejects_non_numeric_string() -> None:
    with pytest.raises(ValidationError):
        Job(job_title="Engineer", start_date="abc")


def test_ingested_record_requires_nested_models() -> None:
    with pytest.raises(ValidationError):
        IngestedRecord(  # type: ignore[call-arg]
            organization=Organization(org_name="Org"),
            job=Job(job_title="Title"),
        )

    with pytest.raises(ValidationError):
        IngestedRecord(  # type: ignore[call-arg]
            person=Person(first_name="Ada", last_name="Lovelace"),
            job=Job(job_title="Title"),
        )

    with pytest.raises(ValidationError):
        IngestedRecord(  # type: ignore[call-arg]
            person=Person(first_name="Ada", last_name="Lovelace"),
            organization=Organization(org_name="Org"),
        )
