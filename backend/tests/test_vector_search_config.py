from types import SimpleNamespace

from fastapi.testclient import TestClient

from docifer_backend.config.settings import Settings, get_settings
from docifer_backend.main import create_app
from docifer_backend.retrieval.vector_store import (
    ensure_text_collection,
    search_table_evidence_points,
    search_text_chunks,
    search_visual_evidence_points,
)
from docifer_backend.storage.qdrant import get_vector_collection_stats


def setup_function():
    get_settings.cache_clear()


def teardown_function():
    get_settings.cache_clear()


def test_settings_parse_qdrant_search_config(monkeypatch):
    monkeypatch.setenv("QDRANT_EXACT_SEARCH", "true")
    monkeypatch.setenv("QDRANT_SEARCH_EF", "128")
    monkeypatch.setenv("QDRANT_HNSW_M", "32")
    monkeypatch.setenv("QDRANT_HNSW_EF_CONSTRUCT", "200")
    monkeypatch.setenv("QDRANT_CREATE_PAYLOAD_INDEXES", "false")

    settings = Settings()

    assert settings.qdrant_exact_search is True
    assert settings.qdrant_search_ef == 128
    assert settings.qdrant_hnsw_m == 32
    assert settings.qdrant_hnsw_ef_construct == 200
    assert settings.qdrant_create_payload_indexes is False


def test_vector_search_params_apply_to_text_table_and_visual(monkeypatch):
    monkeypatch.setenv("QDRANT_EXACT_SEARCH", "true")
    monkeypatch.setenv("QDRANT_SEARCH_EF", "128")
    get_settings.cache_clear()
    client = FakeQueryClient()

    text_results = search_text_chunks(
        client,
        collection_name="text",
        query_vector=[0.1, 0.2, 0.3],
        top_k=1,
        content_hash="a" * 64,
    )
    assert text_results[0].chunk_id == "chunk-1"
    assert client.calls[-1]["search_params"].exact is True
    assert client.calls[-1]["search_params"].hnsw_ef == 128

    table_results = search_table_evidence_points(
        client,
        collection_name="tables",
        query_vector=[0.1, 0.2, 0.3],
        top_k=1,
    )
    assert table_results == [("table-1", 0.75)]
    assert client.calls[-1]["search_params"].exact is True
    assert client.calls[-1]["search_params"].hnsw_ef == 128

    visual_results = search_visual_evidence_points(
        client,
        collection_name="visuals",
        query_vector=[0.1, 0.2, 0.3],
        top_k=1,
    )
    assert visual_results == [("visual-1", 0.75)]
    assert client.calls[-1]["search_params"].exact is True
    assert client.calls[-1]["search_params"].hnsw_ef == 128


def test_payload_index_creation_called_for_text_collection(monkeypatch):
    monkeypatch.setenv("QDRANT_HNSW_M", "32")
    monkeypatch.setenv("QDRANT_HNSW_EF_CONSTRUCT", "200")
    monkeypatch.setenv("QDRANT_CREATE_PAYLOAD_INDEXES", "true")
    get_settings.cache_clear()
    client = FakeCollectionClient(collection_exists=False)

    ensure_text_collection(client, collection_name="docifer_text_chunks", vector_size=1536)

    assert client.created_collection["collection_name"] == "docifer_text_chunks"
    assert client.created_collection["hnsw_config"].m == 32
    assert client.created_collection["hnsw_config"].ef_construct == 200
    indexed_fields = {call["field_name"] for call in client.payload_index_calls}
    assert indexed_fields == {"content_hash", "document_id", "source_path", "page_start"}


def test_collection_stats_endpoint_returns_expected_fields(monkeypatch):
    import docifer_backend.api.vector as vector_module

    fake_client = FakeStatsClient(collection_exists=True)
    monkeypatch.setattr(vector_module, "get_qdrant_client", lambda: fake_client)

    app = create_app()
    response = TestClient(app).get("/vector/collections/docifer_text_chunks/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["collection_name"] == "docifer_text_chunks"
    assert data["points_count"] == 1235
    assert data["vector_size"] == 1536
    assert data["distance"] == "Cosine"
    assert data["payload_indexes"] == ["content_hash", "document_id", "page_start"]
    assert data["status"] == "green"


def test_collection_stats_function_raises_for_missing_collection():
    fake_client = FakeStatsClient(collection_exists=False)

    try:
        get_vector_collection_stats(
            collection_name="missing",
            client=fake_client,
        )
    except KeyError as exc:
        assert str(exc).strip("'") == "missing"
    else:
        raise AssertionError("Expected missing collection to raise KeyError")


def test_ready_handles_missing_optional_collections_gracefully(monkeypatch):
    import docifer_backend.api.health as health_module

    monkeypatch.setattr(health_module, "check_database_connection", lambda: True)
    monkeypatch.setattr(health_module, "check_qdrant_connection", lambda: True)
    monkeypatch.setattr(
        health_module,
        "get_qdrant_collection_checks",
        lambda: {
            "text_collection": "ok",
            "table_collection": "missing",
            "visual_collection": "missing",
        },
    )

    app = create_app()
    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["qdrant"] == "ok"
    assert data["checks"]["table_collection"] == "missing"
    assert data["checks"]["visual_collection"] == "missing"


class FakeQueryClient:
    def __init__(self):
        self.calls = []

    def query_points(
        self,
        *,
        collection_name,
        query,
        query_filter=None,
        search_params=None,
        limit,
        with_payload=True,
    ):
        self.calls.append(
            {
                "collection_name": collection_name,
                "query": query,
                "query_filter": query_filter,
                "search_params": search_params,
                "limit": limit,
                "with_payload": with_payload,
            }
        )
        if collection_name == "text":
            payload = {
                "chunk_id": "chunk-1",
                "text": "A retrieved text chunk.",
                "filename": "sample.pdf",
                "source_path": "datasets/raw_pdfs/sample.pdf",
                "source_artifact_path": "datasets/processed/sample/canonical.json",
                "content_hash": "a" * 64,
                "page_start": 1,
                "page_end": 1,
            }
        elif collection_name == "tables":
            payload = {"table_id": "table-1"}
        else:
            payload = {"visual_id": "visual-1"}
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    payload=payload,
                    score=0.75,
                )
            ]
        )


class FakeCollectionClient:
    def __init__(self, *, collection_exists: bool):
        self._collection_exists = collection_exists
        self.created_collection = None
        self.payload_index_calls = []

    def collection_exists(self, collection_name):
        return self._collection_exists

    def create_collection(self, **kwargs):
        self.created_collection = kwargs

    def create_payload_index(self, **kwargs):
        self.payload_index_calls.append(kwargs)


class FakeStatsClient:
    def __init__(self, *, collection_exists: bool):
        self._collection_exists = collection_exists

    def collection_exists(self, collection_name):
        return self._collection_exists

    def get_collection(self, collection_name):
        return SimpleNamespace(
            status=SimpleNamespace(value="green"),
            points_count=1235,
            indexed_vectors_count=1200,
            payload_schema={
                "content_hash": object(),
                "document_id": object(),
                "page_start": object(),
            },
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=SimpleNamespace(
                        size=1536,
                        distance=SimpleNamespace(value="Cosine"),
                    )
                ),
                hnsw_config=SimpleNamespace(
                    m=16,
                    ef_construct=100,
                ),
            ),
        )
