import asyncio
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from starlette.datastructures import UploadFile

from docifer_backend.config.settings import get_settings
from docifer_backend.ingestion.service import IngestionService
from docifer_backend.schemas.ingestion import IngestPdfRequest, IngestionJobResponse


def _get_uploads_dir() -> Path:
    return Path(__file__).parents[3] / "uploads"


def _sanitise_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w\-.]", "_", name)
    stem = name[: max(1, 116)]  # leave room for .pdf (4 chars)
    return stem + ".pdf"


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
async def upload_pdf(request: Request) -> IngestionJobResponse:
    settings = get_settings()
    max_bytes = settings.docling_max_file_size_bytes
    form = await request.form(max_part_size=max_bytes)
    file = form.get("file")
    force_reprocess_raw = form.get("force_reprocess", "false")
    force_reprocess = str(force_reprocess_raw).lower() in ("true", "1")

    if not isinstance(file, UploadFile):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file field.")
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
    data = await file.read()
    dest.write_bytes(data)

    try:
        outcome = await asyncio.to_thread(
            _ingest_pdf,
            str(dest),
            force_reprocess=force_reprocess,
        )
    except FileNotFoundError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingestion pipeline error.",
        ) from exc

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
