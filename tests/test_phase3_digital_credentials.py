import hashlib
from datetime import date
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.main import app
from app.models.certificate import Certificate
from app.models.enrolment import Enrolment
from app.models.student import Student
from app.services.certificate_service import (
    CertificateService,
    ACTIVE_KEY_ID,
    LEGACY_HMAC_KEY_ID,
    TEST_HMAC_KEY_ID,
)


def register_token(role: str, subject: str, institution_id=None, verifier_org_id=None, purpose_scope=None) -> str:
    token = f"phase3-{role}-{subject}-token"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    settings.API_TOKEN_PRINCIPALS[token_hash] = {
        "subject": subject,
        "role": role,
        **({"institution_id": institution_id} if institution_id else {}),
        **({"verifier_org_id": verifier_org_id} if verifier_org_id else {}),
        **({"purpose_scope": purpose_scope} if purpose_scope else {}),
    }
    return token


@pytest.fixture
def phase3_env(db_sessions, monkeypatch):
    prev_auth = settings.AUTH_REQUIRED
    prev_tokens = dict(settings.API_TOKEN_PRINCIPALS)
    settings.AUTH_REQUIRED = True

    admin_token = register_token("administrator", "admin-p3")
    officer_dtu_token = register_token("institution_officer", "officer-dtu", institution_id="INST-DELHI-DTU")
    officer_other_token = register_token("institution_officer", "officer-other", institution_id="INST-OTHER-UNIV")
    auditor_token = register_token("read_only_auditor", "auditor-p3")
    verifier_token = register_token(
        "external_verifier",
        "verifier-p3",
        verifier_org_id="ORG-TCS-BGV",
        purpose_scope="EMPLOYMENT_VERIFICATION",
    )

    with db_sessions() as db:
        s1 = Student(
            student_ref="STU-P3-001",
            apaar_id="9999-1111-2222",
            full_name="Pooja Patel",
            primary_institution_id="INST-DELHI-DTU",
            nationality="Indian",
        )
        db.add(s1)
        db.flush()

        e1 = Enrolment(
            student_ref="STU-P3-001",
            apaar_id="9999-1111-2222",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University (Demo)",
            programme_id="BTECH-CSE",
            programme_name="Computer Science & Engineering",
            academic_year="2022-2026",
            admission_cycle="REGULAR_AUTUMN",
            seat_category="OPEN",
            enrolment_start=date(2022, 8, 1),
            enrolment_status="Completed",
        )
        db.add(e1)
        db.commit()

    tokens = {
        "admin": admin_token,
        "officer_dtu": officer_dtu_token,
        "officer_other": officer_other_token,
        "auditor": auditor_token,
        "verifier": verifier_token,
    }

    yield tokens, db_sessions

    settings.AUTH_REQUIRED = prev_auth
    settings.API_TOKEN_PRINCIPALS = prev_tokens


def test_valid_certificate_ed25519(phase3_env):
    """Test issuing and verifying a valid asymmetric Ed25519 digital credential."""
    tokens, db_sessions = phase3_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    issue_payload = {
        "student_ref": "STU-P3-001",
        "student_name": "Pooja Patel",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University (Demo)",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-31",
        "apaar_id": "9999-1111-2222",
        "algorithm": "Ed25519",
    }
    resp = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers)
    assert resp.status_code == 201
    cert_id = resp.json()["certificate_id"]
    sig_hex = resp.json()["signature_hex"]
    assert resp.json()["signature_algorithm"] == "Ed25519"
    assert resp.json()["public_key_id"] == ACTIVE_KEY_ID

    # Verify endpoint
    v_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "VALID"
    assert v_data["is_authentic"] is True
    assert v_data["signature_valid"] is True
    assert v_data["status"] == "VALID"
    assert v_data["algorithm"] == "Ed25519"
    assert v_data["public_key_id"] == ACTIVE_KEY_ID

    # Public-key offline verification
    pubkey_resp = client.get(f"/api/v1/certificates/public-keys/{ACTIVE_KEY_ID}", headers=headers)
    pub_hex = pubkey_resp.json()["public_key_hex"]
    pubkey = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
    with db_sessions() as db:
        cert = db.query(Certificate).filter(Certificate.certificate_id == cert_id).first()
        canonical_bytes = CertificateService.canonical_json(cert.payload_json)
    pubkey.verify(bytes.fromhex(sig_hex), canonical_bytes)


def test_valid_certificate_legacy_hmac(phase3_env):
    """Test legacy HMAC-SHA256 credentials remain verifiable with symmetric MAC."""
    tokens, db_sessions = phase3_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    issue_payload = {
        "student_ref": "STU-P3-001",
        "student_name": "Pooja Patel",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University (Demo)",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2025-06-15",
        "completion_date": "2025-05-31",
        "algorithm": "HMAC-SHA256",
    }
    resp = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers)
    assert resp.status_code == 201
    cert_id = resp.json()["certificate_id"]
    assert resp.json()["signature_algorithm"] == "HMAC-SHA256"
    assert resp.json()["public_key_id"] == LEGACY_HMAC_KEY_ID

    v_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "VALID"
    assert v_data["is_authentic"] is True
    assert v_data["signature_valid"] is True
    assert v_data["algorithm"] == "HMAC-SHA256"


def test_modified_payload_fails_verification(phase3_env):
    """Confirm that an altered payload fails cryptographic integrity verification."""
    tokens, db_sessions = phase3_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    # Issue an Ed25519 credential
    issue_payload = {
        "student_ref": "STU-P3-001",
        "student_name": "Pooja Patel",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University (Demo)",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-31",
        "algorithm": "Ed25519",
    }
    cert_id = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers).json()["certificate_id"]

    # Direct verification with tampered payload
    with db_sessions() as db:
        cert = db.query(Certificate).filter(Certificate.certificate_id == cert_id).first()
        tampered_payload = dict(cert.payload_json)
        tampered_payload["student_name"] = "Impostor Student"
        result = CertificateService.verify_certificate(db, cert_id, tampered_payload=tampered_payload)

    assert result["verification_status"] == "TAMPER_DETECTED"
    assert result["is_authentic"] is False
    assert result["signature_valid"] is False
    assert "MISMATCH" in result["message"]


def test_invalid_signature_hex(phase3_env):
    """Confirm that a corrupted signature fails verification."""
    _, db_sessions = phase3_env

    with db_sessions() as db:
        # Create a certificate with arbitrary bad signature
        cert = Certificate(
            certificate_id="CERT-BAD-SIG-001",
            student_ref="STU-P3-001",
            apaar_id="9999-1111-2222",
            student_name="Pooja Patel",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University (Demo)",
            programme_id="BTECH-CSE",
            programme_name="Computer Science & Engineering",
            issue_date="2026-06-15",
            completion_date="2026-05-31",
            status="VALID",
            signature_algorithm="Ed25519",
            signature_hex="deadbeef" * 16,  # Valid length hex, completely bogus signature
            public_key_id=ACTIVE_KEY_ID,
            payload_json={"certificate_id": "CERT-BAD-SIG-001", "student_name": "Pooja Patel"},
        )
        db.add(cert)
        db.commit()

        result = CertificateService.verify_certificate(db, "CERT-BAD-SIG-001")
        assert result["verification_status"] == "TAMPER_DETECTED"
        assert result["is_authentic"] is False
        assert result["signature_valid"] is False


def test_untrusted_key_id(phase3_env):
    """Confirm that certificates signed with unknown or untrusted key IDs are rejected."""
    _, db_sessions = phase3_env

    with db_sessions() as db:
        cert = Certificate(
            certificate_id="CERT-ROGUE-KEY-001",
            student_ref="STU-P3-001",
            apaar_id="9999-1111-2222",
            student_name="Pooja Patel",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University (Demo)",
            programme_id="BTECH-CSE",
            programme_name="Computer Science & Engineering",
            issue_date="2026-06-15",
            completion_date="2026-05-31",
            status="VALID",
            signature_algorithm="Ed25519",
            signature_hex="abcdef0123456789" * 8,
            public_key_id="ATTACKER-ROGUE-KEY-2026",
            payload_json={"certificate_id": "CERT-ROGUE-KEY-001"},
        )
        db.add(cert)
        db.commit()

        result = CertificateService.verify_certificate(db, "CERT-ROGUE-KEY-001")
        assert result["verification_status"] == "UNTRUSTED_KEY"
        assert result["is_authentic"] is False
        assert result["signature_valid"] is False


def test_revoked_certificate_distinguishable_from_tampered(phase3_env):
    """
    Confirm that revoked certificates remain distinguishable from tampered certificates:
    - Untampered revoked: signature_valid=True, is_authentic=False, verification_status="REVOKED"
    - Tampered revoked: signature_valid=False, is_authentic=False, verification_status="TAMPER_DETECTED"
    """
    tokens, db_sessions = phase3_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    # Issue and revoke a credential
    issue_payload = {
        "student_ref": "STU-P3-001",
        "student_name": "Pooja Patel",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University (Demo)",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-31",
        "algorithm": "Ed25519",
    }
    cert_id = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers).json()["certificate_id"]

    revoke_resp = client.post(
        f"/api/v1/certificates/{cert_id}/revoke",
        json={"reason": "Degree canceled due to concurrent duplicate regular seat."},
        headers=headers,
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "REVOKED"

    # Untampered revoked credential verification
    v_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "REVOKED"
    assert v_data["status"] == "REVOKED"
    assert v_data["is_authentic"] is False
    assert v_data["signature_valid"] is True  # Mathematically intact!
    assert "revocation_reason" in v_data

    # Now tamper the revoked credential payload
    with db_sessions() as db:
        cert = db.query(Certificate).filter(Certificate.certificate_id == cert_id).first()
        tampered_payload = dict(cert.payload_json)
        tampered_payload["programme_name"] = "Forged M.Tech CSE"
        t_res = CertificateService.verify_certificate(db, cert_id, tampered_payload=tampered_payload)

    # Tampered revoked credential must report TAMPER_DETECTED, not REVOKED
    assert t_res["verification_status"] == "TAMPER_DETECTED"
    assert t_res["is_authentic"] is False
    assert t_res["signature_valid"] is False


def test_unknown_certificate(phase3_env):
    """Test verification and retrieval for non-existent certificate IDs."""
    tokens, db_sessions = phase3_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    # Direct retrieval returns 404
    get_resp = client.get("/api/v1/certificates/CERT-NONEXISTENT-999", headers=headers)
    assert get_resp.status_code == 404

    # Verify endpoint returns NOT_FOUND status
    v_resp = client.get("/api/v1/certificates/CERT-NONEXISTENT-999/verify", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "NOT_FOUND"
    assert v_data["is_authentic"] is False
    assert v_data["signature_valid"] is False


def test_unauthorized_verification_and_scoping(phase3_env):
    """Test authentication requirements, role authorization, and institution scoping."""
    tokens, _ = phase3_env
    client = TestClient(app)

    # Issue certificate for INST-DELHI-DTU
    issue_payload = {
        "student_ref": "STU-P3-001",
        "student_name": "Pooja Patel",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University (Demo)",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-31",
        "algorithm": "Ed25519",
    }
    cert_id = client.post(
        "/api/v1/certificates/issue",
        json=issue_payload,
        headers={"Authorization": f"Bearer {tokens['admin']}"},
    ).json()["certificate_id"]

    # 1. Missing authentication (when AUTH_REQUIRED=True)
    no_auth_resp = client.get(f"/api/v1/certificates/{cert_id}/verify")
    assert no_auth_resp.status_code == 401

    # 2. Invalid bearer token
    bad_token_resp = client.get(
        f"/api/v1/certificates/{cert_id}/verify",
        headers={"Authorization": "Bearer invalid-token-xyz"},
    )
    assert bad_token_resp.status_code == 401

    # 3. Institution officer of OTHER university cannot access or verify DTU certificate
    officer_other_headers = {"Authorization": f"Bearer {tokens['officer_other']}"}
    other_verify_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=officer_other_headers)
    assert other_verify_resp.status_code == 404

    other_tamper_resp = client.post(
        f"/api/v1/certificates/{cert_id}/simulate-tamper",
        json={"student_name": "Hacked"},
        headers=officer_other_headers,
    )
    # institution_officer is not permitted to execute tamper simulation operations
    assert other_tamper_resp.status_code == 403

    # 4. Read-only auditor or external verifier cannot run tamper simulation
    auditor_headers = {"Authorization": f"Bearer {tokens['auditor']}"}
    auditor_tamper_resp = client.post(
        f"/api/v1/certificates/{cert_id}/simulate-tamper",
        json={"student_name": "Hacked"},
        headers=auditor_headers,
    )
    assert auditor_tamper_resp.status_code == 403

    # 5. Non-admin roles (auditor) have apaar_id masked and signature_hex omitted
    auditor_verify_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=auditor_headers)
    assert auditor_verify_resp.status_code == 200
    v_data = auditor_verify_resp.json()
    assert v_data["signature_hex"] is None
    assert "9999-1111-2222" not in str(v_data.get("apaar_id"))


def test_tamper_test_does_not_damage_original_record(phase3_env):
    """
    CRITICAL SAFETY REQUIREMENT:
    Confirm that executing a tamper simulation operates against an isolated in-memory clone
    and does NOT modify or damage the stored original database record.
    """
    tokens, db_sessions = phase3_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    # Issue an active valid credential
    issue_payload = {
        "student_ref": "STU-P3-001",
        "student_name": "Pooja Patel",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University (Demo)",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-31",
        "algorithm": "Ed25519",
    }
    cert_id = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers).json()["certificate_id"]

    # 1. Snapshot database record state before test
    with db_sessions() as db:
        cert_before = db.query(Certificate).filter(Certificate.certificate_id == cert_id).first()
        payload_before = dict(cert_before.payload_json)
        sig_before = cert_before.signature_hex
        status_before = cert_before.status
        name_before = cert_before.student_name

    assert status_before == "VALID"
    assert name_before == "Pooja Patel"

    # 2. Execute tamper simulation altering student_name
    tamper_resp = client.post(
        f"/api/v1/certificates/{cert_id}/simulate-tamper",
        json={"student_name": "Adulterated Attacker Identity"},
        headers=headers,
    )
    assert tamper_resp.status_code == 200
    tamper_data = tamper_resp.json()
    assert tamper_data["database_mutated"] is False
    assert tamper_data["isolation_mode"] == "IN_MEMORY_DISPOSABLE_CLONE"
    assert tamper_data["verification_result"]["verification_status"] == "TAMPER_DETECTED"
    assert tamper_data["verification_result"]["is_authentic"] is False
    assert tamper_data["verification_result"]["signature_valid"] is False

    # 3. Verify that database record is 100% UNTOUCHED
    with db_sessions() as db:
        cert_after = db.query(Certificate).filter(Certificate.certificate_id == cert_id).first()
        assert cert_after.student_name == "Pooja Patel"
        assert cert_after.payload_json == payload_before
        assert cert_after.signature_hex == sig_before
        assert cert_after.status == "VALID"

        # Re-verify the certificate in the database — MUST BE FULLY VALID!
        reverify_res = CertificateService.verify_certificate(db, cert_id)
        assert reverify_res["verification_status"] == "VALID"
        assert reverify_res["is_authentic"] is True
        assert reverify_res["signature_valid"] is True
