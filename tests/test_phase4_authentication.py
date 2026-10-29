import hashlib
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.user import User, RevokedToken
from app.services.auth_service import AuthService, PasswordHasher, TokenManager


@pytest.fixture
def auth_env(db_sessions, monkeypatch):
    """Fixture ensuring clean database state with seeded demo users and AUTH_REQUIRED=True."""
    prev_auth = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True

    with db_sessions() as db:
        # Seed the 5 standard demo personas
        AuthService.seed_demo_users(db)

    yield db_sessions

    settings.AUTH_REQUIRED = prev_auth


def test_valid_login_for_each_persona(auth_env):
    """Test valid login for all 5 operational personas."""
    client = TestClient(app)

    personas = [
        ("admin", "PramaanAdmin@2026!", "administrator", "PROTOTYPE_ADMIN", "/admin-dashboard"),
        ("aicte_reviewer", "AicteReviewer@2026!", "reviewer", "AICTE_REGIONAL_REVIEWER", "/aicte-dashboard"),
        ("dtu_registrar", "DtuRegistrar@2026!", "institution_officer", "INSTITUTION_REGISTRAR", "/institution-dashboard"),
        ("tcs_verifier", "TcsVerifier@2026!", "external_verifier", "BGV_VERIFIER", "/employer-portal"),
        ("compliance_auditor", "ComplianceAuditor@2026!", "read_only_auditor", "COMPLIANCE_AUDITOR", "/auditor-dashboard"),
    ]

    for username, password, expected_role, expected_category, expected_route in personas:
        resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert resp.status_code == 200, f"Failed login for {username}: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert "access_token" in data
        assert data["user"]["role"] == expected_role
        assert data["user"]["role_category"] == expected_category
        assert data["user"]["dashboard_route"] == expected_route

        # Also test that email login works equivalently
        email = f"{username}@pramaan.gov.in" if username == "admin" else (
            "ro102@aicte.gov.in" if username == "aicte_reviewer" else (
                "registrar@dtu.ac.in" if username == "dtu_registrar" else (
                    "bgv.verify@tcs.com" if username == "tcs_verifier" else "auditor@cag.gov.in"
                )
            )
        )
        email_resp = client.post("/api/v1/auth/login", json={"username": email, "password": password})
        assert email_resp.status_code == 200


def test_invalid_credentials_generic_error(auth_env):
    """Confirm invalid password and unknown user return generic 401 without exposing existence."""
    client = TestClient(app)

    # 1. Known user, incorrect password
    resp1 = client.post("/api/v1/auth/login", json={"username": "admin", "password": "WrongPassword!999"})
    assert resp1.status_code == 401
    assert resp1.json()["detail"] == "Invalid username/email or password."

    # 2. Unknown user
    resp2 = client.post("/api/v1/auth/login", json={"username": "nonexistent_officer_xyz", "password": "AnyPassword!123"})
    assert resp2.status_code == 401
    assert resp2.json()["detail"] == "Invalid username/email or password."


def test_logout_and_token_invalidation(auth_env):
    """Confirm logging out revokes the JWT session and prevents reuse."""
    client = TestClient(app)

    # Login
    login_resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "PramaanAdmin@2026!"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify authenticated profile works
    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "admin"

    # Logout
    logout_resp = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # Attempt to reuse the revoked token -> must fail with 401
    me_after_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_after_resp.status_code == 401
    assert "revoked" in me_after_resp.json()["detail"].lower()


def test_expired_or_invalid_session(auth_env, db_sessions):
    """Test expired tokens and tampered tokens are rejected."""
    client = TestClient(app)

    with db_sessions() as db:
        user = db.query(User).filter(User.username == "admin").first()
        # Generate an already expired token
        expired_token, _, _ = TokenManager.create_access_token(user, expires_delta=timedelta(seconds=-10))

    # Test expired token
    resp_exp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp_exp.status_code == 401
    assert "expired" in resp_exp.json()["detail"].lower()

    # Test tampered token (flip characters in signature)
    tampered_token = expired_token[:-4] + "wxyz"
    resp_tamp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert resp_tamp.status_code == 401


def test_every_roles_permitted_operations(auth_env):
    """Verify each role can execute its authorized operations."""
    client = TestClient(app)

    # 1. Admin can list users
    admin_token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "PramaanAdmin@2026!"}).json()["access_token"]
    users_resp = client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert users_resp.status_code == 200
    assert len(users_resp.json()) >= 5

    # 2. AICTE Reviewer can list alerts
    reviewer_token = client.post("/api/v1/auth/login", json={"username": "aicte_reviewer", "password": "AicteReviewer@2026!"}).json()["access_token"]
    alerts_resp = client.get("/api/v1/alerts", headers={"Authorization": f"Bearer {reviewer_token}"})
    assert alerts_resp.status_code == 200

    # 3. DTU Registrar can access institution dashboard
    dtu_token = client.post("/api/v1/auth/login", json={"username": "dtu_registrar", "password": "DtuRegistrar@2026!"}).json()["access_token"]
    dtu_dash_resp = client.get("/api/v1/institution/dashboard-summary?institution_id=INST-DELHI-DTU", headers={"Authorization": f"Bearer {dtu_token}"})
    assert dtu_dash_resp.status_code == 200

    # 4. Verifier can list verifier logs
    verifier_token = client.post("/api/v1/auth/login", json={"username": "tcs_verifier", "password": "TcsVerifier@2026!"}).json()["access_token"]
    v_logs_resp = client.get("/api/v1/verifier/logs", headers={"Authorization": f"Bearer {verifier_token}"})
    assert v_logs_resp.status_code == 200

    # 5. Auditor can read audit trail
    auditor_token = client.post("/api/v1/auth/login", json={"username": "compliance_auditor", "password": "ComplianceAuditor@2026!"}).json()["access_token"]
    audit_resp = client.get("/api/v1/audit-trail", headers={"Authorization": f"Bearer {auditor_token}"})
    assert audit_resp.status_code == 200


def test_every_roles_forbidden_operations(auth_env):
    """Verify unauthorized operations are blocked with 403 Forbidden."""
    client = TestClient(app)

    # 1. Reviewer cannot list/create users (admin only)
    reviewer_token = client.post("/api/v1/auth/login", json={"username": "aicte_reviewer", "password": "AicteReviewer@2026!"}).json()["access_token"]
    r_forbidden = client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {reviewer_token}"})
    assert r_forbidden.status_code == 403

    # 2. Verifier cannot view student records list
    verifier_token = client.post("/api/v1/auth/login", json={"username": "tcs_verifier", "password": "TcsVerifier@2026!"}).json()["access_token"]
    v_forbidden = client.get("/api/v1/students", headers={"Authorization": f"Bearer {verifier_token}"})
    assert v_forbidden.status_code == 403

    # 3. Auditor cannot make state mutations (POST issue certificate)
    auditor_token = client.post("/api/v1/auth/login", json={"username": "compliance_auditor", "password": "ComplianceAuditor@2026!"}).json()["access_token"]
    a_forbidden = client.post(
        "/api/v1/certificates/issue",
        json={"student_ref": "STU-001", "student_name": "Test", "institution_id": "INST-DTU", "institution_name": "DTU", "programme_id": "CSE", "programme_name": "CSE", "issue_date": "2026-01-01", "completion_date": "2026-01-01"},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert a_forbidden.status_code == 403


def test_cross_institution_access_denial(auth_env):
    """Confirm horizontal privilege escalation between institutions is denied."""
    client = TestClient(app)

    dtu_token = client.post("/api/v1/auth/login", json={"username": "dtu_registrar", "password": "DtuRegistrar@2026!"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {dtu_token}"}

    # Attempting to access another institution's dashboard returns 403
    cross_resp = client.get("/api/v1/institution/dashboard-summary?institution_id=INST-MUMBAI-IITB", headers=headers)
    assert cross_resp.status_code == 403
    assert "Cross-institution" in cross_resp.json()["detail"]


def test_unauthorized_role_assignment(auth_env):
    """Ensure non-admin users cannot grant roles or create users."""
    client = TestClient(app)

    dtu_token = client.post("/api/v1/auth/login", json={"username": "dtu_registrar", "password": "DtuRegistrar@2026!"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {dtu_token}"}

    create_resp = client.post(
        "/api/v1/auth/users",
        json={
            "username": "rogue_admin",
            "email": "rogue@hack.net",
            "password": "Password@1234!",
            "full_name": "Rogue Operator",
            "role_category": "PROTOTYPE_ADMIN",
        },
        headers=headers,
    )
    assert create_resp.status_code == 403


def test_direct_api_access_without_authentication(auth_env):
    """Ensure protected endpoints deny unauthenticated requests with 401 Unauthorized."""
    client = TestClient(app)

    resp_students = client.get("/api/v1/students")
    assert resp_students.status_code == 401

    resp_alerts = client.get("/api/v1/alerts")
    assert resp_alerts.status_code == 401

    resp_me = client.get("/api/v1/auth/me")
    assert resp_me.status_code == 401


def test_production_configuration_with_demo_authentication_disabled(auth_env, db_sessions, monkeypatch):
    """Confirm demo accounts are never seeded if ENVIRONMENT is production."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with db_sessions() as db:
        seeded = AuthService.seed_demo_users(db)
        assert seeded == {}
