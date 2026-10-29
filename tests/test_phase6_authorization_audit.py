import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.auth_service import AuthService


@pytest.fixture
def auth_env(db_sessions):
    """Fixture ensuring clean database state with seeded demo users and AUTH_REQUIRED=True."""
    prev_auth = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True

    with db_sessions() as db:
        AuthService.seed_demo_users(db)

    yield db_sessions

    settings.AUTH_REQUIRED = prev_auth


def get_token(client, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


def test_unauthenticated_requests_fail_closed(auth_env):
    """Verify that requests without authentication headers fail closed across protected endpoints."""
    client = TestClient(app)
    protected_endpoints = [
        ("GET", "/api/v1/students"),
        ("GET", "/api/v1/enrolments"),
        ("GET", "/api/v1/alerts"),
        ("GET", "/api/v1/intake-compliance"),
        ("GET", "/api/v1/analytics/anomalies"),
        ("GET", "/api/v1/certificates"),
        ("GET", "/api/v1/consent/student/STU-DEMO-001"),
        ("GET", "/api/v1/verifier/logs"),
        ("GET", "/api/v1/reports/executive-summary"),
        ("GET", "/api/v1/audit-trail"),
        ("GET", "/api/v1/auth/users"),
    ]

    for method, path in protected_endpoints:
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json={})
        assert resp.status_code in (401, 403), f"Endpoint {method} {path} did not fail closed: {resp.status_code}"


def test_invalid_and_malformed_authentication_tokens(auth_env):
    """Verify that forged, malformed, or invalid tokens are rejected with HTTP 401."""
    client = TestClient(app)
    invalid_headers = [
        {"Authorization": "Bearer not-a-valid-token"},
        {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.forged.signature"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    ]

    for headers in invalid_headers:
        resp = client.get("/api/v1/students", headers=headers)
        assert resp.status_code == 401
        assert "detail" in resp.json()


def test_role_restriction_external_verifier_cannot_browse_internal_registers(auth_env):
    """Verify external BGV verifiers cannot browse internal academic registers or admin consoles."""
    client = TestClient(app)
    token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    forbidden_paths = [
        "/api/v1/students",
        "/api/v1/enrolments",
        "/api/v1/alerts",
        "/api/v1/intake-compliance",
        "/api/v1/analytics/anomalies",
        "/api/v1/consent/student/STU-DEMO-001",
        "/api/v1/reports/executive-summary",
        "/api/v1/audit-trail",
        "/api/v1/auth/users",
        "/api/v1/dashboard/summary",
        "/api/v1/institution/dashboard-summary",
    ]

    for path in forbidden_paths:
        resp = client.get(path, headers=headers)
        assert resp.status_code == 403, f"Verifier was not blocked from {path}: {resp.status_code}"


def test_role_restriction_read_only_auditor_cannot_mutate_state(auth_env):
    """Verify compliance auditors are strictly prohibited from performing any mutating actions."""
    client = TestClient(app)
    token = get_token(client, "compliance_auditor", "ComplianceAuditor@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    mutations = [
        ("POST", "/api/v1/students", {"student_ref": "STU-NEW", "full_name": "Test", "institution_id": "INST-DELHI-DTU"}),
        ("POST", "/api/v1/enrolments", {"student_ref": "STU-001", "institution_id": "INST-DELHI-DTU"}),
        ("PATCH", "/api/v1/alerts/ALT-2025-001/review", {"decision": "CONFIRMED_CONFLICT", "note": "Auditor review attempt"}),
        ("PATCH", "/api/v1/alerts/ALT-2025-001/assignment", {"assigned_to": "auditor"}),
        ("POST", "/api/v1/certificates/issue", {"student_ref": "STU-001", "institution_id": "INST-DELHI-DTU"}),
        ("POST", "/api/v1/certificates/CERT-2024-001/revoke", {"reason": "Auditor revocation attempt"}),
        ("POST", "/api/v1/certificates/CERT-2024-001/simulate-tamper", {"tamper_type": "CGPA_INFLATION"}),
        ("PATCH", "/api/v1/consent/1/toggle", {"consent_granted": False}),
        ("POST", "/api/v1/consent", {"student_ref": "STU-001"}),
        ("POST", "/api/v1/intake-compliance/rules", {"institution_id": "INST-DELHI-DTU", "programme_id": "BTECH-CSE"}),
        ("PATCH", "/api/v1/analytics/anomalies/1/dismiss", {"reason": "Dismiss attempt"}),
        ("POST", "/api/v1/auth/users", {"username": "new_user"}),
    ]

    for method, path, payload in mutations:
        if method == "POST":
            resp = client.post(path, json=payload, headers=headers)
        else:
            resp = client.patch(path, json=payload, headers=headers)
        assert resp.status_code == 403, f"Auditor was not blocked from {method} {path}: {resp.status_code}"


def test_institution_scope_cross_institution_rejection(auth_env):
    """Verify an institution registrar cannot supply another institution ID to obtain or modify records."""
    client = TestClient(app)
    token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Querying another institution's dashboard -> 403
    resp = client.get("/api/v1/institution/dashboard-summary?institution_id=INST-PUNE-COEP", headers=headers)
    assert resp.status_code == 403
    assert "Cross-institution access is not permitted" in resp.text

    # 2. Querying another institution's programme intake detail -> 403
    resp = client.get("/api/v1/intake-compliance/INST-PUNE-COEP/BTECH-ECE", headers=headers)
    assert resp.status_code == 403

    # 3. Querying another institution's rule history -> 403
    resp = client.get("/api/v1/intake-compliance/INST-PUNE-COEP/BTECH-ECE/rule-history?academic_year=2025-2026", headers=headers)
    assert resp.status_code == 403

    # 4. Querying another institution's historical trends -> 403
    resp = client.get("/api/v1/analytics/historical/INST-PUNE-COEP/BTECH-ECE", headers=headers)
    assert resp.status_code == 403

    # 5. Querying another institution's enrolment trends -> 403
    resp = client.get("/api/v1/analytics/enrolment-trends?institution_id=INST-PUNE-COEP", headers=headers)
    assert resp.status_code == 403

    # 6. Creating enrolment for another institution -> 403
    resp = client.post(
        "/api/v1/enrolments",
        json={
            "student_ref": "STU-TEST-SCOPE",
            "apaar_id": "9876-5432-9999",
            "institution_id": "INST-PUNE-COEP",
            "programme_id": "BTECH-ECE",
            "academic_year": "2025-2026",
            "admission_cycle": "Regular 2025",
            "enrolment_start": "2025-08-01",
            "enrolment_status": "Active",
            "seat_category": "General",
        },
        headers=headers
    )
    assert resp.status_code == 403

    # 7. Creating student with enrolment in another institution -> 403
    resp = client.post(
        "/api/v1/students",
        json={
            "student_ref": "STU-TEST-SCOPE-2",
            "apaar_id": "9876-5432-9998",
            "full_name": "Unauthorized Enrolment",
            "institution_id": "INST-PUNE-COEP",
            "programme_id": "BTECH-ECE",
            "academic_year": "2025-2026",
            "admission_cycle": "Regular 2025",
            "enrolment_start": "2025-08-01",
            "enrolment_status": "Active",
            "seat_category": "General",
        },
        headers=headers
    )
    assert resp.status_code == 403


def test_verifier_organization_scope_isolation(auth_env):
    """Verify BGV verifiers cannot query credentials or logs using another organization ID."""
    client = TestClient(app)
    token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Attempting to verify credentials under another verifier organization ID -> 403
    resp = client.post(
        "/api/v1/verifier/verify-credential",
        json={
            "verifier_org_id": "ORG-INFOSYS-BGV",
            "student_ref": "STU-DEMO-001"
        },
        headers=headers
    )
    assert resp.status_code == 403
    assert "Verifier credentials cannot be used for another organization" in resp.text

    # 2. Attempting to view another verifier organization's audit logs -> 403
    resp = client.get("/api/v1/verifier/logs?verifier_org_id=ORG-INFOSYS-BGV", headers=headers)
    assert resp.status_code == 403
    assert "Verifier credentials cannot read another organization's logs" in resp.text

    # 3. Querying with assigned organization ID -> 200 OK
    valid_resp = client.post(
        "/api/v1/verifier/verify-credential",
        json={
            "verifier_org_id": "ORG-TCS-BGV",
            "student_ref": "STU-DEMO-001"
        },
        headers=headers
    )
    assert valid_resp.status_code == 200
    assert "verified" in valid_resp.json()


def test_sensitive_field_masking_for_non_administrators(auth_env):
    """Verify sensitive fields (APAAR ID, identity evidence, raw signatures) are masked for non-admins."""
    client = TestClient(app)

    # 1. Student list: APAAR ID masked for reviewer
    rev_token = get_token(client, "aicte_reviewer", "AicteReviewer@2026!")
    rev_resp = client.get("/api/v1/students?limit=5", headers={"Authorization": f"Bearer {rev_token}"})
    assert rev_resp.status_code == 200
    for s in rev_resp.json()["items"]:
        if s.get("apaar_id"):
            assert s["apaar_id"].startswith("****"), f"APAAR ID was not masked for reviewer: {s['apaar_id']}"
        assert s.get("passport_ref") is None

    # 2. Student list: APAAR ID unmasked for administrator
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    admin_resp = client.get("/api/v1/students?limit=5", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_resp.status_code == 200
    for s in admin_resp.json()["items"]:
        if s.get("apaar_id"):
            assert not s["apaar_id"].startswith("****"), "APAAR ID should be unmasked for admin"

    # 3. Certificate detail: raw signature_hex redacted for non-admin
    cert_rev_resp = client.get("/api/v1/certificates/CERT-2024-001", headers={"Authorization": f"Bearer {rev_token}"})
    if cert_rev_resp.status_code == 200:
        assert cert_rev_resp.json().get("signature_hex") is None

    cert_admin_resp = client.get("/api/v1/certificates/CERT-2024-001", headers={"Authorization": f"Bearer {admin_token}"})
    if cert_admin_resp.status_code == 200:
        assert cert_admin_resp.json().get("signature_hex") is not None
