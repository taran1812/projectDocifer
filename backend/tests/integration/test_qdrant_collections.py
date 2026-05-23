import pytest

from docifer_backend.retrieval.vector_store import (
    TEXT_PAYLOAD_INDEXES,
    TABLE_PAYLOAD_INDEXES,
    ensure_text_collection,
    ensure_table_collection,
)
from docifer_backend.storage.qdrant import get_vector_collection_stats

from helpers import TEXT_COLLECTION, TABLE_COLLECTION, TEST_EMBED_DIM


pytestmark = pytest.mark.integration


def test_text_collection_can_be_created(qdrant_client):
    ensure_text_collection(
        qdrant_client, collection_name=TEXT_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    assert qdrant_client.collection_exists(TEXT_COLLECTION)


def test_table_collection_can_be_created(qdrant_client):
    ensure_table_collection(
        qdrant_client, collection_name=TABLE_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    assert qdrant_client.collection_exists(TABLE_COLLECTION)


def test_collection_stats_return_correct_vector_size(qdrant_client):
    ensure_text_collection(
        qdrant_client, collection_name=TEXT_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    stats = get_vector_collection_stats(
        collection_name=TEXT_COLLECTION, client=qdrant_client
    )
    assert stats["collection_name"] == TEXT_COLLECTION
    assert stats["vector_size"] == TEST_EMBED_DIM
    assert stats["status"] in ("green", "yellow", "grey", "red")


def test_text_payload_indexes_are_registered(qdrant_client):
    ensure_text_collection(
        qdrant_client, collection_name=TEXT_COLLECTION, vector_size=TEST_EMBED_DIM
    )
    stats = get_vector_collection_stats(
        collection_name=TEXT_COLLECTION, client=qdrant_client
    )
    for field in TEXT_PAYLOAD_INDEXES:
        assert field in stats["payload_indexes"], f"Missing payload index: {field}"


def test_nonexistent_collection_stats_raises_key_error(qdrant_client):
    with pytest.raises(KeyError):
        get_vector_collection_stats(
            collection_name="nonexistent_xyzzy_99", client=qdrant_client
        )
