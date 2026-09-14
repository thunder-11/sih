def test_login_and_current_user_contract(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "inspector.sharma@cyberpolice.gov.in", "password": "cfas2026"},
    )

    assert login.status_code == 200
    payload = login.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["role"] == "investigator"

    profile = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"})
    assert profile.status_code == 200
    assert profile.json()["email"] == payload["user"]["email"]


def test_case_list_keeps_frontend_wrapper_and_adds_canonical_page(client, auth_headers):
    response = client.get("/api/v1/cases?page=1&page_size=2", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["cases"] == payload["items"]
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["total"] >= len(payload["items"])


def test_frontend_read_contracts_keep_expected_wrappers(client, auth_headers):
    cases = client.get("/api/v1/cases", headers=auth_headers).json()["cases"]
    assert cases
    case_id = cases[0]["id"]

    detail = client.get(f"/api/v1/cases/{case_id}", headers=auth_headers)
    graph = client.get(f"/api/v1/cases/{case_id}/graph", headers=auth_headers)
    related = client.get(f"/api/v1/cases/{case_id}/related", headers=auth_headers)
    alerts = client.get("/api/v1/alerts", headers=auth_headers)
    vasps = client.get("/api/v1/vasp/directory", headers=auth_headers)
    addresses = client.get("/api/v1/vasp/addresses", headers=auth_headers)
    dashboard = client.get("/api/v1/dashboard/stats", headers=auth_headers)

    assert detail.status_code == 200 and "wallets" in detail.json()
    assert graph.status_code == 200 and {"nodes", "edges"} <= set(graph.json())
    assert related.status_code == 200 and "linked_cases" in related.json()
    assert alerts.status_code == 200 and alerts.json()["alerts"] == alerts.json()["items"]
    assert vasps.status_code == 200 and vasps.json()["vasps"] == vasps.json()["items"]
    assert addresses.status_code == 200 and addresses.json()["addresses"] == addresses.json()["items"]
    assert dashboard.status_code == 200 and "total_cases" in dashboard.json()


def test_auth_dependency_rejects_missing_credentials_with_standard_error(client):
    response = client.get("/api/v1/cases")

    assert response.status_code in {401, 403}
    assert response.json()["error"]["code"] in {"UNAUTHORIZED", "FORBIDDEN"}
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_trace_rejects_missing_origin_instead_of_creating_synthetic_wallet(client, auth_headers):
    from database import SessionLocal
    from models import Case

    db = SessionLocal()
    try:
        db.add(Case(
            id="phase1-no-origin",
            external_complaint_id="PHASE1-NO-ORIGIN",
            reported_loss_amount=1,
            fraud_typology="OTHER",
            assigned_officer_id="usr-io-001",
        ))
        db.commit()
    finally:
        db.close()

    response = client.post("/api/v1/cases/phase1-no-origin/trace", json={}, headers=auth_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ORIGIN_WALLET_REQUIRED"


def test_trace_rejects_ambiguous_network_instead_of_guessing(client, auth_headers):
    response = client.post(
        "/api/v1/cases/case-demo-001/trace",
        json={"start_wallet": "ambiguous-address"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NETWORK_REQUIRED"
