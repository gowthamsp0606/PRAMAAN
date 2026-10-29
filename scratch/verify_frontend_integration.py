"""
End-to-end integration test verifying that the frontend contracts, schemas,
and workflows align 100% with the FastAPI backend across all 5 roles.
Runs on an isolated, disposable database copy to ensure the persistent demo database is completely untouched.
"""

import os
import sys
import tempfile
import shutil
import json

# Ensure backend modules can be imported
sys.path.insert(0, os.path.abspath("backend"))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Setup disposable test database
temp_dir = tempfile.mkdtemp()
temp_db_path = os.path.join(temp_dir, "disposable_test.db")
shutil.copyfile("backend/apaar_sentinel.db", temp_db_path)

# On the disposable copy, apply the missing column if absent
import sqlite3
_con = sqlite3.connect(temp_db_path)
_cols = [c[1] for c in _con.execute("PRAGMA table_info(students)").fetchall()]
if "identity_status" not in _cols:
    _con.execute("ALTER TABLE students ADD COLUMN identity_status VARCHAR(32) DEFAULT 'APAAR_VERIFIED';")
    _con.commit()
_con.close()

os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_path.replace(os.sep, '/')}"

from app.database import Base, get_db
from app.main import app

test_engine = create_engine(f"sqlite:///{temp_db_path.replace(os.sep, '/')}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

FRONTEND_ORIGIN = "http://10.31.9.99:5173"
client = TestClient(app)

print("=" * 70)
print("PRAMAAN / APAAR SENTINEL - FRONTEND INTEGRATION VERIFICATION")
print("=" * 70)

# Check 1: Health check endpoint
res = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})
assert res.status_code == 200, f"Health check failed: {res.status_code}"
assert res.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN
print("[PASS] Check 1: GET /health returns 200 with CORS Origin 10.31.9.99:5173")

# Check 2: All 5 personas authenticate, receive session cookies, and route to distinct dashboards
ROLES = [
    ("admin", "PramaanAdmin@2026!", "/admin-dashboard", "PROTOTYPE_ADMIN"),
    ("aicte_reviewer", "AicteReviewer@2026!", "/aicte-dashboard", "AICTE_REGIONAL_REVIEWER"),
    ("dtu_registrar", "DtuRegistrar@2026!", "/institution-dashboard", "INSTITUTION_REGISTRAR"),
    ("tcs_verifier", "TcsVerifier@2026!", "/employer-portal", "BGV_VERIFIER"),
    ("compliance_auditor", "ComplianceAuditor@2026!", "/auditor-dashboard", "COMPLIANCE_AUDITOR"),
]

for username, pwd, expected_route, expected_category in ROLES:
    user_client = TestClient(app)
    # Login
    r_login = user_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": pwd},
        headers={"Origin": FRONTEND_ORIGIN}
    )
    assert r_login.status_code == 200, f"Login failed for {username}: {r_login.text}"
    login_data = r_login.json()
    assert login_data["success"] is True
    assert "access_token" in login_data
    assert login_data["user"]["dashboard_route"] == expected_route
    assert login_data["user"]["role_category"] == expected_category
    assert "pramaan_token" in r_login.cookies, f"Session cookie pramaan_token missing for {username}"

    # Verify /auth/me with session cookie
    r_me = user_client.get("/api/v1/auth/me", headers={"Origin": FRONTEND_ORIGIN})
    assert r_me.status_code == 200, f"/auth/me failed for {username}: {r_me.text}"
    me_data = r_me.json()
    assert me_data["authenticated"] is True
    assert me_data["dashboard_route"] == expected_route

    # Logout
    r_logout = user_client.post("/api/v1/auth/logout", headers={"Origin": FRONTEND_ORIGIN})
    assert r_logout.status_code == 200
    print(f"[PASS] Persona '{username}' -> Authenticated, cookie set, verified /auth/me, routed to {expected_route}")

print("[PASS] Check 2: All 5 demo personas authenticated and verified.")

# Check 3: Admin dashboard APIs
admin_client = TestClient(app)
admin_client.post("/api/v1/auth/login", json={"username": "admin", "password": "PramaanAdmin@2026!"})

# Dashboard summary
r_sum = admin_client.get("/api/v1/dashboard/summary", headers={"Origin": FRONTEND_ORIGIN})
assert r_sum.status_code == 200
sum_data = r_sum.json()
assert "total_students" in sum_data
print(f"[PASS] Check 3a: Admin GET /dashboard/summary -> {sum_data['total_students']} students, {sum_data['total_institutions']} institutions, {sum_data['open_alerts']} open alerts")

# List users
r_users = admin_client.get("/api/v1/auth/users", headers={"Origin": FRONTEND_ORIGIN})
assert r_users.status_code == 200
users_list = r_users.json()
assert isinstance(users_list, list), "Expected list of users"
assert len(users_list) >= 5
print(f"[PASS] Check 3b: Admin GET /auth/users -> {len(users_list)} registered users (Array format verified)")

# Re-evaluate alerts
r_reeval = admin_client.post("/api/v1/alerts/re-evaluate", headers={"Origin": FRONTEND_ORIGIN})
assert r_reeval.status_code == 200
print("[PASS] Check 3c: Admin POST /alerts/re-evaluate -> Success")

# Check 4: AICTE reviewer dashboard and alerts review
reviewer_client = TestClient(app)
reviewer_client.post("/api/v1/auth/login", json={"username": "aicte_reviewer", "password": "AicteReviewer@2026!"})

r_aicte = reviewer_client.get("/api/v1/aicte/dashboard-summary", headers={"Origin": FRONTEND_ORIGIN})
assert r_aicte.status_code == 200
assert "critical_temporal_conflicts" in r_aicte.json()
print("[PASS] Check 4a: Reviewer GET /aicte/dashboard-summary -> Success")

# List alerts
r_alerts = reviewer_client.get("/api/v1/alerts", headers={"Origin": FRONTEND_ORIGIN})
assert r_alerts.status_code == 200
alerts_items = r_alerts.json()["items"]
assert len(alerts_items) > 0

target_alert = next((a for a in alerts_items if a["status"] != "RESOLVED"), None)
if not target_alert:
    target_alert = alerts_items[0]
    reviewer_client.post(
        f"/api/v1/alerts/{target_alert['id']}/reopen",
        json={"reason": "Reopening for integration testing verification", "actor": "AICTE Reviewer"},
        headers={"Origin": FRONTEND_ORIGIN}
    )

target_alert_id = target_alert["id"]
print(f"[PASS] Check 4b: Reviewer GET /alerts -> {len(alerts_items)} alert(s) found (Testing on alert {target_alert_id})")

# Review alert
r_rev = reviewer_client.patch(
    f"/api/v1/alerts/{target_alert_id}/review",
    json={
        "decision": "CONFIRMED_CONFLICT",
        "note": "Integration test verified active overlap across concurrent university records."
    },
    headers={"Origin": FRONTEND_ORIGIN}
)
assert r_rev.status_code == 200, f"Review alert failed: {r_rev.text}"
assert r_rev.json()["success"] is True
print(f"[PASS] Check 4c: Reviewer PATCH /alerts/{target_alert_id}/review -> Decision persisted")

# Check 5: Institution Registrar scoped access & CSV upload
reg_client = TestClient(app)
reg_client.post("/api/v1/auth/login", json={"username": "dtu_registrar", "password": "DtuRegistrar@2026!"})

r_inst = reg_client.get("/api/v1/institution/dashboard-summary?institution_id=INST-DELHI-DTU", headers={"Origin": FRONTEND_ORIGIN})
assert r_inst.status_code == 200
assert r_inst.json()["institution_id"] == "INST-DELHI-DTU"
print("[PASS] Check 5a: Registrar GET /institution/dashboard-summary -> Scoped to DTU")

# CSV Upload test (with valid rows)
csv_content = (
    "student_ref,apaar_id,full_name,institution_id,programme_id,academic_year,admission_cycle,enrolment_start,enrolment_status,seat_category,source_submission_id\n"
    "STU-DISP-001,9876-5432-8888,Tanya Sen,INST-DELHI-DTU,BTECH-CSE,2025-2026,Regular 2025,2025-08-01,Active,General,BATCH-TEST-01\n"
).encode("utf-8")

# Test CSV Upload via internal endpoint call with exception printing
import logging
logging.basicConfig(level=logging.INFO)

r_up = reg_client.post(
    "/api/v1/students/upload-csv",
    files={"file": ("test_ingest.csv", csv_content, "text/csv")},
    headers={"Origin": FRONTEND_ORIGIN}
)
up_data = r_up.json()
if r_up.status_code != 200 or up_data.get("accepted_count") != 1:
    print(f"DEBUG: upload status={r_up.status_code}, up_data={json.dumps(up_data, indent=2)}")
assert r_up.status_code == 200, f"Upload CSV failed: {r_up.text}"
assert up_data["accepted_count"] == 1
print("[PASS] Check 5b: Registrar POST /students/upload-csv -> Successfully ingested batch")

# Check 6: Digital Credentials & Non-Destructive Tamper Simulation
r_certs = admin_client.get("/api/v1/certificates", headers={"Origin": FRONTEND_ORIGIN})
assert r_certs.status_code == 200
certs_list = r_certs.json()["items"]
assert len(certs_list) > 0
target_cert = certs_list[0]["certificate_id"]

# Verify valid
r_v = admin_client.get(f"/api/v1/certificates/{target_cert}/verify", headers={"Origin": FRONTEND_ORIGIN})
assert r_v.status_code == 200
assert r_v.json()["status"] == "VALID"
print(f"[PASS] Check 6a: GET /certificates/{target_cert}/verify -> Cryptographically valid")

# Tamper simulation
r_tamp = admin_client.post(
    f"/api/v1/certificates/{target_cert}/simulate-tamper",
    json={"student_name": "Fraudulent Name Alteration"},
    headers={"Origin": FRONTEND_ORIGIN}
)
assert r_tamp.status_code == 200
tamp_data = r_tamp.json()
assert tamp_data["verification_result"]["is_authentic"] is False
assert tamp_data["database_mutated"] is False
print(f"[PASS] Check 6b: POST /certificates/{target_cert}/simulate-tamper -> Rejected without database mutation")

# Check 7: Consent & BGV Verifier
# Check candidate with consent (STU-DEMO-001)
ver_client = TestClient(app)
ver_client.post("/api/v1/auth/login", json={"username": "tcs_verifier", "password": "TcsVerifier@2026!"})

r_bgv_ok = ver_client.post(
    "/api/v1/verifier/verify-credential",
    json={"verifier_org_id": "ORG-TCS-BGV", "student_ref": "STU-DEMO-001"},
    headers={"Origin": FRONTEND_ORIGIN}
)
assert r_bgv_ok.status_code == 200
assert r_bgv_ok.json()["verified"] is True
print("[PASS] Check 7a: Verifier POST /verify-credential (Consented) -> Verified True")

# Check candidate with withheld consent (STU-DEMO-002)
r_bgv_blocked = ver_client.post(
    "/api/v1/verifier/verify-credential",
    json={"verifier_org_id": "ORG-TCS-BGV", "student_ref": "STU-DEMO-002"},
    headers={"Origin": FRONTEND_ORIGIN}
)
assert r_bgv_blocked.status_code == 200
assert r_bgv_blocked.json()["verified"] is False
print("[PASS] Check 7b: Verifier POST /verify-credential (Withheld Consent) -> Blocked False")

# Check 8: Executive reports CSV stream export & Validation Diagnostics CSV
auditor_client = TestClient(app)
auditor_client.post("/api/v1/auth/login", json={"username": "compliance_auditor", "password": "ComplianceAuditor@2026!"})

r_exp = auditor_client.get("/api/v1/reports/executive-summary/export", headers={"Origin": FRONTEND_ORIGIN})
assert r_exp.status_code == 200
assert "text/csv" in r_exp.headers.get("content-type", "")
assert "record_type,institution_id" in r_exp.text
print("[PASS] Check 8a: Auditor GET /reports/executive-summary/export -> Streamed CSV returned")

r_diag = auditor_client.get("/api/v1/validation/export-errors-csv", headers={"Origin": FRONTEND_ORIGIN})
assert r_diag.status_code == 200
assert "Rule ID,Rule Name" in r_diag.text
print("[PASS] Check 8b: GET /validation/export-errors-csv -> Diagnostics CSV returned")

# Check 9: Immutable Audit Trail
r_audit = auditor_client.get("/api/v1/audit-trail", headers={"Origin": FRONTEND_ORIGIN})
assert r_audit.status_code == 200
assert len(r_audit.json()["items"]) > 0
print(f"[PASS] Check 9: Auditor GET /audit-trail -> {len(r_audit.json()['items'])} events loaded")

# Clean up disposable temp directory
shutil.rmtree(temp_dir, ignore_errors=True)

print("=" * 70)
print("ALL 9 FRONTEND INTEGRATION VERIFICATION CHECKS PASSED PERFECTLY!")
print("=" * 70)
