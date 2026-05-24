from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

import httpx
import pytest

import docifer_backend.api.documents as documents_api
import docifer_backend.api.retrieval as retrieval_api
from docifer_backend.main import create_app
from docifer_backend.retrieval.indexing import TextIndexOutcome
from docifer_backend.schemas.documents import (
    DocumentListResponse,
    DocumentModalitiesResponse,
    DocumentSummaryResponse,
    ModalityIndexStatus,
)


@pytest.mark.asyncio
async def test_document_list_requests_do_not_serialize_blocking_registry_work(monkeypatch):
    monkeypatch.setattr(
        documents_api,
        "DocumentRegistryService",
        lambda: SlowDocumentRegistryService(constructor_delay=0.2, call_delay=0.05),
    )

    elapsed = await _time_two_requests("GET", "/documents")

    assert elapsed < 0.35


@pytest.mark.asyncio
async def test_text_index_requests_do_not_serialize_blocking_index_work(monkeypatch):
    monkeypatch.setattr(
        retrieval_api,
        "TextIndexingService",
        lambda: SlowTextIndexingService(constructor_delay=0.2, call_delay=0.05),
    )

    elapsed = await _time_two_requests(
        "POST",
        "/index/text",
        json={"canonical_path": "datasets/processed/test/canonical.json"},
    )

    assert elapsed < 0.35


async def _time_two_requests(method: str, url: str, **kwargs) -> float:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        start = time.perf_counter()
        responses = await asyncio.gather(
            client.request(method, url, **kwargs),
            client.request(method, url, **kwargs),
        )
        elapsed = time.perf_counter() - start

    assert [response.status_code for response in responses] == [200, 200]
    return elapsed


@dataclass
class SlowDocumentRegistryService:
    constructor_delay: float
    call_delay: float

    def __post_init__(self) -> None:
        time.sleep(self.constructor_delay)

    def list_documents(self, **kwargs) -> DocumentListResponse:
        time.sleep(self.call_delay)
        return DocumentListResponse(
            documents=[
                DocumentSummaryResponse(
                    document_id="doc-1",
                    doc_id="DOC-TEST",
                    content_hash="a" * 64,
                    filename="test.pdf",
                    source_path="datasets/raw_pdfs/test.pdf",
                    parser_name="docling",
                    latest_ingestion_status="parsed",
                    quality_status="good",
                    modalities=DocumentModalitiesResponse(
                        text=ModalityIndexStatus(status="indexed", count=1),
                        table=ModalityIndexStatus(status="not_indexed", count=0),
                        visual=ModalityIndexStatus(status="not_indexed", count=0),
                    ),
                )
            ],
            total=1,
            limit=kwargs["limit"],
            offset=kwargs["offset"],
        )


@dataclass
class SlowTextIndexingService:
    constructor_delay: float
    call_delay: float

    def __post_init__(self) -> None:
        time.sleep(self.constructor_delay)

    def index_canonical_document(self, canonical_path, *, force_reindex=False):
        time.sleep(self.call_delay)
        return TextIndexOutcome(
            document_id="doc-1",
            content_hash="a" * 64,
            status="indexed",
            chunk_count=1,
            collection_name="docifer_text_chunks",
            reused_existing=False,
        )
