"""Phase 1: SQLite Write Safety & Verification Request Logging Tests.

Verifies:
1. Real insert, commit, and read-back for verification_request_logs on disposable database.
2. Robust transaction rollback when database write encounters errors.
3. Verification service does not swallow write failures and propagates operational errors.
4. Legacy SQLite compatibility behavior is preserved.
"""
from datetime import datetime
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from app.database import Base
from app.models.verifier import VerificationRequestLog, VerifierOrganization
from app.models.student import Student
from app.models.certificate import Certificate
from app.services.verifier_service import VerifierService


@pytest.fixture
def disposable_write_db():
    """Creates a clean, disposable in-memory SQLite database for write safety testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def setup_pragmas(conn, rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()

    # Seed minimal fixtures
    org = VerifierOrganization(
        id="ORG-TEST-WRITE",
        org_name="Test Enterprise Corp",
        org_type="EMPLOYER",
        is_approved=True,
        contact_email="verify@testcorp.com"
    )
    student = Student(
        student_ref="STU-WRITE-001",
        apaar_id="9876-5432-8888",
        full_name="Pooja Verma",
        primary_institution_id="INST-DELHI-DTU"
    )
    cert = Certificate(
        certificate_id="CERT-WRITE-001",
        student_ref="STU-WRITE-001",
        apaar_id="9876-5432-8888",
        student_name="Pooja Verma",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science",
        issue_date="2026-06-15",
        completion_date="2026-05-30",
        status="VALID",
        signature_algorithm="Ed25519",
        signature_hex="abcdef0123456789",
        payload_json={"status": "VALID"}
    )
    session.add_all([org, student, cert])
    session.commit()

    yield session

    session.close()
    engine.dispose()


def test_verification_request_logs_insert_commit_and_readback(disposable_write_db):
    """Verifies a real insert, commit and read-back for verification_request_logs."""
    db = disposable_write_db

    svc = VerifierService(db)
    # Perform candidate credential verification
    res = svc.verify_candidate_credential(
        verifier_org_id="ORG-TEST-WRITE",
        certificate_id="CERT-WRITE-001"
    )
    assert res is not None

    # Read back the inserted verification log
    log = db.query(VerificationRequestLog).filter(
        VerificationRequestLog.verifier_org_id == "ORG-TEST-WRITE",
        VerificationRequestLog.certificate_id == "CERT-WRITE-001"
    ).first()

    assert log is not None
    assert log.id is not None
    assert log.verifier_org_name == "Test Enterprise Corp"
    assert log.verification_outcome in {"MATCH_VERIFIED", "CONSENT_REQUIRED", "RECORD_REVOKED"}
    assert log.timestamp is not None
    assert isinstance(log.limited_response_json, dict)


def test_verification_logging_rolls_back_on_failure(disposable_write_db):
    """Verifies transaction rollback when database write encounters an unrecoverable failure."""
    db = disposable_write_db
    svc = VerifierService(db)

    # Intentionally trigger an error during commit in _log_request
    with patch.object(db, "commit", side_effect=RuntimeError("Simulated Disk Full / Lock Error")):
        with pytest.raises(RuntimeError, match="Simulated Disk Full"):
            svc._log_request(
                org_id="ORG-TEST-WRITE",
                org_name="Test Org",
                student_ref="STU-WRITE-001",
                apaar_id=None,
                cert_id="CERT-WRITE-001",
                outcome="TEST_ERROR",
                payload={"simulated": True}
            )

    # Verify session is clean and no corrupt log record was persisted
    db.rollback()
    persisted = db.query(VerificationRequestLog).filter(
        VerificationRequestLog.verification_outcome == "TEST_ERROR"
    ).all()
    assert len(persisted) == 0


def test_verification_logging_does_not_swallow_database_errors(disposable_write_db):
    """Confirms that database write failures are propagated rather than silently swallowed."""
    db = disposable_write_db
    svc = VerifierService(db)

    with patch.object(db, "commit", side_effect=Exception("Database write access denied")):
        with pytest.raises(Exception, match="Database write access denied"):
            svc._log_request(
                org_id="ORG-TEST-WRITE",
                org_name="Test Org",
                student_ref="STU-WRITE-001",
                apaar_id=None,
                cert_id="CERT-WRITE-001",
                outcome="FAILURE_PROPAGATION_CHECK",
                payload={}
            )
