from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.alert import Alert
from app.models.enrolment import Enrolment
from app.models.import_job import ImportJob, ImportRowResult
from app.models.intake import ApprovedIntake
from app.models.student import Student
from app.services.reports_service import ReportsService


@pytest.fixture
def reporting_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        db.add_all([
            Student(student_ref="REPORT-A", apaar_id="MASK-A", full_name="Report A", primary_institution_id="INST-A"),
            Student(student_ref="REPORT-B", apaar_id="MASK-B", full_name="Report B", primary_institution_id="INST-B"),
        ])
        db.flush()
        db.add_all([
            Enrolment(
                student_ref="REPORT-A", apaar_id="MASK-A", institution_id="INST-A",
                programme_id="PROG-A", academic_year="2025-2026", admission_cycle="Regular 2025",
                enrolment_start=date(2025, 8, 1), enrolment_status="Active",
                created_at=datetime(2026, 10, 22, 12), seat_category="General",
            ),
            Enrolment(
                student_ref="REPORT-B", apaar_id="MASK-B", institution_id="INST-B",
                programme_id="PROG-B", academic_year="2025-2026", admission_cycle="Regular 2025",
                enrolment_start=date(2025, 8, 1), enrolment_status="Withdrawn",
                enrolment_end=date(2025, 11, 1), created_at=datetime(2026, 10, 20, 12),
                seat_category="General",
            ),
        ])
        db.flush()
        enrolment_a = db.query(Enrolment).filter(Enrolment.student_ref == "REPORT-A").one()
        db.add_all([
            ApprovedIntake(
                institution_id="INST-A", institution_name="Institute A", programme_id="PROG-A",
                programme_name="Programme A", academic_year="2025-2026", admission_cycle="Regular 2025",
                approved_intake_seats=1, supernumerary_quota=None, nri_quota=None,
                rule_id="RULE-A", rule_source="Synthetic report test", effective_date="2025-04-01",
                rule_configured=True,
            ),
            Alert(
                id="REPORT-ALERT-OPEN", student_ref="REPORT-A", apaar_id="MASK-A",
                alert_type="TEMPORAL_OVERLAP_CONFLICT", severity="HIGH", status="OPEN",
                title="Pending test alert", explanation="Synthetic report fixture.",
                supporting_record_ids=[enrolment_a.id], created_at=datetime(2026, 10, 20, 12),
            ),
            ImportJob(
                id="IMPORT-REPORT-1", institution_id="INST-A", submitted_by="operator-a",
                original_filename="safe.csv", status="COMPLETED_WITH_ERRORS", total_rows=2,
                accepted_rows=1, rejected_rows=1, review_rows=0,
                validation_summary={"error_count_by_severity": {"ERROR": 1}},
                uploaded_at=datetime(2026, 10, 22, 9), completed_at=datetime(2026, 10, 22, 9, 1),
            ),
            ImportRowResult(
                import_job_id="IMPORT-REPORT-1", row_number=1, record_reference="REPORT-A",
                identity_hash="a" * 64, outcome="ACCEPTED", persisted=True,
                issue_codes=[], validation_messages=[],
            ),
            ImportRowResult(
                import_job_id="IMPORT-REPORT-1", row_number=2, record_reference="REPORT-B",
                identity_hash="b" * 64, outcome="REJECTED", persisted=False,
                issue_codes=["VAL-DAT-001"],
                validation_messages=[{"code": "VAL-DAT-001", "message": "Invalid date."}],
            ),
        ])
        db.commit()
        yield db
    engine.dispose()


def test_reports_use_persisted_age_import_results_and_phase2_intake(reporting_db):
    report = ReportsService(reporting_db).generate_executive_reports(
        institution_id="INST-A",
        reference_time=datetime(2026, 10, 24, 12),
    )

    assert report["total_pending_reviews"] == 1
    assert report["pending_cases"][0]["days_pending"] == 4
    assert report["import_summary"]["jobs"] == 1
    assert report["import_summary"]["total_rows"] == 2
    assert report["import_summary"]["outcomes"]["REJECTED"] == 1
    assert report["import_summary"]["validation_issue_counts"] == {"VAL-DAT-001": 1}
    assert report["enrolment_summary"] == {
        "enrolment_records": 1,
        "distinct_students": 1,
        "records_by_status": {"Active": 1, "Completed": 0, "Withdrawn": 0, "Suspended": 0},
    }
    assert len(report["intake_compliance_results"]) == 1
    assert report["intake_compliance_results"][0]["compliance_status"] == "COMPLIANT"
    assert report["monthly_summary"] == [{
        "month": "2026-10",
        "new_admissions": 1,
        "alerts_triggered": 1,
        "resolved_cases": 0,
        "imports_completed": 1,
    }]
    assert report["region_distribution_available"] is False


def test_report_filters_and_date_range_use_persisted_timestamps(reporting_db):
    report = ReportsService(reporting_db).generate_executive_reports(
        institution_id="INST-A",
        programme_id="PROG-A",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        start_date=date(2026, 10, 20),
        end_date=date(2026, 10, 23),
        reference_time=datetime(2026, 10, 24),
    )

    assert report["enrolment_summary"]["enrolment_records"] == 1
    assert report["total_pending_reviews"] == 1
    assert report["import_summary"]["jobs"] == 1
    assert report["filters"]["academic_year"] == "2025-2026"


def test_report_route_and_export_are_authorized_and_data_derived(reporting_db):
    def override_get_db():
        yield reporting_db

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/reports/executive-summary", params={"institution_id": "INST-A"})
            export = client.get("/api/v1/reports/executive-summary/export", params={"institution_id": "INST-A"})
            invalid_range = client.get(
                "/api/v1/reports/executive-summary",
                params={"start_date": "2026-10-24", "end_date": "2026-10-20"},
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 200
    assert response.json()["total_pending_reviews"] == 1
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert "INTAKE_COMPLIANCE" in export.text
    assert "RULE-A" not in export.text
    assert invalid_range.status_code == 422