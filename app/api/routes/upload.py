from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_conn, get_registry
from app.models.responses import UploadSummary
from app.parsers.base import InvalidFormatError, UnsupportedFormatError
from app.services.ingest import ingest

router = APIRouter()


@router.post("/upload", response_model=UploadSummary)
async def upload_file(
    file: UploadFile | None = File(None),
    conn=Depends(get_conn),
    registry=Depends(get_registry),
):
    if file is None:
        raise HTTPException(status_code=400, detail="Missing file part")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        result = ingest(conn, registry, file.filename or "", content)
    except UnsupportedFormatError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except InvalidFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return UploadSummary(
        format=result.format,
        persons_created=result.persons_created,
        persons_updated=result.persons_updated,
        jobs_created=result.jobs_created,
        organizations_created=result.organizations_created,
        history_rows_written=result.history_rows_written,
    )
