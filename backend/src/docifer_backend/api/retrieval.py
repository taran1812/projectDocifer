from fastapi import APIRouter

from docifer_backend.retrieval.indexing import TextIndexingService
from docifer_backend.retrieval.query import TextQueryService
from docifer_backend.retrieval.vector_store import vector_search_debug
from docifer_backend.retrieval.tables.indexing import TableIndexingService
from docifer_backend.retrieval.visuals.indexing import VisualIndexingService
from docifer_backend.retrieval.visuals.retriever import VisualRetriever
from docifer_backend.schemas.retrieval import (
    CitationResponse,
    EvidenceResponse,
    CitationVerificationResponse,
    QueryRequest,
    QueryResponse,
    TableCitationResponse,
    TableEvidenceResponse,
    TableIndexRequest,
    TableIndexResponse,
    TextIndexRequest,
    TextIndexResponse,
    VisualCandidateResponse,
    VisualCitationResponse,
    VisualEvidenceResponse,
    VisualIndexRequest,
    VisualIndexResponse,
    VisualObservationResponse,
    VisualRetrieveRequest,
    VisualRetrieveResponse,
)

router = APIRouter(tags=["retrieval"])


@router.post("/index/text", response_model=TextIndexResponse)
def index_text(request: TextIndexRequest) -> TextIndexResponse:
    outcome = TextIndexingService().index_canonical_document(
        request.canonical_path,
        force_reindex=request.force_reindex,
    )
    return TextIndexResponse(**outcome.__dict__)


@router.post("/index/tables", response_model=TableIndexResponse)
def index_tables(request: TableIndexRequest) -> TableIndexResponse:
    outcome = TableIndexingService().index_canonical_document(
        request.canonical_path,
        force_reindex=request.force_reindex,
    )
    return TableIndexResponse(**outcome.__dict__)


@router.post("/query", response_model=QueryResponse)
def query_text(request: QueryRequest) -> QueryResponse:
    outcome = TextQueryService().query(
        question=request.question,
        content_hash=request.content_hash,
        top_k=request.top_k,
        retrieval_mode=request.retrieval_mode,
        evidence_mode=request.evidence_mode,
        table_top_k=request.table_top_k,
        visual_top_k=request.visual_top_k,
        verify_citations=request.verify_citations,
        rerank=request.rerank,
        rerank_top_n=request.rerank_top_n,
    )
    evidence = _evidence_responses(outcome.evidence)
    table_evidence = _table_evidence_responses(outcome.table_evidence)
    visual_evidence = _visual_evidence_responses(outcome.visual_evidence)
    unused_chunk_ids = {chunk.chunk_id for chunk in outcome.unused_evidence}
    unused_evidence = _evidence_responses(
        outcome.evidence,
        include_chunk_ids=unused_chunk_ids,
    )
    unused_table_ids = {table.table_id for table in outcome.unused_table_evidence}
    unused_table_evidence = _table_evidence_responses(
        outcome.table_evidence,
        include_table_ids=unused_table_ids,
    )
    unused_visual_ids = {visual.visual_id for visual in outcome.unused_visual_evidence}
    unused_visual_evidence = _visual_evidence_responses(
        outcome.visual_evidence,
        include_visual_ids=unused_visual_ids,
    )
    citations = [CitationResponse(**citation.__dict__) for citation in outcome.citations]
    table_citations = [
        TableCitationResponse(**citation.__dict__)
        for citation in outcome.table_citations
    ]
    visual_citations = [
        VisualCitationResponse(**citation.__dict__)
        for citation in outcome.visual_citations
    ]
    visual_observations = [
        VisualObservationResponse(**observation.__dict__)
        for observation in (
            outcome.visual_interpretation.observations
            if outcome.visual_interpretation is not None
            else []
        )
    ]

    return QueryResponse(
        answer=outcome.answer,
        citations=citations,
        table_citations=table_citations,
        visual_citations=visual_citations,
        answer_citations=citations,
        evidence=evidence,
        table_evidence=table_evidence,
        visual_evidence=visual_evidence,
        visual_observations=visual_observations,
        retrieved_evidence=evidence,
        unused_retrieved_evidence=unused_evidence,
        unused_table_evidence=unused_table_evidence,
        unused_visual_evidence=unused_visual_evidence,
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
                rerank_score=chunk.rerank_score,
                pre_rerank_rank=chunk.pre_rerank_rank,
                post_rerank_rank=chunk.post_rerank_rank,
                reranker_model=chunk.reranker_model,
                retrieval_mode=chunk.retrieval_mode,
                text=chunk.text,
                source_path=chunk.source_path,
                source_artifact_path=chunk.source_artifact_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
        )
    return responses


def _table_evidence_responses(
    tables,
    *,
    include_table_ids: set[str] | None = None,
) -> list[TableEvidenceResponse]:
    responses = []
    for index, table in enumerate(tables, start=1):
        if include_table_ids is not None and table.table_id not in include_table_ids:
            continue
        responses.append(
            TableEvidenceResponse(
                citation_id=f"T{index}",
                table_id=table.table_id,
                score=table.score,
                dense_score=table.dense_score,
                lexical_score=table.lexical_score,
                hybrid_score=table.hybrid_score,
                retrieval_mode=table.retrieval_mode,
                table_type=table.table_type,
                source_kind=table.source_kind,
                table_readiness=table.table_readiness,
                raw_text=table.raw_text,
                markdown_table=table.markdown_table,
                structured_json=table.structured_json,
                section_heading=table.section_heading,
                source_path=table.source_path,
                source_artifact_path=table.source_artifact_path,
                source_chunk_id=table.source_chunk_id,
                page_start=table.page_start,
                page_end=table.page_end,
            )
        )
    return responses


def _visual_evidence_responses(
    visuals,
    *,
    include_visual_ids: set[str] | None = None,
) -> list[VisualEvidenceResponse]:
    responses = []
    for index, visual in enumerate(visuals, start=1):
        if include_visual_ids is not None and visual.visual_id not in include_visual_ids:
            continue
        responses.append(
            VisualEvidenceResponse(
                citation_id=f"V{index}",
                visual_id=visual.visual_id,
                document_id=visual.document_id,
                content_hash=visual.content_hash,
                score=visual.score,
                dense_score=visual.dense_score,
                lexical_score=visual.lexical_score,
                hybrid_score=visual.hybrid_score,
                retrieval_mode=visual.retrieval_mode,
                visual_type=visual.visual_type,
                source_kind=visual.source_kind,
                page_start=visual.page_start,
                page_end=visual.page_end,
                artifact_path=visual.artifact_path,
                caption=visual.caption,
                section_heading=visual.section_heading,
                nearby_text=visual.nearby_text,
                figure_label=visual.figure_label,
                visual_readiness=visual.visual_readiness,
                filename=visual.filename,
                source_path=visual.source_path,
                source_artifact_path=visual.source_artifact_path,
            )
        )
    return responses


@router.post("/index/visuals", response_model=VisualIndexResponse)
def index_visuals(request: VisualIndexRequest) -> VisualIndexResponse:
    outcome = VisualIndexingService().index_canonical_document(
        request.canonical_path,
        force_reindex=request.force_reindex,
    )
    return VisualIndexResponse(**outcome.__dict__)


@router.post("/retrieve/visuals", response_model=VisualRetrieveResponse)
def retrieve_visuals(request: VisualRetrieveRequest) -> VisualRetrieveResponse:
    retriever = VisualRetriever()
    results = retriever.search(
        query=request.question,
        top_k=request.top_k,
        content_hash=request.content_hash,
        retrieval_mode=request.retrieval_mode,
    )
    candidates = [
        VisualCandidateResponse(
            visual_id=result.visual_id,
            document_id=result.document_id,
            content_hash=result.content_hash,
            score=result.score,
            dense_score=result.dense_score,
            lexical_score=result.lexical_score,
            hybrid_score=result.hybrid_score,
            retrieval_mode=result.retrieval_mode,
            visual_type=result.visual_type,
            source_kind=result.source_kind,
            page_start=result.page_start,
            page_end=result.page_end,
            artifact_path=result.artifact_path,
            caption=result.caption,
            section_heading=result.section_heading,
            nearby_text=result.nearby_text,
            figure_label=result.figure_label,
            visual_readiness=result.visual_readiness,
            filename=result.filename,
            source_path=result.source_path,
            source_artifact_path=result.source_artifact_path,
        )
        for result in results
    ]
    debug: dict = {}
    if request.debug:
        debug = {
            "retrieved_count": len(results),
            "retrieval_mode": request.retrieval_mode,
            **vector_search_debug(collection_name=retriever.collection_name),
            "scores": [
                {
                    "visual_id": r.visual_id,
                    "dense_score": r.dense_score,
                    "lexical_score": r.lexical_score,
                    "hybrid_score": r.hybrid_score,
                }
                for r in results
            ],
        }
    return VisualRetrieveResponse(candidates=candidates, debug=debug)
