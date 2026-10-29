import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.review_event import AlertReviewEvent


@pytest.fixture
def review_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        db.add(Alert(
            id="ALT-CASE-001",
            student_ref="STU-CASE-001",
            apaar_id="MASKED-CASE-001",
            alert_type="TEMPORAL_OVERLAP_CONFLICT",
            severity="HIGH",
            status="OPEN",
            title="Potential timeline overlap",
            explanation="Two active periods overlap.",
            evidence_summary={"rule_id": "TEMPORAL-OVERLAP-001"},
        ))
        db.commit()

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()


def test_case_actions_persist_history_and_require_explicit_reopening(review_client):
    client, sessions = review_client
    alert_path = "/api/v1/alerts/ALT-CASE-001"

    assignment = client.patch(
        f"{alert_path}/assignment",
        json={"assigned_to": "Reviewer 17", "actor": "Supervisor 2"},
    )
    assert assignment.status_code == 200

    clarification = client.post(
        f"{alert_path}/clarification",
        json={
            "note": "Please provide the institution transfer letter.",
            "actor": "Reviewer 17",
            "evidence_references": ["DOC-REF-77"],
        },
    )
    assert clarification.status_code == 200
    assert clarification.json()["status"] == "AWAITING_CLARIFICATION"

    resolution = client.patch(
        f"{alert_path}/review",
        json={
            "decision": "CONFIRMED_CONFLICT",
            "note": "Both source records confirm concurrent active status.",
            "reviewed_by": "Reviewer 17",
            "resolution_reason": "The institution confirmed the overlapping periods.",
            "evidence_references": ["CASE-ATTACH-9"],
        },
    )
    assert resolution.status_code == 200
    assert resolution.json()["status"] == "RESOLVED"

    invalid_repeat = client.patch(
        f"{alert_path}/review",
        json={"decision": "NOT_A_CONFLICT", "note": "Attempt without reopening."},
    )
    assert invalid_repeat.status_code == 409

    reopened = client.post(
        f"{alert_path}/reopen",
        json={"reason": "New institution evidence was received.", "actor": "Supervisor 2"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "UNDER_REVIEW"

    history = client.get(f"{alert_path}/history")
    assert history.status_code == 200
    events = history.json()["events"]
    assert [event["action"] for event in events] == [
        "ASSIGNED", "CLARIFICATION_REQUESTED", "REVIEW_DECISION", "REOPENED"
    ]
    assert events[1]["evidence_references"] == ["DOC-REF-77"]
    assert events[2]["resolution_reason"] == "The institution confirmed the overlapping periods."
    assert history.json()["assigned_to"] == "Reviewer 17"

    with sessions() as db:
        assert db.query(AlertReviewEvent).count() == 4
        assert db.query(AuditLog).filter(AuditLog.entity_id == "ALT-CASE-001").count() == 4


def test_invalid_decision_is_rejected_by_schema(review_client):
    client, _ = review_client
    response = client.patch(
        "/api/v1/alerts/ALT-CASE-001/review",
        json={"decision": "MARK_FRAUD", "note": "Not an allowed decision."},
    )

    assert response.status_code == 422