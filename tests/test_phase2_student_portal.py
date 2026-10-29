import pytest
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.certificate import Certificate
from app.models.consent import StudentConsent
from app.models.transfer import TransferRequest, TransferStatus
from app.models.user import User
from app.models.student_user import StudentUserLink
from app.services.auth_service import AuthService, PasswordHasher
from app.services.student_service import StudentService
import app.seed_data as seed_data


@pytest.fixture
def student_env(db_sessions):
    prev_auth = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True

    # Seed baseline students, enrolments, certificates, consents, demo accounts
    seed_data.init_db_and_seed()
    with db_sessions() as db:
        AuthService.seed_demo_users(db)

        # Create an unlinked student user account for orphaned account testing
        if not db.query(User).filter(User.username == "unlinked_student").first():
            db.add(User(
                username="unlinked_student",
                email="unlinked@pramaan.gov.in",
                password_hash=PasswordHasher.hash_password("UnlinkedStudent@2026!"),
                full_name="Orphaned Student Account",
                role="student",
                role_category="STUDENT",
                institution_id=None,
                is_active=True,
            ))

        # Add a sample transfer record for STU-DEMO-001 so transfers endpoint can be tested
        if not db.query(TransferRequest).filter(TransferRequest.student_ref == "STU-DEMO-001").first():
            db.add(TransferRequest(
                id="TRF-DEMO-PORTAL-01",
                student_ref="STU-DEMO-001",
                apaar_id="9876-5432-1001",
                source_institution_id="INST-DELHI-DTU",
                source_institution_name="Delhi Technological University (Demo)",
                destination_institution_id="INST-DELHI-IIITD",
                destination_institution_name="Indraprastha Institute of Information Technology Delhi",
                source_state="Delhi",
                destination_state="Delhi",
                programme_id="BTECH-CSE",
                programme_name="B.Tech Computer Science & Engineering",
                academic_year="2025-2026",
                initiation_date=date(2025, 7, 20),
                requested_effective_date=date(2025, 8, 1),
                status=TransferStatus.RELEASED,
                noc_certificate_ref="NOC-DTU-2025-0881",
                reviewer_notes="Branch credit transfer requested by student",
                source_decision="APPROVED",
                source_decision_reason="No dues clearance verified",
                created_by="dtu_registrar",
            ))

        db.commit()

    yield db_sessions
    settings.AUTH_REQUIRED = prev_auth


def get_token(client, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


def test_unauthenticated_requests_are_rejected(student_env):
    """
    Verify that unauthenticated callers cannot access any student portal endpoints (401 Unauthorized).
    """
    client = TestClient(app)
    endpoints = [
        "/api/v1/student/profile",
        "/api/v1/student/academic-history",
        "/api/v1/student/credentials",
        "/api/v1/student/transfers",
    ]
    for endpoint in endpoints:
        resp = client.get(endpoint)
        assert resp.status_code == 401, f"Expected 401 for {endpoint}, got {resp.status_code}"
        assert "authentication is required" in resp.json()["detail"].lower()


def test_authenticated_student_profile_access(student_env):
    """
    Verify student can authenticate and retrieve their profile, masked APAAR ID,
    institution, active programme, and DPDP consent preferences.
    """
    client = TestClient(app)
    token = get_token(client, "student_demo", "StudentDemo@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Profile retrieval
    resp = client.get("/api/v1/student/profile", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["student_ref"] == "STU-DEMO-001"
    assert data["full_name"] == "Aarav Sharma"
    assert data["masked_apaar_id"].endswith("1001")
    assert data["identity_route"] == "AADHAAR_APAAR"
    assert data["identity_status"] == "APAAR_VERIFIED"
    assert data["nationality"] == "Indian"
    assert data["account"]["username"] == "student_demo"
    assert data["account"]["role"] == "student"
    assert isinstance(data["consents"], list)
    assert len(data["consents"]) > 0

    # Verify no forbidden demographic fields (religion, caste)
    assert "religion" not in data
    assert "caste" not in data


def test_authenticated_student_academic_history(student_env):
    """
    Verify student can inspect chronological enrolments and status versions.
    """
    client = TestClient(app)
    token = get_token(client, "student_demo", "StudentDemo@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/student/academic-history", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["student_ref"] == "STU-DEMO-001"
    assert data["student_name"] == "Aarav Sharma"
    assert data["total_enrolments"] >= 2
    enrolments = data["enrolments"]
    assert any(e["institution_id"] == "INST-DELHI-DTU" for e in enrolments)
    assert any(e["institution_id"] == "INST-DELHI-NSUT" for e in enrolments)


def test_authenticated_student_credentials(student_env):
    """
    Verify student can retrieve certificates, cryptographic verification status,
    and public key IDs, while internal secrets and private signing keys are never exposed.
    """
    client = TestClient(app)
    token = get_token(client, "student_demo", "StudentDemo@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/student/credentials", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["student_ref"] == "STU-DEMO-001"
    assert data["total_credentials"] >= 1
    cert = data["credentials"][0]
    assert cert["student_ref"] == "STU-DEMO-001"
    assert cert["status"] in {"VALID", "REVOKED"}
    assert cert["signature_algorithm"] in {"HMAC-SHA256", "Ed25519"}
    assert "public_key_id" in cert
    assert cert["is_authentic"] is True
    assert cert["verification_status"] in {"VALID", "AUTHENTIC"}

    # Strict secrecy assertions: No private keys or internal signing keys leaked
    assert "private_key" not in cert
    assert "signing_key" not in cert
    assert "hmac_secret" not in cert


def test_authenticated_student_transfers(student_env):
    """
    Verify student can review their cross-state / inter-institution migration requests.
    """
    client = TestClient(app)
    token = get_token(client, "student_demo", "StudentDemo@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/student/transfers", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["student_ref"] == "STU-DEMO-001"
    assert data["total_transfers"] >= 1
    transfer = data["transfers"][0]
    assert transfer["id"] == "TRF-DEMO-PORTAL-01"
    assert transfer["source_institution_id"] == "INST-DELHI-DTU"
    assert transfer["destination_institution_id"] == "INST-DELHI-IIITD"
    assert transfer["status"] == "RELEASED"
    assert transfer["noc_certificate_ref"] == "NOC-DTU-2025-0881"


def test_student_isolation_student_a_cannot_access_student_b(student_env):
    """
    Strict Tenant Isolation & Identity Binding:
    Student A (Aarav, STU-DEMO-001) attempting to inspect Student B (Priya, STU-DEMO-002)
    via explicit query parameter override is rejected with 403 Forbidden.
    """
    client = TestClient(app)
    token_a = get_token(client, "student_demo", "StudentDemo@2026!")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    token_b = get_token(client, "student_priya", "StudentPriya@2026!")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Student A attempts to access Student B
    resp_tamper = client.get("/api/v1/student/profile?student_ref=STU-DEMO-002", headers=headers_a)
    assert resp_tamper.status_code == 403
    assert "access denied" in resp_tamper.json()["detail"].lower()

    # Student A attempts to access Student B academic history
    resp_tamper_hist = client.get("/api/v1/student/academic-history?student_ref=STU-DEMO-002", headers=headers_a)
    assert resp_tamper_hist.status_code == 403

    # Student B accesses own profile -> gets STU-DEMO-002 cleanly
    resp_b = client.get("/api/v1/student/profile", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["student_ref"] == "STU-DEMO-002"

    # Student B attempts to access Student A
    resp_b_tamper = client.get("/api/v1/student/profile?student_ref=STU-DEMO-001", headers=headers_b)
    assert resp_b_tamper.status_code == 403


def test_strict_read_only_enforcement_student_forbidden_mutations(student_env):
    """
    Strict server-side RBAC: Authenticated students must be completely blocked
    from mutating academic records, enrolments, certificates, or transfers (403 Forbidden).
    """
    client = TestClient(app)
    token = get_token(client, "student_demo", "StudentDemo@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Attempt to create official student record
    resp1 = client.post("/api/v1/students", json={
        "student_ref": "STU-HACK-001",
        "full_name": "Injected Record",
    }, headers=headers)
    assert resp1.status_code == 403, resp1.text

    # 2. Attempt CSV batch ingestion
    resp2 = client.post("/api/v1/students/upload-csv", data={"institution_id": "INST-DELHI-DTU"}, headers=headers)
    assert resp2.status_code == 403, resp2.text

    # 3. Attempt to create enrolment
    resp3 = client.post("/api/v1/enrolments", json={
        "student_ref": "STU-DEMO-001",
        "institution_id": "INST-DELHI-DTU",
        "programme_id": "PROG-HACK",
        "academic_year": "2025-2026",
    }, headers=headers)
    assert resp3.status_code == 403, resp3.text

    # 4. Attempt to issue digital credential
    resp4 = client.post("/api/v1/certificates/issue", json={
        "student_ref": "STU-DEMO-001",
        "student_name": "Aarav Sharma",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "DTU",
        "programme_id": "BTECH-CSE",
        "programme_name": "CSE",
        "issue_date": "2026-05-31",
        "completion_date": "2026-05-31",
    }, headers=headers)
    assert resp4.status_code == 403, resp4.text

    # 5. Attempt to revoke credential
    resp5 = client.post("/api/v1/certificates/CERT-DEMO-001/revoke", json={"reason": "Malicious revocation"}, headers=headers)
    assert resp5.status_code == 403, resp5.text

    # 6. Attempt to initiate transfer on behalf of institution
    resp6 = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-001",
        "destination_institution_id": "INST-DELHI-IIITD",
        "programme_id": "BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers=headers)
    assert resp6.status_code == 403, resp6.text

    # 7. Attempt to release transfer
    resp7 = client.post("/api/v1/transfers/TRF-DEMO-PORTAL-01/release", json={"action": "APPROVE"}, headers=headers)
    assert resp7.status_code == 403, resp7.text

    # 8. Attempt to admit transfer
    resp8 = client.post("/api/v1/transfers/TRF-DEMO-PORTAL-01/admit", json={"action": "ADMIT"}, headers=headers)
    assert resp8.status_code == 403, resp8.text


def test_student_forbidden_from_institution_and_reviewer_endpoints(student_env):
    """
    Students cannot browse institution-scoped student lists, compliance dashboards, or alerts.
    """
    client = TestClient(app)
    token = get_token(client, "student_demo", "StudentDemo@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    institution_routes = [
        "/api/v1/students",
        "/api/v1/institution/dashboard-summary",
        "/api/v1/intake-compliance",
        "/api/v1/alerts",
        "/api/v1/analytics/anomalies",
        "/api/v1/reports/executive-summary",
        "/api/v1/audit-trail",
    ]
    for route in institution_routes:
        resp = client.get(route, headers=headers)
        assert resp.status_code == 403, f"Expected 403 for {route}, got {resp.status_code}"


def test_invalid_and_revoked_session_handling(student_env):
    """
    Verify malformed tokens return 401 and logging out revokes the session token.
    """
    client = TestClient(app)
    # Malformed token
    bad_resp = client.get("/api/v1/student/profile", headers={"Authorization": "Bearer not-a-valid-token"})
    assert bad_resp.status_code == 401

    # Valid login followed by logout
    token = get_token(client, "student_demo", "StudentDemo@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    profile_ok = client.get("/api/v1/student/profile", headers=headers)
    assert profile_ok.status_code == 200

    logout_resp = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200

    # Subsequent request using revoked token must be rejected
    post_logout_resp = client.get("/api/v1/student/profile", headers=headers)
    assert post_logout_resp.status_code == 401
    assert "revoked" in post_logout_resp.json()["detail"].lower()


def test_unlinked_student_account_handling(student_env):
    """
    Verify that an authenticated user with role 'student' but without any linked
    student record receives 404 Not Found rather than leaking other data.
    """
    client = TestClient(app)
    token = get_token(client, "unlinked_student", "UnlinkedStudent@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/student/profile", headers=headers)
    assert resp.status_code == 404
    assert "no verified student record" in resp.json()["detail"].lower()


def test_student_dpdp_consent_self_management(student_env):
    """
    Verify student can toggle their own DPDP consent preferences,
    while attempting to toggle another student's consent returns 403 Forbidden.
    """
    client = TestClient(app)
    token_a = get_token(client, "student_demo", "StudentDemo@2026!")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Retrieve Student A's consents
    profile = client.get("/api/v1/student/profile", headers=headers_a).json()
    consent_a = profile["consents"][0]
    consent_id_a = consent_a["id"]
    initial_status = consent_a["status"]

    # Toggle Student A's own consent
    resp_toggle = client.patch(f"/api/v1/student/consent/{consent_id_a}/toggle", headers=headers_a)
    assert resp_toggle.status_code == 200, resp_toggle.text
    toggled = resp_toggle.json()
    assert toggled["status"] != initial_status

    # Student B attempts to toggle Student A's consent
    token_b = get_token(client, "student_priya", "StudentPriya@2026!")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    resp_cross_toggle = client.patch(f"/api/v1/student/consent/{consent_id_a}/toggle", headers=headers_b)
    assert resp_cross_toggle.status_code == 403
    assert "not authorized to modify another student's consent" in resp_cross_toggle.json()["detail"].lower()
