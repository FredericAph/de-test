from pathlib import Path

import pytest

from app.models.record import IngestedRecord, Job, Organization, Person
from app.parsers import build_default_registry
from app.parsers.base import FormatHandler, InvalidFormatError, UnsupportedFormatError
from app.parsers.registry import FormatRegistry
from app.services.ingest import ingest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def csv_bytes() -> bytes:
    return (FIXTURES / "sample_format_1.csv").read_bytes()


@pytest.fixture(scope="module")
def xlsx_bytes() -> bytes:
    return (FIXTURES / "sample_format_1.xlsx").read_bytes()


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_ingest_csv(conn, csv_bytes: bytes) -> None:
    result = ingest(conn, build_default_registry(), "sample_format_1.csv", csv_bytes)

    assert result.persons_created == 3
    assert result.organizations_created == 1
    assert result.jobs_created == 3
    assert _count(conn, "person") == 3
    assert _count(conn, "organization") == 1
    assert _count(conn, "job") == 3


def test_ingest_xlsx(conn, xlsx_bytes: bytes) -> None:
    result = ingest(conn, build_default_registry(), "sample_format_1.xlsx", xlsx_bytes)

    assert result.persons_created == 3
    assert result.organizations_created == 1
    assert result.jobs_created == 3
    assert _count(conn, "person") == 3
    assert _count(conn, "organization") == 1
    assert _count(conn, "job") == 3


def test_ingest_csv_twice_is_idempotent(conn, csv_bytes: bytes) -> None:
    registry = build_default_registry()
    ingest(conn, registry, "sample_format_1.csv", csv_bytes)

    second = ingest(conn, registry, "sample_format_1.csv", csv_bytes)

    assert second.persons_created == 0
    assert second.persons_updated == 0
    assert second.jobs_created == 0
    assert second.organizations_created == 0


def test_ingest_unsupported_format_raises(conn) -> None:
    with pytest.raises(UnsupportedFormatError):
        ingest(conn, build_default_registry(), "file.xyz", b"")


def test_ingest_invalid_content_raises(conn) -> None:
    with pytest.raises(InvalidFormatError):
        ingest(conn, build_default_registry(), "file.csv", b"a;b\n1;2\n")


def test_ingest_with_stub_handler(conn) -> None:
    class StubHandler(FormatHandler):
        format_id = "stub"
        extensions = (".stb",)

        def probe(self, filename: str, content: bytes) -> bool:
            return filename.endswith(".stb")

        def parse(self, content: bytes) -> list[IngestedRecord]:
            return [
                IngestedRecord(
                    person=Person(first_name="Stub", last_name="Person"),
                    organization=Organization(org_name="Stub Org"),
                    job=Job(job_title="Stub Job"),
                )
            ]

    registry = FormatRegistry()
    registry.register(StubHandler())

    result = ingest(conn, registry, "x.stb", b"anything")

    assert result.persons_created == 1
    assert result.organizations_created == 1
    assert result.jobs_created == 1
    assert _count(conn, "person") == 1
    assert _count(conn, "organization") == 1
    assert _count(conn, "job") == 1
