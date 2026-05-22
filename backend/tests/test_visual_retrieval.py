import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from docifer_backend.retrieval.visuals.models import DocumentVisualIndexRun, VisualEvidenceRecord
from docifer_backend.storage.database import Base


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_visual_evidence_record_persists(session_factory):
    with session_factory() as session:
        record = VisualEvidenceRecord(
            document_id="doc-1",
            content_hash="c" * 64,
            canonical_path="datasets/processed/cccccccccccc/job1/canonical.json",
            filename="sample.pdf",
            source_path="datasets/raw_pdfs/sample.pdf",
            source_artifact_path="datasets/processed/cccccccccccc/job1/canonical.json",
            visual_id="cccccccccccc:picture:0000",
            visual_index=0,
            visual_type="docling_picture",
            source_kind="docling_picture",
            page_start=3,
            page_end=3,
            artifact_path="datasets/processed/cccccccccccc/job1/visuals/pages/page_0003.jpg",
            caption="Figure 1: Trade growth",
            section_heading="Trade Policy",
            nearby_text="As shown in the figure below...",
            figure_label="Figure 1",
            visual_readiness="good",
            extraction_method="docling_picture",
            source_chunk_ids_json=["chunk:text:0002"],
            span_hash=None,
        )
        session.add(record)
        session.commit()

    with session_factory() as session:
        loaded = session.scalar(
            select(VisualEvidenceRecord).where(
                VisualEvidenceRecord.visual_id == "cccccccccccc:picture:0000"
            )
        )
        assert loaded is not None
        assert loaded.caption == "Figure 1: Trade growth"
        assert loaded.visual_type == "docling_picture"
        assert loaded.qdrant_point_id is None


def test_document_visual_index_run_persists(session_factory):
    with session_factory() as session:
        run = DocumentVisualIndexRun(
            document_id="doc-1",
            content_hash="c" * 64,
            canonical_path="datasets/processed/cccccccccccc/job1/canonical.json",
            status="indexed",
            page_render_count=10,
            figure_candidate_count=3,
            visual_record_count=13,
            collection_name="docifer_visual_evidence",
        )
        session.add(run)
        session.commit()

    with session_factory() as session:
        loaded = session.scalar(select(DocumentVisualIndexRun))
        assert loaded.status == "indexed"
        assert loaded.visual_record_count == 13


from qdrant_client import QdrantClient

from docifer_backend.retrieval.vector_store import (
    delete_visual_evidence_by_content_hash,
    ensure_visual_collection,
    search_visual_evidence_points,
    upsert_visual_evidence,
)
from docifer_backend.retrieval.visuals.schemas import VisualEvidence


def _make_visual_evidence(visual_id: str, page: int) -> VisualEvidence:
    return VisualEvidence(
        visual_id=visual_id,
        visual_index=page - 1,
        document_id="doc-1",
        content_hash="c" * 64,
        canonical_path="datasets/processed/cccccccccccc/job1/canonical.json",
        filename="sample.pdf",
        source_path="datasets/raw_pdfs/sample.pdf",
        source_artifact_path="datasets/processed/cccccccccccc/job1/canonical.json",
        visual_type="page_render",
        source_kind="page_render",
        page_start=page,
        page_end=page,
        artifact_path=f"datasets/processed/cccccccccccc/job1/visuals/pages/page_{page:04d}.jpg",
        caption=None,
        section_heading="Introduction",
        nearby_text="Regional trade statistics for 2023.",
        figure_label=None,
        visual_readiness="weak",
        extraction_method="page_render",
        source_chunk_ids=[],
        span_hash=None,
    )


_POINT_IDS = [
    "00000000-0000-0000-0000-000000000001",
    "00000000-0000-0000-0000-000000000002",
    "00000000-0000-0000-0000-000000000003",
]


def test_upsert_and_search_visual_evidence():
    client = QdrantClient(":memory:")
    visuals = [_make_visual_evidence(f"cccccccccccc:page:{i:04d}", i) for i in range(1, 4)]
    embeddings = [[float(i), 0.0, 0.0, 1.0] for i in range(1, 4)]
    point_ids = _POINT_IDS

    upsert_visual_evidence(
        client,
        collection_name="test_visual",
        visuals=visuals,
        embeddings=embeddings,
        point_ids=point_ids,
    )

    results = search_visual_evidence_points(
        client,
        collection_name="test_visual",
        query_vector=[3.0, 0.0, 0.0, 1.0],
        top_k=2,
        content_hash="c" * 64,
    )
    assert len(results) == 2
    assert results[0][0].startswith("cccccccccccc:page:")


def test_delete_visual_evidence_by_content_hash():
    client = QdrantClient(":memory:")
    visuals = [_make_visual_evidence("cccccccccccc:page:0001", 1)]
    upsert_visual_evidence(
        client,
        collection_name="test_visual",
        visuals=visuals,
        embeddings=[[1.0, 0.0, 0.0, 1.0]],
        point_ids=[_POINT_IDS[0]],
    )
    delete_visual_evidence_by_content_hash(client, collection_name="test_visual", content_hash="c" * 64)
    results = search_visual_evidence_points(
        client,
        collection_name="test_visual",
        query_vector=[1.0, 0.0, 0.0, 1.0],
        top_k=5,
        content_hash="c" * 64,
    )
    assert results == []


from docifer_backend.retrieval.visuals.rendering import render_pdf_pages


def test_render_pdf_pages_creates_jpegs(tmp_path):
    import pypdfium2 as pdfium

    # Create a minimal valid PDF with 3 pages using pypdfium2
    pdf = pdfium.PdfDocument.new()
    for _ in range(3):
        page = pdf.new_page(595, 842)
        page.close()
    pdf_path = tmp_path / "test.pdf"
    pdf.save(str(pdf_path))
    pdf.close()

    output_dir = tmp_path / "pages"
    results = render_pdf_pages(pdf_path, output_dir, scale=0.5)

    assert len(results) == 3
    for page_number, jpeg_path in results:
        assert jpeg_path.exists()
        assert jpeg_path.suffix == ".jpg"
        assert jpeg_path.stat().st_size > 0

    page_numbers = [r[0] for r in results]
    assert page_numbers == [1, 2, 3]
    assert (output_dir / "page_0001.jpg").exists()
    assert (output_dir / "page_0002.jpg").exists()
    assert (output_dir / "page_0003.jpg").exists()


import json

from docifer_backend.retrieval.visuals.extraction import extract_visual_evidence_from_canonical


def write_visual_canonical_artifacts(tmp_path):
    content_hash = "v" * 64
    source_path = str(tmp_path / "sample.pdf")
    docling_path = tmp_path / "docling.json"
    markdown_path = tmp_path / "document.md"
    canonical_path = tmp_path / "canonical.json"

    docling_path.write_text(
        json.dumps({
            "texts": [
                {
                    "label": "section_header",
                    "text": "Economic Trends",
                    "prov": [{"page_no": 5}],
                    "self_ref": "#/texts/0",
                },
                {
                    "label": "caption",
                    "text": "Figure 2: GDP growth trajectory 2010-2023",
                    "prov": [{"page_no": 5}],
                    "self_ref": "#/texts/1",
                },
            ],
            "pictures": [
                {
                    "captions": [{"$ref": "#/texts/1"}],
                    "prov": [{"page_no": 5, "bbox": {"l": 50, "t": 200, "r": 500, "b": 600}}],
                    "self_ref": "#/pictures/0",
                }
            ],
        }),
        encoding="utf-8",
    )
    markdown_path.write_text(
        "\n".join([
            "<!-- page 4 -->",
            "This section covers trade policy analysis.",
            "<!-- page 5 -->",
            "Economic Trends section begins here.",
            "Figure 2 illustrates the GDP growth trajectory across major economies.",
        ]),
        encoding="utf-8",
    )
    canonical_path.write_text(
        json.dumps({
            "artifacts": {
                "docling_json": str(docling_path),
                "markdown": str(markdown_path),
                "directory": str(tmp_path),
            },
            "document": {
                "content_hash": content_hash,
                "filename": "sample.pdf",
                "source_path": source_path,
            },
            "parser": {"name": "docling"},
            "parse": {"page_count": 5, "figure_count": 1, "table_count": 0, "errors": []},
        }),
        encoding="utf-8",
    )
    return canonical_path, content_hash, source_path


def test_docling_picture_extraction(tmp_path):
    canonical_path, content_hash, _ = write_visual_canonical_artifacts(tmp_path)
    evidence = extract_visual_evidence_from_canonical(canonical_path)

    pictures = [e for e in evidence if e.source_kind == "docling_picture"]
    assert len(pictures) == 1
    assert pictures[0].caption == "Figure 2: GDP growth trajectory 2010-2023"
    assert pictures[0].page_start == 5
    assert pictures[0].visual_type == "docling_picture"
    assert pictures[0].section_heading == "Economic Trends"
    assert pictures[0].visual_readiness == "good"
    assert pictures[0].visual_id.endswith(":picture:0000")


def test_page_render_records_created_for_all_pages(tmp_path):
    canonical_path, content_hash, _ = write_visual_canonical_artifacts(tmp_path)
    evidence = extract_visual_evidence_from_canonical(canonical_path)

    pages = [e for e in evidence if e.source_kind == "page_render"]
    assert len(pages) == 5
    page_numbers = sorted(e.page_start for e in pages)
    assert page_numbers == [1, 2, 3, 4, 5]
    page5 = next(e for e in pages if e.page_start == 5)
    assert "Economic Trends" in (page5.nearby_text or "")


def test_figure_candidate_fallback_when_no_docling_pictures(tmp_path):
    content_hash = "f" * 64
    docling_path = tmp_path / "docling.json"
    markdown_path = tmp_path / "document.md"
    canonical_path = tmp_path / "canonical.json"

    docling_path.write_text(json.dumps({"texts": [], "pictures": []}), encoding="utf-8")
    markdown_path.write_text(
        "\n".join([
            "<!-- page 3 -->",
            "Figure 1: Poverty rate trends show a declining trajectory.",
            "<!-- page 7 -->",
            "Chart 2 shows the GDP comparison across countries.",
        ]),
        encoding="utf-8",
    )
    canonical_path.write_text(
        json.dumps({
            "artifacts": {
                "docling_json": str(docling_path),
                "markdown": str(markdown_path),
                "directory": str(tmp_path),
            },
            "document": {
                "content_hash": content_hash,
                "filename": "fallback.pdf",
                "source_path": str(tmp_path / "fallback.pdf"),
            },
            "parser": {"name": "docling"},
            "parse": {"page_count": 10, "figure_count": 2, "table_count": 0, "errors": []},
        }),
        encoding="utf-8",
    )

    evidence = extract_visual_evidence_from_canonical(canonical_path)
    candidates = [e for e in evidence if e.source_kind == "text_reference"]
    assert len(candidates) >= 2
    assert any("Figure 1" in (e.figure_label or "") or "Figure 1" in (e.nearby_text or "") for e in candidates)


import json
from pathlib import Path

import pypdfium2 as pdfium
from qdrant_client import QdrantClient
from sqlalchemy import select

from docifer_backend.ingestion.models import Document
from docifer_backend.retrieval.visuals.indexing import (
    VISUAL_INDEX_STATUS_INDEXED,
    VisualIndexingService,
)
from docifer_backend.retrieval.visuals.models import DocumentVisualIndexRun, VisualEvidenceRecord


class FakeVisualAIProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 10) / 10.0, 0.5, 0.3, 1.0] for t in texts]

    def generate_grounded_answer(self, *, question: str, evidence: list) -> str:
        return "No interpretation in Phase 7D."

    def verify_citation_grounding(self, *, question: str, answer: str, evidence: list):
        return None


def write_visual_indexing_artifacts(tmp_path: Path) -> tuple[Path, str, str]:
    content_hash = "a" * 64
    source_path = tmp_path / "sample.pdf"

    # Create a real 2-page PDF so rendering works
    pdf = pdfium.PdfDocument.new()
    for _ in range(2):
        page = pdf.new_page(595, 842)
        page.close()
    pdf.save(str(source_path))
    pdf.close()

    docling_path = tmp_path / "docling.json"
    markdown_path = tmp_path / "document.md"
    canonical_path = tmp_path / "canonical.json"

    docling_path.write_text(
        json.dumps({
            "texts": [
                {
                    "label": "section_header",
                    "text": "Results",
                    "prov": [{"page_no": 1}],
                    "self_ref": "#/texts/0",
                },
                {
                    "label": "caption",
                    "text": "Figure 1: Main findings",
                    "prov": [{"page_no": 1}],
                    "self_ref": "#/texts/1",
                },
            ],
            "pictures": [
                {
                    "captions": [{"$ref": "#/texts/1"}],
                    "prov": [{"page_no": 1}],
                }
            ],
        }),
        encoding="utf-8",
    )
    markdown_path.write_text(
        "<!-- page 1 -->\nFigure 1 shows the main findings.\n<!-- page 2 -->\nConclusions follow.\n",
        encoding="utf-8",
    )
    canonical_path.write_text(
        json.dumps({
            "artifacts": {
                "docling_json": str(docling_path),
                "markdown": str(markdown_path),
                "directory": str(tmp_path),
            },
            "document": {
                "content_hash": content_hash,
                "filename": "sample.pdf",
                "source_path": str(source_path),
            },
            "parser": {"name": "docling"},
            "parse": {"page_count": 2, "figure_count": 1, "table_count": 0, "errors": []},
        }),
        encoding="utf-8",
    )
    return canonical_path, content_hash, str(source_path)


def test_visual_indexing_creates_records_and_renders_pages(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_visual_indexing_artifacts(tmp_path)
    with session_factory() as session:
        session.add(Document(
            filename="sample.pdf",
            source_path=source_path,
            content_hash=content_hash,
            file_size_bytes=100,
        ))
        session.commit()

    qdrant_client = QdrantClient(":memory:")
    service = VisualIndexingService(
        session_factory=session_factory,
        ai_provider=FakeVisualAIProvider(),
        qdrant_client=qdrant_client,
        collection_name="test_visual_evidence",
        initialize_schema=False,
    )

    outcome = service.index_canonical_document(canonical_path)

    assert outcome.status == VISUAL_INDEX_STATUS_INDEXED
    assert outcome.page_render_count == 2
    # With docling pictures present, figure_candidate_count is 0 (fallback not triggered)
    assert outcome.figure_candidate_count == 0
    assert outcome.visual_record_count >= 3  # 1 docling_picture + 2 page_renders

    with session_factory() as session:
        records = list(session.scalars(select(VisualEvidenceRecord)))
        run = session.scalar(select(DocumentVisualIndexRun))
        assert len(records) == outcome.visual_record_count
        assert all(r.qdrant_point_id for r in records)
        assert run.status == VISUAL_INDEX_STATUS_INDEXED

    # Verify page JPEGs were created
    pages_dir = tmp_path / "visuals" / "pages"
    assert (pages_dir / "page_0001.jpg").exists()
    assert (pages_dir / "page_0002.jpg").exists()


def test_visual_indexing_is_idempotent(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_visual_indexing_artifacts(tmp_path)
    with session_factory() as session:
        session.add(Document(
            filename="sample.pdf",
            source_path=source_path,
            content_hash=content_hash,
            file_size_bytes=100,
        ))
        session.commit()

    qdrant_client = QdrantClient(":memory:")
    service = VisualIndexingService(
        session_factory=session_factory,
        ai_provider=FakeVisualAIProvider(),
        qdrant_client=qdrant_client,
        collection_name="test_visual_evidence",
        initialize_schema=False,
    )

    first = service.index_canonical_document(canonical_path)
    second = service.index_canonical_document(canonical_path)

    assert first.status == VISUAL_INDEX_STATUS_INDEXED
    assert second.reused_existing is True


from docifer_backend.retrieval.visuals.retriever import VisualRetriever


def test_visual_retriever_hybrid_returns_picture_record(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_visual_indexing_artifacts(tmp_path)
    qdrant_client = _index_visual_fixture(canonical_path, content_hash, source_path, session_factory)

    results = VisualRetriever(
        ai_provider=FakeVisualAIProvider(),
        qdrant_client=qdrant_client,
        session_factory=session_factory,
        collection_name="test_visual_evidence",
    ).search(
        query="Which figure shows the main findings?",
        content_hash=content_hash,
        top_k=5,
        retrieval_mode="visual_hybrid",
    )

    assert results
    assert results[0].retrieval_mode == "visual_hybrid"
    assert results[0].hybrid_score is not None
    picture_results = [r for r in results if r.visual_type == "docling_picture"]
    assert picture_results, "Expected at least one docling_picture in hybrid results"


def test_visual_retriever_bm25_scores_figure_label_match(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_visual_indexing_artifacts(tmp_path)
    qdrant_client = _index_visual_fixture(canonical_path, content_hash, source_path, session_factory)

    results = VisualRetriever(
        ai_provider=FakeVisualAIProvider(),
        qdrant_client=qdrant_client,
        session_factory=session_factory,
        collection_name="test_visual_evidence",
    ).search(
        query="Figure 1 main findings",
        content_hash=content_hash,
        top_k=5,
        retrieval_mode="visual_bm25",
    )

    assert results
    assert results[0].lexical_score is not None
    assert results[0].dense_score is None


def _index_visual_fixture(canonical_path, content_hash, source_path, session_factory) -> QdrantClient:
    with session_factory() as session:
        session.add(Document(
            filename="sample.pdf",
            source_path=source_path,
            content_hash=content_hash,
            file_size_bytes=100,
        ))
        session.commit()

    qdrant_client = QdrantClient(":memory:")
    VisualIndexingService(
        session_factory=session_factory,
        ai_provider=FakeVisualAIProvider(),
        qdrant_client=qdrant_client,
        collection_name="test_visual_evidence",
        initialize_schema=False,
    ).index_canonical_document(canonical_path)
    return qdrant_client
