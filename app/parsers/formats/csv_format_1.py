import io

import pandas as pd

from app.models.record import IngestedRecord, Job, Organization, Person
from app.parsers.base import FormatHandler, InvalidFormatError


class CSVFormatHandler(FormatHandler):
    """Handles the 'data_1.csv' style: semicolon-delimited, UTF-8 BOM, first+middle fused in
    'dataFirstNames' as 'first, middle'."""

    format_id = "csv_format_1"
    extensions = (".csv",)

    REQUIRED_COLUMNS = (
        "dataFirstNames", "dataLastName", "dataEmail", "dataPhone", "dataFax",
        "dataTitle", "dataJobTitle", "dataPositionType", "dataOrganization",
        "dataJobStartDate", "dataURI",
    )

    def probe(self, filename: str, content: bytes) -> bool:
        # Check if the file has a .csv extension (case-insensitive)
        # This is a simple heuristic; more complex probing could be added if needed.
        
        return filename.lower().endswith(".csv")

    def parse(self, content: bytes) -> list[IngestedRecord]:
        try:
            df = pd.read_csv(
                io.BytesIO(content), sep=";", encoding="utf-8-sig",
                dtype=str, keep_default_na=False,
            )
        except Exception as exc:  # noqa: BLE001 - wrap any read error
            raise InvalidFormatError(f"Could not read CSV: {exc}") from exc

        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise InvalidFormatError(f"Missing required columns: {missing}")

        return [self._row_to_record(row) for _, row in df.iterrows()]

    def _row_to_record(self, row: pd.Series) -> IngestedRecord:
        first, middle = self._split_name(row["dataFirstNames"])
        person = Person(
            first_name=first,
            middle_name=middle,
            last_name=self._s(row["dataLastName"]),
            email=self._s(row["dataEmail"]) or None,
            phone=self._s(row["dataPhone"]) or None,
            fax=self._s(row["dataFax"]) or None,
            title=self._s(row["dataTitle"]) or None,
        )
        organization = Organization(
            org_name=self._s(row["dataOrganization"]),
            org_vivo_uri=self._s(row["dataURI"]),
        )
        job = Job(
            job_title=self._s(row["dataJobTitle"]),
            job_type=self._s(row["dataPositionType"]),
            start_date=self._to_year(row["dataJobStartDate"]),
        )
        return IngestedRecord(person=person, organization=organization, job=job)

    @staticmethod
    def _s(value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _split_name(value) -> tuple[str, str]:
        v = str(value).strip()
        if ", " in v:
            first, middle = v.split(", ", 1)
        elif "," in v:
            first, middle = v.split(",", 1)
        else:
            first, middle = v, ""
        return first.strip(), middle.strip()

    @staticmethod
    def _to_year(value) -> int:
        v = str(value).strip()
        if v == "":
            return -1
        try:
            return int(v)
        except ValueError as exc:
            raise InvalidFormatError(f"Invalid start_date: {value!r}") from exc
