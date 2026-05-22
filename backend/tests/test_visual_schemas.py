from docifer_backend.retrieval.visuals.schemas import (
    VisualEvidence,
    VisualIndexOutcome,
    VisualQueryResult,
    format_visual_evidence_for_embedding,
)


def _make_evidence(**overrides) -> VisualEvidence:
    defaults = dict(
        visual_id="abc:picture:0001",
        visual_index=1,
        document_id="doc-1",
        content_hash="c" * 64,
        canonical_path="datasets/processed/abc/job/canonical.json",
        filename="sample.pdf",
        source_path="datasets/raw_pdfs/sample.pdf",
        source_artifact_path="datasets/processed/abc/job/canonical.json",
        visual_type="docling_picture",
        source_kind="docling_picture",
        page_start=5,
        page_end=5,
        artifact_path="datasets/processed/abc/job/visuals/pages/page_0005.jpg",
        caption="Figure 2: GDP growth trajectory",
        section_heading="Economic Trends",
        nearby_text="The figure below shows GDP growth across regions.",
        figure_label="Figure 2",
        visual_readiness="good",
        extraction_method="docling_picture",
        source_chunk_ids=["chunk:text:0004"],
        span_hash=None,
    )
    defaults.update(overrides)
    return VisualEvidence(**defaults)


def test_format_docling_picture_for_embedding():
    evidence = _make_evidence()
    text = format_visual_evidence_for_embedding(evidence)
    assert "sample.pdf" in text
    assert "Figure 2: GDP growth trajectory" in text
    assert "Economic Trends" in text
    assert "docling_picture" in text
    assert "5" in text


def test_format_page_render_for_embedding():
    evidence = _make_evidence(
        visual_id="abc:page:0001",
        visual_type="page_render",
        source_kind="page_render",
        caption=None,
        figure_label=None,
        extraction_method="page_render",
        nearby_text="This chapter covers regional trade statistics.",
    )
    text = format_visual_evidence_for_embedding(evidence)
    assert "page_render" in text
    assert "regional trade statistics" in text


def test_visual_index_outcome_fields():
    outcome = VisualIndexOutcome(
        document_id="doc-1",
        content_hash="c" * 64,
        status="indexed",
        page_render_count=42,
        figure_candidate_count=8,
        visual_record_count=50,
        collection_name="docifer_visual_evidence",
        reused_existing=False,
    )
    assert outcome.visual_record_count == 50
    assert outcome.reused_existing is False
