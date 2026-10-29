import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.services.audit_service import AuditService

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()

def test_alert_review_decision_persistence(test_db):
    alert = Alert(
        id="ALT-TEST-001",
        student_ref="STU-REV-01",
        apaar_id="9999-REV-01",
        alert_type="TEMPORAL_OVERLAP_CONFLICT",
        severity="HIGH",
        status="OPEN",
        title="Test Overlap Alert",
        explanation="Test explanation"
    )
    test_db.add(alert)
    test_db.commit()

    # Simulate reviewer taking decision
    alert.reviewer_decision = "EXCEPTION_ACCEPTED"
    alert.reviewer_note = "Valid state transfer decree verified by administrative committee."
    alert.reviewed_by = "Officer-Test-42"
    alert.reviewed_at = datetime.utcnow()
    alert.status = "RESOLVED"
    test_db.commit()

    # Audit log
    AuditService.log_event(
        test_db, "ALERT", alert.id, "REVIEW_DECISION", alert.reviewed_by,
        {"decision": alert.reviewer_decision, "note": alert.reviewer_note}
    )

    # Reload from fresh query
    persisted = test_db.query(Alert).filter(Alert.id == "ALT-TEST-001").first()
    assert persisted.status == "RESOLVED"
    assert persisted.reviewer_decision == "EXCEPTION_ACCEPTED"
    assert persisted.reviewed_by == "Officer-Test-42"

    audit_entry = test_db.query(AuditLog).filter(AuditLog.entity_id == "ALT-TEST-001").first()
    assert audit_entry is not None
    assert audit_entry.action == "REVIEW_DECISION"
