import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from docifer_backend.ingestion.models import Document
from docifer_backend.providers.base import CitationGroundingVerdict, GroundingEvidence
from docifer_backend.retrieval.query import TextQueryService, detect_table_intent
from docifer_backend.retrieval.tables.extraction import extract_table_evidence_from_canonical
from docifer_backend.retrieval.tables.indexing import (
    TABLE_INDEX_STATUS_INDEXED,
    TableIndexingService,
)
from docifer_backend.retrieval.tables.models import DocumentTableIndexRun, TableEvidenceRecord
from docifer_backend.retrieval.tables.reasoning import (
    parse_numeric_value,
    parse_table_question_intent,
    reason_over_table_evidence,
)
from docifer_backend.retrieval.tables.retriever import TableRetriever
from docifer_backend.retrieval.tables.schemas import TableQueryResult
from docifer_backend.storage.database import Base


class FakeTableAIProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_fake_embedding(text) for text in texts]

    def generate_grounded_answer(
        self,
        *,
        question: str,
        evidence: list[GroundingEvidence],
    ) -> str:
        table_evidence = [item for item in evidence if item.citation_id.startswith("T")]
        if table_evidence:
            return f"Commercial & Investment Bank had the highest 2025 net income [{table_evidence[0].citation_id}]."
        return f"The strategy is supported by text evidence [{evidence[0].citation_id}]."

    def verify_citation_grounding(
        self,
        *,
        question: str,
        answer: str,
        evidence: list[GroundingEvidence],
    ) -> CitationGroundingVerdict:
        supported = [item.citation_id for item in evidence if f"[{item.citation_id}]" in answer]
        return CitationGroundingVerdict(
            verdict="supported",
            supported_citation_ids=supported,
            weak_citation_ids=[],
            unsupported_claims=[],
            reasoning="The cited evidence supports the answer.",
            revised_answer=None,
        )


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_structured_docling_table_extraction(tmp_path):
    canonical_path, _, _ = write_table_canonical_artifacts(tmp_path)

    evidence = extract_table_evidence_from_canonical(canonical_path)

    structured = [item for item in evidence if item.source_kind == "docling_table"]
    assert len(structured) == 1
    assert structured[0].table_type == "structured"
    assert structured[0].structured_json["headers"] == ["Segment", "2025", "2024"]
    assert structured[0].row_count == 2
    assert structured[0].table_readiness == "good"
    assert structured[0].table_id.endswith(":table:0000")


def test_markdown_and_fallback_table_like_extraction(tmp_path):
    canonical_path, _, _ = write_table_canonical_artifacts(tmp_path)

    evidence = extract_table_evidence_from_canonical(canonical_path)

    assert any(item.source_kind == "markdown_table" for item in evidence)
    fallback = [item for item in evidence if item.source_kind == "text_pattern"]
    assert fallback
    assert fallback[0].table_type == "table_like_text"
    assert "Net income" in fallback[0].raw_text
    assert fallback[0].table_readiness == "weak"


def test_table_indexing_is_idempotent_and_marks_qdrant_ids(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_table_canonical_artifacts(tmp_path)
    with session_factory() as session:
        session.add(
            Document(
                filename="sample.pdf",
                source_path=source_path,
                content_hash=content_hash,
                file_size_bytes=100,
            )
        )
        session.commit()

    qdrant_client = QdrantClient(":memory:")
    service = TableIndexingService(
        session_factory=session_factory,
        ai_provider=FakeTableAIProvider(),
        qdrant_client=qdrant_client,
        collection_name="test_table_evidence",
        initialize_schema=False,
    )

    first = service.index_canonical_document(canonical_path)
    second = service.index_canonical_document(canonical_path)

    assert first.status == TABLE_INDEX_STATUS_INDEXED
    assert first.table_evidence_count >= 3
    assert second.reused_existing is True
    with session_factory() as session:
        records = session.scalars(select(TableEvidenceRecord)).all()
        run = session.scalar(select(DocumentTableIndexRun))
        assert len(records) == first.table_evidence_count
        assert all(record.qdrant_point_id for record in records)
        assert run.status == TABLE_INDEX_STATUS_INDEXED


def test_table_retriever_hybrid_returns_financial_table(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_table_canonical_artifacts(tmp_path)
    qdrant_client = index_table_fixture(
        canonical_path=canonical_path,
        content_hash=content_hash,
        source_path=source_path,
        session_factory=session_factory,
    )

    results = TableRetriever(
        ai_provider=FakeTableAIProvider(),
        qdrant_client=qdrant_client,
        session_factory=session_factory,
        collection_name="test_table_evidence",
    ).search(
        query="Which segment had the highest 2025 net income?",
        content_hash=content_hash,
        top_k=4,
        retrieval_mode="table_hybrid",
    )

    assert results
    assert results[0].retrieval_mode == "table_hybrid"
    assert results[0].hybrid_score is not None
    assert "Commercial & Investment Bank" in results[0].raw_text


def test_query_table_mode_returns_table_citation(tmp_path, session_factory):
    canonical_path, content_hash, source_path = write_table_canonical_artifacts(tmp_path)
    qdrant_client = index_table_fixture(
        canonical_path=canonical_path,
        content_hash=content_hash,
        source_path=source_path,
        session_factory=session_factory,
    )

    outcome = TextQueryService(
        ai_provider=FakeTableAIProvider(),
        qdrant_client=qdrant_client,
        session_factory=session_factory,
        collection_name="unused_text_collection",
        table_collection_name="test_table_evidence",
    ).query_sync(
        question="Which segment had the highest 2025 net income?",
        content_hash=content_hash,
        evidence_mode="table",
        table_top_k=4,
        verify_citations=True,
    )

    used_citation_ids = outcome.debug["table_reasoning"]["used_citation_ids"]

    assert len(used_citation_ids) == 1
    assert f"[{used_citation_ids[0]}]" in outcome.answer
    assert outcome.citations == []
    assert [citation.citation_id for citation in outcome.table_citations] == used_citation_ids
    assert outcome.citation_verification.verdict == "supported"
    assert outcome.debug["table_retrieved_count"] > 0
    assert outcome.debug["table_reasoning_status"] == "supported"


def test_table_intent_detection_compound_signals_and_false_positive():
    false_positive = detect_table_intent(
        "Which strategy does the report recommend for upper-middle-income countries?"
    )
    compound = detect_table_intent("Which segment had the highest 2025 net income?")

    assert false_positive["detected"] is False
    assert compound["detected"] is True
    assert {"segment", "highest", "2025", "net income"}.issubset(set(compound["matches"]))


def test_table_reasoning_parses_question_and_numeric_values():
    intent = parse_table_question_intent("Which segment had the highest 2025 net income?")

    assert intent.metric == "net income"
    assert intent.year == 2025
    assert intent.operation == "max"
    assert intent.entity_hint == "segment"
    assert parse_numeric_value("$27,761") == 27761
    assert parse_numeric_value("(425)") == -425
    assert parse_numeric_value("32%") == 32


def test_table_reasoning_selects_jpmorgan_segment_from_fallback_text():
    table = make_table_query_result(
        table_id="jpm:table_text:0001:00",
        raw_text="\n".join(
            [
                "Segment & Corporate results",
                "As of or for the year ended December 31,",
                "(in millions, except ratios)",
                "Consumer & Community Banking Commercial & Investment Bank Asset & Wealth Management",
                "2025 2024 2023 2025 2024 2023 2025 2024 2023",
                "Total net revenue 76,029 71,507 70,148 78,454 70,114 64,353 24,073 21,578 19,827",
                "Net income $ 18,245 $ 17,603 $ 21,232 $ 27,761 $ 24,846 $ 20,272 $ 6,522 $ 5,421 $ 5,227",
                "Net income $ 57,048 $ 58,471 $ 49,552",
            ]
        ),
    )

    result = reason_over_table_evidence(
        question="Which segment had the highest 2025 net income?",
        tables=[table],
    )

    assert result.status == "supported"
    assert result.selected_observation is not None
    assert result.selected_observation.label == "Commercial & Investment Bank"
    assert result.selected_observation.value == 27761
    assert result.selected_observation.display_value == "$27,761 million"
    assert result.used_citation_ids == ["T1"]


def test_table_reasoning_uses_structured_table_caption_metric():
    table = make_table_query_result(
        table_id="sample:table:0000",
        raw_text="Segment | 2025 | 2024\nConsumer & Community Banking | $18,245 | $17,603\nCommercial & Investment Bank | $27,761 | $24,846",
        structured_json={
            "headers": ["Segment", "2025", "2024"],
            "rows": [
                ["Consumer & Community Banking", "$18,245", "$17,603"],
                ["Commercial & Investment Bank", "$27,761", "$24,846"],
            ],
        },
        caption="Segment net income by year",
    )

    result = reason_over_table_evidence(
        question="Which segment had the highest 2025 net income?",
        tables=[table],
    )

    assert result.status == "supported"
    assert result.selected_observation is not None
    assert result.selected_observation.label == "Commercial & Investment Bank"


def index_table_fixture(
    *,
    canonical_path: Path,
    content_hash: str,
    source_path: str,
    session_factory,
) -> QdrantClient:
    with session_factory() as session:
        session.add(
            Document(
                filename="sample.pdf",
                source_path=source_path,
                content_hash=content_hash,
                file_size_bytes=100,
            )
        )
        session.commit()

    qdrant_client = QdrantClient(":memory:")
    TableIndexingService(
        session_factory=session_factory,
        ai_provider=FakeTableAIProvider(),
        qdrant_client=qdrant_client,
        collection_name="test_table_evidence",
        initialize_schema=False,
    ).index_canonical_document(canonical_path)
    return qdrant_client


def write_table_canonical_artifacts(tmp_path: Path) -> tuple[Path, str, str]:
    content_hash = "c" * 64
    source_path = str(tmp_path / "sample.pdf")
    docling_path = tmp_path / "docling.json"
    markdown_path = tmp_path / "document.md"
    canonical_path = tmp_path / "canonical.json"

    docling_path.write_text(
        json.dumps(
            {
                "texts": [
                    {
                        "label": "section_header",
                        "text": "Segment Results",
                        "prov": [{"page_no": 1}],
                        "self_ref": "#/texts/0",
                    },
                    {
                        "label": "caption",
                        "text": "Segment net income by year",
                        "prov": [{"page_no": 1}],
                        "self_ref": "#/texts/1",
                    },
                ],
                "tables": [
                    {
                        "captions": [{"$ref": "#/texts/1"}],
                        "prov": [{"page_no": 1}],
                        "data": {
                            "grid": [
                                [
                                    {"text": "Segment", "column_header": True},
                                    {"text": "2025", "column_header": True},
                                    {"text": "2024", "column_header": True},
                                ],
                                [
                                    {"text": "Consumer & Community Banking"},
                                    {"text": "$18,245"},
                                    {"text": "$17,603"},
                                ],
                                [
                                    {"text": "Commercial & Investment Bank"},
                                    {"text": "$27,761"},
                                    {"text": "$24,846"},
                                ],
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    markdown_path.write_text(
        "\n".join(
            [
                "<!-- page 7 -->",
                "Segment Summary",
                "| Metric | 2025 | 2024 |",
                "|---|---:|---:|",
                "| Revenue | $78,454 | $70,114 |",
                "| Net income | $27,761 | $24,846 |",
                "",
                "<!-- page 8 -->",
                "Segment & Corporate results",
                "As of or for the year ended December 31,",
                "(in millions, except ratios)",
                "Consumer & Community Banking Commercial & Investment Bank Asset & Wealth Management",
                "2025 2024 2023 2025 2024 2023 2025 2024 2023",
                "Total net revenue 76,029 71,507 70,148 78,454 70,114 64,353 24,073 21,578 19,827",
                "Net income $ 18,245 $ 17,603 $ 21,232 $ 27,761 $ 24,846 $ 20,272 $ 6,522 $ 5,421 $ 5,227",
                "Return on equity 32 % 32 % 38 % 18 % 18 % 14 % 40 % 34 % 31 %",
            ]
        ),
        encoding="utf-8",
    )
    canonical_path.write_text(
        json.dumps(
            {
                "artifacts": {
                    "docling_json": str(docling_path),
                    "markdown": str(markdown_path),
                },
                "document": {
                    "content_hash": content_hash,
                    "filename": "sample.pdf",
                    "source_path": source_path,
                },
                "parser": {"name": "docling"},
                "content": {"markdown_char_count": markdown_path.stat().st_size},
            }
        ),
        encoding="utf-8",
    )
    return canonical_path, content_hash, source_path


def _fake_embedding(text: str) -> list[float]:
    lower = text.lower()
    return [
        1.0 if "net income" in lower else 0.0,
        1.0 if "commercial" in lower else 0.0,
        1.0 if "segment" in lower else 0.0,
        1.0,
    ]


def make_table_query_result(
    *,
    table_id: str,
    raw_text: str,
    structured_json: dict | None = None,
    caption: str | None = None,
) -> TableQueryResult:
    return TableQueryResult(
        table_id=table_id,
        score=1.0,
        dense_score=1.0,
        lexical_score=1.0,
        hybrid_score=1.0,
        retrieval_mode="table_hybrid",
        table_type="structured" if structured_json else "table_like_text",
        source_kind="docling_table" if structured_json else "text_pattern",
        page_start=1,
        page_end=1,
        raw_text=raw_text,
        markdown_table=None,
        structured_json=structured_json,
        section_heading="Segment Results",
        table_readiness="good" if structured_json else "weak",
        document_id="doc-id",
        content_hash="c" * 64,
        filename="sample.pdf",
        source_path="datasets/raw_pdfs/sample.pdf",
        source_artifact_path="datasets/processed/sample/canonical.json",
        source_chunk_id=None,
        caption=caption,
    )
