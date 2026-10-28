from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def csv_bytes() -> bytes:
    return (FIXTURES / "sample_format_1.csv").read_bytes()


@pytest.fixture(scope="module")
def xlsx_bytes() -> bytes:
    return (FIXTURES / "sample_format_1.xlsx").read_bytes()


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_csv(client, csv_bytes: bytes) -> None:
    response = client.post(
        "/upload",
        files={"file": ("sample_format_1.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["format"] == "csv_format_1"
    assert body["persons_created"] == 3
    assert body["organizations_created"] == 1
    assert body["jobs_created"] == 3
    assert body["persons_updated"] == 0
    assert body["history_rows_written"] == 0


def test_upload_xlsx(client, xlsx_bytes: bytes) -> None:
    response = client.post(
        "/upload",
        files={
            "file": (
                "sample_format_1.xlsx",
                xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["format"] == "xlsx_format_1"
    assert body["persons_created"] == 3
    assert body["jobs_created"] == 3


def test_upload_unsupported_extension_returns_415(client) -> None:
    response = client.post(
        "/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_upload_empty_file_returns_400(client) -> None:
    response = client.post(
        "/upload",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 400


def test_upload_missing_file_part_returns_400(client) -> None:
    response = client.post("/upload")
    assert response.status_code == 400


def test_upload_malformed_csv_returns_422(client) -> None:
    response = client.post(
        "/upload",
        files={"file": ("bad.csv", b"a;b\n1;2\n", "text/csv")},
    )
    assert response.status_code == 422
