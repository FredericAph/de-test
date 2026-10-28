from pathlib import Path

import pytest

from app.models.record import IngestedRecord
from app.parsers import build_default_registry
from app.parsers.base import InvalidFormatError
from app.parsers.formats.csv_format_1 import CSVFormatHandler
from app.parsers.formats.xlsx_format_1 import XLSXFormatHandler

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def csv_bytes() -> bytes:
    return (FIXTURES / "sample_format_1.csv").read_bytes()


@pytest.fixture(scope="module")
def xlsx_bytes() -> bytes:
    return (FIXTURES / "sample_format_1.xlsx").read_bytes()


# --- probing ---------------------------------------------------------------


def test_csv_probe_accepts_csv_rejects_xlsx() -> None:
    handler = CSVFormatHandler()
    assert handler.probe("a.csv", b"") is True
    assert handler.probe("a.xlsx", b"") is False


def test_xlsx_probe_accepts_xlsx_rejects_csv() -> None:
    handler = XLSXFormatHandler()
    assert handler.probe("a.xlsx", b"") is True
    assert handler.probe("a.csv", b"") is False


def test_xlsx_probe_accepts_magic_bytes_without_extension() -> None:
    assert XLSXFormatHandler().probe("no_extension", b"PK\x03\x04....") is True


def test_default_registry_probes_handlers() -> None:
    registry = build_default_registry()
    assert isinstance(registry.probe("a.csv", b""), CSVFormatHandler)
    assert isinstance(registry.probe("a.xlsx", b""), XLSXFormatHandler)
    assert registry.probe("a.json", b"") is None
    assert registry.probe("a.txt", b"") is None


def test_default_registry_supported_extensions() -> None:
    assert build_default_registry().supported_extensions() == [".csv", ".xlsx"]


# --- CSV parsing -----------------------------------------------------------


def test_csv_parse_returns_three_records(csv_bytes: bytes) -> None:
    records = CSVFormatHandler().parse(csv_bytes)
    assert len(records) == 3
    assert all(isinstance(r, IngestedRecord) for r in records)


def test_csv_parse_splits_fused_name(csv_bytes: bytes) -> None:
    record = CSVFormatHandler().parse(csv_bytes)[0]
    assert record.person.first_name == "Edgar"
    assert record.person.middle_name == "Estes"
    assert record.person.last_name == "Moises"


def test_csv_parse_handles_missing_middle_and_empty_email(csv_bytes: bytes) -> None:
    record = CSVFormatHandler().parse(csv_bytes)[1]
    assert record.person.first_name == "Rosella"
    assert record.person.middle_name == ""
    assert record.person.email is None


def test_csv_parse_strips_trailing_space(csv_bytes: bytes) -> None:
    record = CSVFormatHandler().parse(csv_bytes)[0]
    assert record.person.title == "Professor"


def test_csv_parse_maps_job_fields(csv_bytes: bytes) -> None:
    record = CSVFormatHandler().parse(csv_bytes)[0]
    assert record.job.job_title == "Professor of Thermodynamics"
    assert record.job.job_type == "Faculty"
    assert record.job.start_date == 2000


def test_csv_parse_maps_organization_fields(csv_bytes: bytes) -> None:
    record = CSVFormatHandler().parse(csv_bytes)[0]
    assert record.organization.org_name == "Geothermal Technology Department"
    assert record.organization.org_vivo_uri.endswith("#Department")


# --- XLSX parsing ----------------------------------------------------------


def test_xlsx_parse_returns_three_records(xlsx_bytes: bytes) -> None:
    records = XLSXFormatHandler().parse(xlsx_bytes)
    assert len(records) == 3
    assert all(isinstance(r, IngestedRecord) for r in records)


def test_xlsx_parse_maps_person_fields(xlsx_bytes: bytes) -> None:
    record = XLSXFormatHandler().parse(xlsx_bytes)[0]
    assert record.person.first_name == "Johnathan"
    assert record.person.last_name == "Baxter"
    assert record.person.middle_name == "Browning"


def test_xlsx_parse_nan_middle_becomes_empty(xlsx_bytes: bytes) -> None:
    record = XLSXFormatHandler().parse(xlsx_bytes)[1]
    assert record.person.middle_name == ""


def test_xlsx_parse_maps_job_and_org_fields(xlsx_bytes: bytes) -> None:
    record = XLSXFormatHandler().parse(xlsx_bytes)[0]
    assert record.job.start_date == 2001
    assert isinstance(record.job.start_date, int)
    assert record.job.job_type == "Faculty"
    assert record.organization.org_name == "Geothermal Technology Department"


# --- error handling --------------------------------------------------------


def test_csv_parse_missing_columns_raises() -> None:
    with pytest.raises(InvalidFormatError):
        CSVFormatHandler().parse(b"header1;header2\n1;2\n")


def test_xlsx_parse_invalid_content_raises() -> None:
    with pytest.raises(InvalidFormatError):
        XLSXFormatHandler().parse(b"not an xlsx at all")


def test_xlsx_parse_csv_bytes_raises(csv_bytes: bytes) -> None:
    with pytest.raises(InvalidFormatError):
        XLSXFormatHandler().parse(csv_bytes)
