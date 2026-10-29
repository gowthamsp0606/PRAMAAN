"""
PRAMAAN: Comprehensive Integration Verification Suite for Final Platform Fixes
Tests:
1. Real PDF Binary Downloads:
   - Degree Certificate PDF
   - Semester Academic Transcript PDF
   - Bond Effect Certificate PDF
   - Transfer NOC PDF
2. Official CSV & Excel (.xlsx) Exports:
   - Student Roster CSV & Excel
   - State Institutions CSV & Excel
   - Transfers Register CSV & Excel
   - Integrity Alerts CSV & Excel
3. Flexible CSV Upload with Aliased & Reordered Columns
4. State Directorate (Tamil Nadu) Scoping & Student Listing
5. Primary College Setup (St. Joseph's College of Engineering - INST-CHENNAI-SJCE)
6. RBAC & IDOR Boundaries
7. Protected Baseline Database SHA-256 Invariant
"""

import io
import os
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


# =============================================================================
# 1. REAL PDF BINARY DOWNLOAD TESTS
# =============================================================================
def test_pdf_downloads_binary_validity(client):
    """Verify that all PDF download endpoints return real binary streams with %PDF magic bytes."""
    student_headers = _get_auth_headers(client, "student_karthik", "StudentKarthik@2026!", "student")

    # 1. Academic Transcript PDF
    transcript_res = client.get("/api/v1/student/transcripts/1/download", headers=student_headers)
    assert transcript_res.status_code == 200
    assert transcript_res.headers.get("content-type") == "application/pdf"
    assert "attachment" in transcript_res.headers.get("content-disposition", "")
    assert transcript_res.content.startswith(b"%PDF-"), "Transcript is not a valid PDF binary"

    # 2. Degree / Certificate PDF
    certs_res = client.get("/api/v1/student/certificates", headers=student_headers)
    assert certs_res.status_code == 200
    cert_list = certs_res.json()
    assert len(cert_list) > 0, "Student has no certificates seeded"
    cert_id = cert_list[0]["certificate_id"]

    cert_pdf_res = client.get(f"/api/v1/student/certificates/{cert_id}/download", headers=student_headers)
    assert cert_pdf_res.status_code == 200
    assert cert_pdf_res.headers.get("content-type") == "application/pdf"
    assert cert_pdf_res.content.startswith(b"%PDF-"), "Certificate is not a valid PDF binary"

    # 3. Direct Certificate download endpoint
    direct_cert_res = client.get(f"/api/v1/certificates/{cert_id}/download", headers=student_headers)
    assert direct_cert_res.status_code == 200
    assert direct_cert_res.headers.get("content-type") == "application/pdf"
    assert direct_cert_res.content.startswith(b"%PDF-")

    # 4. Transfer Bond Effect Certificate & NOC
    # Initiate a test transfer or fetch existing
    sjce_headers = _get_auth_headers(client, "sjce_registrar", "SjceRegistrar@2026!", "institution_officer")
    trf_list_res = client.get("/api/v1/transfers/", headers=sjce_headers)
    assert trf_list_res.status_code == 200
    transfers = trf_list_res.json().get("items", [])

    if transfers:
        trf_id = transfers[0]["id"]
        # Bond effect certificate download
        bond_res = client.get(f"/api/v1/transfers/{trf_id}/bond-effect-certificate", headers=sjce_headers)
        assert bond_res.status_code == 200
        assert bond_res.headers.get("content-type") == "application/pdf"
        assert bond_res.content.startswith(b"%PDF-"), "Bond Effect Certificate is not a valid PDF binary"

        # Transfer NOC download
        noc_res = client.get(f"/api/v1/transfers/{trf_id}/noc-download", headers=sjce_headers)
        assert noc_res.status_code == 200
        assert noc_res.headers.get("content-type") == "application/pdf"
        assert noc_res.content.startswith(b"%PDF-"), "Transfer NOC is not a valid PDF binary"


# =============================================================================
# 2. OFFICIAL CSV & EXCEL EXPORT TESTS
# =============================================================================
def test_csv_and_excel_exports(client):
    """Verify that export endpoints return valid CSV text and valid OpenXML Excel bytes."""
    sjce_headers = _get_auth_headers(client, "sjce_registrar", "SjceRegistrar@2026!", "institution_officer")

    # 1. Student Roster CSV Export
    csv_res = client.get("/api/v1/students/export-csv", headers=sjce_headers)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("content-type", "")
    assert "Student Ref" in csv_res.text
    assert "STU-SJCE" in csv_res.text

    # 2. Student Roster Excel Export
    excel_res = client.get("/api/v1/students/export-excel", headers=sjce_headers)
    assert excel_res.status_code == 200
    assert "openxmlformats" in excel_res.headers.get("content-type", "")
    assert excel_res.content.startswith(b"PK\x03\x04"), "Excel export lacks valid ZIP/XLSX header"

    # 3. State Institutions CSV & Excel Export
    tn_headers = _get_auth_headers(client, "tn_state_officer", "TnOfficer@2026!", "state_officer")
    state_csv_res = client.get("/api/v1/state/export-csv?state=TAMIL_NADU", headers=tn_headers)
    assert state_csv_res.status_code == 200
    assert "text/csv" in state_csv_res.headers.get("content-type", "")
    assert "INST-CHENNAI-SJCE" in state_csv_res.text

    state_excel_res = client.get("/api/v1/state/export-excel?state=TAMIL_NADU", headers=tn_headers)
    assert state_excel_res.status_code == 200
    assert state_excel_res.content.startswith(b"PK\x03\x04")

    # 4. Transfers CSV & Excel Export
    trf_csv_res = client.get("/api/v1/transfers/export-csv", headers=sjce_headers)
    assert trf_csv_res.status_code == 200
    assert "text/csv" in trf_csv_res.headers.get("content-type", "")

    trf_excel_res = client.get("/api/v1/transfers/export-excel", headers=sjce_headers)
    assert trf_excel_res.status_code == 200
    assert trf_excel_res.content.startswith(b"PK\x03\x04")

    # 5. Integrity Alerts CSV & Excel Export
    aicte_headers = _get_auth_headers(client, "aicte_reviewer", "AicteReviewer@2026!", "reviewer")
    alert_csv_res = client.get("/api/v1/alerts/export-csv", headers=aicte_headers)
    assert alert_csv_res.status_code == 200
    assert "text/csv" in alert_csv_res.headers.get("content-type", "")

    alert_excel_res = client.get("/api/v1/alerts/export-excel", headers=aicte_headers)
    assert alert_excel_res.status_code == 200
    assert alert_excel_res.content.startswith(b"PK\x03\x04")


# =============================================================================
# 3. CSV UPLOAD WITH ALIASED & REORDERED HEADERS
# =============================================================================
def test_csv_upload_flexible_columns(client):
    """Verify that CSV upload handles aliased, reordered, and spaced column headers cleanly."""
    sjce_headers = _get_auth_headers(client, "sjce_registrar", "SjceRegistrar@2026!", "institution_officer")

    # Non-standard column order with realistic human aliases
    csv_content = (
        "Roll Number,Student Name,Aadhaar / Identifier,Department,Batch,Contact Email,Phone\n"
        "STU-UPLOAD-991,Ramesh Patel,123456789012,Computer Science,2025,ramesh.patel@sjce.edu.in,9876543210\n"
        "STU-UPLOAD-992,Sneha Reddy,987654321098,Information Technology,2025,sneha.reddy@sjce.edu.in,9876543211\n"
    )

    file_obj = io.BytesIO(csv_content.encode("utf-8"))
    files = {"file": ("students_roster_custom.csv", file_obj, "text/csv")}

    res = client.post("/api/v1/students/upload", files=files, headers=sjce_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 0
    assert body["total_rows"] == 2

    # Verify that StudentProfile was created automatically
    detail_res = client.get("/api/v1/institution/students/STU-UPLOAD-991", headers=sjce_headers)
    assert detail_res.status_code == 200
    profile = detail_res.json().get("profile")
    assert profile is not None
    assert profile["roll_number"] == "STU-UPLOAD-991"
    assert profile["department"] == "Computer Science"


# =============================================================================
# 4. PRIMARY COLLEGE SETUP & CAPACITY
# =============================================================================
def test_primary_college_population(client):
    """Verify that St. Joseph's College of Engineering (INST-CHENNAI-SJCE) has >= 150 students and approved intakes."""
    sjce_headers = _get_auth_headers(client, "sjce_registrar", "SjceRegistrar@2026!", "institution_officer")

    # Check institution summary
    summary_res = client.get("/api/v1/institution/dashboard-summary?institution_id=INST-CHENNAI-SJCE", headers=sjce_headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["institution_id"] == "INST-CHENNAI-SJCE"
    assert summary["total_enrolments"] >= 150, f"Expected >= 150 students in SJCE, found {summary['total_enrolments']}"
    assert len(summary["programmes"]) >= 5, "Expected at least 5 approved programmes for SJCE"

    # Check student roster pagination
    roster_res = client.get("/api/v1/institution/students?institution_id=INST-CHENNAI-SJCE&page=1&page_size=20", headers=sjce_headers)
    assert roster_res.status_code == 200
    roster = roster_res.json()
    assert roster["total"] >= 150
    assert len(roster["items"]) == 20


# =============================================================================
# 5. STATE DIRECTORATE SCOPING FOR TAMIL NADU
# =============================================================================
def test_state_directorate_scoping(client):
    """Verify that State Officer for Tamil Nadu is strictly scoped to TN institutions and students."""
    tn_headers = _get_auth_headers(client, "tn_state_officer", "TnOfficer@2026!", "state_officer")

    # 1. State Institutions
    inst_res = client.get("/api/v1/state/institutions", headers=tn_headers)
    assert inst_res.status_code == 200
    institutions = inst_res.json().get("items", [])
    inst_ids = [i["institution_id"] for i in institutions]
    assert "INST-CHENNAI-SJCE" in inst_ids, "St. Joseph's College of Engineering must be under Tamil Nadu"
    assert "INST-DELHI-DTU" not in inst_ids, "Delhi Technological University must not appear in TN state"

    # 2. State Student Directory for SJCE
    sjce_students_res = client.get("/api/v1/state/institutions/INST-CHENNAI-SJCE/students?page=1&limit=25", headers=tn_headers)
    assert sjce_students_res.status_code == 200
    sjce_students = sjce_students_res.json()
    assert sjce_students["institution_id"] == "INST-CHENNAI-SJCE"
    assert sjce_students["state"] == "TAMIL_NADU"
    assert sjce_students["total"] >= 150
    assert len(sjce_students["items"]) == 25

    # 3. IDOR Prevention: Attempting to access students of an out-of-state institution
    out_of_state_res = client.get("/api/v1/state/institutions/INST-DELHI-DTU/students", headers=tn_headers)
    assert out_of_state_res.status_code in (403, 404), "State officer must not access out-of-state colleges"


# =============================================================================
# 6. INVESTIGATION CASES SUPPORT NEUTRAL CATEGORIES & STATUSES
# =============================================================================
def test_investigation_cases_neutral_categories(client):
    """Verify that alerts support neutral categories (missing documents, attendance, transfer review) and statuses."""
    aicte_headers = _get_auth_headers(client, "aicte_reviewer", "AicteReviewer@2026!", "reviewer")

    alerts_res = client.get("/api/v1/alerts/investigation-cases?page=1&page_size=50", headers=aicte_headers)
    assert alerts_res.status_code == 200
    cases = alerts_res.json().get("items", [])
    assert len(cases) > 0

    # Ensure not every case is labeled 'fraud' or 'CRITICAL'
    types = {c.get("alert_type") or c.get("anomaly_type") for c in cases}
    neutral_types = {"DUPLICATE_IDENTIFIERS", "ACADEMIC_DATA_INCONSISTENCY", "MISSING_INFORMATION", "CONFLICTING_ENROLMENT", "EXCEPTION_REVIEW_REQUIRED", "DOCUMENT_REVIEW", "ATTENDANCE_SHORTAGE", "TRANSFER_REVIEW"}
    assert any(t in types for t in neutral_types), (
        f"Expected neutral review categories in cases, found {types}"
    )


# =============================================================================
# 7. PROTECTED DATABASE SHA-256 INVARIANT
# =============================================================================
def test_protected_db_invariant_preserved():
    """Verify that backend/apaar_sentinel.db is 100% byte-for-byte identical to baseline."""
    hasher = hashlib.sha256()
    db_path = "apaar_sentinel.db" if os.path.exists("apaar_sentinel.db") else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apaar_sentinel.db"))
    with open(db_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    assert hasher.hexdigest().upper() == PROTECTED_DB_HASH, "Protected database has been modified!"
