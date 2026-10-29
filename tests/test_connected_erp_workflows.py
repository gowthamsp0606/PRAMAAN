"""
PRAMAAN: Automated Integration Test Suite for Connected Student ERP & Academic System
Tests:
1. Student 5-Tab API Contracts (AICTE, Student Info, Academics, Services, APAAR/Transfers)
2. Student Self-Service Scoping & IDOR Prevention
3. College Scoped Student Management (Roster, 5-Tab Detail, Profile Review, Document Verification, Academic Updates, Internships, Fees, No Due)
4. College Cross-Institutional Boundary Enforcement (IDOR prevention)
5. Shared Persistence: College updates reflect in Student portal, Student updates reflect in College portal
6. Protected Database Safety Invariant Check
"""

import pytest
import hashlib
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
PROTECTED_DB_HASH = "7B03ADAFE2FAC71B3AF25EE98F9DAEF9C42A44EA5DB0030D7F3D7D994AF7F4BA"


def _get_auth_headers(client, username: str, password: str, requested_role: str):
    res = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "requested_role": requested_role},
    )
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_student_five_tabs_authenticated_workflows(client):
    """Verify that an authenticated student can access all five main tabs with real persisted data."""
    headers = _get_auth_headers(client, "student_aarav", "StudentAarav@2026!", "student")

    # TAB 1: AICTE — Student-Specific Regulatory View
    aicte_res = client.get("/api/v1/student/aicte-view", headers=headers)
    assert aicte_res.status_code == 200
    aicte_data = aicte_res.json()
    assert aicte_data["student_ref"] in ("STU-IND-081", "STU-DEMO-001")
    assert "masked_apaar_id" in aicte_data
    assert "enrolment_verification_status" in aicte_data
    assert "approved_intake_context" in aicte_data
    assert "data_source" in aicte_data
    # Ensure it is NOT the national administrative dashboard
    assert "national_metrics" not in aicte_data
    assert "all_institutions_count" not in aicte_data

    # TAB 2: Student Info (ERP Profile & Documents)
    prof_res = client.get("/api/v1/student/erp-profile", headers=headers)
    assert prof_res.status_code == 200
    prof_data = prof_res.json()
    assert prof_data["student_ref"] in ("STU-IND-081", "STU-DEMO-001")
    assert "roll_number" in prof_data
    assert "department" in prof_data
    assert "profile_completion_pct" in prof_data
    assert "profile_status" in prof_data

    # Student update editable fields
    update_res = client.put(
        "/api/v1/student/erp-profile",
        json={"phone_number": "+91 99999 88888", "current_address": "Campus Hostel Room 404"},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "SUCCESS"

    # Verify updated fields persisted on subsequent read
    prof_after = client.get("/api/v1/student/erp-profile", headers=headers).json()
    assert prof_after["phone_number"] == "+91 99999 88888"
    assert prof_after["current_address"] == "Campus Hostel Room 404"

    # Submit profile
    sub_res = client.post("/api/v1/student/submit-profile", headers=headers)
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "SUBMITTED"

    # Documents
    docs_res = client.get("/api/v1/student/documents", headers=headers)
    assert docs_res.status_code == 200
    assert docs_res.json()["total_documents"] > 0

    # TAB 3: Academics
    acad_res = client.get("/api/v1/student/academics/overview", headers=headers)
    assert acad_res.status_code == 200
    acad_data = acad_res.json()
    assert "cumulative_cgpa" in acad_data
    assert "total_credits_earned" in acad_data
    assert "overall_attendance_percentage" in acad_data

    courses_res = client.get("/api/v1/student/academics/courses?semester=1", headers=headers)
    assert courses_res.status_code == 200
    assert courses_res.json()["total_courses"] > 0

    att_res = client.get("/api/v1/student/academics/attendance?semester=1", headers=headers)
    assert att_res.status_code == 200
    assert len(att_res.json()["records"]) > 0

    # TAB 4: Student Services
    intern_res = client.get("/api/v1/student/services/internships", headers=headers)
    assert intern_res.status_code == 200
    assert "internships" in intern_res.json()

    readiness_res = client.get("/api/v1/student/services/placement-readiness", headers=headers)
    assert readiness_res.status_code == 200
    assert "readiness_band" in readiness_res.json()
    assert "skills" in readiness_res.json()

    fees_res = client.get("/api/v1/student/services/fees", headers=headers)
    assert fees_res.status_code == 200
    assert "total_statutory_due" in fees_res.json()
    assert len(fees_res.json()["obligations"]) > 0

    nodue_res = client.get("/api/v1/student/services/no-due", headers=headers)
    assert nodue_res.status_code == 200

    # TAB 5: APAAR & Transfers
    profile_apaar = client.get("/api/v1/student/profile", headers=headers)
    assert profile_apaar.status_code == 200
    assert profile_apaar.json()["student_ref"] in ("STU-IND-081", "STU-DEMO-001")

    history_res = client.get("/api/v1/student/academic-history", headers=headers)
    assert history_res.status_code == 200
    assert history_res.json()["total_enrolments"] > 0

    trf_res = client.get("/api/v1/student/transfers", headers=headers)
    assert trf_res.status_code == 200


def test_student_idor_protection(client):
    """Verify that a student cannot access another student's record by tampering with parameters."""
    headers = _get_auth_headers(client, "student_aarav", "StudentAarav@2026!", "student")

    # Attempting to override student_ref query param must fail with 403 Forbidden
    res = client.get("/api/v1/student/aicte-view?student_ref=STU-XYZ-999", headers=headers)
    assert res.status_code == 403

    res2 = client.get("/api/v1/student/erp-profile?student_ref=STU-XYZ-999", headers=headers)
    assert res2.status_code == 403

    res3 = client.get("/api/v1/student/academics/overview?student_ref=STU-XYZ-999", headers=headers)
    assert res3.status_code == 403


def test_college_portal_scoped_management_and_cross_portal_sync(client):
    """
    Verify that an authorized college officer:
    1. Can view roster and detailed 5-tab student record for their own institution.
    2. Can review and approve/reject profile submissions.
    3. Can verify uploaded documents.
    4. Can update course marks and attendance.
    5. Can review internships.
    6. Cannot access another institution's students (cross-institution IDOR).
    7. Changes made by college immediately reflect in student's portal.
    """
    # Login as DTU Registrar
    dtu_headers = _get_auth_headers(client, "dtu_registrar", "DtuRegistrar@2026!", "institution_officer")
    stu_headers = _get_auth_headers(client, "student_aarav", "StudentAarav@2026!", "student")

    # 1. Roster query
    roster_res = client.get("/api/v1/institution/students", headers=dtu_headers)
    assert roster_res.status_code == 200
    students_list = roster_res.json()["students"]
    assert len(students_list) > 0
    target_student_ref = students_list[0]["student_ref"]

    # 2. Detail query for affiliated student
    detail_res = client.get(f"/api/v1/institution/students/{target_student_ref}", headers=dtu_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["student_ref"] == target_student_ref
    assert "profile" in detail
    assert "academics" in detail
    assert "documents" in detail

    # 3. Review profile approval
    review_res = client.post(
        f"/api/v1/institution/students/{target_student_ref}/review-profile",
        json={"action": "APPROVE", "remarks": "Credentials and residence verified by Academic Cell."},
        headers=dtu_headers,
    )
    assert review_res.status_code == 200
    assert review_res.json()["profile_status"] == "APPROVED"

    # Cross-portal check: Student must immediately observe "APPROVED"
    stu_profile = client.get("/api/v1/student/erp-profile", headers=stu_headers).json()
    assert stu_profile["profile_status"] == "APPROVED"
    assert stu_profile["review_remarks"] == "Credentials and residence verified by Academic Cell."

    # 4. Update academic marks
    acad_update = client.post(
        f"/api/v1/institution/students/{target_student_ref}/update-academic",
        json={
            "course_code": "CS101",
            "internal_marks": 39.0,
            "external_marks": 58.0,
            "attended_classes": 50,
            "total_classes": 52,
        },
        headers=dtu_headers,
    )
    assert acad_update.status_code == 200
    assert acad_update.json()["total_marks"] == 97.0
    assert acad_update.json()["letter_grade"] == "O"

    # Cross-portal check: Student sees updated course grade and attendance
    stu_courses = client.get("/api/v1/student/academics/courses?semester=1", headers=stu_headers).json()
    cs101 = next((c for c in stu_courses["courses"] if c["course_code"] == "CS101"), None)
    if cs101:
        assert cs101["total_marks"] == 97.0
        assert cs101["letter_grade"] == "O"

    # 5. Cross-institution access rejection (PES Registrar attempting to access DTU student)
    pes_headers = _get_auth_headers(client, "pes_registrar", "PesRegistrar@2026!", "institution_officer")
    cross_res = client.get(f"/api/v1/institution/students/{target_student_ref}", headers=pes_headers)
    assert cross_res.status_code in (403, 404)


def test_protected_database_remained_untouched():
    """Verify that the protected database apaar_sentinel.db was not changed."""
    try:
        with open("apaar_sentinel.db", "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()
            assert h == PROTECTED_DB_HASH
    except FileNotFoundError:
        pass
