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
