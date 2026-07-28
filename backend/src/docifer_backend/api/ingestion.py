import asyncio
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from starlette.datastructures import UploadFile

from docifer_backend.config.paths import resolve_project_path
from docifer_backend.config.settings import get_settings
from docifer_backend.ingestion.service import IngestionService
from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.tables.indexing import TableIndexingService
from docifer_backend.retrieval.visuals.indexing import VisualIndexingService
from docifer_backend.schemas.ingestion import IngestPdfRequest, IngestionJobResponse

_PDF_MAGIC = b"%PDF"


def _validate_data_path(path_str: str, *allowed_roots: Path) -> Path:
    resolved = Path(path_str).resolve()
    for root in allowed_roots:
        if resolved.is_relative_to(root.resolve()):
            return resolved
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Path is outside the allowed data directories.",
    )


def _get_uploads_dir() -> Path:
    return Path(__file__).parents[3] / "uploads"


def _sanitise_filename(name: str) -> str:
    name = Path(name).name
    stem = Path(name).stem or "document"
    stem = re.sub(r"[^\w\-.]", "_", stem)
    stem = stem[: max(1, 116)]  # leave room for .pdf (4 chars)
    return stem + ".pdf"


def _format_bytes(value: int) -> str:
    units = ("bytes", "KB", "MB", "GB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    if unit == "bytes":
        return f"{int(amount)} {unit}"
    return f"{amount:.1f} {unit}"


async def _write_upload_file(file: UploadFile, dest: Path, *, max_bytes: int) -> None:
    total = 0
    try:
        with dest.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            f"Uploaded file exceeds the configured limit of "
                            f"{_format_bytes(max_bytes)}."
                        ),
                    )
                output.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise


router = APIRouter(prefix="/ingestion", tags=["ingestion"])

_ingestion_service: IngestionService | None = None


def _get_ingestion_service() -> IngestionService:
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service


@router.post(
    "/jobs",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ingestion_job(request: IngestPdfRequest) -> IngestionJobResponse:
    settings = get_settings()
    _validate_data_path(
        request.source_path,
        resolve_project_path(settings.raw_pdf_dir),
        _get_uploads_dir(),
    )
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

    if outcome.artifact_path:
        await asyncio.to_thread(
            _index_all,
            outcome.artifact_path,
            force_reindex=request.force_reprocess,
        )
        return IngestionJobResponse(**{**outcome.__dict__, "status": "indexed"})
    return IngestionJobResponse(**outcome.__dict__)


@router.post(
    "/upload",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_pdf(request: Request) -> IngestionJobResponse:
    settings = get_settings()
    max_upload_bytes = settings.upload_max_file_size_bytes
    form = await request.form()
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
    await _write_upload_file(file, dest, max_bytes=max_upload_bytes)

    with dest.open("rb") as f:
        if f.read(len(_PDF_MAGIC)) != _PDF_MAGIC:
            dest.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is not a valid PDF.",
            )

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

    if outcome.artifact_path:
        try:
            await asyncio.to_thread(
                _index_all,
                outcome.artifact_path,
                force_reindex=force_reprocess,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Indexing pipeline error.",
            ) from exc
        return IngestionJobResponse(**{**outcome.__dict__, "status": "indexed"})
    return IngestionJobResponse(**outcome.__dict__)


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(job_id: str) -> IngestionJobResponse:
    outcome = await asyncio.to_thread(_get_ingestion_job, job_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found.")
    return IngestionJobResponse(**outcome.__dict__)


def _ingest_pdf(source_path: str, *, force_reprocess: bool):
    return _get_ingestion_service().ingest_pdf(
        source_path,
        force_reprocess=force_reprocess,
    )


def _index_all(canonical_path: str, *, force_reindex: bool = False) -> None:
    TextIndexingService().index_canonical_document(canonical_path, force_reindex=force_reindex)
    TableIndexingService().index_canonical_document(canonical_path, force_reindex=force_reindex)
    VisualIndexingService().index_canonical_document(canonical_path, force_reindex=force_reindex)


def _get_ingestion_job(job_id: str):
    return _get_ingestion_service().get_job(job_id)
