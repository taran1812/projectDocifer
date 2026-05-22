from docifer_backend.config.settings import Settings


def test_default_visual_collection_name():
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        qdrant_url="http://localhost:6333",
    )
    assert settings.qdrant_visual_collection == "docifer_visual_evidence"
