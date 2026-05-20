from types import SimpleNamespace

from docifer_backend.evaluation.dataset import load_golden_questions
from docifer_backend.evaluation.metrics import score_answer
from docifer_backend.evaluation.runner import EvaluationRunner


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
        content_hash: str,
        top_k: int,
        retrieval_mode: str = "dense",
        verify_citations: bool = False,
    ):
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
    runner = EvaluationRunner(
        output_root=tmp_path,
        query_service=FakeQueryService(),
        registry=FakeRegistry(),
        trace_enabled=False,
    )

    outcome = runner.run(run_name="test-run", doc_ids={"DOC-005"}, top_k=2)

    assert outcome.summary["evaluated"] == 3
    assert outcome.summary["by_status"]["evaluated"] == 3
    assert outcome.summary["by_status"]["skipped_by_filter"] == 37
    assert (tmp_path / "test-run" / "results.jsonl").exists()
    assert (tmp_path / "test-run" / "summary.json").exists()
    assert (tmp_path / "test-run" / "report.md").exists()
    assert (tmp_path / "test-run" / "ragas_input.jsonl").exists()
