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
