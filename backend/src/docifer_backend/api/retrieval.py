from fastapi import APIRouter

from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.query import TextQueryService
from docifer_backend.schemas.retrieval import (
    CitationResponse,
    EvidenceResponse,
    QueryRequest,
    QueryResponse,
    TextIndexRequest,
    TextIndexResponse,
)

router = APIRouter(tags=["retrieval"])


@router.post("/index/text", response_model=TextIndexResponse)
def index_text(request: TextIndexRequest) -> TextIndexResponse:
    outcome = TextIndexingService().index_canonical_document(
        request.canonical_path,
        force_reindex=request.force_reindex,
    )
    return TextIndexResponse(**outcome.__dict__)


@router.post("/query", response_model=QueryResponse)
def query_text(request: QueryRequest) -> QueryResponse:
    outcome = TextQueryService().query(
        question=request.question,
        content_hash=request.content_hash,
        top_k=request.top_k,
    )
    citation_by_id = {citation.citation_id: citation for citation in outcome.citations}
    evidence = []
    for index, chunk in enumerate(outcome.evidence, start=1):
        citation_id = f"C{index}"
        citation = citation_by_id[citation_id]
        evidence.append(
            EvidenceResponse(
                citation_id=citation_id,
                chunk_id=chunk.chunk_id,
                score=chunk.score,
                text=chunk.text,
                source_path=citation.source_path,
                source_artifact_path=citation.source_artifact_path,
                page_start=citation.page_start,
                page_end=citation.page_end,
            )
        )

    return QueryResponse(
        answer=outcome.answer,
        citations=[CitationResponse(**citation.__dict__) for citation in outcome.citations],
        evidence=evidence,
        debug=outcome.debug,
    )
