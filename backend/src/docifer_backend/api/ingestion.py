import asyncio
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile, status

from docifer_backend.ingestion.service import IngestionService
from docifer_backend.schemas.ingestion import IngestPdfRequest, IngestionJobResponse


def _get_uploads_dir() -> Path:
    return Path(__file__).parents[3] / "uploads"


def _sanitise_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:120]


router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post(
    "/jobs",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ingestion_job(request: IngestPdfRequest) -> IngestionJobResponse:
    try:
        outcome = await asyncio.to_thread(
            _ingest_pdf,
            request.source_path,
            force_reprocess=request.force_reprocess,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return IngestionJobResponse(**outcome.__dict__)


@router.post(
    "/upload",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_pdf(
    file: UploadFile,
    force_reprocess: bool = Form(False),
) -> IngestionJobResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a .pdf extension.",
        )
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected content-type application/pdf, got {file.content_type!r}.",
        )

    uploads_dir = _get_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitise_filename(file.filename)
    dest = uploads_dir / f"{uuid.uuid4().hex}_{safe_name}"
    dest.write_bytes(await file.read())

    try:
        outcome = await asyncio.to_thread(
            _ingest_pdf,
            str(dest),
            force_reprocess=force_reprocess,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return IngestionJobResponse(**outcome.__dict__)


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(job_id: str) -> IngestionJobResponse:
    outcome = await asyncio.to_thread(_get_ingestion_job, job_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found.")
    return IngestionJobResponse(**outcome.__dict__)


def _ingest_pdf(source_path: str, *, force_reprocess: bool):
    return IngestionService().ingest_pdf(
        source_path,
        force_reprocess=force_reprocess,
    )


def _get_ingestion_job(job_id: str):
    return IngestionService().get_job(job_id)
