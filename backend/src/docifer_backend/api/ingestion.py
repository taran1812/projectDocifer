import asyncio

from fastapi import APIRouter, HTTPException, status

from docifer_backend.ingestion.service import IngestionService
from docifer_backend.schemas.ingestion import IngestPdfRequest, IngestionJobResponse

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post(
    "/jobs",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ingestion_job(request: IngestPdfRequest) -> IngestionJobResponse:
    try:
        service = IngestionService()
        outcome = await asyncio.to_thread(
            service.ingest_pdf,
            request.source_path,
            force_reprocess=request.force_reprocess,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return IngestionJobResponse(**outcome.__dict__)


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(job_id: str) -> IngestionJobResponse:
    outcome = IngestionService().get_job(job_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found.")
    return IngestionJobResponse(**outcome.__dict__)
