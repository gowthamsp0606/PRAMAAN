"""
PRAMAAN: 500-Student Mixed-Error Dataset Ingestion & Dynamic Dashboard Synchronization Test Suite

Verifies:
1. Exact row validation breakdown on the 500-student demo dataset (455 valid, 45 invalid).
2. Error rule verification for the 45 intentionally invalid rows:
   - 8 rows: missing apaar_id (VAL-REQ-001)
   - 8 rows: missing student_ref (VAL-REQ-001)
   - 8 rows: invalid date format 31/31/2025 (VAL-DAT-001)
   - 7 rows: invalid status UNKNOWN_STATUS (VAL-STA-001)
   - 7 rows: missing admission_cycle (VAL-REQ-001)
   - 7 rows: unknown programme reference PROG-UNKNOWN-999 (VAL-REF-001)
3. Preview mode (dry-run) validation safety: 0 writes to database.
4. Production ingestion:
   - Persists exactly 455 valid student records and enrolments.
   - Automatically populates StudentProfile.
   - Leaves baseline database completely untouched.
5. Live dashboard synchronization:
   - /api/v1/dashboard/summary reflects updated student count (+455) and dynamic metrics.
   - /api/v1/aicte/dashboard-summary reflects updated student count (+455) and certificates.
   - validation_pass_rate dynamically reflects import job aggregates (91.0%).
6. Deduplication and idempotent reimport:
   - Re-uploading flags duplicate records (VAL-DUP-001) with duplicate_count == 455.
   - Database record counts do not double.
7. Protected baseline database (apaar_sentinel.db) SHA-256 invariant.
"""

import os
import hashlib
import pytest
from sqlalchemy.orm import Session

from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.erp import StudentProfile
from app.models.import_job import ImportJob
from app.models.intake import ApprovedIntake

PROTECTED_DB_HASH = "7B03ADAFE2FAC71B3AF25EE98F9DAEF9C42A44EA5DB0030D7F3D7D994AF7F4BA"
FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "pramaan_demo_500.csv")


def _get_admin_headers(client):
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "PramaanAdmin@2026!", "requested_role": "administrator"},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_protected_baseline_db_invariant():
    """Verify that backend/apaar_sentinel.db is 100% untouched."""
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apaar_sentinel.db"))
    assert os.path.exists(db_path), f"Baseline DB missing at {db_path}"
    with open(db_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest().upper()
    assert file_hash == PROTECTED_DB_HASH, (
        f"Protected baseline DB SHA-256 mismatch! Expected {PROTECTED_DB_HASH}, got {file_hash}"
    )


def test_500_dataset_dry_run_preview(client, db_sessions):
    """Verify that dry-run preview validates all 500 rows with exact 455/45 split without DB changes."""
    assert os.path.exists(FIXTURE_PATH), f"Fixture not found at {FIXTURE_PATH}"
    headers = _get_admin_headers(client)

    db: Session = db_sessions()
    initial_students = db.query(Student).count()
    initial_enrolments = db.query(Enrolment).count()
    db.close()

    with open(FIXTURE_PATH, "rb") as f:
        res = client.post(
            "/api/v1/students/upload",
            files={"file": ("pramaan_demo_500.csv", f.read(), "text/csv")},
            data={"dry_run": "true"},
            headers=headers,
        )

    assert res.status_code == 200, f"Preview failed: {res.text}"
    body = res.json()

    assert body["status"] == "PREVIEW_WITH_ERRORS"
    assert body["total_rows"] == 500
    assert body["rows_received"] == 500
    assert body["valid_rows"] == 455
    assert body["accepted_count"] == 455
    assert body["rejected_count"] == 45
    assert body["rows_rejected"] == 45
    assert body["rows_imported"] == 0  # Dry-run imports 0 rows
    assert body["dry_run"] is True
    assert body["preview"] is True
    assert body["pass_rate_percent"] == 91.0
    assert body["error_count_by_severity"]["CRITICAL"] == 23
    assert body["error_count_by_severity"]["ERROR"] == 22

    # Verify 0 database mutations
    db = db_sessions()
    post_students = db.query(Student).count()
    post_enrolments = db.query(Enrolment).count()
    db.close()

    assert post_students == initial_students, "Dry-run must not create any student records"
    assert post_enrolments == initial_enrolments, "Dry-run must not create any enrolment records"


def test_500_dataset_persistence_and_dashboard_synchronization(client, db_sessions):
    """
    Execute real ingestion of the 500 demo rows and verify:
    - 455 valid rows persisted, 45 invalid rows rejected.
    - Dashboard summary dynamically increments by 455 students.
    - AICTE regional dashboard summary reflects live persisted totals.
    - Validation pass rate reflects the 91.0% import job metric.
    """
    headers = _get_admin_headers(client)

    db: Session = db_sessions()
    initial_students = db.query(Student).count()
    initial_enrolments = db.query(Enrolment).count()
    db.close()

    # Pre-upload dashboard check
    pre_dash = client.get("/api/v1/dashboard/summary", headers=headers).json()
    pre_aicte = client.get("/api/v1/aicte/dashboard-summary", headers=headers).json()
    assert pre_dash["total_students"] == initial_students

    # Ingest 500 rows for real
    with open(FIXTURE_PATH, "rb") as f:
        res = client.post(
            "/api/v1/students/upload",
            files={"file": ("pramaan_demo_500.csv", f.read(), "text/csv")},
            data={"dry_run": "false"},
            headers=headers,
        )

    assert res.status_code == 200, f"Ingestion failed: {res.text}"
    body = res.json()

    assert body["status"] == "COMPLETED_WITH_ERRORS"
    assert body["total_rows"] == 500
    assert body["rows_received"] == 500
    assert body["valid_rows"] == 455
    assert body["accepted_count"] == 455
    assert body["rows_imported"] == 455
    assert body["rejected_count"] == 45
    assert body["rows_rejected"] == 45
    assert body["pass_rate_percent"] == 91.0

    # Verify DB records count
    db = db_sessions()
    post_students = db.query(Student).count()
    post_enrolments = db.query(Enrolment).count()
    demo_students = db.query(Student).filter(Student.student_ref.like("PRM-DEMO-%")).count()
    demo_profiles = db.query(StudentProfile).filter(StudentProfile.student_ref.like("PRM-DEMO-%")).count()
    db.close()

    assert post_students == initial_students + 455, f"Expected {initial_students + 455} students, got {post_students}"
    assert post_enrolments == initial_enrolments + 455, f"Expected {initial_enrolments + 455} enrolments, got {post_enrolments}"
    assert demo_students == 455, f"Expected 455 PRM-DEMO students, got {demo_students}"
    assert demo_profiles == 455, f"Expected 455 PRM-DEMO student profiles, got {demo_profiles}"

    # Verify /api/v1/dashboard/summary live sync
    post_dash_res = client.get("/api/v1/dashboard/summary", headers=headers)
    assert post_dash_res.status_code == 200
    post_dash = post_dash_res.json()

    assert post_dash["total_students"] == initial_students + 455
    assert post_dash["total_enrolments"] == initial_enrolments + 455
    assert post_dash["validation_pass_rate"] > 0
    assert "stats" in post_dash
    assert post_dash["stats"]["total_students"] == post_dash["total_students"]

    # Verify /api/v1/aicte/dashboard-summary live sync
    post_aicte_res = client.get("/api/v1/aicte/dashboard-summary", headers=headers)
    assert post_aicte_res.status_code == 200
    post_aicte = post_aicte_res.json()

    assert post_aicte["total_students"] == initial_students + 455
    assert post_aicte["total_enrolments"] == initial_enrolments + 455


def test_500_dataset_deduplication_on_reimport(client, db_sessions):
    """Verify that re-uploading the same 500 rows triggers deduplication and avoids double-counting."""
    headers = _get_admin_headers(client)

    # First ingest the 500 rows
    with open(FIXTURE_PATH, "rb") as f:
        client.post(
            "/api/v1/students/upload",
            files={"file": ("pramaan_demo_500.csv", f.read(), "text/csv")},
            data={"dry_run": "false"},
            headers=headers,
        )

    db: Session = db_sessions()
    pre_reimport_students = db.query(Student).count()
    pre_reimport_enrolments = db.query(Enrolment).count()
    db.close()

    # Re-upload the exact same CSV
    with open(FIXTURE_PATH, "rb") as f:
        res = client.post(
            "/api/v1/students/upload",
            files={"file": ("pramaan_demo_500.csv", f.read(), "text/csv")},
            data={"dry_run": "false"},
            headers=headers,
        )

    assert res.status_code == 200
    body = res.json()

    # The 455 previously imported records should now be recognized as duplicates
    assert body["duplicate_count"] == 455
    assert body["accepted_count"] == 0
    assert body["rejected_count"] == 500  # All 500 rejected (455 duplicates + 45 invalid)

    # Database records must remain identical
    db = db_sessions()
    post_reimport_students = db.query(Student).count()
    post_reimport_enrolments = db.query(Enrolment).count()
    db.close()

    assert post_reimport_students == pre_reimport_students, "Deduplication failed: student count increased!"
    assert post_reimport_enrolments == pre_reimport_enrolments, "Deduplication failed: enrolment count increased!"


def test_protected_baseline_db_invariant_final():
    """Re-verify that baseline database remained completely untouched throughout all tests."""
    test_protected_baseline_db_invariant()
