import hashlib
from datetime import date
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.alert import Alert
from app.models.enrolment import Enrolment
from app.models.import_job import ImportJob, ImportRowResult
from app.models.review_event import AlertReviewEvent
from app.models.student import Student
from app.models.verifier import VerifierOrganization, VerificationRequestLog
from app.services.verifier_service import VerifierService


@pytest.fixture
def phase1_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        db.add_all([
            Student(student_ref="STU-SCOPE-A", apaar_id="1234-5678-0001", full_name="Scope A", primary_institution_id="INST-A"),
            Student(student_ref="STU-SCOPE-B", apaar_id="1234-5678-0002", full_name="Scope B", primary_institution_id="INST-B"),
            VerifierOrganization(id="ORG-A", org_name="Verifier A", org_type="EMPLOYER", is_approved=True, contact_email="a@example.invalid"),
        ])
        db.flush()
        db.add_all([
            Enrolment(
                student_ref="STU-SCOPE-A", apaar_id="1234-5678-0001", institution_id="INST-A",
                programme_id="PROG-A", academic_year="2025-2026", admission_cycle="Regular",
                enrolment_start=date(2025, 8, 1), enrolment_status="Active",
            ),
            Enrolment(
                student_ref="STU-SCOPE-B", apaar_id="1234-5678-0002", institution_id="INST-B",
                programme_id="PROG-B", academic_year="2025-2026", admission_cycle="Regular",
                enrolment_start=date(2025, 8, 1), enrolment_status="Active",
            ),
        ])
        db.flush()
        enrolment_a = db.query(Enrolment).filter(Enrolment.student_ref == "STU-SCOPE-A").one()
        db.add(Alert(
            id="ALT-SCOPE-A",
            student_ref="STU-SCOPE-A",
            apaar_id="1234-5678-0001",
            alert_type="TEMPORAL_OVERLAP_CONFLICT",
            severity="MEDIUM",
            status="OPEN",
            title="Review test alert",
            explanation="Synthetic test finding.",
            evidence_summary={"identity_evidence": "Matched APAAR ID 1234-5678-0001"},
            supporting_record_ids=[enrolment_a.id],
        ))
        db.commit()

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    previous_auth_required = settings.AUTH_REQUIRED
    previous_token_principals = settings.API_TOKEN_PRINCIPALS
    app.dependency_overrides[get_db] = override_get_db
    settings.AUTH_REQUIRED = True
    settings.API_TOKEN_PRINCIPALS = {}
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        settings.AUTH_REQUIRED = previous_auth_required
        settings.API_TOKEN_PRINCIPALS = previous_token_principals
        engine.dispose()


def set_principal(
    role: str,
    *,
    subject: str,
    institution_id: str | None = None,
    verifier_org_id: str | None = None,
    purpose_scope: str | None = None,
):
    token = f"phase1-{role}-token"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    settings.API_TOKEN_PRINCIPALS = {
        token_hash: {
            "subject": subject,
            "role": role,
            **({"institution_id": institution_id} if institution_id else {}),
            **({"verifier_org_id": verifier_org_id} if verifier_org_id else {}),
            **({"purpose_scope": purpose_scope} if purpose_scope else {}),
        }
    }
    return {"Authorization": f"Bearer {token}"}


def test_auth_required_rejects_missing_and_invalid_tokens_but_health_is_public(phase1_client):
    client, _ = phase1_client

    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/students").status_code == 401
    assert client.get("/api/v1/students", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_external_verifier_role_cannot_read_student_api(phase1_client):
    client, _ = phase1_client
    headers = set_principal(
        "external_verifier", subject="verifier-a", verifier_org_id="ORG-A",
        purpose_scope="EMPLOYMENT_VERIFICATION",
    )

    response = client.get("/api/v1/students", headers=headers)

    assert response.status_code == 403


def test_auditor_does_not_receive_raw_legacy_identity_evidence(phase1_client):
    client, _ = phase1_client
    headers = set_principal("read_only_auditor", subject="auditor-identity")

    response = client.get("/api/v1/alerts", headers=headers)

    assert response.status_code == 200
    serialized = response.text
    assert "1234-5678-0001" not in serialized
    assert "[redacted]" in serialized


def test_institution_officer_is_scoped_and_identifier_is_masked(phase1_client):
    client, _ = phase1_client
    headers = set_principal("institution_officer", subject="operator-a", institution_id="INST-A")

    visible = client.get("/api/v1/students", headers=headers)
    cross_query = client.get("/api/v1/students?institution_id=INST-B", headers=headers)
    cross_detail = client.get("/api/v1/students/STU-SCOPE-B", headers=headers)
    own_detail = client.get("/api/v1/students/STU-SCOPE-A", headers=headers)
    own_dashboard = client.get("/api/v1/institution/dashboard-summary", headers=headers)

    assert visible.status_code == 200
    assert [item["student_ref"] for item in visible.json()["items"]] == ["STU-SCOPE-A"]
    assert visible.json()["items"][0]["apaar_id"].endswith("0001")
    assert visible.json()["items"][0]["apaar_id"] != "1234-5678-0001"
    assert cross_query.status_code == 403
    assert cross_detail.status_code == 404
    assert own_detail.status_code == 200
    assert own_detail.json()["student"]["apaar_id"] != "1234-5678-0001"
    assert own_detail.json()["student"]["passport_ref"] is None
    assert own_dashboard.status_code == 200
    assert own_dashboard.json()["institution_id"] == "INST-A"


def test_external_verifier_cannot_spoof_organization_identity(phase1_client):
    client, _ = phase1_client
    unscoped_headers = set_principal("external_verifier", subject="unscoped", verifier_org_id="ORG-A")
    unscoped = client.post(
        "/api/v1/verifier/verify-credential",
        headers=unscoped_headers,
        json={"verifier_org_id": "ORG-A", "student_ref": "STU-SCOPE-A"},
    )
    assert unscoped.status_code == 403

    headers = set_principal(
        "external_verifier", subject="verifier-a", verifier_org_id="ORG-A",
        purpose_scope="EMPLOYMENT_VERIFICATION",
    )

    response = client.post(
        "/api/v1/verifier/verify-credential",
        headers=headers,
        json={"verifier_org_id": "ORG-OTHER", "student_ref": "STU-SCOPE-A"},
    )

    assert response.status_code == 403
    authorized = client.post(
        "/api/v1/verifier/verify-credential",
        headers=headers,
        json={"verifier_org_id": "ORG-A", "student_ref": "STU-SCOPE-A"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["outcome"] == "CONSENT_REQUIRED"


def test_reviewer_actor_comes_from_authenticated_principal(phase1_client):
    client, sessions = phase1_client
    headers = set_principal("reviewer", subject="reviewer-42")

    response = client.patch(
        "/api/v1/alerts/ALT-SCOPE-A/review",
        headers=headers,
        json={
            "decision": "NOT_A_CONFLICT",
            "note": "Review completed.",
            "reviewed_by": "spoofed-reviewer",
        },
    )

    assert response.status_code == 200
    assert response.json()["reviewed_by"] == "reviewer-42"
    reevaluate = client.post("/api/v1/alerts/re-evaluate", headers=headers)
    assert reevaluate.status_code == 403
    with sessions() as db:
        event = db.query(AlertReviewEvent).filter(AlertReviewEvent.alert_id == "ALT-SCOPE-A").one()
        assert event.actor == "reviewer-42"


def test_auditor_is_read_only_and_empty_required_registry_fails_startup(phase1_client):
    client, _ = phase1_client
    headers = set_principal("read_only_auditor", subject="auditor-1")
    denied = client.post("/api/v1/students", headers=headers, json={})
    assert denied.status_code == 403

    environment = os.environ.copy()
    environment["AUTH_REQUIRED"] = "true"
    environment["API_TOKEN_PRINCIPALS_JSON"] = "{}"
    environment["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-c", "import app.security"], cwd=backend_dir, env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "no API token principals are configured" in result.stderr


def test_authenticated_student_detail_does_not_recalculate_integrity(phase1_client, monkeypatch):
    client, _ = phase1_client

    def unexpected_recalculation(*args, **kwargs):
        raise AssertionError("Authenticated GET must not recompute/persist integrity findings.")

    monkeypatch.setattr(
        "app.routers.students.TemporalIntegrityEngine.evaluate_student",
        unexpected_recalculation,
    )
    headers = set_principal("reviewer", subject="reviewer-read")

    response = client.get("/api/v1/students/STU-SCOPE-A", headers=headers)

    assert response.status_code == 200
    assert "did not recalculate integrity" in response.json()["integrity_summary"]


def test_import_history_is_institution_scoped_and_paginates(phase1_client):
    client, sessions = phase1_client
    with sessions() as db:
        db.add_all([
            ImportJob(
                id="IMPORT-INST-A", institution_id="INST-A", submitted_by="operator-a",
                original_filename="a.csv", status="COMPLETED", total_rows=1,
                accepted_rows=1, rejected_rows=0, review_rows=0, validation_summary={},
            ),
            ImportJob(
                id="IMPORT-INST-B", institution_id="INST-B", submitted_by="operator-b",
                original_filename="b.csv", status="COMPLETED", total_rows=1,
                accepted_rows=1, rejected_rows=0, review_rows=0, validation_summary={},
            ),
        ])
        db.flush()
        db.add(ImportRowResult(
            import_job_id="IMPORT-INST-A", row_number=1, record_reference="STU-SCOPE-A",
            identity_hash="c" * 64, outcome="ACCEPTED", persisted=True,
            issue_codes=[], validation_messages=[],
        ))
        db.commit()

    headers = set_principal("institution_officer", subject="operator-a", institution_id="INST-A")
    listing = client.get("/api/v1/students/import-jobs?page=1&limit=1", headers=headers)
    own_rows = client.get("/api/v1/students/import-jobs/IMPORT-INST-A/rows", headers=headers)
    other_job = client.get("/api/v1/students/import-jobs/IMPORT-INST-B", headers=headers)
    invalid_status = client.get("/api/v1/students/import-jobs?status=BOGUS", headers=headers)

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["import_job_id"] == "IMPORT-INST-A"
    assert own_rows.status_code == 200
    assert own_rows.json()["items"][0]["record_reference"] == "STU-SCOPE-A"
    assert other_job.status_code == 404
    assert invalid_status.status_code == 422


def test_verification_fails_closed_without_current_purpose_consent(phase1_client):
    _, sessions = phase1_client
    with sessions() as db:
        result = VerifierService(db).verify_candidate_credential(
            verifier_org_id="ORG-A",
            student_ref="STU-SCOPE-A",
        )
        log = db.query(VerificationRequestLog).order_by(VerificationRequestLog.id.desc()).first()

    assert result["verified"] is False
    assert result["outcome"] == "CONSENT_REQUIRED"
    assert log is not None
    assert log.query_apaar_id is None