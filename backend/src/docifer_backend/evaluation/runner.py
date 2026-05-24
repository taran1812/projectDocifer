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
from docifer_backend.providers.base import ProviderRateLimitError


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
    table_ids: list[str] = field(default_factory=list)
    visual_ids: list[str] = field(default_factory=list)
    evidence_texts: list[str] = field(default_factory=list)
    retrieval_scores: list[float] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None
    skip_reason: str | None = None
    error_message: str | None = None
    content_hash: str | None = None
    retrieval_mode: str = "dense"
    evidence_mode: str = "text"
    scope: str = "single"
    max_documents: int = 5
    max_evidence_per_document: int = 3
    rerank: bool = False
    rerank_top_n: int | None = None
    verifier_verdict: str | None = None


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
        retrieval_mode: str = "dense",
        evidence_mode: str = "category",
        scope: str = "single",
        max_documents: int = 5,
        max_evidence_per_document: int = 3,
        verify_citations: bool = False,
        rerank: bool = False,
        rerank_top_n: int = 20,
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

            results.append(
                self._evaluate_question(
                    question,
                    doc_ref,
                    top_k=top_k,
                    retrieval_mode=retrieval_mode,
                    evidence_mode=evidence_mode,
                    scope=scope,
                    scoped_doc_ids=sorted(doc_ids) if doc_ids else None,
                    max_documents=max_documents,
                    max_evidence_per_document=max_evidence_per_document,
                    verify_citations=verify_citations,
                    rerank=rerank,
                    rerank_top_n=rerank_top_n,
                )
            )

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
        retrieval_mode: str,
        evidence_mode: str,
        scope: str,
        scoped_doc_ids: list[str] | None,
        max_documents: int,
        max_evidence_per_document: int,
        verify_citations: bool,
        rerank: bool,
        rerank_top_n: int,
    ) -> EvaluationResult:
        query_service = self._get_query_service()
        resolved_evidence_mode = resolve_evidence_mode(question, requested=evidence_mode)
        trace_inputs = {
            "qa_id": question.qa_id,
            "doc_id": question.doc_id,
            "category": question.category,
            "question": question.question,
            "content_hash": doc_ref.content_hash,
            "top_k": top_k,
            "retrieval_mode": retrieval_mode,
            "evidence_mode": resolved_evidence_mode,
            "scope": scope,
            "max_documents": max_documents,
            "max_evidence_per_document": max_evidence_per_document,
            "verify_citations": verify_citations,
            "rerank": rerank,
            "rerank_top_n": rerank_top_n,
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
                    scope=scope,
                    content_hash=doc_ref.content_hash if scope == "single" else None,
                    doc_ids=scoped_doc_ids if scope == "doc_ids" else None,
                    max_documents=max_documents,
                    max_evidence_per_document=max_evidence_per_document,
                    top_k=top_k,
                    retrieval_mode=retrieval_mode,
                    evidence_mode=resolved_evidence_mode,
                    table_top_k=top_k,
                    visual_top_k=min(max(top_k, 1), 5),
                    verify_citations=verify_citations,
                    rerank=rerank,
                    rerank_top_n=rerank_top_n,
                )
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                table_evidence = list(getattr(outcome, "table_evidence", []) or [])
                visual_evidence = list(getattr(outcome, "visual_evidence", []) or [])
                visual_observations = list(
                    getattr(getattr(outcome, "visual_interpretation", None), "observations", []) or []
                )
                retrieval_scores = (
                    [chunk.score for chunk in outcome.evidence]
                    + [table.score for table in table_evidence]
                    + [visual.score for visual in visual_evidence]
                )
                citation_ids = (
                    [citation.citation_id for citation in outcome.citations]
                    + [
                        citation.citation_id
                        for citation in getattr(outcome, "table_citations", [])
                    ]
                    + [
                        citation.citation_id
                        for citation in getattr(outcome, "visual_citations", [])
                    ]
                )
                evidence_texts = (
                    [chunk.text for chunk in outcome.evidence]
                    + [(table.raw_text or "") for table in table_evidence]
                    + [
                        " ".join(
                            (getattr(observation, "extracted_facts", None) or [])
                            + (getattr(observation, "limitations", None) or [])
                        )
                        for observation in visual_observations
                    ]
                )
                retrieved_evidence_text = " ".join(evidence_texts)
                metrics = score_answer(
                    question=question,
                    answer=outcome.answer,
                    citation_count=len(citation_ids),
                    retrieved_evidence_count=len(retrieval_scores),
                    retrieval_scores=retrieval_scores,
                    retrieved_evidence_text=retrieved_evidence_text,
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
                    citation_ids=citation_ids,
                    evidence_chunk_ids=[chunk.chunk_id for chunk in outcome.evidence],
                    table_ids=[table.table_id for table in table_evidence],
                    visual_ids=[visual.visual_id for visual in visual_evidence],
                    evidence_texts=evidence_texts,
                    retrieval_scores=retrieval_scores,
                    metrics=asdict(metrics),
                    latency_ms=latency_ms,
                    content_hash=doc_ref.content_hash,
                    retrieval_mode=retrieval_mode,
                    evidence_mode=resolved_evidence_mode,
                    scope=scope,
                    max_documents=max_documents,
                    max_evidence_per_document=max_evidence_per_document,
                    rerank=rerank,
                    rerank_top_n=rerank_top_n if rerank else None,
                    verifier_verdict=(
                        outcome.citation_verification.verdict
                        if outcome.citation_verification is not None
                        else None
                    ),
                )
                trace.add_outputs(
                    {
                        "answer": outcome.answer,
                        "citation_ids": result.citation_ids,
                        "metrics": result.metrics,
                        "latency_ms": latency_ms,
                        "retrieval_mode": retrieval_mode,
                        "evidence_mode": resolved_evidence_mode,
                        "scope": scope,
                        "rerank": rerank,
                        "rerank_top_n": rerank_top_n if rerank else None,
                        "verifier_verdict": result.verifier_verdict,
                    }
                )
                return result
        except ProviderRateLimitError as exc:
            return EvaluationResult(
                qa_id=question.qa_id,
                doc_id=question.doc_id,
                category=question.category,
                question=question.question,
                expected_answer=question.expected_answer,
                should_abstain=question.should_abstain,
                status="provider_failed",
                error_message=str(exc),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                content_hash=doc_ref.content_hash,
                evidence_mode=resolved_evidence_mode,
                scope=scope,
                max_documents=max_documents,
                max_evidence_per_document=max_evidence_per_document,
                rerank=rerank,
                rerank_top_n=rerank_top_n if rerank else None,
            )
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
                evidence_mode=resolved_evidence_mode,
                scope=scope,
                max_documents=max_documents,
                max_evidence_per_document=max_evidence_per_document,
                rerank=rerank,
                rerank_top_n=rerank_top_n if rerank else None,
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
    parser.add_argument("--retrieval-mode", default="dense", choices=["dense", "bm25", "hybrid"])
    parser.add_argument("--evidence-mode", default="category", choices=["category", "text", "table", "visual", "auto"])
    parser.add_argument("--scope", default="single", choices=["single", "all", "doc_ids"])
    parser.add_argument("--max-documents", type=int, default=5)
    parser.add_argument("--max-evidence-per-document", type=int, default=3)
    parser.add_argument("--verify-citations", action="store_true")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--rerank-top-n", type=int, default=20)
    parser.add_argument("--no-trace", action="store_true")
    args = parser.parse_args(argv)
    if args.scope == "doc_ids" and not args.doc_ids:
        parser.error("--scope doc_ids requires at least one --doc-id.")

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
        retrieval_mode=args.retrieval_mode,
        evidence_mode=args.evidence_mode,
        scope=args.scope,
        max_documents=args.max_documents,
        max_evidence_per_document=args.max_evidence_per_document,
        verify_citations=args.verify_citations,
        rerank=args.rerank,
        rerank_top_n=args.rerank_top_n,
    )
    print(json.dumps(asdict(outcome), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def resolve_evidence_mode(question: GoldenQuestion, *, requested: str = "category") -> str:
    if requested != "category":
        return requested
    category = question.category.lower()
    expected = (question.expected_evidence_type or "").lower()
    if "mixed" in category:
        return "auto"
    if any(term in category or term in expected for term in ["chart", "visual", "figure", "image", "graph"]):
        return "visual"
    if "table" in category or "table" in expected:
        return "table"
    return "text"


if __name__ == "__main__":
    raise SystemExit(main())
