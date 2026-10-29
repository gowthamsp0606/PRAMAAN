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


def test_role_specific_dashboard_routes_returned_on_login(auth_env):
    """Verify that backend returns exact authorized dashboard_route for each role on login."""
    client = TestClient(app)
    personas = [
        ("admin", "PramaanAdmin@2026!", "/admin-dashboard", "PROTOTYPE_ADMIN", "administrator"),
        ("aicte_reviewer", "AicteReviewer@2026!", "/aicte-dashboard", "AICTE_REGIONAL_REVIEWER", "reviewer"),
        ("dtu_registrar", "DtuRegistrar@2026!", "/institution-dashboard", "INSTITUTION_REGISTRAR", "institution_officer"),
        ("tcs_verifier", "TcsVerifier@2026!", "/employer-portal", "BGV_VERIFIER", "external_verifier"),
        ("compliance_auditor", "ComplianceAuditor@2026!", "/auditor-dashboard", "COMPLIANCE_AUDITOR", "read_only_auditor"),
    ]

    for username, password, expected_route, expected_category, expected_role in personas:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password}
        )
        assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
        data = resp.json()
        assert data["user"]["dashboard_route"] == expected_route
        assert data["user"]["role_category"] == expected_category
        assert data["user"]["role"] == expected_role


def test_auth_me_reflects_dashboard_route_and_scopes(auth_env):
    """Verify /api/v1/auth/me returns accurate persona and dashboard routing."""
    client = TestClient(app)
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "dtu_registrar", "password": "DtuRegistrar@2026!"}
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me = me_resp.json()
    assert me["authenticated"] is True
    assert me["role"] == "institution_officer"
    assert me["institution_id"] == "INST-DELHI-DTU"
    assert me["dashboard_route"] == "/institution-dashboard"


def test_institution_scope_enforcement_for_registrar(auth_env):
    """Verify that an institution registrar cannot query another institution's data."""
    client = TestClient(app)
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "dtu_registrar", "password": "DtuRegistrar@2026!"}
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Querying own institution should work
    own_resp = client.get(
        "/api/v1/institution/dashboard-summary?institution_id=INST-DELHI-DTU",
        headers=headers
    )
    assert own_resp.status_code == 200
    data = own_resp.json()
    assert data["institution_id"] == "INST-DELHI-DTU"

    # Querying another institution should raise 403 Forbidden
    other_resp = client.get(
        "/api/v1/institution/dashboard-summary?institution_id=INST-PUNE-COEP",
        headers=headers
    )
    assert other_resp.status_code == 403
    assert "Cross-institution access is not permitted" in other_resp.text


def test_admin_dashboard_user_management_authorization(auth_env):
    """Verify that only administrators can access /api/v1/auth/users."""
    client = TestClient(app)
    # 1. Admin accessing users
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "PramaanAdmin@2026!"}
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    admin_users_resp = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert admin_users_resp.status_code == 200
    users_data = admin_users_resp.json()
    assert isinstance(users_data, list)
    assert len(users_data) >= 5

    # 2. Reviewer accessing users -> 403 Forbidden
    rev_login = client.post(
        "/api/v1/auth/login",
        json={"username": "aicte_reviewer", "password": "AicteReviewer@2026!"}
    )
    assert rev_login.status_code == 200
    rev_token = rev_login.json()["access_token"]
    rev_users_resp = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {rev_token}"}
    )
    assert rev_users_resp.status_code == 403

    # 3. Auditor accessing users -> 403 Forbidden
    aud_login = client.post(
        "/api/v1/auth/login",
        json={"username": "compliance_auditor", "password": "ComplianceAuditor@2026!"}
    )
    assert aud_login.status_code == 200
    aud_token = aud_login.json()["access_token"]
    aud_users_resp = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {aud_token}"}
    )
    assert aud_users_resp.status_code == 403


def test_auditor_prohibited_from_mutating_state(auth_env):
    """Verify that compliance auditor is strictly prohibited from executing mutations."""
    client = TestClient(app)
    aud_login = client.post(
        "/api/v1/auth/login",
        json={"username": "compliance_auditor", "password": "ComplianceAuditor@2026!"}
    )
    assert aud_login.status_code == 200
    aud_token = aud_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {aud_token}"}

    # Auditor accessing read-only endpoints succeeds
    audit_resp = client.get("/api/v1/audit-trail", headers=headers)
    assert audit_resp.status_code == 200

    report_resp = client.get("/api/v1/reports/executive-summary", headers=headers)
    assert report_resp.status_code == 200

    # Auditor attempting tamper simulation fails with 403
    tamper_resp = client.post(
        "/api/v1/certificates/CERT-2024-001/simulate-tamper",
        json={"tamper_type": "CGPA_INFLATION"},
        headers=headers
    )
    assert tamper_resp.status_code == 403


def test_external_verifier_scoped_access(auth_env):
    """Verify that external BGV verifier cannot access internal student registers or rules."""
    client = TestClient(app)
    v_login = client.post(
        "/api/v1/auth/login",
        json={"username": "tcs_verifier", "password": "TcsVerifier@2026!"}
    )
    assert v_login.status_code == 200
    v_token = v_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {v_token}"}

    # Verifier can check credentials
    check_resp = client.post(
        "/api/v1/verifier/verify-credential",
        json={
            "verifier_org_id": "ORG-TCS-BGV",
            "student_ref": "STU-DEMO-001"
        },
        headers=headers
    )
    assert check_resp.status_code == 200

    # Verifier cannot browse full student directory (403)
    stu_resp = client.get("/api/v1/students", headers=headers)
    assert stu_resp.status_code == 403
