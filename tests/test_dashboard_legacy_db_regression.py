"""Regression test for Dashboard Summary on legacy SQLite databases without identity_status column.

Verifies:
1. Dashboard summary succeeds with HTTP 200 on unmigrated legacy databases.
2. Direct aggregation count (func.count) works without selecting missing columns.
3. Response schema satisfies the frontend DashboardSummary contract.
4. Certificates endpoint continues returning HTTP 200.
"""
from datetime import date
import sqlite3
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.enrolment import Enrolment
from app.models.certificate import Certificate
from app.models.alert import Alert


def test_dashboard_summary_legacy_schema_regression():
    """Reproduces and verifies fix for HTTP 500 when students table lacks identity_status."""
    # Create raw in-memory SQLite database mimicking unmigrated apaar_sentinel.db
    raw_conn = sqlite3.connect(":memory:", check_same_thread=False)
    cur = raw_conn.cursor()
    
    # Create students table WITHOUT identity_status
    cur.execute("""
        CREATE TABLE students (
            student_ref VARCHAR(64) PRIMARY KEY,
            apaar_id VARCHAR(32),
            full_name VARCHAR(128) NOT NULL,
            primary_institution_id VARCHAR(64),
            identity_route VARCHAR(32),
            passport_ref VARCHAR(64),
            nationality VARCHAR(64),
            is_nri BOOLEAN,
            is_oci BOOLEAN,
            is_foreign_national BOOLEAN,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)
    cur.execute("""
        INSERT INTO students (student_ref, apaar_id, full_name, primary_institution_id)
        VALUES 
            ('STU-LEGACY-001', '9876-1111-2222', 'Aarav Sharma', 'INST-DTU'),
            ('STU-LEGACY-002', '9876-1111-3333', 'Neha Patel', 'INST-DTU'),
            ('STU-LEGACY-003', '9876-1111-4444', 'Rohan Gupta', 'INST-IITD')
    """)
    raw_conn.commit()

    # Create remaining tables via SQLAlchemy metadata
    engine = create_engine(
        "sqlite://",
        creator=lambda: raw_conn,
        poolclass=StaticPool,
    )
    
    # Register the SQLite temp view hook for legacy tables
    @event.listens_for(engine, "connect")
    def setup_legacy_sqlite(conn, rec):
        c = conn.cursor()
        c.execute("PRAGMA foreign_keys=ON")
        try:
            cols = [col[1] for col in c.execute("PRAGMA table_info(students)").fetchall()]
            if cols and "identity_status" not in cols:
                col_str = ", ".join(cols)
                c.execute(f"CREATE TEMP VIEW IF NOT EXISTS students AS SELECT {col_str}, 'APAAR_VERIFIED' AS identity_status FROM main.students")
        except Exception:
            pass
        c.close()

    # Create all remaining tables (enrolments, alerts, audit_logs, approved_intakes, etc.)
    Base.metadata.create_all(bind=engine)

    test_sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with test_sessions() as db:
        db.add_all([
            Enrolment(
                student_ref="STU-LEGACY-001",
                apaar_id="9876-1111-2222",
                institution_id="INST-DTU",
                programme_id="BTECH-CSE",
                academic_year="2025-2026",
                admission_cycle="Regular",
                enrolment_start=date(2025, 8, 1),
                enrolment_status="Active",
            ),
            Certificate(
                certificate_id="CERT-TEST-LEGACY-001",
                student_ref="STU-LEGACY-001",
                apaar_id="9876-1111-2222",
                student_name="Aarav Sharma",
                institution_id="INST-DTU",
                institution_name="Delhi Technological University",
                programme_id="BTECH-CSE",
                programme_name="B.Tech Computer Science",
                issue_date="2026-06-15",
                completion_date="2026-05-30",
                status="VALID",
                signature_algorithm="HMAC-SHA256",
                signature_hex="abcdef123456",
                payload_json='{"status": "VALID"}',
            )
        ])
        db.commit()

    def override_get_db():
        db = test_sessions()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            # 1. Verify GET /api/v1/dashboard/summary succeeds with HTTP 200
            resp_dash = client.get("/api/v1/dashboard/summary")
            assert resp_dash.status_code == 200, f"Dashboard summary failed: {resp_dash.text}"
            data = resp_dash.json()
            assert data["total_students"] == 3
            assert "total_institutions" in data
            assert "open_alerts" in data
            assert "validation_pass_rate" in data
            assert "alert_severity_distribution" in data
            assert "enrolment_trends" in data
            assert "recent_activity" in data
            assert "programme_admissions_vs_intake" in data

            # 2. Verify filter by institution_id
            resp_scoped = client.get("/api/v1/dashboard/summary?institution_id=INST-DTU")
            assert resp_scoped.status_code == 200
            assert resp_scoped.json()["total_students"] == 1

            # 3. Verify certificates list works
            resp_cert = client.get("/api/v1/certificates")
            assert resp_cert.status_code == 200
            assert len(resp_cert.json()["items"]) == 1

            # 4. Verify students list works with legacy schema
            resp_stu = client.get("/api/v1/students")
            assert resp_stu.status_code == 200
            assert resp_stu.json()["total"] == 3
            assert resp_stu.json()["items"][0]["identity_status"] == "APAAR_VERIFIED"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()
        raw_conn.close()
