import io
import os
import tempfile
from datetime import date, datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.enrolment import Enrolment
from app.models.intake import ApprovedIntake
from app.models.student import Student
from app.services.identity_service import IdentityLifecycleService, IdentityStatus
from app.security import Principal, get_current_principal

CSV_HEADER = (
    "student_ref,apaar_id,full_name,institution_id,institution_name,programme_id,"
    "programme_name,academic_year,admission_cycle,enrolment_start,enrolment_end,"
    "enrolment_status,seat_category,admission_category,passport_number\n"
)


def test_historical_student_csv_import_without_apaar():
    """Historical student records (pre-2024) can be imported without an APAAR ID and get HISTORICAL_NO_APAAR status."""
    with TestClient(app) as client:
        csv_row = (
            "HIST-001,,Ramesh Kumar,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
            "Computer Engineering,2022-2023,Regular 2022,2022-08-01,,Active,General,General,\n"
        )
        response = client.post(
            "/api/v1/students/upload-csv",
            files={"file": ("historical_batch.csv", (CSV_HEADER + csv_row).encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["accepted_count"] == 1
        assert data["rejected_count"] == 0

        # Verify student details via API
        stu_resp = client.get("/api/v1/students/HIST-001")
        assert stu_resp.status_code == 200, stu_resp.text
        stu_data = stu_resp.json()
        assert stu_data["student"]["identity_status"] == IdentityStatus.HISTORICAL_NO_APAAR
        assert stu_data["student"]["apaar_id"] is None


def test_foreign_national_csv_import_without_apaar():
    """International / Foreign National students can be imported without an APAAR ID under policy exemption."""
    with TestClient(app) as client:
        csv_row = (
            "FN-001,,Hans Zimmer,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
            "Computer Engineering,2025-2026,Regular 2025,2025-08-01,,Active,General,Foreign National,GER-P-882910\n"
        )
        response = client.post(
            "/api/v1/students/upload-csv",
            files={"file": ("foreign_students.csv", (CSV_HEADER + csv_row).encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["accepted_count"] == 1
        assert data["rejected_count"] == 0

        # Verify student details via API
        stu_resp = client.get("/api/v1/students/FN-001")
        assert stu_resp.status_code == 200, stu_resp.text
        stu_data = stu_resp.json()
        assert stu_data["student"]["identity_status"] == IdentityStatus.EXEMPT_WHERE_POLICY_PERMITS
        assert stu_data["student"]["apaar_id"] is None


def test_contemporary_student_without_apaar_rejected():
    """Contemporary domestic students (2024+) without APAAR ID are rejected with VAL-REQ-001."""
    with TestClient(app) as client:
        csv_row = (
            "DOM-001,,Anita Verma,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
            "Computer Engineering,2025-2026,Regular 2025,2025-08-01,,Active,General,General,\n"
        )
        response = client.post(
            "/api/v1/students/upload-csv",
            files={"file": ("contemporary_invalid.csv", (CSV_HEADER + csv_row).encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["rejected_count"] == 1
        assert data["accepted_count"] == 0
        row_issues = [f.get("rule_id") or f.get("code") for f in data["field_errors"]]
        assert "VAL-REQ-001" in row_issues


def test_historical_student_apaar_collision_prevention():
    """Updating a student to an APAAR ID already held by another student raises collision error."""
    with TestClient(app) as client:
        # Upload one verified student
        csv_verified = (
            "STU-EXIST,1111-2222-3333,Existing Student,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
            "Computer Engineering,2025-2026,Regular 2025,2025-08-01,,Active,General,General,\n"
        )
        resp1 = client.post(
            "/api/v1/students/upload-csv",
            files={"file": ("verified.csv", (CSV_HEADER + csv_verified).encode("utf-8"), "text/csv")},
        )
        assert resp1.status_code == 200, resp1.text

        # Upload one historical student without APAAR
        csv_hist = (
            "STU-HIST,,Legacy Student,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
            "Computer Engineering,2021-2022,Regular 2021,2021-08-01,,Active,General,General,\n"
        )
        resp2 = client.post(
            "/api/v1/students/upload-csv",
            files={"file": ("hist.csv", (CSV_HEADER + csv_hist).encode("utf-8"), "text/csv")},
        )
        assert resp2.status_code == 200, resp2.text

        # Attempt to patch STU-HIST with STU-EXIST's APAAR ID
        patch_resp = client.patch(
            "/api/v1/students/STU-HIST/identity-status",
            json={
                "new_status": IdentityStatus.APAAR_VERIFIED,
                "reason": "Student provided late APAAR verification",
                "new_apaar_id": "1111-2222-3333",
            },
        )
        assert patch_resp.status_code == 422
        assert "already assigned to student" in patch_resp.json()["detail"]

        # Valid update with an unused APAAR ID
        patch_valid = client.patch(
            "/api/v1/students/STU-HIST/identity-status",
            json={
                "new_status": IdentityStatus.APAAR_VERIFIED,
                "reason": "Student provided late APAAR verification",
                "new_apaar_id": "9999-8888-7777",
            },
        )
        assert patch_valid.status_code == 200, patch_valid.text
        assert patch_valid.json()["current_status"] == IdentityStatus.APAAR_VERIFIED
        assert patch_valid.json()["apaar_id"] == "9999-8888-7777"


def test_identity_status_transition_rules_and_audit():
    """Transition validation prevents arbitrary invalid transitions and records audit logs."""
    with TestClient(app) as client:
        # Upload a historical student
        csv_hist = (
            "STU-TRANS,,Transition Student,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
            "Computer Engineering,2021-2022,Regular 2021,2021-08-01,,Active,General,General,\n"
        )
        client.post(
            "/api/v1/students/upload-csv",
            files={"file": ("hist.csv", (CSV_HEADER + csv_hist).encode("utf-8"), "text/csv")},
        )

        # Invalid transition directly to arbitrary or unpermitted status
        invalid_resp = client.patch(
            "/api/v1/students/STU-TRANS/identity-status",
            json={
                "new_status": "BOGUS_STATUS",
                "reason": "Invalid test attempt",
            },
        )
        assert invalid_resp.status_code == 422
        assert "Unknown identity status 'BOGUS_STATUS'" in invalid_resp.json()["detail"]

        # Valid transition to APAAR_PENDING
        valid_resp = client.patch(
            "/api/v1/students/STU-TRANS/identity-status",
            json={
                "new_status": IdentityStatus.APAAR_PENDING,
                "reason": "Applied for APAAR card via DigiLocker drive",
                "evidence_reference": "DIGI-ACK-2026-001",
            },
        )
        assert valid_resp.status_code == 200, valid_resp.text
        assert valid_resp.json()["current_status"] == IdentityStatus.APAAR_PENDING


def test_list_students_filter_by_identity_status():
    """GET /api/v1/students filters accurately by identity_status."""
    with TestClient(app) as client:
        csv_batch = (
            "STU-F-1,,Hist 1,INST-DELHI-DTU,DTU,BTECH-CSE,CSE,2020-2021,Regular 2020,2020-08-01,,Active,General,General,\n"
            "STU-F-2,,Foreign 1,INST-DELHI-DTU,DTU,BTECH-CSE,CSE,2025-2026,Regular 2025,2025-08-01,,Active,General,Foreign National,PASS-991\n"
            "STU-F-3,5555-4444-3333,Verified 1,INST-DELHI-DTU,DTU,BTECH-CSE,CSE,2025-2026,Regular 2025,2025-08-01,,Active,General,General,\n"
        )
        client.post(
            "/api/v1/students/upload-csv",
            files={"file": ("batch.csv", (CSV_HEADER + csv_batch).encode("utf-8"), "text/csv")},
        )

        resp_hist = client.get("/api/v1/students?identity_status=HISTORICAL_NO_APAAR")
        assert resp_hist.status_code == 200
        items_hist = resp_hist.json()["items"]
        assert all(item["identity_status"] == IdentityStatus.HISTORICAL_NO_APAAR for item in items_hist)
        assert any(item["student_ref"] == "STU-F-1" for item in items_hist)

        resp_exempt = client.get("/api/v1/students?identity_status=EXEMPT_WHERE_POLICY_PERMITS")
        assert resp_exempt.status_code == 200
        items_exempt = resp_exempt.json()["items"]
        assert all(item["identity_status"] == IdentityStatus.EXEMPT_WHERE_POLICY_PERMITS for item in items_exempt)
        assert any(item["student_ref"] == "STU-F-2" for item in items_exempt)


def test_enrolment_conflicts_endpoint_and_scoping():
    """GET /api/v1/enrolments/conflicts returns conflict details and respects pagination and filtering."""
    with TestClient(app) as client:
        resp = client.get("/api/v1/enrolments/conflicts")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert isinstance(data["items"], list)

        # Check pagination
        resp_paged = client.get("/api/v1/enrolments/conflicts?page=1&limit=2")
        assert resp_paged.status_code == 200
        data_paged = resp_paged.json()
        assert data_paged["limit"] == 2
        assert len(data_paged["items"]) <= 2

        # Check filter with non-existent type
        resp_filtered = client.get("/api/v1/enrolments/conflicts?conflict_type=NON_EXISTENT_TYPE")
        assert resp_filtered.status_code == 200
        assert resp_filtered.json()["total"] == 0


def test_intake_compliance_findings_endpoint():
    """GET /api/v1/intake-compliance/findings returns explainable findings with quota calculations."""
    with TestClient(app) as client:
        resp = client.get("/api/v1/intake-compliance/findings")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "total_findings" in data
        assert "findings" in data
        assert isinstance(data["findings"], list)

        if data["total_findings"] > 0:
            finding = data["findings"][0]
            assert "institution_id" in finding
            assert "programme_id" in finding
            assert "academic_year" in finding
            assert "compliance_status" in finding
            assert "approved_intake" in finding
            assert "review_recommended" in finding

        # Filter by compliance status
        compliant_resp = client.get("/api/v1/intake-compliance/findings?compliance_status=COMPLIANT")
        assert compliant_resp.status_code == 200
        comp_data = compliant_resp.json()
        for f in comp_data["findings"]:
            assert f["compliance_status"] == "COMPLIANT"


def test_alembic_phase3_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    """Forward Alembic migration 20261027_01 applies cleanly and downgrades safely on a disposable database."""
    from pathlib import Path

    temp_db = tmp_path / "migration_disposable.db"
    temp_url = f"sqlite:///{temp_db.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", temp_url)

    backend_root = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", temp_url)

    engine = create_engine(temp_url)

    # Create pre-migration schema matching state at 20261026_01
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE students (
                student_ref VARCHAR(64) PRIMARY KEY,
                apaar_id VARCHAR(32) NOT NULL UNIQUE,
                full_name VARCHAR(128) NOT NULL,
                primary_institution_id VARCHAR(64),
                date_of_birth DATE,
                gender VARCHAR(16),
                contact_email VARCHAR(128),
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE enrolments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_ref VARCHAR(64) NOT NULL,
                apaar_id VARCHAR(32) NOT NULL,
                institution_id VARCHAR(64) NOT NULL,
                programme_id VARCHAR(64) NOT NULL,
                academic_year VARCHAR(16) NOT NULL,
                admission_cycle VARCHAR(64) NOT NULL,
                enrolment_start DATE NOT NULL,
                enrolment_end DATE,
                enrolment_status VARCHAR(32) NOT NULL,
                seat_category VARCHAR(32) DEFAULT 'General',
                created_at TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL,
                PRIMARY KEY (version_num)
            );
        """))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20261026_01');"))
        conn.execute(
            text(
                "INSERT INTO students (student_ref, apaar_id, full_name, primary_institution_id, "
                "date_of_birth, gender, contact_email, is_active, created_at, updated_at) "
                "VALUES ('MIG-STU-1', '1234-5678-9012', 'Migration Student', 'INST001', "
                "'2002-01-01', 'Female', 'mig@example.invalid', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.commit()

    # 1. Upgrade to Phase 3 revision 20261027_01
    command.upgrade(alembic_cfg, "20261027_01")

    # Inspect schema
    inspector = inspect(engine)
    student_columns = {col["name"]: col for col in inspector.get_columns("students")}
    assert "identity_status" in student_columns
    assert student_columns["apaar_id"]["nullable"] is True

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT student_ref, apaar_id, identity_status FROM students WHERE student_ref = 'MIG-STU-1'")
        ).fetchone()
        assert row is not None
        assert row[0] == "MIG-STU-1"
        assert row[1] == "1234-5678-9012"
        # server_default should have set APAAR_VERIFIED
        assert row[2] == "APAAR_VERIFIED"

        # Verify nullable apaar_id insertion works
        conn.execute(
            text(
                "INSERT INTO students (student_ref, apaar_id, full_name, primary_institution_id, "
                "date_of_birth, gender, contact_email, is_active, created_at, updated_at, identity_status) "
                "VALUES ('MIG-STU-HIST', NULL, 'Historical Migration Student', 'INST001', "
                "'2001-01-01', 'Male', 'hist@example.invalid', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'HISTORICAL_NO_APAAR')"
            )
        )
        conn.commit()

    # 2. Clean up null apaar_id record prior to downgrade (since 20261026_01 has NOT NULL on apaar_id)
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM students WHERE student_ref = 'MIG-STU-HIST'"))
        conn.commit()

    # Downgrade back to Phase 2 revision
    command.downgrade(alembic_cfg, "20261026_01")
    inspector_after = inspect(engine)
    student_cols_after = {col["name"]: col for col in inspector_after.get_columns("students")}
    assert "identity_status" not in student_cols_after
    assert student_cols_after["apaar_id"]["nullable"] is False

    engine.dispose()
