from pathlib import Path

import pytest

from docifer_backend.ingestion.parser import AutoPdfParser, ParsedDocument


class RecordingParser:
    def __init__(self, name: str, *, should_fail: bool = False) -> None:
        self.name = name
        self.should_fail = should_fail
        self.calls = 0

    def parse(self, source_path: Path) -> ParsedDocument:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError(f"{self.name} failed")
        return ParsedDocument(
            parser_name=self.name,
            parser_version="0.0-test",
            docling_status="success",
            raw_document={"pages": {"1": {}}, "texts": []},
            markdown="hello",
            page_count=1,
            table_count=0,
            figure_count=0,
            errors=[],
        )


def test_auto_pdf_parser_uses_text_parser_for_large_files(tmp_path):
    pdf_path = tmp_path / "large.pdf"
    pdf_path.write_bytes(b"x" * 20)
    docling = RecordingParser("docling")
    text = RecordingParser("pdfium")
    parser = AutoPdfParser(
        docling_parser=docling,
        text_parser=text,
        docling_max_file_size_bytes=10,
    )

    parsed = parser.parse(pdf_path)

    assert parsed.parser_name == "pdfium"
    assert docling.calls == 0
    assert text.calls == 1
    assert parsed.errors[0]["type"] == "parser_selection"


def test_auto_pdf_parser_falls_back_when_docling_fails(tmp_path):
    pdf_path = tmp_path / "small.pdf"
    pdf_path.write_bytes(b"x")
    docling = RecordingParser("docling", should_fail=True)
    text = RecordingParser("pdfium")
    parser = AutoPdfParser(docling_parser=docling, text_parser=text)

    parsed = parser.parse(pdf_path)

    assert parsed.parser_name == "pdfium"
    assert docling.calls == 1
    assert text.calls == 1
    assert parsed.errors[0]["stage"] == "docling_primary_parser"


def test_auto_pdf_parser_rejects_unknown_backend(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"x")
    parser = AutoPdfParser(backend="nope")

    with pytest.raises(ValueError, match="Unsupported PDF parser backend"):
        parser.parse(pdf_path)
