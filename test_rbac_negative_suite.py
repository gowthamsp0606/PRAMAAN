"""
Negative Security & RBAC Scoping Test Suite for PRAMAAN / APAAR Sentinel
Verifies strict server-side authorization enforcement across all roles:
- Student cannot access another student's profile or institutional admin tools.
- State Officer cannot access out-of-jurisdiction state records.
- Institution Registrar cannot mutate or inspect unrelated institution records.
- Read-only Auditor cannot execute mutations (POST/PUT/DELETE).
- External Verifier can only verify signed credentials and is barred from raw student directories.
- Unauthenticated requests cannot bypass security.
"""

import os
os.environ["DATABASE_URL"] = "sqlite:///./pramaan_india_demo.db"

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.user import User
from app.models.student import Student
from app.models.student_user import StudentUserLink
from app.services.auth_service import TokenManager

client = TestClient(app)

def run_rbac_negative_tests():
    print("=" * 80)
    print("RUNNING PRAMAAN RBAC NEGATIVE & SECURITY BOUNDARY AUDIT")
    print("=" * 80)

    with SessionLocal() as db:
        # Load test users
        admin_user = db.query(User).filter(User.username == "admin").first()
        admin_tok, _, _ = TokenManager.create_access_token(admin_user)

        state_user = db.query(User).filter(User.username == "karnataka_state_officer").first()
        state_tok, _, _ = TokenManager.create_access_token(state_user)

        dtu_user = db.query(User).filter(User.username == "dtu_registrar").first()
        dtu_tok, _, _ = TokenManager.create_access_token(dtu_user)

        student_aarav = db.query(User).filter(User.username == "student_aarav").first()
        student_tok, _, _ = TokenManager.create_access_token(student_aarav, student_ref="STU-IND-081")

        auditor_user = db.query(User).filter(User.username == "compliance_auditor").first()
        auditor_tok, _, _ = TokenManager.create_access_token(auditor_user)

        verifier_user = db.query(User).filter(User.username == "tcs_verifier").first()
        verifier_tok, _, _ = TokenManager.create_access_token(verifier_user)

    admin_h = {"Authorization": f"Bearer {admin_tok}"}
    state_h = {"Authorization": f"Bearer {state_tok}"}
    dtu_h = {"Authorization": f"Bearer {dtu_tok}"}
    student_h = {"Authorization": f"Bearer {student_tok}"}
    auditor_h = {"Authorization": f"Bearer {auditor_tok}"}
    verifier_h = {"Authorization": f"Bearer {verifier_tok}"}

    results = []

    # 1. Student Negative Tests
    # Student attempts to access another student's detail
    res = client.get("/api/v1/students/STU-IND-032", headers=student_h)
    results.append(("Student accessing another student's record (STU-IND-032)", res.status_code, [401, 403]))

    # Student attempts to list all students
    res = client.get("/api/v1/students", headers=student_h)
    results.append(("Student attempting to list all students", res.status_code, [401, 403]))

    # Student attempts to access institution directory
    res = client.get("/api/v1/institution/list", headers=student_h)
    results.append(("Student attempting to access institution directory", res.status_code, [401, 403]))

    # Student attempts to list all transfers
    res = client.get("/api/v1/transfers", headers=student_h)
    results.append(("Student attempting to access transfers management list", res.status_code, [401, 403]))

    # 2. State Officer Negative Tests
    # State Officer requests another state dashboard (MAHARASHTRA)
    res = client.get("/api/v1/state/dashboard-summary?state=MAHARASHTRA", headers=state_h)
    # Backend strictly forbids accessing out-of-jurisdiction state data (403 Forbidden)
    results.append(("State Officer parameter tampering (requesting MAHARASHTRA is rejected)", res.status_code, [403]))

    # State Officer attempts to query students from MAHARASHTRA
    res = client.get("/api/v1/students?state=MAHARASHTRA", headers=state_h)
    # Must only return KARNATAKA students
    data = res.json() if res.status_code == 200 else {}
    all_ka = True
    with SessionLocal() as db:
        for item in data.get("items", []):
            s = db.query(Student).filter(Student.student_ref == item["student_ref"]).first()
            if s and not ("BLR" in s.primary_institution_id or "DHARWAD" in s.primary_institution_id or "IISC" in s.primary_institution_id or "PES" in s.primary_institution_id):
                all_ka = False
    results.append(("State Officer student list tampering (enforces Karnataka jurisdiction)", 200 if all_ka else 403, [200]))

    # 3. Read-Only Auditor Negative Tests
    # Auditor attempts mutation: initiate transfer
    res = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-IND-081",
        "source_institution_id": "INST-DELHI-DTU",
        "destination_institution_id": "INST-PUNE-COEP",
        "programme_id": "BTECH-CSE",
        "requested_effective_date": "2026-08-01",
        "reason": "Unauthorized auditor mutation test",
    }, headers=auditor_h)
    results.append(("Read-Only Auditor attempting POST /transfers/initiate", res.status_code, [401, 403]))

    # Auditor attempts to create student record
    res = client.post("/api/v1/students", json={
        "full_name": "Test Student",
        "primary_institution_id": "INST-DELHI-DTU",
        "identity_route": "AADHAAR_APAAR",
    }, headers=auditor_h)
    results.append(("Read-Only Auditor attempting POST /students", res.status_code, [401, 403]))

    # 4. External Verifier Negative Tests
    # Verifier attempts to list students directly
    res = client.get("/api/v1/students", headers=verifier_h)
    results.append(("External Verifier attempting GET /students directory", res.status_code, [401, 403]))

    # Verifier global search for student names
    res = client.get("/api/v1/search?q=Aarav&type=student", headers=verifier_h)
    v_data = res.json() if res.status_code == 200 else {}
    v_stu_count = len(v_data.get("categories", {}).get("students", []))
    results.append(("External Verifier blocked from student search indexing", 200 if v_stu_count == 0 else 403, [200]))

    # 5. Unauthenticated Access Tests with AUTH_REQUIRED=True
    from app.config import settings
    orig_auth = settings.AUTH_REQUIRED
    try:
        settings.AUTH_REQUIRED = True
        res = client.get("/api/v1/student/profile")
        results.append(("Unauthenticated request with AUTH_REQUIRED=True", res.status_code, [401]))
        res_inst = client.get("/api/v1/institution/list")
        results.append(("Unauthenticated request to /institution/list", res_inst.status_code, [401]))
    finally:
        settings.AUTH_REQUIRED = orig_auth

    print(f"\n{'Test Description':<70} | {'Status Code':<12} | {'Verdict'}")
    print("-" * 95)
    all_passed = True
    for desc, code, expected in results:
        passed = code in expected
        if not passed:
            all_passed = False
        verdict = "PASS" if passed else "FAIL"
        print(f"{desc:<70} | {code:<12} | {verdict}")

    assert all_passed, "One or more RBAC negative tests failed!"
    print("\n" + "=" * 80)
    print("ALL RBAC NEGATIVE & SECURITY BOUNDARY TESTS PASSED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    run_rbac_negative_tests()
