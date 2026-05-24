"""Tests for vector store async functionality."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from docifer_backend.retrieval.vector_store import search_text_chunks_async


@pytest.mark.asyncio
async def test_search_text_chunks_async_returns_list():
    mock_client = AsyncMock()
    mock_point = MagicMock()
    mock_point.id = "chunk-001"
    mock_point.score = 0.95
    mock_point.payload = {
        "text": "hello world",
        "source_path": "doc.pdf",
        "source_artifact_path": "artifacts/doc.json",
        "page_start": 1,
        "page_end": 1,
        "content_hash": "abc123",
        "chunk_index": 0,
    }
    mock_client.query_points = AsyncMock(return_value=MagicMock(points=[mock_point]))

    mock_embedder = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    results = await search_text_chunks_async(
        query="hello",
        client=mock_client,
        collection_name="test_collection",
        embed_fn=mock_embedder,
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].text == "hello world"
    assert results[0].score == 0.95
