"""
End-to-End Test Suite for Unified Login, Requested-Role Context Validation,
and 7-Role Dashboard & Data Isolation Security.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.user import User
from app.models.student import Student
from app.models.student_user import StudentUserLink
from app.services.auth_service import AuthService


@pytest.fixture
def rbac_integration_env(db_sessions):
    prev_auth = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True

    with db_sessions() as db:
        AuthService.seed_demo_users(db)

        # Ensure student_aarav is linked to STU-IND-081 for testing
        stu = db.query(Student).filter(Student.student_ref == "STU-IND-081").first()
        if not stu:
            stu = Student(
                student_ref="STU-IND-081",
                apaar_id="9876-2026-0081",
                full_name="Aarav Sharma",
                primary_institution_id="INST-DELHI-DTU",
                identity_route="AADHAAR_APAAR",
                identity_status="APAAR_VERIFIED",
                nationality="Indian",
            )
            db.add(stu)
            db.flush()

        user_aarav = db.query(User).filter(User.username == "student_aarav").first()
        if not user_aarav:
            from app.services.auth_service import PasswordHasher
            user_aarav = User(
                username="student_aarav",
                email="aarav.student@pramaan.gov.in",
                password_hash=PasswordHasher.hash_password("StudentAarav@2026!"),
                full_name="Aarav Sharma",
                role="student",
                role_category="STUDENT",
                institution_id="INST-DELHI-DTU",
                is_active=True,
            )
            db.add(user_aarav)
            db.flush()

        link = db.query(StudentUserLink).filter(StudentUserLink.user_id == user_aarav.id).first()
        if not link:
            db.add(StudentUserLink(user_id=user_aarav.id, student_ref="STU-IND-081", is_primary=True))
        db.commit()

    yield db_sessions

    settings.AUTH_REQUIRED = prev_auth


def test_all_7_roles_successful_login_and_dashboard_routing(rbac_integration_env):
    """Verify each of the 7 supported roles logs in cleanly and receives its exact dashboard route."""
    client = TestClient(app)

    personas = [
        ("admin", "PramaanAdmin@2026!", "administrator", "/admin-dashboard"),
        ("aicte_reviewer", "AicteReviewer@2026!", "reviewer", "/aicte-dashboard"),
        ("dtu_registrar", "DtuRegistrar@2026!", "institution_officer", "/institution-dashboard"),
        ("tcs_verifier", "TcsVerifier@2026!", "external_verifier", "/employer-portal"),
        ("compliance_auditor", "ComplianceAuditor@2026!", "read_only_auditor", "/auditor-dashboard"),
        ("delhi_state_officer", "DelhiOfficer@2026!", "state_officer", "/state-dashboard"),
        ("student_aarav", "StudentAarav@2026!", "student", "/student-dashboard"),
    ]

    for username, password, expected_role, expected_route in personas:
        # Submit credentials with requested_role context
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": password,
                "requested_role": expected_role,
            },
        )
        assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert "access_token" in data
        assert data["user"]["role"] == expected_role
        assert data["user"]["dashboard_route"] == expected_route

        # Verify /auth/me returns identity & matching dashboard_route
        token = data["access_token"]
        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["role"] == expected_role
        assert me_resp.json()["dashboard_route"] == expected_route


def test_invalid_credentials_returns_generic_401(rbac_integration_env):
    """Verify invalid password returns generic 401 without leaking internal details."""
    client = TestClient(app)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "WrongPassword@999!"},
    )
    assert resp.status_code == 401
    assert "Invalid username/email or password" in resp.json()["detail"]


def test_role_mismatch_rejection_upon_login(rbac_integration_env):
    """Verify user attempting to select a role they do not possess is rejected with 403."""
    client = TestClient(app)

    # 1. Student attempting to log in as administrator
    resp1 = client.post(
        "/api/v1/auth/login",
        json={
            "username": "student_aarav",
            "password": "StudentAarav@2026!",
            "requested_role": "administrator",
        },
    )
    assert resp1.status_code == 403
    assert "does not possess the requested role" in resp1.json()["detail"]

    # 2. Registrar attempting to log in as external_verifier
    resp2 = client.post(
        "/api/v1/auth/login",
        json={
            "username": "dtu_registrar",
            "password": "DtuRegistrar@2026!",
            "requested_role": "external_verifier",
        },
    )
    assert resp2.status_code == 403
    assert "does not possess the requested role" in resp2.json()["detail"]


def test_state_officer_scope_enforcement(rbac_integration_env):
    """Verify state officer can access their own state data but is blocked from other states."""
    client = TestClient(app)

    # Login as Delhi State Officer
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "delhi_state_officer", "password": "DelhiOfficer@2026!"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Allowed: Delhi dashboard summary
    resp_delhi = client.get("/api/v1/state/dashboard-summary?state=DELHI", headers=headers)
    assert resp_delhi.status_code == 200

    # Forbidden: Maharashtra dashboard summary
    resp_mh = client.get("/api/v1/state/dashboard-summary?state=MAHARASHTRA", headers=headers)
    assert resp_mh.status_code == 403


def test_student_self_service_scoping(rbac_integration_env):
    """Verify student accesses own profile but is forbidden from administrative directories."""
    client = TestClient(app)

    # Login as Student
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "student_aarav", "password": "StudentAarav@2026!"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Allowed: own profile
    resp_prof = client.get("/api/v1/student/profile", headers=headers)
    assert resp_prof.status_code == 200
    assert resp_prof.json()["student_ref"] == "STU-IND-081"

    # Forbidden: administrative student directory
    resp_dir = client.get("/api/v1/students", headers=headers)
    assert resp_dir.status_code == 403

    # Forbidden: administrative intake compliance
    resp_intake = client.get("/api/v1/intake-compliance", headers=headers)
    assert resp_intake.status_code == 403


def test_logout_session_revocation(rbac_integration_env):
    """Verify logout revokes the JWT session and prevents reuse."""
    client = TestClient(app)

    # Login
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "PramaanAdmin@2026!"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Logout
    logout_resp = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # Re-using revoked token must fail
    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 401
