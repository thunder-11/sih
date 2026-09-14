import uuid
from hashlib import sha256

from services import report_generator


def _login(client, email):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "cfas2026"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_scoped_search_report_history_and_admin_audit_contracts(client, auth_headers):
    search = client.get("/api/v1/search", params={"q": "NCRP"}, headers=auth_headers)
    assert search.status_code == 200
    assert all(item["type"] == "case" for item in search.json()["items"])
    reports = client.get("/api/v1/reports", headers=auth_headers)
    assert reports.status_code == 200
    assert "items" in reports.json()
    denied = client.get("/api/v1/audit-logs", headers=auth_headers)
    assert denied.status_code == 403


def test_admin_settings_are_versioned_and_never_expose_secrets(client):
    headers = _login(client, "admin@cfas.gov.in")
    current = client.get("/api/v1/admin/settings", headers=headers)
    assert current.status_code == 200
    assert current.json()["secrets_exposed"] is False
    assert set(current.json()["providers"].values()) <= {"configured", "missing_credentials"}
    version = f"phase11-{uuid.uuid4()}"
    created = client.post("/api/v1/admin/settings", headers=headers, json={
        "policy_name": "report-retention", "version": version,
        "effective_at": "2026-09-13T18:00:00Z", "thresholds": {"retention_days": 365},
        "preferences": {"legal_hold_override": True}, "change_reason": "Phase 11 policy verification",
    })
    assert created.status_code == 201, created.text
    assert len(created.json()["content_hash"]) == 64
    audit = client.get("/api/v1/audit-logs", params={"action": "policy.create"}, headers=headers)
    assert audit.status_code == 200
    assert any(item["action"] == "policy.create" for item in audit.json()["items"])


def test_report_generator_separates_content_and_pdf_digests(tmp_path, monkeypatch):
    monkeypatch.setattr(report_generator, "REPORTS_DIR", str(tmp_path))
    result = report_generator.generate_forensic_report(
        {"external_complaint_id": "PHASE11-1", "reported_loss_amount": 1, "loss_currency": "USDT"},
        {"edges": [], "vasp_attribution": None}, {"composite_risk_score": 0, "risk_tier": "unknown"}, {"linked_cases": []})
    assert result["pdf_bytes"].startswith(b"%PDF")
    assert result["sha256_pdf_hash"] == sha256(result["pdf_bytes"]).hexdigest()
    assert result["sha256_content_hash"] != result["sha256_pdf_hash"]
