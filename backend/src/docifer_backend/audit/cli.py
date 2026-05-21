from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from docifer_backend.audit.service import ParseQualityReport, ParseQualityService
from docifer_backend.evaluation.registry import DocumentRegistry


def _build_service() -> ParseQualityService:
    return ParseQualityService()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run parse quality audits on Docifer canonical artifacts."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--canonical-path", type=Path, help="Path to a canonical.json artifact.")
    group.add_argument("--content-hash", help="Document content hash to audit.")
    group.add_argument("--doc-id", help="Starter corpus document ID, such as DOC-001.")
    group.add_argument("--all-indexed", action="store_true", help="Audit every indexed document.")
    parser.add_argument("--audit-run-id", help="Optional shared run ID for batch audits.")
    args = parser.parse_args(argv)

    service = _build_service()
    run_id = args.audit_run_id or str(uuid4())

    if args.all_indexed:
        reports = service.audit_all_indexed(audit_run_id=run_id)
        print(json.dumps([_report_to_dict(report) for report in reports], indent=2, sort_keys=True))
        return 0 if all(report.audit_status == "completed" for report in reports) else 1

    if args.canonical_path:
        report = _audit_canonical_path(service, args.canonical_path, audit_run_id=run_id)
    elif args.content_hash:
        report = service.audit_by_content_hash(args.content_hash, audit_run_id=run_id)
    else:
        report = _audit_doc_id(service, args.doc_id, audit_run_id=run_id)

    print(json.dumps(_report_to_dict(report), indent=2, sort_keys=True))
    return 0 if report.audit_status == "completed" else 1


def _audit_canonical_path(
    service: ParseQualityService,
    canonical_path: Path,
    *,
    audit_run_id: str,
) -> ParseQualityReport:
    canonical = canonical_path.resolve()
    canonical_data = json.loads(canonical.read_text(encoding="utf-8"))
    content_hash = str(canonical_data["document"]["content_hash"])
    return service.audit(canonical, content_hash, audit_run_id=audit_run_id)


def _audit_doc_id(
    service: ParseQualityService,
    doc_id: str,
    *,
    audit_run_id: str,
) -> ParseQualityReport:
    registry = DocumentRegistry()
    doc_ref = registry.resolve(doc_id)
    if not doc_ref.content_hash:
        return ParseQualityReport(
            audit_id="",
            content_hash="",
            audit_status="failed",
            quality_status=None,
            text_readiness=None,
            table_readiness=None,
            visual_readiness=None,
            error_message=f"No indexed document found for doc_id {doc_id!r}.",
            failed_stage="resolve_doc_id",
        )
    return service.audit_by_content_hash(doc_ref.content_hash, audit_run_id=audit_run_id)


def _report_to_dict(report: ParseQualityReport) -> dict:
    return {
        "audit_id": report.audit_id,
        "content_hash": report.content_hash,
        "audit_status": report.audit_status,
        "quality_status": report.quality_status,
        "text_readiness": report.text_readiness,
        "table_readiness": report.table_readiness,
        "visual_readiness": report.visual_readiness,
        "risk_flags": report.risk_flags,
        "elapsed_ms": report.elapsed_ms,
        "error_message": report.error_message,
        "failed_stage": report.failed_stage,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
