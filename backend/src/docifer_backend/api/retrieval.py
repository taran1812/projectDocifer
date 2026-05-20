from fastapi import APIRouter

from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.query import TextQueryService
from docifer_backend.schemas.retrieval import (
    CitationResponse,
    EvidenceResponse,
    CitationVerificationResponse,
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
        retrieval_mode=request.retrieval_mode,
        verify_citations=request.verify_citations,
    )
    evidence = _evidence_responses(outcome.evidence)
    unused_chunk_ids = {chunk.chunk_id for chunk in outcome.unused_evidence}
    unused_evidence = _evidence_responses(
        outcome.evidence,
        include_chunk_ids=unused_chunk_ids,
    )
    citations = [CitationResponse(**citation.__dict__) for citation in outcome.citations]

    return QueryResponse(
        answer=outcome.answer,
        citations=citations,
        answer_citations=citations,
        evidence=evidence,
        retrieved_evidence=evidence,
        unused_retrieved_evidence=unused_evidence,
        citation_verification=(
            CitationVerificationResponse(**outcome.citation_verification.__dict__)
            if outcome.citation_verification is not None
            else None
        ),
        debug=outcome.debug,
    )


def _evidence_responses(chunks, *, include_chunk_ids: set[str] | None = None) -> list[EvidenceResponse]:
    responses = []
    for index, chunk in enumerate(chunks, start=1):
        if include_chunk_ids is not None and chunk.chunk_id not in include_chunk_ids:
            continue
        responses.append(
            EvidenceResponse(
                citation_id=f"C{index}",
                chunk_id=chunk.chunk_id,
                score=chunk.score,
                dense_score=chunk.dense_score,
                lexical_score=chunk.lexical_score,
                hybrid_score=chunk.hybrid_score,
                retrieval_mode=chunk.retrieval_mode,
                text=chunk.text,
                source_path=chunk.source_path,
                source_artifact_path=chunk.source_artifact_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
        )
    return responses
