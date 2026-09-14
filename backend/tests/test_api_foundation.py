from app.main import create_app
from app.core.config import Settings
from fastapi.testclient import TestClient


LEGACY_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/api/v1/complaints",
    "/api/v1/cases",
    "/api/v1/cases/{case_id}",
    "/api/v1/cases/{case_id}/trace",
    "/api/v1/cases/{case_id}/graph",
    "/api/v1/cases/{case_id}/related",
    "/api/v1/alerts",
    "/api/v1/alerts/{alert_id}/read",
    "/api/v1/vasp/directory",
    "/api/v1/vasp/addresses",
    "/api/v1/cases/{case_id}/generate-freeze-notice",
    "/api/v1/cases/{case_id}/generate-court-report",
    "/api/v1/dashboard/stats",
}


def test_legacy_frontend_paths_and_new_health_paths_are_registered(client):
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])

    assert LEGACY_PATHS <= paths
    assert {"/health/live", "/health/ready"} <= paths
    assert "StandardError" in schema["components"]["schemas"]
    assert schema["paths"]["/api/v1/cases"]["get"]["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/StandardError")


def test_request_and_correlation_ids_are_returned(client):
    response = client.get("/health/live", headers={"X-Request-ID": "phase1-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "phase1-request"
    assert response.headers["X-Correlation-ID"] == "phase1-request"


def test_invalid_request_id_is_replaced(client):
    response = client.get("/health/live", headers={"X-Request-ID": "invalid request id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id"


def test_http_and_validation_errors_use_standard_envelope(client, auth_headers):
    not_found = client.get("/missing-resource")
    invalid_page = client.get("/api/v1/cases?page=0", headers=auth_headers)

    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "NOT_FOUND"
    assert not_found.json()["error"]["request_id"] == not_found.headers["X-Request-ID"]
    assert invalid_page.status_code == 422
    assert invalid_page.json()["error"]["code"] == "VALIDATION_ERROR"
    assert invalid_page.json()["error"]["field_errors"][0]["field"] == "page"


def test_health_does_not_expose_secret_values(client):
    payload = client.get("/health/ready").json()

    assert payload["data_mode"] == "fixture"
    assert "phase-one-test-secret" not in str(payload)
    assert set(payload["providers"]) == {"BTC", "ETH", "TRON", "BSC", "POLYGON"}


def test_live_mode_does_not_seed_fixture_data(monkeypatch):
    settings = Settings.from_env({
        "APP_ENV": "test",
        "DATA_MODE": "live",
        "DEMO_ENABLED": "false",
        "JWT_SECRET_KEY": "phase-one-test-secret-with-safe-length",
        "ENABLED_CHAINS": "BTC",
    })
    monkeypatch.setattr("app.main.seed_all", lambda _: (_ for _ in ()).throw(AssertionError("seed called")))

    app = create_app(settings)
    assert app.state.settings.fixture_data_enabled is False
    with TestClient(app) as live_client:
        assert live_client.get("/health/live").status_code == 200


def test_cors_has_no_wildcard_origin(client):
    middleware_options = [item.kwargs for item in client.app.user_middleware if item.cls.__name__ == "CORSMiddleware"]

    assert middleware_options
    assert "*" not in middleware_options[0]["allow_origins"]
