import io

import pandas as pd

from app.models.record import IngestedRecord, Job, Organization, Person
from app.parsers.base import FormatHandler, InvalidFormatError


class XLSXFormatHandler(FormatHandler):
    """Handles the 'data_2/3/4.xlsx' style: raw_* prefixed columns, first/middle/last already split."""

    format_id = "xlsx_format_1"
    extensions = (".xlsx",)

    REQUIRED_COLUMNS = (
        "raw_first", "raw_last", "raw_middle", "raw_email", "raw_phone", "raw_fax",
        "raw_title", "raw_job_title", "raw_position_type", "raw_org_name",
        "raw_date", "raw_uri",
    )

    def probe(self, filename: str, content: bytes) -> bool:
        return filename.lower().endswith(".xlsx") or content[:4] == b"PK\x03\x04"

    def parse(self, content: bytes) -> list[IngestedRecord]:
        try:
            df = pd.read_excel(io.BytesIO(content))
        except Exception as exc:  # noqa: BLE001
            raise InvalidFormatError(f"Could not read XLSX: {exc}") from exc

        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise InvalidFormatError(f"Missing required columns: {missing}")

        return [self._row_to_record(row) for _, row in df.iterrows()]

    def _row_to_record(self, row: pd.Series) -> IngestedRecord:
        person = Person(
            first_name=self._s(row["raw_first"]),
            middle_name=self._s(row["raw_middle"]),
            last_name=self._s(row["raw_last"]),
            email=self._s(row["raw_email"]) or None,
            phone=self._s(row["raw_phone"]) or None,
            fax=self._s(row["raw_fax"]) or None,
            title=self._s(row["raw_title"]) or None,
        )
        organization = Organization(
            org_name=self._s(row["raw_org_name"]),
            org_vivo_uri=self._s(row["raw_uri"]),
        )
        job = Job(
            job_title=self._s(row["raw_job_title"]),
            job_type=self._s(row["raw_position_type"]),
            start_date=self._to_year(row["raw_date"]),
        )
        return IngestedRecord(person=person, organization=organization, job=job)

    @staticmethod
    def _s(value) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).strip()

    @staticmethod
    def _to_year(value) -> int:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return -1
        if isinstance(value, (int, float)) and float(value).is_integer():
            return int(value)
        v = str(value).strip()
        if v == "":
            return -1
        try:
            return int(float(v))
        except ValueError as exc:
            raise InvalidFormatError(f"Invalid start_date: {value!r}") from exc
