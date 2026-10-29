"""
Live Workflow Verification for all 7 Supported PRAMAAN Roles
Runs against pramaan_india_demo.db with AUTH_REQUIRED=True.
Tests genuine login and at least one complete API workflow for each role.
"""

import os
os.environ["DATABASE_URL"] = "sqlite:///pramaan_india_demo.db"
os.environ["ENVIRONMENT"] = "development"

from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

settings.AUTH_REQUIRED = True

client = TestClient(app)

print("=" * 80)
print("TESTING 7-ROLE COMPLETE WORKFLOW INTEGRATION (TARGET: pramaan_india_demo.db)")
print("=" * 80)

# Persona 1: National Administrator
print("\n[1/7] Testing National Administrator (admin)...")
res1 = client.post("/api/v1/auth/login", json={"username": "admin", "password": "PramaanAdmin@2026!", "requested_role": "administrator"})
assert res1.status_code == 200, f"Admin login failed: {res1.text}"
token1 = res1.json()["access_token"]
h1 = {"Authorization": f"Bearer {token1}"}
sum_res = client.get("/api/v1/dashboard/summary", headers=h1)
assert sum_res.status_code == 200
users_res = client.get("/api/v1/auth/users", headers=h1)
assert users_res.status_code == 200
print(f"  [PASS] Logged in cleanly -> Route: {res1.json()['user']['dashboard_route']}")
print(f"  [PASS] Workflow: National Summary ({sum_res.json()['total_students']} students), User Registry ({len(users_res.json())} users)")

# Persona 2: AICTE Regional Reviewer
print("\n[2/7] Testing AICTE Regional Reviewer (aicte_reviewer)...")
res2 = client.post("/api/v1/auth/login", json={"username": "aicte_reviewer", "password": "AicteReviewer@2026!", "requested_role": "reviewer"})
assert res2.status_code == 200, f"Reviewer login failed: {res2.text}"
token2 = res2.json()["access_token"]
h2 = {"Authorization": f"Bearer {token2}"}
aicte_res = client.get("/api/v1/aicte/dashboard-summary", headers=h2)
assert aicte_res.status_code == 200
alerts_res = client.get("/api/v1/alerts", headers=h2)
assert alerts_res.status_code == 200
print(f"  [PASS] Logged in cleanly -> Route: {res2.json()['user']['dashboard_route']}")
print(f"  [PASS] Workflow: Regional Oversight ({aicte_res.json()['jurisdiction']}), Alerts ({len(alerts_res.json()['items'])} open)")

# Persona 3: Institution Registrar
print("\n[3/7] Testing Institution Registrar (dtu_registrar)...")
res3 = client.post("/api/v1/auth/login", json={"username": "dtu_registrar", "password": "DtuRegistrar@2026!", "requested_role": "institution_officer"})
assert res3.status_code == 200, f"Registrar login failed: {res3.text}"
token3 = res3.json()["access_token"]
h3 = {"Authorization": f"Bearer {token3}"}
inst_res = client.get("/api/v1/institution/dashboard-summary?institution_id=INST-DELHI-DTU", headers=h3)
assert inst_res.status_code == 200
stu_res = client.get("/api/v1/students?institution_id=INST-DELHI-DTU", headers=h3)
assert stu_res.status_code == 200
print(f"  [PASS] Logged in cleanly -> Route: {res3.json()['user']['dashboard_route']}")
print(f"  [PASS] Workflow: Campus Intake ({inst_res.json()['institution_name']}), Students ({stu_res.json()['total']} enrolled)")

# Persona 4: Employer / BGV Verifier
print("\n[4/7] Testing Employer / BGV Verifier (tcs_verifier)...")
res4 = client.post("/api/v1/auth/login", json={"username": "tcs_verifier", "password": "TcsVerifier@2026!", "requested_role": "external_verifier"})
assert res4.status_code == 200, f"Verifier login failed: {res4.text}"
token4 = res4.json()["access_token"]
h4 = {"Authorization": f"Bearer {token4}"}
orgs_res = client.get("/api/v1/verifier/organizations", headers=h4)
assert orgs_res.status_code == 200
# Verification with DPDP consent gate
v_res = client.post("/api/v1/verifier/verify-credential", json={
    "verifier_org_id": "ORG-TCS-BGV",
    "student_ref": "STU-IND-081",
}, headers=h4)
assert v_res.status_code == 200
print(f"  [PASS] Logged in cleanly -> Route: {res4.json()['user']['dashboard_route']}")
print(f"  [PASS] Workflow: Verifier Orgs ({len(orgs_res.json()['items'])} orgs), Candidate Check Outcome: {v_res.json()['outcome']}")

# Persona 5: Compliance Auditor
print("\n[5/7] Testing Compliance Auditor (compliance_auditor)...")
res5 = client.post("/api/v1/auth/login", json={"username": "compliance_auditor", "password": "ComplianceAuditor@2026!", "requested_role": "read_only_auditor"})
assert res5.status_code == 200, f"Auditor login failed: {res5.text}"
token5 = res5.json()["access_token"]
h5 = {"Authorization": f"Bearer {token5}"}
audit_res = client.get("/api/v1/audit-trail?limit=10", headers=h5)
assert audit_res.status_code == 200
exec_res = client.get("/api/v1/reports/executive-summary", headers=h5)
assert exec_res.status_code == 200
print(f"  [PASS] Logged in cleanly -> Route: {res5.json()['user']['dashboard_route']}")
print(f"  [PASS] Workflow: Audit Log ({audit_res.json()['total']} events), Executive Reports ({exec_res.json()['total_pending_reviews']} pending reviews)")

# Persona 6: State Education Officer
print("\n[6/7] Testing State Education Officer (delhi_state_officer)...")
res6 = client.post("/api/v1/auth/login", json={"username": "delhi_state_officer", "password": "DelhiOfficer@2026!", "requested_role": "state_officer"})
assert res6.status_code == 200, f"State officer login failed: {res6.text}"
token6 = res6.json()["access_token"]
h6 = {"Authorization": f"Bearer {token6}"}
state_sum = client.get("/api/v1/state/dashboard-summary?state=DELHI", headers=h6)
assert state_sum.status_code == 200
state_inst = client.get("/api/v1/state/institutions?state=DELHI", headers=h6)
assert state_inst.status_code == 200
print(f"  [PASS] Logged in cleanly -> Route: {res6.json()['user']['dashboard_route']}")
print(f"  [PASS] Workflow: State Telemetry ({state_sum.json()['state_name']}), Institutions ({len(state_inst.json())} campuses)")

# Persona 7: Student Self-Service
print("\n[7/7] Testing Student Self-Service (student_aarav)...")
res7 = client.post("/api/v1/auth/login", json={"username": "student_aarav", "password": "StudentAarav@2026!", "requested_role": "student"})
assert res7.status_code == 200, f"Student login failed: {res7.text}"
token7 = res7.json()["access_token"]
h7 = {"Authorization": f"Bearer {token7}"}
prof_res = client.get("/api/v1/student/profile", headers=h7)
assert prof_res.status_code == 200
hist_res = client.get("/api/v1/student/academic-history", headers=h7)
assert hist_res.status_code == 200
cred_res = client.get("/api/v1/student/credentials", headers=h7)
assert cred_res.status_code == 200
print(f"  [PASS] Logged in cleanly -> Route: {res7.json()['user']['dashboard_route']}")
print(f"  [PASS] Workflow: Profile ({prof_res.json()['full_name']}, APAAR: {prof_res.json()['apaar_id']}), Enrolments ({hist_res.json()['total_enrolments']}), Credentials ({cred_res.json()['total_credentials']})")

print("\n" + "=" * 80)
print("ALL 7 OPERATIONAL ROLES AUTHENTICATED & EXECUTED WORKFLOWS WITH 100% PASS STATUS!")
print("=" * 80)
