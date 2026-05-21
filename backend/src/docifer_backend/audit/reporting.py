from __future__ import annotations

import json
from pathlib import Path

from docifer_backend.audit.metrics import AUDIT_VERSION, AuditSummary, AuditVerdicts


def write_audit_artifacts(
    *,
    artifact_dir: Path,
    content_hash: str,
    audit_run_id: str,
    audit_status: str,
    summary: AuditSummary | None,
    verdicts: AuditVerdicts | None,
    elapsed_ms: int | None,
    fallback_used: bool,
    parser_name: str,
    error_message: str | None = None,
) -> tuple[str, str]:
    """Write parse_audit.json and parse_audit.md to artifact_dir.

    Raises OSError if the directory is unwritable.
    Returns (json_path_str, md_path_str).
    """
    json_path = artifact_dir / "parse_audit.json"
    md_path = artifact_dir / "parse_audit.md"

    payload = _build_json_payload(
        content_hash=content_hash,
        audit_run_id=audit_run_id,
        audit_status=audit_status,
        summary=summary,
        verdicts=verdicts,
        elapsed_ms=elapsed_ms,
        fallback_used=fallback_used,
        parser_name=parser_name,
        error_message=error_message,
    )
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(_build_md_report(payload), encoding="utf-8")

    return str(json_path), str(md_path)


def _build_json_payload(
    *,
    content_hash: str,
    audit_run_id: str,
    audit_status: str,
    summary: AuditSummary | None,
    verdicts: AuditVerdicts | None,
    elapsed_ms: int | None,
    fallback_used: bool,
    parser_name: str,
    error_message: str | None,
) -> dict:
    payload: dict = {
        "audit_version": AUDIT_VERSION,
        "audit_run_id": audit_run_id,
        "audit_status": audit_status,
        "content_hash": content_hash,
        "parser_name": parser_name,
        "fallback_used": fallback_used,
        "elapsed_ms": elapsed_ms,
    }
    if error_message is not None:
        payload["error_message"] = error_message
    if verdicts is not None:
        payload["verdicts"] = {
            "quality_status": verdicts.quality_status,
            "text_readiness": verdicts.text_readiness,
            "table_readiness": verdicts.table_readiness,
            "visual_readiness": verdicts.visual_readiness,
            "risk_flags": verdicts.risk_flags,
        }
    if summary is not None:
        payload["summary"] = {
            "page_count": summary.page_count,
            "table_count": summary.table_count,
            "table_candidate_count": summary.table_candidate_count,
            "table_like_page_count": summary.table_like_page_count,
            "figure_count": summary.figure_count,
            "figure_candidate_count": summary.figure_candidate_count,
            "caption_candidate_count": summary.caption_candidate_count,
            "empty_page_count": summary.empty_page_count,
            "text_chars_total": summary.text_chars_total,
            "avg_chars_per_page": summary.avg_chars_per_page,
            "parse_error_count": summary.parse_error_count,
            "chunk_count": summary.chunk_count,
        }
    return payload


def _build_md_report(payload: dict) -> str:
    lines = [
        "# Parse Quality Audit Report",
        "",
        f"**Status:** {payload['audit_status']}",
        f"**Content Hash:** `{payload['content_hash'][:16]}...`",
        f"**Parser:** {payload['parser_name']} (fallback: {payload['fallback_used']})",
        f"**Elapsed:** {payload.get('elapsed_ms', 'n/a')} ms",
        "",
    ]
    if "verdicts" in payload:
        v = payload["verdicts"]
        lines += [
            "## Readiness Verdicts",
            "",
            "| Dimension | Verdict |",
            "|---|---|",
            f"| Overall | **{v['quality_status']}** |",
            f"| Text | {v['text_readiness']} |",
            f"| Tables | {v['table_readiness']} |",
            f"| Visual | {v['visual_readiness']} |",
            "",
        ]
        if v["risk_flags"]:
            lines += ["## Risk Flags", ""]
            lines += [f"- `{flag}`" for flag in v["risk_flags"]]
            lines.append("")
    if "summary" in payload:
        s = payload["summary"]
        lines += [
            "## Summary",
            "",
            f"- Pages: {s['page_count']} ({s['empty_page_count']} empty)",
            f"- Tables: {s['table_count']} structured, {s['table_candidate_count']} candidates",
            f"- Figures: {s['figure_count']} structured, {s['figure_candidate_count']} candidates",
            f"- Text: {s['text_chars_total']:,} chars, {s['avg_chars_per_page']:.0f} avg/page",
            "",
        ]
    if "error_message" in payload:
        lines += ["## Error", "", payload["error_message"], ""]
    return "\n".join(lines)
