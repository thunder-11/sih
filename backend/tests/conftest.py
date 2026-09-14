import os

import pytest


os.environ["APP_ENV"] = "test"
os.environ["DATA_MODE"] = "fixture"
os.environ["DEMO_ENABLED"] = "true"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "phase-one-test-secret-with-safe-length"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:5173"

from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth_headers(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "inspector.sharma@cyberpolice.gov.in", "password": "cfas2026"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
