from collections.abc import Callable
import logging
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Query, status

from docifer_backend.documents.service import (
    DocumentRegistryAmbiguousError,
    DocumentRegistryNotFoundError,
    DocumentRegistryService,
)
from docifer_backend.schemas.documents import (
    DocumentArtifactsResponse,
    DocumentAuditResponse,
    DocumentDetailResponse,
    DocumentIndexStatusResponse,
    DocumentListResponse,
    DocumentModalityStatus,
)

router = APIRouter(prefix="/documents", tags=["documents"])
ResponseT = TypeVar("ResponseT")
logger = logging.getLogger(__name__)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    q: str | None = None,
    doc_id: str | None = None,
    quality_status: str | None = None,
    text_status: DocumentModalityStatus | None = None,
    table_status: DocumentModalityStatus | None = None,
    visual_status: DocumentModalityStatus | None = None,
    parser_name: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DocumentListResponse:
    return _run_service_call(
        lambda: DocumentRegistryService().list_documents(
            q=q,
            doc_id=doc_id,
            quality_status=quality_status,
            text_status=text_status,
            table_status=table_status,
            visual_status=visual_status,
            parser_name=parser_name,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/by-doc-id/{doc_id}", response_model=DocumentDetailResponse)
def get_document_by_doc_id(doc_id: str) -> DocumentDetailResponse:
    return _run_service_call(lambda: DocumentRegistryService().get_by_doc_id(doc_id))


@router.get("/by-content-hash/{content_hash}", response_model=DocumentDetailResponse)
def get_document_by_content_hash(content_hash: str) -> DocumentDetailResponse:
    return _run_service_call(
        lambda: DocumentRegistryService().get_by_content_hash(content_hash)
    )


@router.get("/{document_id}/indexes", response_model=DocumentIndexStatusResponse)
def get_document_indexes(document_id: str) -> DocumentIndexStatusResponse:
    return _run_service_call(lambda: DocumentRegistryService().get_indexes(document_id))


@router.get("/{document_id}/audit", response_model=DocumentAuditResponse)
def get_document_audit(document_id: str) -> DocumentAuditResponse:
    return _run_service_call(lambda: DocumentRegistryService().get_audit(document_id))


@router.get("/{document_id}/artifacts", response_model=DocumentArtifactsResponse)
def get_document_artifacts(document_id: str) -> DocumentArtifactsResponse:
    return _run_service_call(lambda: DocumentRegistryService().get_artifacts(document_id))


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(document_id: str) -> DocumentDetailResponse:
    return _run_service_call(lambda: DocumentRegistryService().get_document(document_id))


def _run_service_call(operation: Callable[[], ResponseT]) -> ResponseT:
    try:
        return operation()
    except DocumentRegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DocumentRegistryAmbiguousError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unable to load document registry state: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load document registry state.",
        ) from exc
