import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Force in-memory database before app imports
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ENVIRONMENT"] = "development"

from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.consent import StudentConsent
from app.models.verifier import VerifierOrganization, VerificationRequestLog
from app.models.alert import Alert
from app.models.certificate import Certificate
from app.services.auth_service import AuthService
from app.services.identity_service import IdentityStatus

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
settings.AUTH_REQUIRED = True

results = {}

with SessionLocal() as db:
    AuthService.seed_demo_users(db)

    # Seed test entities
    org = VerifierOrganization(id="ORG-TCS-BGV", org_name="TCS BGV", is_approved=True, contact_email="bgv@tcs.com")
    db.add(org)

    s1 = Student(student_ref="STU-DTU-01", apaar_id="1111-2222-3333", full_name="Aarav Sharma", primary_institution_id="INST-DELHI-DTU")
    s2 = Student(student_ref="STU-IIT-01", apaar_id="4444-5555-6666", full_name="Bhavna Patel", primary_institution_id="INST-IITB")
    db.add_all([s1, s2])
    db.flush()

    e1 = Enrolment(
        student_ref="STU-DTU-01", apaar_id="1111-2222-3333", institution_id="INST-DELHI-DTU",
        institution_name="DTU", programme_id="BTECH-CSE", programme_name="CSE",
        academic_year="2025-2026", admission_cycle="Regular 2025", seat_category="General",
        enrolment_start=date(2025, 8, 1), enrolment_status="Active"
    )
    e2 = Enrolment(
        student_ref="STU-IIT-01", apaar_id="4444-5555-6666", institution_id="INST-IITB",
        institution_name="IITB", programme_id="BTECH-CSE", programme_name="CSE",
        academic_year="2025-2026", admission_cycle="Regular 2025", seat_category="General",
        enrolment_start=date(2025, 8, 1), enrolment_status="Active"
    )
    db.add_all([e1, e2])

    c1 = StudentConsent(student_ref="STU-DTU-01", apaar_id="1111-2222-3333", purpose="EMPLOYMENT_VERIFICATION", consent_granted=True, status="ACTIVE")
    c2 = StudentConsent(student_ref="STU-IIT-01", apaar_id="4444-5555-6666", purpose="EMPLOYMENT_VERIFICATION", consent_granted=False, status="WITHDRAWN")
    db.add_all([c1, c2])

    alt = Alert(
        id="ALT-TST-001", student_ref="STU-DTU-01", apaar_id="1111-2222-3333",
        alert_type="TEMPORAL_OVERLAP_CONFLICT", severity="HIGH", status="OPEN",
        title="Overlap", explanation="Concurrent enrolment observed across duplicate institute records.",
        supporting_record_ids=[e1.id]
    )
    db.add(alt)
    db.commit()

client = TestClient(app)

# 1. Authenticate 5 roles
personas = [
    ("admin", "PramaanAdmin@2026!", "administrator", "/admin-dashboard"),
    ("aicte_reviewer", "AicteReviewer@2026!", "reviewer", "/aicte-dashboard"),
    ("dtu_registrar", "DtuRegistrar@2026!", "institution_officer", "/institution-dashboard"),
    ("tcs_verifier", "TcsVerifier@2026!", "external_verifier", "/employer-portal"),
    ("compliance_auditor", "ComplianceAuditor@2026!", "read_only_auditor", "/auditor-dashboard"),
]

tokens = {}
auth_ok = True
for user, pwd, exp_role, exp_route in personas:
    r = client.post("/api/v1/auth/login", json={"username": user, "password": pwd})
    if r.status_code != 200:
        auth_ok = False
        print(f"FAILED login: {user}")
        break
    data = r.json()
    if data["user"]["role"] != exp_role or data["user"]["dashboard_route"] != exp_route:
        auth_ok = False
        print(f"FAILED role/route mismatch: {user}")
        break
    tokens[user] = data["access_token"]

results["all_five_roles_authenticated_and_routed"] = auth_ok

# 2. Authorization and institution scoping
headers_dtu = {"Authorization": f"Bearer {tokens['dtu_registrar']}"}
headers_tcs = {"Authorization": f"Bearer {tokens['tcs_verifier']}"}
headers_aud = {"Authorization": f"Bearer {tokens['compliance_auditor']}"}
headers_adm = {"Authorization": f"Bearer {tokens['admin']}"}

# DTU officer querying students only sees DTU
r_stu = client.get("/api/v1/students", headers=headers_dtu)
print("r_stu status:", r_stu.status_code, "items:", len(r_stu.json().get("items", [])))
dtu_scope_ok = r_stu.status_code == 200 and all(s["primary_institution_id"] == "INST-DELHI-DTU" for s in r_stu.json()["items"])
print("dtu_scope_ok:", dtu_scope_ok)

# DTU officer cross-institution request blocked
r_cross = client.get("/api/v1/students?institution_id=INST-IITB", headers=headers_dtu)
print("r_cross status:", r_cross.status_code)
cross_blocked_ok = r_cross.status_code == 403
print("cross_blocked_ok:", cross_blocked_ok)

# Verifier cannot browse student records
r_ver_stu = client.get("/api/v1/students", headers=headers_tcs)
print("r_ver_stu status:", r_ver_stu.status_code)
verifier_blocked_ok = r_ver_stu.status_code == 403
print("verifier_blocked_ok:", verifier_blocked_ok)

# Unauthenticated request fails closed (fresh client without cookies)
fresh_client = TestClient(app)
r_unauth = fresh_client.get("/api/v1/students")
print("r_unauth status:", r_unauth.status_code)
unauth_blocked_ok = r_unauth.status_code in (401, 403)
print("unauth_blocked_ok:", unauth_blocked_ok)

results["institution_scoping_and_rbac"] = dtu_scope_ok and cross_blocked_ok and verifier_blocked_ok and unauth_blocked_ok

# 3. Review decision persistence
r_rev = client.patch(
    "/api/v1/alerts/ALT-TST-001/review",
    json={"decision": "CONFIRMED_CONFLICT", "note": "Verified concurrent overlap."},
    headers=headers_adm
)
rev_ok = r_rev.status_code == 200 and r_rev.json()["status"] == "RESOLVED"
results["review_decision_persisted"] = rev_ok

# 4. Credential issuance, verification, revocation, and non-destructive tamper test
r_issue = client.post(
    "/api/v1/certificates/issue",
    json={
        "student_ref": "STU-DTU-01", "student_name": "Aarav Sharma",
        "institution_id": "INST-DELHI-DTU", "institution_name": "DTU",
        "programme_id": "BTECH-CSE", "programme_name": "CSE",
        "issue_date": "2026-06-30", "completion_date": "2026-05-31",
        "algorithm": "Ed25519"
    },
    headers=headers_dtu
)
print("r_issue status:", r_issue.status_code, r_issue.text[:150])
issue_ok = r_issue.status_code == 201
cert_id = r_issue.json()["certificate_id"] if issue_ok else None

# Verify valid
r_v1 = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers_dtu) if cert_id else None
print("r_v1:", r_v1.status_code if r_v1 else None)
v1_ok = r_v1 and r_v1.status_code == 200 and r_v1.json()["verification_status"] == "VALID"

# Non-destructive tamper simulation (administrator authorized)
r_tamper = client.post(
    f"/api/v1/certificates/{cert_id}/simulate-tamper",
    json={"student_name": "Tampered Attacker"},
    headers=headers_adm
) if cert_id else None
print("r_tamper:", r_tamper.status_code if r_tamper else None)
tamper_ok = r_tamper and r_tamper.status_code == 200 and r_tamper.json()["verification_result"]["verification_status"] == "TAMPER_DETECTED"

# Re-verify original to confirm non-destructive
r_v2 = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers_dtu) if cert_id else None
print("r_v2:", r_v2.status_code if r_v2 else None)
non_destructive_ok = r_v2 and r_v2.status_code == 200 and r_v2.json()["verification_status"] == "VALID"

# Revoke
r_revoke = client.post(
    f"/api/v1/certificates/{cert_id}/revoke",
    json={"reason": "Degree recalled following academic re-audit."},
    headers=headers_dtu
) if cert_id else None
print("r_revoke:", r_revoke.status_code if r_revoke else None)
revoke_ok = r_revoke and r_revoke.status_code == 200 and r_revoke.json()["status"] == "REVOKED"

# Verify revoked
r_v3 = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers_dtu) if cert_id else None
print("r_v3:", r_v3.status_code if r_v3 else None)
revoked_verify_ok = r_v3 and r_v3.status_code == 200 and r_v3.json()["verification_status"] == "REVOKED"

results["credential_lifecycle_and_tamper_detection"] = (
    issue_ok and v1_ok and tamper_ok and non_destructive_ok and revoke_ok and revoked_verify_ok
)

# 5. Consent-gated verification and verification_request_logs write
r_ver_active = client.post(
    "/api/v1/verifier/verify-credential",
    json={"student_ref": "STU-DTU-01", "verifier_org_id": "ORG-TCS-BGV"},
    headers=headers_tcs
)
active_ok = r_ver_active.status_code == 200 and r_ver_active.json()["outcome"] == "MATCH_VERIFIED" and "apaar_id" not in r_ver_active.json()

r_ver_withdrawn = client.post(
    "/api/v1/verifier/verify-credential",
    json={"student_ref": "STU-IIT-01", "verifier_org_id": "ORG-TCS-BGV"},
    headers=headers_tcs
)
withdrawn_ok = r_ver_withdrawn.status_code == 200 and r_ver_withdrawn.json()["outcome"] == "CONSENT_WITHHELD"

# Query logs written to verification_request_logs
r_logs = client.get("/api/v1/verifier/logs", headers=headers_tcs)
logs_ok = r_logs.status_code == 200 and len(r_logs.json()["items"]) >= 2

results["consent_enforcement_and_verification_logging"] = active_ok and withdrawn_ok and logs_ok

# 6. Logout and token revocation
r_logout = client.post("/api/v1/auth/logout", headers=headers_adm)
logout_ok = r_logout.status_code == 200
r_after_logout = client.get("/api/v1/auth/me", headers=headers_adm)
revoked_token_rejected_ok = r_after_logout.status_code == 401
results["logout_and_token_revocation"] = logout_ok and revoked_token_rejected_ok

print("BACKEND VERIFICATION RESULTS:")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
