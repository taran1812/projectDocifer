from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docifer_backend.config.paths import resolve_project_path
from docifer_backend.config.settings import get_settings
from docifer_backend.evaluation.dataset import GoldenQuestion, load_golden_questions
from docifer_backend.evaluation.metrics import score_answer
from docifer_backend.evaluation.registry import DocumentRegistry, IndexedDocumentRef
from docifer_backend.evaluation.reporting import (
    build_summary,
    write_json,
    write_jsonl,
    write_markdown_report,
)
from docifer_backend.observability.langsmith import evaluation_trace


@dataclass
class EvaluationResult:
    qa_id: str
    doc_id: str
    category: str
    question: str
    expected_answer: str
    should_abstain: bool
    status: str
    answer: str | None = None
    citation_ids: list[str] = field(default_factory=list)
    evidence_chunk_ids: list[str] = field(default_factory=list)
    evidence_texts: list[str] = field(default_factory=list)
    retrieval_scores: list[float] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None
    skip_reason: str | None = None
    error_message: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class EvaluationRunOutcome:
    run_name: str
    output_dir: str
    summary: dict[str, Any]


class EvaluationRunner:
    def __init__(
        self,
        *,
        dataset_path: str | Path | None = None,
        output_root: str | Path | None = None,
        query_service: Any | None = None,
        registry: DocumentRegistry | None = None,
        trace_enabled: bool | None = None,
    ) -> None:
        settings = get_settings()
        self.dataset_path = resolve_project_path(dataset_path or settings.golden_eval_path)
        self.output_root = resolve_project_path(output_root or settings.eval_runs_dir)
        self.query_service = query_service
        self.registry = registry or DocumentRegistry()
        self.trace_enabled = trace_enabled

    def run(
        self,
        *,
        run_name: str | None = None,
        doc_ids: set[str] | None = None,
        limit: int | None = None,
        top_k: int = 4,
    ) -> EvaluationRunOutcome:
        resolved_run_name = run_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = self.output_root / resolved_run_name
        output_dir.mkdir(parents=True, exist_ok=True)

        questions = load_golden_questions(self.dataset_path)
        results: list[EvaluationResult] = []

        for question in questions:
            if doc_ids and question.doc_id not in doc_ids:
                results.append(_skipped(question, "skipped_by_filter", "doc_id filter"))
                continue
            if limit is not None and len([r for r in results if r.status == "evaluated"]) >= limit:
                results.append(_skipped(question, "skipped_by_limit", "evaluation limit reached"))
                continue

            doc_ref = self.registry.resolve(question.doc_id)
            if not doc_ref.is_indexed:
                results.append(
                    _skipped(
                        question,
                        "skipped_not_indexed",
                        f"No indexed text chunks found for {doc_ref.filename or question.doc_id}",
                    )
                )
                continue

            results.append(self._evaluate_question(question, doc_ref, top_k=top_k))

        serializable_results = [asdict(result) for result in results]
        summary = build_summary(results)
        write_jsonl(output_dir / "results.jsonl", serializable_results)
        write_json(output_dir / "summary.json", summary)
        write_jsonl(output_dir / "ragas_input.jsonl", _ragas_records(results))
        write_markdown_report(
            output_dir / "report.md",
            run_name=resolved_run_name,
            summary=summary,
            results=results,
        )

        return EvaluationRunOutcome(
            run_name=resolved_run_name,
            output_dir=str(output_dir),
            summary=summary,
        )

    def _evaluate_question(
        self,
        question: GoldenQuestion,
        doc_ref: IndexedDocumentRef,
        *,
        top_k: int,
    ) -> EvaluationResult:
        query_service = self._get_query_service()
        trace_inputs = {
            "qa_id": question.qa_id,
            "doc_id": question.doc_id,
            "category": question.category,
            "question": question.question,
            "content_hash": doc_ref.content_hash,
            "top_k": top_k,
        }
        started = time.perf_counter()
        try:
            with evaluation_trace(
                name=f"phase5_eval_{question.qa_id}",
                inputs=trace_inputs,
                metadata={
                    "qa_id": question.qa_id,
                    "doc_id": question.doc_id,
                    "category": question.category,
                    "should_abstain": question.should_abstain,
                },
                enabled=self.trace_enabled,
            ) as trace:
                outcome = query_service.query(
                    question=question.question,
                    content_hash=doc_ref.content_hash,
                    top_k=top_k,
                )
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                retrieval_scores = [citation.score for citation in outcome.citations]
                metrics = score_answer(
                    question=question,
                    answer=outcome.answer,
                    citation_count=len(outcome.citations),
                    retrieved_evidence_count=len(outcome.evidence),
                    retrieval_scores=retrieval_scores,
                )
                result = EvaluationResult(
                    qa_id=question.qa_id,
                    doc_id=question.doc_id,
                    category=question.category,
                    question=question.question,
                    expected_answer=question.expected_answer,
                    should_abstain=question.should_abstain,
                    status="evaluated",
                    answer=outcome.answer,
                    citation_ids=[citation.citation_id for citation in outcome.citations],
                    evidence_chunk_ids=[chunk.chunk_id for chunk in outcome.evidence],
                    evidence_texts=[chunk.text for chunk in outcome.evidence],
                    retrieval_scores=retrieval_scores,
                    metrics=asdict(metrics),
                    latency_ms=latency_ms,
                    content_hash=doc_ref.content_hash,
                )
                trace.add_outputs(
                    {
                        "answer": outcome.answer,
                        "citation_ids": result.citation_ids,
                        "metrics": result.metrics,
                        "latency_ms": latency_ms,
                    }
                )
                return result
        except Exception as exc:
            return EvaluationResult(
                qa_id=question.qa_id,
                doc_id=question.doc_id,
                category=question.category,
                question=question.question,
                expected_answer=question.expected_answer,
                should_abstain=question.should_abstain,
                status="failed",
                error_message=str(exc),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                content_hash=doc_ref.content_hash,
            )

    def _get_query_service(self) -> Any:
        if self.query_service is not None:
            return self.query_service
        from docifer_backend.retrieval.query import TextQueryService

        self.query_service = TextQueryService()
        return self.query_service


def _skipped(question: GoldenQuestion, status: str, reason: str) -> EvaluationResult:
    return EvaluationResult(
        qa_id=question.qa_id,
        doc_id=question.doc_id,
        category=question.category,
        question=question.question,
        expected_answer=question.expected_answer,
        should_abstain=question.should_abstain,
        status=status,
        skip_reason=reason,
    )


def _ragas_records(results: list[EvaluationResult]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for result in results:
        if result.status != "evaluated":
            continue
        records.append(
            {
                "question": result.question,
                "answer": result.answer,
                "ground_truth": result.expected_answer,
                "contexts": result.evidence_texts,
                "qa_id": result.qa_id,
                "doc_id": result.doc_id,
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Docifer Phase 5 baseline evaluation.")
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--doc-id", action="append", dest="doc_ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--no-trace", action="store_true")
    args = parser.parse_args(argv)

    runner = EvaluationRunner(
        dataset_path=args.dataset,
        output_root=args.output_root,
        trace_enabled=False if args.no_trace else None,
    )
    outcome = runner.run(
        run_name=args.run_name,
        doc_ids=set(args.doc_ids) if args.doc_ids else None,
        limit=args.limit,
        top_k=args.top_k,
    )
    print(json.dumps(asdict(outcome), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
