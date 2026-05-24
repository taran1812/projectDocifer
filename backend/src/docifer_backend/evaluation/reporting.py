from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from statistics import median
from typing import Any


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)
        + ("\n" if records else ""),
        encoding="utf-8",
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def build_summary(results: list[Any]) -> dict[str, Any]:
    total = len(results)
    evaluated = [result for result in results if result.status == "evaluated"]
    skipped = [result for result in results if result.status.startswith("skipped")]
    failed = [result for result in results if result.status == "failed"]
    latencies = [result.latency_ms for result in evaluated if result.latency_ms is not None]

    summary = {
        "total_questions_seen": total,
        "evaluated": len(evaluated),
        "skipped": len(skipped),
        "failed": len(failed),
        "by_status": _count_by(results, "status"),
        "by_category": _count_by(results, "category"),
        "by_doc_id": _count_by(results, "doc_id"),
        "metrics": {
            "answer_present_rate": _rate(evaluated, lambda result: result.metrics.get("answer_present")),
            "citation_presence_rate": _rate(evaluated, lambda result: result.metrics.get("citation_presence")),
            "average_expected_answer_token_recall": _average(
                [
                    result.metrics.get("expected_answer_token_recall")
                    for result in evaluated
                    if result.metrics.get("expected_answer_token_recall") is not None
                ]
            ),
            "abstention_correct_rate": _rate(
                [
                    result
                    for result in evaluated
                    if result.metrics.get("abstention_correct") is not None
                ],
                lambda result: result.metrics.get("abstention_correct"),
            ),
            "true_abstention_accuracy": _rate(
                [
                    result
                    for result in evaluated
                    if result.should_abstain and result.metrics.get("abstention_correct") is not None
                ],
                lambda result: result.metrics.get("abstention_correct"),
            ),
            "false_abstention_rate": _rate(
                [
                    result
                    for result in evaluated
                    if not result.should_abstain
                ],
                lambda result: result.metrics.get("abstention_detected"),
            ),
            "latency_ms_p50": round(median(latencies), 2) if latencies else None,
            "latency_ms_p95": _percentile(latencies, 95),
            "average_retrieved_evidence_token_recall": _average(
                [
                    result.metrics.get("retrieved_evidence_token_recall")
                    for result in evaluated
                    if result.metrics.get("retrieved_evidence_token_recall") is not None
                ]
            ),
            "average_answer_token_recall": _average(
                [
                    result.metrics.get("answer_token_recall")
                    for result in evaluated
                    if result.metrics.get("answer_token_recall") is not None
                ]
            ),
            "average_evidence_answer_gap": _average(
                [
                    result.metrics.get("evidence_answer_gap")
                    for result in evaluated
                    if result.metrics.get("evidence_answer_gap") is not None
                ]
            ),
        },
    }
    return summary


def write_markdown_report(
    path: Path,
    *,
    run_name: str,
    summary: dict[str, Any],
    results: list[Any],
) -> None:
    evaluated = [result for result in results if result.status == "evaluated"]
    skipped = [result for result in results if result.status.startswith("skipped")]

    lines = [
        f"# Docifer Phase 5 Baseline Report - {run_name}",
        "",
        "## Summary",
        "",
        f"- Questions seen: {summary['total_questions_seen']}",
        f"- Evaluated: {summary['evaluated']}",
        f"- Skipped: {summary['skipped']}",
        f"- Failed: {summary['failed']}",
        f"- Citation presence rate: {summary['metrics']['citation_presence_rate']}",
        f"- Average expected-answer token recall: {summary['metrics']['average_expected_answer_token_recall']}",
        f"- P50 latency ms: {summary['metrics']['latency_ms_p50']}",
        f"- P95 latency ms: {summary['metrics']['latency_ms_p95']}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in summary["by_status"].items():
        lines.append(f"- {status}: {count}")

    lines.extend(["", "## Category Counts", ""])
    for category, count in summary["by_category"].items():
        lines.append(f"- {category}: {count}")

    avg_evidence_recall = summary["metrics"].get("average_retrieved_evidence_token_recall")
    avg_answer_recall = summary["metrics"].get("average_answer_token_recall")
    avg_gap = summary["metrics"].get("average_evidence_answer_gap")
    lines.extend(
        [
            "",
            "## Evidence Recall vs Answer Recall",
            "",
            f"- Average retrieved evidence token recall: {avg_evidence_recall}",
            f"- Average answer token recall: {avg_answer_recall}",
            f"- Average evidence-answer gap: {avg_gap}",
            "",
            "### Worst Evidence Recall Questions (retrieval problem)",
            "",
        ]
    )
    non_abstain_evaluated = [
        r for r in evaluated if not r.should_abstain
        and r.metrics.get("retrieved_evidence_token_recall") is not None
    ]
    worst_evidence = sorted(
        non_abstain_evaluated,
        key=lambda r: r.metrics.get("retrieved_evidence_token_recall", 1.0),
    )[:5]
    if worst_evidence:
        for r in worst_evidence:
            lines.append(
                f"- {r.qa_id} ({r.doc_id}): evidence_recall="
                f"{r.metrics.get('retrieved_evidence_token_recall')} | {r.question[:80]}"
            )
    else:
        lines.append("- No data.")

    lines.extend(
        [
            "",
            "### Largest Evidence-Answer Gap Questions (synthesis problem)",
            "",
        ]
    )
    largest_gap = sorted(
        non_abstain_evaluated,
        key=lambda r: r.metrics.get("evidence_answer_gap", 0.0),
        reverse=True,
    )[:5]
    if largest_gap:
        for r in largest_gap:
            lines.append(
                f"- {r.qa_id} ({r.doc_id}): gap="
                f"{r.metrics.get('evidence_answer_gap')} | {r.question[:80]}"
            )
    else:
        lines.append("- No data.")

    lines.extend(["", "## Evaluated Examples", ""])
    for result in evaluated[:5]:
        lines.extend(
            [
                f"### {result.qa_id} - {result.category}",
                "",
                f"Question: {result.question}",
                "",
                f"Answer: {result.answer}",
                "",
                f"Citations: {', '.join(result.citation_ids) if result.citation_ids else 'none'}",
                "",
            ]
        )

    if skipped:
        lines.extend(["", "## Skipped Examples", ""])
        for result in skipped[:10]:
            lines.append(f"- {result.qa_id} ({result.doc_id}): {result.status} - {result.skip_reason}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def asdict_safe(value: Any) -> dict[str, Any]:
    return asdict(value)


def _count_by(results: list[Any], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        key = str(getattr(result, field_name))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _rate(results: list[Any], predicate) -> float | None:
    if not results:
        return None
    return round(sum(1 for result in results if predicate(result)) / len(results), 4)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = max(0, min(len(sorted_values) - 1, round((percentile / 100) * (len(sorted_values) - 1))))
    return round(sorted_values[index], 2)
