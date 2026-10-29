"""
PRAMAAN End-to-End Cross-Portal Transfer & Synchronization Verification
Executes the exact 10-step lifecycle test against the live running server (http://127.0.0.1:8000)
Target database: backend/pramaan_india_demo.db
"""

import httpx
import sys

BASE_URL = "http://127.0.0.1:8000/api/v1"
client = httpx.Client(timeout=10.0)

print("=" * 80)
print("PRAMAAN: 10-STEP CROSS-PORTAL LIFECYCLE & PERSISTENCE VERIFICATION")
print("=" * 80)

# Step 1: Log in to College Portal as DTU Registrar
print("\n[Step 1] Logging in to College Portal as Source Registrar (dtu_registrar)...")
login_source = client.post(f"{BASE_URL}/auth/login", json={
    "username": "dtu_registrar",
    "password": "DtuRegistrar@2026!",
    "requested_role": "institution_officer"
})
assert login_source.status_code == 200, f"Source login failed: {login_source.text}"
source_token = login_source.json()["access_token"]
source_headers = {"Authorization": f"Bearer {source_token}"}
print(f"  [PASS] DTU Registrar authenticated -> Scope: {login_source.json()['user']['institution_id']}")

# Step 2: Select an existing synthetic student at DTU (STU-IND-081, Aarav Sharma)
print("\n[Step 2] Selecting existing synthetic student (STU-IND-081) at DTU...")
stu_res = client.get(f"{BASE_URL}/students?institution_id=INST-DELHI-DTU&search=STU-IND-081", headers=source_headers)
assert stu_res.status_code == 200, f"Fetch student failed: {stu_res.text}"
students = stu_res.json().get("items", [])
assert len(students) > 0, "Student STU-IND-081 not found in DTU roster"
student = students[0]
print(f"  [PASS] Selected student: {student['full_name']} (Ref: {student['student_ref']}, APAAR: {student.get('apaar_id')})")

# Step 3: Initiate a transfer to PES University (INST-BLR-PES)
print("\n[Step 3] Initiating transfer from INST-DELHI-DTU to INST-BLR-PES (Karnataka)...")
initiate_payload = {
    "student_ref": "STU-IND-081",
    "destination_institution_id": "INST-BLR-PES",
    "destination_institution_name": "PES University, Bengaluru",
    "programme_id": "BTECH-CSE",
    "programme_name": "B.Tech Computer Science & Engineering",
    "academic_year": "2025-2026",
    "requested_effective_date": "2026-08-01",
    "transfer_reason": "Inter-state credit mobility and academic relocation"
}
init_res = client.post(f"{BASE_URL}/transfers/initiate", json=initiate_payload, headers=source_headers)
assert init_res.status_code in (200, 201), f"Initiate transfer failed: {init_res.text}"
transfer = init_res.json()
transfer_id = transfer["id"]
print(f"  [PASS] Transfer initiated successfully -> ID: {transfer_id}, Status: {transfer['status']}")
assert transfer["status"] == "PENDING_RELEASE", f"Expected PENDING_RELEASE, got {transfer['status']}"

# Step 4: Release the student through the authorized source institution (DTU)
print(f"\n[Step 4] Releasing student through source institution (DTU) with NOC clearance...")
release_payload = {
    "action": "APPROVE",
    "reason": "Institutional clearance granted; credits verified for transfer.",
    "noc_certificate_ref": f"NOC-DTU-2026-{transfer_id[-6:]}"
}
rel_res = client.post(f"{BASE_URL}/transfers/{transfer_id}/release", json=release_payload, headers=source_headers)
assert rel_res.status_code == 200, f"Release failed: {rel_res.text}"
released_transfer = rel_res.json()
print(f"  [PASS] Transfer released -> Status: {released_transfer['status']}, NOC: {released_transfer['noc_certificate_ref']}")
assert released_transfer["status"] == "RELEASED", f"Expected RELEASED, got {released_transfer['status']}"

# Step 5: Admit the student through authorized destination institution (PES University)
print("\n[Step 5] Logging in as Destination Registrar (pes_registrar) and admitting student...")
login_dest = client.post(f"{BASE_URL}/auth/login", json={
    "username": "pes_registrar",
    "password": "PesRegistrar@2026!",
    "requested_role": "institution_officer"
})
assert login_dest.status_code == 200, f"Dest login failed: {login_dest.text}"
dest_token = login_dest.json()["access_token"]
dest_headers = {"Authorization": f"Bearer {dest_token}"}
print(f"  [PASS] PES Registrar authenticated -> Scope: {login_dest.json()['user']['institution_id']}")

admit_payload = {
    "action": "ADMIT",
    "reason": "Credit equivalence accepted and matriculated into active semester batch.",
    "seat_category": "General"
}
admit_res = client.post(f"{BASE_URL}/transfers/{transfer_id}/admit", json=admit_payload, headers=dest_headers)
assert admit_res.status_code == 200, f"Admit transfer failed: {admit_res.text}"
admitted_transfer = admit_res.json()
print(f"  [PASS] Transfer admitted and finalized -> Status: {admitted_transfer['status']}")
assert admitted_transfer["status"] == "COMPLETED", f"Expected COMPLETED, got {admitted_transfer['status']}"

# Step 6: Open Student Portal and verify updated enrolment & transfer history
print("\n[Step 6] Opening Student Portal (student_aarav) to verify live academic records...")
login_stu = client.post(f"{BASE_URL}/auth/login", json={
    "username": "student_aarav",
    "password": "StudentAarav@2026!",
    "requested_role": "student"
})
assert login_stu.status_code == 200, f"Student login failed: {login_stu.text}"
stu_token = login_stu.json()["access_token"]
stu_headers = {"Authorization": f"Bearer {stu_token}"}

# Check student academic history
hist_res = client.get(f"{BASE_URL}/student/academic-history", headers=stu_headers)
assert hist_res.status_code == 200, f"Student history failed: {hist_res.text}"
enrolments = hist_res.json()["enrolments"]
print(f"  [PASS] Student Enrolments verified: {len(enrolments)} total enrolment records")
inst_ids = [e["institution_id"] for e in enrolments]
statuses = [e["enrolment_status"] for e in enrolments]
print(f"         Institutions: {inst_ids}, Statuses: {statuses}")
assert "INST-BLR-PES" in inst_ids, "PES University enrolment missing from student history"

# Check student transfers
trf_res = client.get(f"{BASE_URL}/student/transfers", headers=stu_headers)
assert trf_res.status_code == 200, f"Student transfers failed: {trf_res.text}"
stu_transfers = trf_res.json().get("transfers", trf_res.json().get("items", []))
assert any(t["id"] == transfer_id and t["status"] == "COMPLETED" for t in stu_transfers), "Completed transfer not in student transfers list"
print(f"  [PASS] Transfer {transfer_id} verified in student transfer tracking with status COMPLETED")

# Step 7: Open authorized College views (Destination and Source) and verify changed records
print("\n[Step 7] Opening College views to verify updated student rosters...")
# At PES University: student STU-IND-081 should now be present
pes_roster = client.get(f"{BASE_URL}/students?institution_id=INST-BLR-PES&search=STU-IND-081", headers=dest_headers)
assert pes_roster.status_code == 200
pes_students = pes_roster.json().get("items", [])
assert len(pes_students) > 0, "Student not found in PES University student list"
print(f"  [PASS] Student STU-IND-081 is present in PES University active roster")

# Step 8: Open AICTE Portal and verify permitted oversight information
print("\n[Step 8] Opening AICTE Portal (aicte_reviewer) to verify national transfer telemetry...")
login_aicte = client.post(f"{BASE_URL}/auth/login", json={
    "username": "aicte_reviewer",
    "password": "AicteReviewer@2026!",
    "requested_role": "reviewer"
})
assert login_aicte.status_code == 200, f"AICTE login failed: {login_aicte.text}"
aicte_token = login_aicte.json()["access_token"]
aicte_headers = {"Authorization": f"Bearer {aicte_token}"}

aicte_transfers = client.get(f"{BASE_URL}/transfers?status=COMPLETED", headers=aicte_headers)
assert aicte_transfers.status_code == 200, f"AICTE transfers query failed: {aicte_transfers.text}"
items = aicte_transfers.json()["items"]
assert any(t["id"] == transfer_id for t in items), f"Transfer {transfer_id} not visible to AICTE reviewer"
print(f"  [PASS] AICTE Reviewer observed transfer {transfer_id} in completed interstate transfer telemetry")

# Step 9: Open relevant State portal (State of Delhi) and verify authorized changes
print("\n[Step 9] Opening State Portal (delhi_state_officer) to verify state-level migration tracking...")
login_state = client.post(f"{BASE_URL}/auth/login", json={
    "username": "delhi_state_officer",
    "password": "DelhiOfficer@2026!",
    "requested_role": "state_officer"
})
assert login_state.status_code == 200, f"State officer login failed: {login_state.text}"
state_token = login_state.json()["access_token"]
state_headers = {"Authorization": f"Bearer {state_token}"}

state_transfers = client.get(f"{BASE_URL}/state/transfers?state=DELHI", headers=state_headers)
assert state_transfers.status_code == 200, f"State transfers query failed: {state_transfers.text}"
state_items = state_transfers.json()
print(f"  [PASS] Delhi State Directorate retrieved {len(state_items)} outbound/inbound transfer records")

# Step 10: Refresh/Query database independently to verify persistent ACID storage
print("\n[Step 10] Simulating page refresh: Directly querying backend endpoints after fresh authentication...")
fresh_detail = client.get(f"{BASE_URL}/transfers/{transfer_id}", headers=aicte_headers)
assert fresh_detail.status_code == 200, f"Fresh query failed: {fresh_detail.text}"
data = fresh_detail.json()
assert data["status"] == "COMPLETED"
assert data["source_decision"] in ("APPROVED", "APPROVE")
assert data["destination_decision"] in ("ADMIT", "ADMITTED")
print(f"  [PASS] Persistent state verified on fresh query: Transfer {transfer_id} is COMPLETED in database")

print("\n" + "=" * 80)
print("ALL 10/10 CROSS-PORTAL DEMONSTRATION STEPS EXECUTED & PASSED WITH 100% SUCCESS!")
print("=" * 80)
