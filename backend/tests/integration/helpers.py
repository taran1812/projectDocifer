from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


# ── Environment helpers ────────────────────────────────────────────────────────

def pg_url() -> str:
    return os.environ.get(
        "DOCIFER_TEST_DATABASE_URL",
        "postgresql+psycopg://docifer:docifer@localhost:5432/docifer_test",
    )


def qdrant_url() -> str:
    return os.environ.get("DOCIFER_TEST_QDRANT_URL", "http://localhost:6333")


def _collection_prefix() -> str:
    return os.environ.get("DOCIFER_TEST_QDRANT_COLLECTION_PREFIX", "test_docifer_")


# ── Constants ─────────────────────────────────────────────────────────────────

TEXT_CONTENT_HASH = "a" * 63 + "1"
TABLE_CONTENT_HASH = "b" * 63 + "1"
VISUAL_CONTENT_HASH = "c" * 63 + "1"
QUERY_HASH_A = "d" * 63 + "1"
QUERY_HASH_B = "e" * 63 + "1"
QUERY_HASH_C = "f" * 63 + "1"
REGISTRY_HASH = "7" * 63 + "2"

TEST_EMBED_DIM = 16

TEXT_COLLECTION = _collection_prefix() + "text_chunks"
TABLE_COLLECTION = _collection_prefix() + "table_evidence"
VISUAL_COLLECTION = _collection_prefix() + "visual_evidence"
ALL_TEST_COLLECTIONS = [TEXT_COLLECTION, TABLE_COLLECTION, VISUAL_COLLECTION]


# ── Fixture data ───────────────────────────────────────────────────────────────

DOCLING_TEXT = {
    "texts": [
        {
            "text": "Middle-income countries need structural reforms to escape the middle-income trap.",
            "label": "text",
            "prov": [{"page_no": 1}],
            "self_ref": "#/texts/0",
        },
        {
            "text": "Institutional quality and investment in human capital are key factors for growth.",
            "label": "text",
            "prov": [{"page_no": 1}],
            "self_ref": "#/texts/1",
        },
    ],
    "tables": [],
    "pictures": [],
}

DOCLING_TABLE = {
    "texts": [
        {
            "text": "GDP growth rate comparison across regions.",
            "label": "text",
            "prov": [{"page_no": 1}],
            "self_ref": "#/texts/0",
        },
    ],
    "tables": [
        {
            "prov": [{"page_no": 1}],
            "data": {
                "grid": [
                    [
                        {"text": "Region", "column_header": True, "row_header": False, "row_section": False},
                        {"text": "Growth %", "column_header": True, "row_header": False, "row_section": False},
                    ],
                    [
                        {"text": "East Asia", "column_header": False, "row_header": False, "row_section": False},
                        {"text": "5.2", "column_header": False, "row_header": False, "row_section": False},
                    ],
                ]
            },
        }
    ],
    "pictures": [],
}

DOCLING_VISUAL = {
    "texts": [],
    "tables": [],
    "pictures": [],
}


# ── Tiny PDF builder ───────────────────────────────────────────────────────────

def make_tiny_pdf() -> bytes:
    obj1 = b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
    obj2 = b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
    obj3 = b"3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>\nendobj\n"
    header = b"%PDF-1.4\n"

    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    xref_start = off3 + len(obj3)

    body = header + obj1 + obj2 + obj3
    xref = (
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        + f"{off1:010d} 00000 n \n".encode()
        + f"{off2:010d} 00000 n \n".encode()
        + f"{off3:010d} 00000 n \n".encode()
        + b"trailer\n<</Size 4/Root 1 0 R>>\nstartxref\n"
        + f"{xref_start}\n%%EOF".encode()
    )
    return body + xref


# ── Canonical fixture factory ──────────────────────────────────────────────────

def make_canonical_fixture(
    base_dir: Path,
    *,
    name: str,
    content_hash: str,
    docling_data: dict,
    page_count: int = 1,
    table_count: int = 0,
    figure_count: int = 0,
    with_pdf: bool = False,
) -> Path:
    doc_dir = base_dir / name
    doc_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = doc_dir / f"{name}.pdf"
    pdf_path.write_bytes(make_tiny_pdf() if with_pdf else b"%PDF-1.4 placeholder")

    docling_path = doc_dir / "docling.json"
    docling_path.write_text(json.dumps(docling_data), encoding="utf-8")

    md_content = "# Integration Test Document\n\nMiddle-income countries need reforms.\n"
    if table_count:
        md_content += "\n<!-- page 1 -->\n| Region | Growth % |\n|---|---|\n| East Asia | 5.2 |\n"
    md_path = doc_dir / "document.md"
    md_path.write_text(md_content, encoding="utf-8")

    canonical = {
        "schema_version": "docifer.canonical_document.v1",
        "document": {
            "filename": f"{name}.pdf",
            "source_path": str(pdf_path),
            "content_hash": content_hash,
        },
        "parse": {
            "page_count": page_count,
            "table_count": table_count,
            "figure_count": figure_count,
        },
        "parser": {"name": "docling", "version": "test"},
        "content": {"markdown_char_count": len(md_content)},
        "artifacts": {
            "directory": str(doc_dir),
            "docling_json": str(docling_path),
            "markdown": str(md_path),
        },
    }
    canonical_path = doc_dir / "canonical.json"
    canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
    return canonical_path


# ── Fake vector helper (shared with conftest FakeIntegrationProvider) ──────────

def fake_vector(text: str, dim: int = TEST_EMBED_DIM) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(dim)]
