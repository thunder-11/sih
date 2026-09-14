from datetime import datetime, timedelta, timezone

from app.persistence.models import AnalysisRun, AuditEvent, BackgroundJob, ComplaintRecord, ReportEvent, UserAgencyScope, UserSession
from auth.utils import hash_password
from database import SessionLocal
from models import Case, User


def login(client, email="inspector.sharma@cyberpolice.gov.in", password="cfas2026"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def test_session_refresh_rotation_and_logout_revocation(client):
    session = login(client)
    assert session["refresh_token"]
    assert session["expires_at"]
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != session["refresh_token"]
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert replay.status_code == 401
    rotated_headers = {"Authorization": f"Bearer {rotated.json()['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=rotated_headers).status_code == 204
    rejected = client.get("/api/v1/auth/me", headers=rotated_headers)
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "SESSION_REVOKED"


def test_wallet_validation_requires_manual_evm_network_selection(client, auth_headers):
    address = "0x" + "a" * 40
    ambiguous = client.post("/api/v1/wallets/validate", json={"address": address}, headers=auth_headers)
    assert ambiguous.status_code == 200
    assert ambiguous.json()["ambiguous"] is True
    assert ambiguous.json()["candidates"] == ["ETH", "BSC", "POLYGON"]

    selected = client.post("/api/v1/wallets/validate", json={"address": address, "chain": "POLYGON"}, headers=auth_headers)
    assert selected.json()["valid"] is True
    assert selected.json()["network"] == "POLYGON"


def test_atomic_intake_report_time_idempotency_and_exactly_one_run(client, auth_headers):
    payload = {
        "complaint_source": "ncrp",
        "external_complaint_id": "NCRP-PHASE3-001",
        "victim_name": "Protected Victim",
        "victim_phone": "+91-9999999999",
        "reported_loss_amount": "12500.1234",
        "loss_currency": "USDT",
        "victim_reported_at": "2026-09-12T10:00:00.500000+05:30",
        "report_timezone": "Asia/Kolkata",
        "report_timestamp_source": "ncrp_receipt",
        "receipt_reference": "receipt-phase3-001",
        "suspect_wallets": [{"address": "0x" + "1" * 40, "chain": "ETH"}],
    }
    headers = {**auth_headers, "Idempotency-Key": "phase3-intake-001"}
    created = client.post("/api/v1/complaints", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "queued"
    assert body["report_event"]["reported_at_utc"].startswith("2026-09-12T04:30:00.500000")
    assert body["trace_id"] and body["job_id"]

    replay = client.post("/api/v1/complaints", json=payload, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["case_id"] == body["case_id"]
    assert replay.json()["idempotent_replay"] is True

    compatibility = client.post(f"/api/v1/cases/{body['case_id']}/trace", json={
        "start_wallet": "0x" + "1" * 40, "chain": "ETH"
    }, headers=auth_headers)
    assert compatibility.status_code == 202
    assert compatibility.json()["trace_id"] == body["trace_id"]
    assert compatibility.json()["idempotent_replay"] is True

    with SessionLocal() as db:
        assert db.query(AnalysisRun).filter(AnalysisRun.case_id == body["case_id"]).count() == 1
        assert db.query(BackgroundJob).filter(BackgroundJob.case_id == body["case_id"]).count() == 1
        complaint = db.query(ComplaintRecord).filter(ComplaintRecord.id == body["complaint_id"]).one()
        assert "Protected Victim" not in (complaint.narrative_ciphertext or "")


def test_invalid_ambiguous_wallet_and_timestamp_fail_with_field_errors(client, auth_headers):
    ambiguous = client.post("/api/v1/complaints", json={
        "external_complaint_id": "PHASE3-AMBIGUOUS",
        "reported_loss_amount": 0,
        "suspect_wallets": [{"address": "0x" + "2" * 40}],
    }, headers=auth_headers)
    assert ambiguous.status_code == 422
    assert ambiguous.json()["error"]["field_errors"][0]["field"].endswith("chain")

    invalid_time = client.post("/api/v1/complaints", json={
        "external_complaint_id": "PHASE3-TIME",
        "reported_loss_amount": 0,
        "victim_reported_at": "2026-09-12T10:00:00",
        "suspect_wallets": [{"address": "0x" + "3" * 40, "chain": "ETH"}],
    }, headers=auth_headers)
    assert invalid_time.status_code == 422
    assert invalid_time.json()["error"]["code"] == "INVALID_REPORT_TIMESTAMP"

    excessive_precision = client.post("/api/v1/complaints", json={
        "external_complaint_id": "PHASE3-PRECISION",
        "victim_reported_at": "2026-09-12T10:00:00.1234567Z",
        "suspect_wallets": [{"address": "0x" + "6" * 40, "chain": "ETH"}],
    }, headers=auth_headers)
    assert excessive_precision.status_code == 422
    assert excessive_precision.json()["error"]["code"] == "UNSUPPORTED_TIMESTAMP_PRECISION"

    timezone_mismatch = client.post("/api/v1/complaints", json={
        "external_complaint_id": "PHASE3-TIMEZONE-MISMATCH",
        "victim_reported_at": "2026-09-12T10:00:00Z", "report_timezone": "Asia/Kolkata",
        "suspect_wallets": [{"address": "0x" + "7" * 40, "chain": "ETH"}],
    }, headers=auth_headers)
    assert timezone_mismatch.status_code == 422
    assert timezone_mismatch.json()["error"]["code"] == "REPORT_TIMEZONE_MISMATCH"


def test_report_correction_and_case_lifecycle_are_append_only_and_audited(client, auth_headers):
    created = client.post("/api/v1/complaints", json={
        "complaint_source": "manual_fir", "external_complaint_id": "PHASE3-CORRECTION",
        "reported_loss_amount": 1, "victim_reported_at": "2026-09-12T10:00:00Z",
        "suspect_wallets": [{"address": "0x" + "4" * 40, "chain": "BSC"}],
    }, headers={**auth_headers, "Idempotency-Key": "phase3-correction"})
    body = created.json()
    corrected = client.post(f"/api/v1/report-events/{body['report_event_id']}/revisions", json={
        "reported_at": "2026-09-12T15:30:01+05:30", "report_timezone": "Asia/Kolkata",
        "source": "investigator_correction", "channel": "manual_fir",
        "verification_status": "verified", "reason": "Receipt record confirmed",
        "expected_revision": 1,
    }, headers=auth_headers)
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["revision"] == 2
    assert corrected.json()["supersedes_id"] == body["report_event_id"]

    status_response = client.get(f"/api/v1/cases/{body['case_id']}/status", headers=auth_headers)
    revision = status_response.json()["revision"]
    denied_assignment = client.patch(f"/api/v1/cases/{body['case_id']}", json={
        "assigned_officer_id": "usr-analyst-001", "reason": "Attempt assignment without role",
        "revision": revision,
    }, headers=auth_headers)
    assert denied_assignment.status_code == 403
    invalid_frozen = client.patch(f"/api/v1/cases/{body['case_id']}", json={
        "status": "frozen", "reason": "Attempt without confirmation", "revision": revision,
    }, headers=auth_headers)
    assert invalid_frozen.status_code == 422

    closed = client.patch(f"/api/v1/cases/{body['case_id']}", json={
        "status": "closed", "reason": "Investigation closed with recorded outcome", "revision": revision,
    }, headers=auth_headers)
    assert closed.status_code == 200
    reopened = client.patch(f"/api/v1/cases/{body['case_id']}", json={
        "status": "investigating", "reason": "New evidence requires review", "revision": closed.json()["revision"],
    }, headers=auth_headers)
    assert reopened.status_code == 200

    note = client.post(f"/api/v1/cases/{body['case_id']}/notes", json={"content": "Protected analyst note"}, headers=auth_headers)
    assert note.status_code == 201
    history = client.get(f"/api/v1/cases/{body['case_id']}/history", headers=auth_headers)
    assert history.status_code == 200
    assert history.json()["total"] >= 4
    with SessionLocal() as db:
        assert db.query(ReportEvent).filter(ReportEvent.case_id == body["case_id"]).count() == 2
        assert db.query(AuditEvent).filter(AuditEvent.case_id == body["case_id"]).count() >= 4


def test_cross_agency_case_is_not_disclosed(client, auth_headers):
    with SessionLocal() as db:
        from app.persistence.models import Agency
        if db.query(Agency).filter(Agency.id == "agency-other").first() is None:
            db.add(Agency(id="agency-other", name="Other Agency", jurisdiction="India", scope={}, status="active"))
            user = User(id="user-other", email="other@example.test", full_name="Other Investigator",
                        password_hash=hash_password("correct-horse"), role="investigator", status="active",
                        primary_agency_id="agency-other")
            db.add(user)
            db.flush()
            db.add(UserAgencyScope(user_id=user.id, agency_id="agency-other", role="investigator",
                                   permissions=["case:read", "case:write"], status="active"))
            db.commit()
    other = login(client, "other@example.test", "correct-horse")
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    denied = client.get("/api/v1/cases/case-demo-001", headers=other_headers)
    assert denied.status_code == 404
    listing = client.get("/api/v1/cases", headers=other_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    same_external_reference = client.post("/api/v1/complaints", json={
        "complaint_source": "ncrp", "external_complaint_id": "NCRP-PHASE3-001",
        "reported_loss_amount": 2,
        "suspect_wallets": [{"address": "0x" + "5" * 40, "chain": "POLYGON"}],
    }, headers={**other_headers, "Idempotency-Key": "other-agency-same-reference"})
    assert same_external_reference.status_code == 201
