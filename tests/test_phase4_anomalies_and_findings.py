import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.intake import HistoricalIntake
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.student import Student
from app.services.anomaly_service import HistoricalAnomalyService
from app.security import Principal, get_current_principal


@pytest.fixture
def phase4_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        # 1. Sufficient history for INST-A (5 years)
        years = ["2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026"]
        counts = [100, 105, 95, 102, 220]  # Latest is anomalous surge
        db.add_all([
            HistoricalIntake(
                institution_id="INST-A",
                institution_name="Alpha Tech Institute",
                programme_id="PROG-CS",
                programme_name="Computer Science",
                academic_year=y,
                admitted_count=c,
                approved_intake=120,
                is_anomaly=idx == 4,
                z_score=3.85 if idx == 4 else 0.2,
                pct_change=115.7 if idx == 4 else 5.0,
                iqr_status="OUTLIER_HIGH" if idx == 4 else "NORMAL",
                ground_truth="ANOMALY" if idx == 4 else "NORMAL",
                anomaly_explanation="Unprecedented 115% surge above moving 4-year baseline." if idx == 4 else None,
            )
            for idx, (y, c) in enumerate(zip(years, counts))
        ])

        # 2. Insufficient history for INST-B (only 1 year)
        db.add(
            HistoricalIntake(
                institution_id="INST-B",
                institution_name="Beta Institute",
                programme_id="PROG-MECH",
                programme_name="Mechanical",
                academic_year="2025-2026",
                admitted_count=50,
                approved_intake=60,
                is_anomaly=False,
                ground_truth="NORMAL",
            )
        )

        # 3. Deterministic rule alert for contrast
        db.add(
            Alert(
                id="ALT-PH4-001",
                student_ref="STU-PH4-OVERLAP",
                apaar_id="1111-2222-3333",
                alert_type="TEMPORAL_OVERLAP_CONFLICT",
                severity="HIGH",
                status="OPEN",
                title="Overlapping Enrolment",
                explanation="Student enrolled concurrently in two institutions.",
                supporting_record_ids=[101, 102],
            )
        )

        # 4. Deterministic identity flagged student
        db.add(
            Student(
                student_ref="STU-PH4-FLAGGED",
                apaar_id=None,
                full_name="Flagged Student",
                primary_institution_id="INST-A",
                identity_status="IDENTITY_FLAGGED",
            )
        )

        db.commit()
        yield sessions
    engine.dispose()


def test_insufficient_history_handled_explicitly(phase4_db):
    with phase4_db() as db:
        svc = HistoricalAnomalyService(db)
        # Empty institution
        empty_res = svc.get_historical_trends("INST-NONEXISTENT", "PROG-CS")
        assert empty_res["insufficient_history"] is True
        assert empty_res["baseline_sample_size"] == 0
        assert "No historical intake records found" in empty_res["message"]

        # 1-year institution
        single_res = svc.get_historical_trends("INST-B", "PROG-MECH")
        assert single_res["insufficient_history"] is True
        assert single_res["baseline_sample_size"] == 1
        assert "At least 3 historical cohort years are required" in single_res["insufficient_reason"]

        # Sufficient history institution
        full_res = svc.get_historical_trends("INST-A", "PROG-CS")
        assert full_res["insufficient_history"] is False
        assert full_res["insufficient_reason"] is None
        assert full_res["baseline_sample_size"] == 4
        assert full_res["baseline_mean"] == 100.5
        assert full_res["baseline_median"] == 101.0
        assert full_res["current_reported_enrolment"] == 220


def test_explainable_findings_separates_statistical_from_deterministic(phase4_db):
    with phase4_db() as db:
        svc = HistoricalAnomalyService(db)
        result = svc.get_explainable_findings()

        assert result["total_findings"] >= 3
        assert result["statistical_anomalies_count"] >= 1
        assert result["deterministic_rule_count"] >= 2

        # Verify statistical finding
        stat_finding = next(f for f in result["findings"] if f["is_statistical_anomaly"])
        assert stat_finding["finding_type"] == "HISTORICAL_DEVIATION"
        assert stat_finding["rule_or_model_id"] == "STAT-ZSCORE-V1"
        assert stat_finding["observed_value"] == 220
        assert "z_score" in stat_finding["evidence"]

        # Verify deterministic finding
        det_finding = next(f for f in result["findings"] if not f["is_statistical_anomaly"])
        assert det_finding["finding_type"] in {"TEMPORAL_CONFLICT", "IDENTITY_INCONSISTENCY"}
        assert det_finding["rule_or_model_id"].startswith("RULE-")


def test_explainable_findings_api_endpoint_filters(phase4_db):
    def override_get_db():
        with phase4_db() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            # All findings
            resp = client.get("/api/v1/analytics/findings")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_findings"] >= 3

            # Filter by is_statistical=true
            stat_resp = client.get("/api/v1/analytics/findings?is_statistical=true")
            assert stat_resp.status_code == 200
            stat_data = stat_resp.json()
            assert all(f["is_statistical_anomaly"] is True for f in stat_data["findings"])

            # Filter by is_statistical=false
            det_resp = client.get("/api/v1/analytics/findings?is_statistical=false")
            assert det_resp.status_code == 200
            det_data = det_resp.json()
            assert all(f["is_statistical_anomaly"] is False for f in det_data["findings"])

            # Filter by institution_id
            inst_resp = client.get("/api/v1/analytics/findings?institution_id=INST-A")
            assert inst_resp.status_code == 200
            for f in inst_resp.json()["findings"]:
                if f["institution_id"]:
                    assert f["institution_id"] == "INST-A"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_anomaly_dismissal_requires_substantive_justification(phase4_db):
    def override_get_db():
        with phase4_db() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with phase4_db() as db:
            anom = db.query(HistoricalIntake).filter(HistoricalIntake.is_anomaly == True).first()
            anom_id = anom.id

        with TestClient(app) as client:
            # 1. Empty reason rejected with 422
            rej1 = client.patch(f"/api/v1/analytics/anomalies/{anom_id}/dismiss", json={"reason": ""})
            assert rej1.status_code == 422
            assert "substantive justification" in rej1.json()["detail"].lower()

            # 2. Short reason (< 5 chars) rejected with 422
            rej2 = client.patch(f"/api/v1/analytics/anomalies/{anom_id}/dismiss", json={"reason": "bad"})
            assert rej2.status_code == 422

            # 3. Nonexistent anomaly ID returns 404
            rej3 = client.patch("/api/v1/analytics/anomalies/999999/dismiss", json={"reason": "Valid reason explanation"})
            assert rej3.status_code == 404

            # 4. Valid dismissal persists and creates audit log
            succ = client.patch(
                f"/api/v1/analytics/anomalies/{anom_id}/dismiss",
                json={"reason": "Approved supernumerary expansion under AICTE PM-USHA scheme.", "dismissed_by": "Director-RO"}
            )
            assert succ.status_code == 200
            assert succ.json()["dismissed"] is True

        with phase4_db() as db:
            updated = db.query(HistoricalIntake).filter(HistoricalIntake.id == anom_id).first()
            assert updated.dismissed is True
            assert updated.dismissal_reason == "Approved supernumerary expansion under AICTE PM-USHA scheme."

            audit = db.query(AuditLog).filter(
                AuditLog.entity_type == "ANOMALY",
                AuditLog.entity_id == str(anom_id)
            ).first()
            assert audit is not None
            assert audit.action == "DISMISS_ANOMALY"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_anomaly_dismissal_role_and_institution_scoping(phase4_db):
    def override_get_db():
        with phase4_db() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with phase4_db() as db:
            anom = db.query(HistoricalIntake).filter(HistoricalIntake.is_anomaly == True).first()
            anom_id = anom.id

        # 1. Read-only auditor is rejected
        def auditor_principal():
            return Principal(subject="auditor-1", role="read_only_auditor")

        app.dependency_overrides[get_current_principal] = auditor_principal
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/analytics/anomalies/{anom_id}/dismiss",
                json={"reason": "Attempting unauthorized auditor dismissal"}
            )
            assert resp.status_code == 403

        # 2. External verifier is rejected
        def verifier_principal():
            return Principal(subject="verifier-1", role="external_verifier", verifier_org_id="ORG-TCS")

        app.dependency_overrides[get_current_principal] = verifier_principal
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/analytics/anomalies/{anom_id}/dismiss",
                json={"reason": "Attempting unauthorized verifier dismissal"}
            )
            assert resp.status_code == 403

        # 3. Institution officer of OTHER institution is rejected
        def other_inst_principal():
            return Principal(subject="officer-b", role="institution_officer", institution_id="INST-OTHER")

        app.dependency_overrides[get_current_principal] = other_inst_principal
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/analytics/anomalies/{anom_id}/dismiss",
                json={"reason": "Officer from wrong institution trying to dismiss"}
            )
            assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_principal, None)
