from __future__ import annotations

from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from docifer_backend.ingestion.models import Document
from docifer_backend.providers.base import (
    CitationGroundingVerdict,
    GroundingEvidence,
    VisualInterpretationResult,
)
from docifer_backend.retrieval.document_registry import DocumentScopeResolver
from docifer_backend.retrieval.models import TextChunkRecord
from docifer_backend.retrieval.query import TextQueryService
from docifer_backend.retrieval.tables.schemas import TableQueryResult
from docifer_backend.retrieval.vector_store import _content_hash_filter
from docifer_backend.retrieval.visuals.schemas import VisualQueryResult
from docifer_backend.schemas.retrieval import QueryRequest
from docifer_backend.storage.database import Base


class FakeAIProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 1.0] for _ in texts]

    def generate_grounded_answer(
        self,
        *,
        question: str,
        evidence: list[GroundingEvidence],
    ) -> str:
        cited = " ".join(f"[{item.citation_id}]" for item in evidence[:2])
        return f"Compared evidence supports the response. {cited}"

    def verify_citation_grounding(self, **kwargs) -> CitationGroundingVerdict:
        return CitationGroundingVerdict(
            verdict="supported",
            supported_citation_ids=["C1", "C2"],
            weak_citation_ids=[],
            unsupported_claims=[],
            reasoning="Supported.",
            revised_answer=None,
        )

    def interpret_visual_evidence(self, **kwargs) -> VisualInterpretationResult:
        return VisualInterpretationResult(
            status="supported",
            answer="The selected visuals support the response. [V1]",
            observations=[],
            used_citation_ids=["V1"],
            abstain_reason="",
            reasoning="Supported.",
        )


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed_text_documents(session_factory) -> None:
    documents = [
        ("doc-005", "a" * 64, "Worldbank2024.pdf", "datasets/raw_pdfs/Worldbank2024.pdf"),
        ("doc-007", "b" * 64, "OECD.pdf", "datasets/raw_pdfs/OECD.pdf"),
    ]
    with session_factory() as session:
        for document_id, content_hash, filename, source_path in documents:
            session.add(
                Document(
                    id=document_id,
                    filename=filename,
                    source_path=source_path,
                    content_hash=content_hash,
                    file_size_bytes=100,
                )
            )
            for index in range(2):
                session.add(
                    TextChunkRecord(
                        id=f"{document_id}-{index}",
                        document_id=document_id,
                        content_hash=content_hash,
                        chunk_id=f"{content_hash[:4]}:text:{index:04d}",
                        chunk_index=index,
                        text=f"Strategy growth evidence for {filename} section {index}.",
                        page_start=index + 1,
                        page_end=index + 1,
                        source_path=source_path,
                        source_artifact_path=f"datasets/processed/{content_hash[:12]}/canonical.json",
                        qdrant_point_id=f"{document_id}-{index}",
                    )
                )
        session.commit()


def _service(session_factory) -> TextQueryService:
    return TextQueryService(
        ai_provider=FakeAIProvider(),
        qdrant_client=QdrantClient(":memory:"),
        session_factory=session_factory,
        collection_name="test_text_chunks",
    )


def test_query_request_requires_explicit_scope_for_corpus_queries():
    try:
        QueryRequest(question="Compare the reports.")
    except ValueError as exc:
        assert "scope='single'" in str(exc)
    else:
        raise AssertionError("Expected an unscoped query to fail validation.")

    request = QueryRequest(question="Compare the reports.", scope="all")
    assert request.scope == "all"


def test_document_scope_resolves_external_doc_ids_and_internal_ids():
    session_factory = _session_factory()
    _seed_text_documents(session_factory)
    resolver = DocumentScopeResolver(session_factory=session_factory)

    external = resolver.resolve(
        scope="doc_ids",
        content_hash=None,
        doc_ids=["DOC-005"],
        document_ids=None,
        evidence_types={"text"},
    )
    internal = resolver.resolve(
        scope="single",
        content_hash=None,
        doc_ids=None,
        document_ids=["doc-007"],
        evidence_types={"text"},
    )

    assert external.documents[0].document_id == "doc-005"
    assert external.documents[0].doc_id == "DOC-005"
    assert internal.documents[0].content_hash == "b" * 64


def test_multi_document_query_caps_per_document_and_enriches_citations():
    session_factory = _session_factory()
    _seed_text_documents(session_factory)

    outcome = _service(session_factory).query(
        question="Compare strategy growth evidence.",
        scope="doc_ids",
        doc_ids=["DOC-005", "DOC-007"],
        top_k=4,
        max_documents=2,
        max_evidence_per_document=1,
        retrieval_mode="bm25",
    )

    assert len(outcome.evidence) == 2
    assert {chunk.doc_id for chunk in outcome.evidence} == {"DOC-005", "DOC-007"}
    assert {citation.document_id for citation in outcome.citations} == {"doc-005", "doc-007"}
    assert outcome.debug["scope"] == "doc_ids"
    assert outcome.debug["documents_used_count"] == 2
    assert all(item["text_count"] == 1 for item in outcome.debug["evidence_by_document"])


def test_scope_all_searches_all_indexed_text_documents():
    session_factory = _session_factory()
    _seed_text_documents(session_factory)

    outcome = _service(session_factory).query(
        question="Compare strategy growth evidence.",
        scope="all",
        top_k=4,
        max_documents=2,
        max_evidence_per_document=1,
        retrieval_mode="bm25",
    )

    assert outcome.debug["documents_searched_count"] == 2
    assert outcome.debug["candidate_pool_top_k"] == 50
    assert {item["doc_id"] for item in outcome.debug["documents_searched"]} == {
        "DOC-005",
        "DOC-007",
    }


def test_selected_document_scope_is_forwarded_to_table_retrieval():
    session_factory = _session_factory()
    _seed_text_documents(session_factory)
    service = _service(session_factory)
    service.table_retriever = CapturingTableRetriever()

    outcome = service.query(
        question="Compare the table values.",
        scope="doc_ids",
        doc_ids=["DOC-005", "DOC-007"],
        evidence_mode="table",
        table_top_k=2,
        max_evidence_per_document=1,
    )

    assert service.table_retriever.content_hashes == ["a" * 64, "b" * 64]
    assert {table.doc_id for table in outcome.table_evidence} == {"DOC-005", "DOC-007"}


def test_selected_document_scope_is_forwarded_to_visual_retrieval():
    session_factory = _session_factory()
    _seed_text_documents(session_factory)
    service = _service(session_factory)
    service.visual_retriever = CapturingVisualRetriever()

    outcome = service.query(
        question="Compare the charts.",
        scope="doc_ids",
        doc_ids=["DOC-005", "DOC-007"],
        evidence_mode="visual",
        visual_top_k=2,
        max_evidence_per_document=1,
    )

    assert service.visual_retriever.content_hashes == ["a" * 64, "b" * 64]
    assert {visual.doc_id for visual in outcome.visual_evidence} == {"DOC-005", "DOC-007"}


def test_multi_content_hash_filter_uses_match_any():
    query_filter = _content_hash_filter(None, ["a" * 64, "b" * 64])

    assert query_filter is not None
    assert query_filter.must[0].match.any == ["a" * 64, "b" * 64]


class CapturingTableRetriever:
    content_hashes: list[str] | None = None

    def search(self, *, query, top_k, content_hash=None, content_hashes=None, retrieval_mode):
        self.content_hashes = content_hashes
        return [
            TableQueryResult(
                table_id=f"table-{index}",
                score=1.0 - (index * 0.1),
                dense_score=None,
                lexical_score=1.0,
                hybrid_score=1.0,
                retrieval_mode="table_hybrid",
                table_type="structured",
                source_kind="docling",
                page_start=1,
                page_end=1,
                raw_text="Metric | value",
                markdown_table=None,
                structured_json=None,
                section_heading=None,
                table_readiness="good",
                document_id=document_id,
                content_hash=content_hash,
                filename=filename,
                source_path=f"datasets/raw_pdfs/{filename}",
                source_artifact_path="datasets/processed/canonical.json",
                source_chunk_id=None,
            )
            for index, (document_id, content_hash, filename) in enumerate(
                [
                    ("doc-005", "a" * 64, "Worldbank2024.pdf"),
                    ("doc-007", "b" * 64, "OECD.pdf"),
                ]
            )
        ]


class CapturingVisualRetriever:
    content_hashes: list[str] | None = None

    def search(self, *, query, top_k, content_hash=None, content_hashes=None, retrieval_mode):
        self.content_hashes = content_hashes
        return [
            VisualQueryResult(
                visual_id=f"visual-{index}",
                score=1.0 - (index * 0.1),
                dense_score=None,
                lexical_score=1.0,
                hybrid_score=1.0,
                retrieval_mode="visual_hybrid",
                visual_type="page_render",
                source_kind="page_render",
                page_start=1,
                page_end=1,
                artifact_path="datasets/processed/page.jpg",
                caption=None,
                section_heading=None,
                nearby_text="A chart.",
                figure_label=None,
                visual_readiness="good",
                document_id=document_id,
                content_hash=content_hash,
                filename=filename,
                source_path=f"datasets/raw_pdfs/{filename}",
                source_artifact_path="datasets/processed/canonical.json",
            )
            for index, (document_id, content_hash, filename) in enumerate(
                [
                    ("doc-005", "a" * 64, "Worldbank2024.pdf"),
                    ("doc-007", "b" * 64, "OECD.pdf"),
                ]
            )
        ]
