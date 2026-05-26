from fastapi.testclient import TestClient

from docifer_backend.config.settings import Settings
from docifer_backend.main import create_app


def test_settings_parse_cors_origins_from_comma_separated_string():
    settings = Settings(cors_allowed_origins="http://localhost:5173,http://127.0.0.1:5173")

    assert settings.parsed_cors_allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_cors_preflight_allows_local_vite_origin(monkeypatch):
    monkeypatch.setattr(
        "docifer_backend.main.get_settings",
        lambda: Settings(cors_allowed_origins="http://localhost:5173"),
    )
    client = TestClient(create_app())

    response = client.options(
        "/documents",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
