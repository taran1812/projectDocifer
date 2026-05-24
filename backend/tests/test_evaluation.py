from types import SimpleNamespace

from docifer_backend.evaluation.dataset import load_golden_questions
from docifer_backend.evaluation.metrics import _detect_abstention, score_answer
from docifer_backend.evaluation.runner import EvaluationRunner, resolve_evidence_mode


class FakeRegistry:
    def resolve(self, doc_id: str):
        if doc_id == "DOC-005":
            return SimpleNamespace(
                doc_id=doc_id,
                filename="Worldbank2024.pdf",
                document_id="doc-1",
                content_hash="abc123",
                indexed_chunk_count=5,
                is_indexed=True,
            )
        return SimpleNamespace(
            doc_id=doc_id,
            filename=f"{doc_id}.pdf",
            document_id=None,
            content_hash=None,
            indexed_chunk_count=0,
            is_indexed=False,
        )


class FakeQueryService:
    def query(
        self,
        *,
        question: str,
        scope: str = "single",
        content_hash: str | None = None,
        doc_ids: list[str] | None = None,
        max_documents: int = 5,
        max_evidence_per_document: int = 3,
        top_k: int,
        retrieval_mode: str = "dense",
        evidence_mode: str = "text",
        table_top_k: int = 4,
        visual_top_k: int = 3,
        verify_citations: bool = False,
        rerank: bool = False,
        rerank_top_n: int | None = None,
    ):
        self.last_call = {
            "top_k": top_k,
            "retrieval_mode": retrieval_mode,
            "evidence_mode": evidence_mode,
            "scope": scope,
            "verify_citations": verify_citations,
            "rerank": rerank,
            "rerank_top_n": rerank_top_n,
        }
        return SimpleNamespace(
            answer="Middle-income countries should move from 1i to 2i and then 3i. [C1]",
            citations=[
                SimpleNamespace(
                    citation_id="C1",
                    chunk_id="chunk-1",
                    score=0.91,
                )
            ],
            evidence=[
                SimpleNamespace(
                    chunk_id="chunk-1",
                    score=0.91,
                    text="The report describes 1i, 2i, and 3i strategies.",
                )
            ],
            citation_verification=None,
            table_citations=[],
            visual_citations=[],
            table_evidence=[],
            visual_evidence=[],
            visual_interpretation=None,
        )


def test_load_golden_questions_reads_40_seeded_rows():
    questions = load_golden_questions("docifer_phase1_corpus_and_golden_eval_v1.xlsx")

    assert len(questions) == 40
    assert questions[0].qa_id == "QA-001"
    assert questions[-1].should_abstain is True


def test_score_answer_tracks_citation_presence_and_expected_recall():
    question = load_golden_questions("docifer_phase1_corpus_and_golden_eval_v1.xlsx")[12]

    metrics = score_answer(
        question=question,
        answer="The strategies are 1i, 2i, and 3i. [C1]",
        citation_count=1,
        retrieved_evidence_count=1,
        retrieval_scores=[0.9],
    )

    assert metrics.answer_present is True
    assert metrics.citation_presence is True
    assert metrics.retrieved_evidence_count == 1
    assert metrics.top_score == 0.9


def test_evaluation_runner_writes_results_and_skips_unindexed_docs(tmp_path):
    query_service = FakeQueryService()
    runner = EvaluationRunner(
        output_root=tmp_path,
        query_service=query_service,
        registry=FakeRegistry(),
        trace_enabled=False,
    )

    outcome = runner.run(
        run_name="test-run",
        doc_ids={"DOC-005"},
        top_k=2,
        rerank=True,
        rerank_top_n=6,
    )

    assert outcome.summary["evaluated"] == 3
    assert outcome.summary["by_status"]["evaluated"] == 3
    assert outcome.summary["by_status"]["skipped_by_filter"] == 37
    assert (tmp_path / "test-run" / "results.jsonl").exists()
    assert (tmp_path / "test-run" / "summary.json").exists()
    assert (tmp_path / "test-run" / "report.md").exists()
    assert (tmp_path / "test-run" / "ragas_input.jsonl").exists()
    assert query_service.last_call["rerank"] is True
    assert query_service.last_call["rerank_top_n"] == 6


def test_resolve_evidence_mode_routes_visual_and_table_categories():
    questions = load_golden_questions("docifer_phase1_corpus_and_golden_eval_v1.xlsx")
    visual_question = next(q for q in questions if "chart" in q.category.lower() or "visual" in q.category.lower())
    table_question = next(q for q in questions if "table" in q.category.lower())
    text_question = next(q for q in questions if q.category.lower().startswith("text"))

    assert resolve_evidence_mode(visual_question) == "visual"
    assert resolve_evidence_mode(table_question) == "table"
    assert resolve_evidence_mode(text_question) == "text"
    assert resolve_evidence_mode(visual_question, requested="auto") == "auto"


def test_detect_abstention_contraction_dont():
    assert _detect_abstention("I don't have enough evidence to answer this.") is True


def test_detect_abstention_contraction_cant():
    assert _detect_abstention("I can't determine the answer from the evidence.") is True


def test_detect_abstention_contraction_cannot_determine():
    assert _detect_abstention("I cannot determine the GPA from the retrieved content.") is True


def test_detect_abstention_does_not_trigger_on_normal_answer():
    assert _detect_abstention("The revenue was $130.5 billion. [C1]") is False


def test_detect_abstention_do_not_have_still_works():
    assert _detect_abstention("I do not have enough evidence to answer.") is True


def test_resolve_evidence_mode_mixed_modality_routes_to_auto():
    from types import SimpleNamespace
    question = SimpleNamespace(
        category="Mixed Modality",
        expected_evidence_type="visual and text",
    )
    assert resolve_evidence_mode(question, requested="category") == "auto"


def test_resolve_evidence_mode_chart_visual_routes_to_visual():
    from types import SimpleNamespace
    question = SimpleNamespace(
        category="Chart / Visual",
        expected_evidence_type="chart",
    )
    assert resolve_evidence_mode(question, requested="category") == "visual"


def test_resolve_evidence_mode_mixed_beats_visual_in_expected():
    from types import SimpleNamespace
    question = SimpleNamespace(
        category="Mixed Modality",
        expected_evidence_type="visual figure and table",
    )
    assert resolve_evidence_mode(question, requested="category") == "auto"


def test_token_recall_high_evidence_low_answer_creates_positive_gap():
    # evidence contains all expected tokens, answer only has some
    from docifer_backend.evaluation.metrics import token_recall
    evidence_recall = token_recall("apple banana cherry", "apple banana cherry date")
    answer_recall = token_recall("apple banana cherry", "apple date")
    assert evidence_recall.recall == 1.0
    assert answer_recall.recall < 1.0
    assert evidence_recall.recall - answer_recall.recall > 0


def test_token_recall_empty_expected_returns_zero():
    from docifer_backend.evaluation.metrics import token_recall
    result = token_recall("", "some answer text")
    assert result.recall == 0.0
    assert result.overlap_count == 0
    assert result.expected_count == 0


def test_score_answer_populates_evidence_recall_fields():
    from docifer_backend.evaluation.metrics import score_answer
    from docifer_backend.evaluation.dataset import load_golden_questions
    question = load_golden_questions("docifer_phase1_corpus_and_golden_eval_v1.xlsx")[12]
    metrics = score_answer(
        question=question,
        answer="The strategies are 1i. [C1]",
        citation_count=1,
        retrieved_evidence_count=1,
        retrieval_scores=[0.9],
        retrieved_evidence_text="The report describes 1i, 2i, and 3i strategies in detail.",
    )
    assert metrics.retrieved_evidence_token_recall is not None
    assert metrics.answer_token_recall is not None
    assert metrics.evidence_answer_gap is not None
    assert metrics.expected_answer_token_count is not None


def test_summary_includes_evidence_recall_averages():
    # use the existing FakeQueryService/FakeRegistry to run a mini eval
    # then check summary has the new keys
    import tempfile, pathlib
    from docifer_backend.evaluation.runner import EvaluationRunner
    from types import SimpleNamespace

    class FakeRegistry2:
        def resolve(self, doc_id):
            if doc_id == "DOC-005":
                return SimpleNamespace(doc_id=doc_id, filename="f.pdf", document_id="d1",
                                       content_hash="h1", indexed_chunk_count=5, is_indexed=True)
            return SimpleNamespace(doc_id=doc_id, filename=f"{doc_id}.pdf", document_id=None,
                                   content_hash=None, indexed_chunk_count=0, is_indexed=False)

    class FakeQueryService2:
        def query(self, *, question, **kwargs):
            return SimpleNamespace(
                answer="Middle-income countries should move from 1i to 2i and then 3i. [C1]",
                citations=[SimpleNamespace(citation_id="C1", chunk_id="chunk-1", score=0.91)],
                evidence=[SimpleNamespace(chunk_id="chunk-1", score=0.91,
                                          text="The report describes 1i, 2i, and 3i strategies.")],
                citation_verification=None,
                table_citations=[], visual_citations=[],
                table_evidence=[], visual_evidence=[], visual_interpretation=None,
            )

    with tempfile.TemporaryDirectory() as tmp:
        runner = EvaluationRunner(
            output_root=pathlib.Path(tmp),
            query_service=FakeQueryService2(),
            registry=FakeRegistry2(),
            trace_enabled=False,
        )
        outcome = runner.run(run_name="t1-test", doc_ids={"DOC-005"}, top_k=2)

    assert "average_retrieved_evidence_token_recall" in outcome.summary["metrics"]
    assert "average_answer_token_recall" in outcome.summary["metrics"]
    assert "average_evidence_answer_gap" in outcome.summary["metrics"]
