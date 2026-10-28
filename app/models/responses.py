from pydantic import BaseModel


class UploadSummary(BaseModel):
    format: str
    persons_created: int
    persons_updated: int
    jobs_created: int
    organizations_created: int
    history_rows_written: int
