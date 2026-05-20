from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ParsedDocument:
    parser_name: str
    parser_version: str
    docling_status: str
    raw_document: dict[str, Any]
    markdown: str
    page_count: int
    table_count: int
    figure_count: int
    errors: list[dict[str, Any]] = field(default_factory=list)


class DocumentParser(Protocol):
    def parse(self, source_path: Path) -> ParsedDocument:
        ...


class DoclingParser:
    parser_name = "docling"

    def parse(self, source_path: Path) -> ParsedDocument:
        from importlib.metadata import version

        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(source_path)
        document = result.document
        raw_document = _json_safe(_export_document(document))
        markdown = _export_markdown(document)

        return ParsedDocument(
            parser_name=self.parser_name,
            parser_version=version("docling"),
            docling_status=_stringify(getattr(result, "status", None)),
            raw_document=raw_document,
            markdown=markdown,
            page_count=_infer_page_count(raw_document),
            table_count=_infer_labeled_count(raw_document, {"table", "table_item"}),
            figure_count=_infer_labeled_count(raw_document, {"picture", "figure", "image"}),
            errors=_json_safe(_serialize_errors(getattr(result, "errors", []))),
        )


def _export_document(document: Any) -> dict[str, Any]:
    if hasattr(document, "export_to_dict"):
        return document.export_to_dict()
    if hasattr(document, "model_dump"):
        return document.model_dump(mode="json")
    return {"repr": repr(document)}


def _export_markdown(document: Any) -> str:
    if hasattr(document, "export_to_markdown"):
        return document.export_to_markdown()
    if hasattr(document, "export_to_text"):
        return document.export_to_text()
    return ""


def _serialize_errors(errors: Any) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for error in errors or []:
        if hasattr(error, "model_dump"):
            serialized.append(error.model_dump(mode="json"))
        elif isinstance(error, dict):
            serialized.append(error)
        else:
            serialized.append({"message": str(error)})
    return serialized


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _stringify(value: Any) -> str:
    if value is None:
        return "unknown"
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _infer_page_count(raw_document: dict[str, Any]) -> int:
    pages = raw_document.get("pages")
    if isinstance(pages, dict):
        return len(pages)
    if isinstance(pages, list):
        return len(pages)
    return 0


def _infer_labeled_count(value: Any, labels: set[str]) -> int:
    count = 0
    if isinstance(value, dict):
        label = value.get("label")
        if isinstance(label, str) and label.lower().replace(" ", "_") in labels:
            count += 1
        for child in value.values():
            count += _infer_labeled_count(child, labels)
    elif isinstance(value, list):
        for child in value:
            count += _infer_labeled_count(child, labels)
    return count
