from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_local_frontend_origin():
    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allows_friend_frontend_origin():
    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://10.31.9.99:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.headers.get("access-control-allow-origin") == "http://10.31.9.99:5173"


def test_cors_rejects_unconfigured_origin():
    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert "access-control-allow-origin" not in response.headers
