import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.certificate import Certificate
from app.services.certificate_service import CertificateService

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()

def test_cryptographic_certificate_verification(test_db):
    payload = {
        "certificate_id": "CERT-TEST-001",
        "student_ref": "STU-CERT-01",
        "apaar_id": "9999-CERT-01",
        "student_name": "Test Student",
        "programme_name": "B.Tech CSE"
    }
    signature = CertificateService.compute_signature(payload)

    cert = Certificate(
        certificate_id="CERT-TEST-001",
        student_ref="STU-CERT-01",
        apaar_id="9999-CERT-01",
        student_name="Test Student",
        institution_id="INST-TEST",
        institution_name="Test Institute",
        programme_id="CSE",
        programme_name="B.Tech CSE",
        issue_date="2026-06-01",
        completion_date="2026-05-31",
        status="VALID",
        signature_algorithm="HMAC-SHA256",
        signature_hex=signature,
        public_key_id="SENTINEL-TEST-KEY",
        payload_json=payload
    )
    test_db.add(cert)
    test_db.commit()

    # 1. Authentic verification check
    res_valid = CertificateService.verify_certificate(test_db, "CERT-TEST-001")
    assert res_valid["is_authentic"] is True
    assert res_valid["verification_status"] == "VALID"
    assert res_valid["signature_valid"] is True

    # 2. Tampered payload check (modifying student name)
    tampered_payload = dict(payload)
    tampered_payload["student_name"] = "Impostor Name"
    res_tampered = CertificateService.verify_certificate(test_db, "CERT-TEST-001", tampered_payload=tampered_payload)
    assert res_tampered["is_authentic"] is False
    assert res_tampered["verification_status"] == "TAMPER_DETECTED"
    assert res_tampered["signature_valid"] is False

    # 3. Revoked certificate check
    cert.status = "REVOKED"
    cert.revocation_reason = "Administrative disciplinary cancellation"
    test_db.commit()

    res_revoked = CertificateService.verify_certificate(test_db, "CERT-TEST-001")
    assert res_revoked["is_authentic"] is False
    assert res_revoked["verification_status"] == "REVOKED"
    assert res_revoked["signature_valid"] is True  # Signature valid mathematically, but status is revoked
