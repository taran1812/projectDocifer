from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
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


class AutoPdfParser:
    """Choose the strongest parser that is practical for a local text-RAG run."""

    def __init__(
        self,
        *,
        docling_parser: DocumentParser | None = None,
        text_parser: DocumentParser | None = None,
        docling_max_file_size_bytes: int = 1_000_000,
        backend: str = "auto",
    ) -> None:
        self.docling_parser = docling_parser or DoclingParser()
        self.text_parser = text_parser or PdfiumTextParser()
        self.docling_max_file_size_bytes = docling_max_file_size_bytes
        self.backend = backend

    def parse(self, source_path: Path) -> ParsedDocument:
        backend = self.backend.lower().strip()
        if backend == "docling":
            return self.docling_parser.parse(source_path)
        if backend in {"pdfium", "pdfium_text", "text"}:
            return self.text_parser.parse(source_path)
        if backend != "auto":
            raise ValueError(
                "Unsupported PDF parser backend. Use auto, docling, or pdfium_text."
            )

        if source_path.stat().st_size > self.docling_max_file_size_bytes:
            parsed = self.text_parser.parse(source_path)
            return replace(
                parsed,
                errors=[
                    {
                        "type": "parser_selection",
                        "message": (
                            "Used text-only PDF parser because file size exceeded "
                            "the local Docling threshold."
                        ),
                        "docling_max_file_size_bytes": self.docling_max_file_size_bytes,
                    },
                    *parsed.errors,
                ],
            )

        try:
            return self.docling_parser.parse(source_path)
        except Exception as exc:
            parsed = self.text_parser.parse(source_path)
            return replace(
                parsed,
                errors=[
                    {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "stage": "docling_primary_parser",
                    },
                    *parsed.errors,
                ],
            )


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


class PdfiumTextParser:
    parser_name = "pypdfium2-text"

    def parse(self, source_path: Path) -> ParsedDocument:
        from importlib.metadata import version

        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(source_path))
        texts: list[dict[str, Any]] = []
        markdown_pages: list[str] = []
        try:
            for page_index in range(len(pdf)):
                page_number = page_index + 1
                page = pdf[page_index]
                text_page = page.get_textpage()
                try:
                    text = _normalize_pdfium_text(text_page.get_text_range())
                finally:
                    text_page.close()
                    page.close()

                if not text:
                    continue

                texts.append(
                    {
                        "self_ref": f"#/texts/{len(texts)}",
                        "label": "text",
                        "text": text,
                        "prov": [{"page_no": page_number}],
                    }
                )
                markdown_pages.append(f"<!-- page {page_number} -->\n\n{text}")

            page_count = len(pdf)
        finally:
            pdf.close()

        raw_document = {
            "schema_name": "docifer.pdfium_text_document",
            "pages": {
                str(page_number): {"page_no": page_number}
                for page_number in range(1, page_count + 1)
            },
            "texts": texts,
        }

        return ParsedDocument(
            parser_name=self.parser_name,
            parser_version=version("pypdfium2"),
            docling_status="text_extracted",
            raw_document=raw_document,
            markdown="\n\n".join(markdown_pages),
            page_count=page_count,
            table_count=0,
            figure_count=0,
            errors=[],
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


def _normalize_pdfium_text(value: str) -> str:
    lines = [line.strip() for line in value.replace("\r", "\n").splitlines()]
    return "\n".join(line for line in lines if line)
