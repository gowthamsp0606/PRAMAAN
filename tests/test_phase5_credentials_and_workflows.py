import hashlib
import pytest
from datetime import date
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.certificate import Certificate
from app.models.consent import StudentConsent
from app.models.enrolment import Enrolment
from app.models.student import Student
from app.models.verifier import VerifierOrganization
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.services.certificate_service import CertificateService, ACTIVE_KEY_ID, LEGACY_HMAC_KEY_ID


def register_token(role: str, subject: str, institution_id=None, verifier_org_id=None, purpose_scope=None) -> str:
    token = f"phase5-{role}-{subject}-token"
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
def phase5_env(db_sessions, monkeypatch):
    prev_auth = settings.AUTH_REQUIRED
    prev_tokens = dict(settings.API_TOKEN_PRINCIPALS)
    settings.AUTH_REQUIRED = True

    admin_token = register_token("administrator", "admin-01")
    officer1_token = register_token("institution_officer", "officer-inst1", institution_id="INST-IITB")
    officer2_token = register_token("institution_officer", "officer-inst2", institution_id="INST-NITK")
    auditor_token = register_token("read_only_auditor", "auditor-01")
    verifier_token = register_token("external_verifier", "verifier-01", verifier_org_id="ORG-TCS-BGV", purpose_scope="EMPLOYMENT_VERIFICATION")

    with db_sessions() as db:
        # Create Institutions & Students
        s1 = Student(
            student_ref="STU-PH5-001",
            apaar_id="111122223333",
            full_name="Ananya Sharma",
            primary_institution_id="INST-IITB",
            nationality="Indian",
        )
        s2 = Student(
            student_ref="STU-PH5-002",
            apaar_id="444455556666",
            full_name="Rahul Verma",
            primary_institution_id="INST-NITK",
            nationality="Indian",
        )
        db.add_all([s1, s2])
        db.flush()

        e1 = Enrolment(
            student_ref="STU-PH5-001",
            apaar_id="111122223333",
            institution_id="INST-IITB",
            institution_name="Indian Institute of Technology Bombay",
            programme_id="BTECH-CSE",
            programme_name="Computer Science & Engineering",
            academic_year="2022-2026",
            admission_cycle="REGULAR_AUTUMN",
            seat_category="OPEN",
            enrolment_start=date(2022, 8, 1),
            enrolment_status="Completed",
        )
        db.add(e1)
        db.flush()

        # Consents
        c1 = StudentConsent(
            student_ref="STU-PH5-001",
            apaar_id="111122223333",
            purpose="EMPLOYMENT_VERIFICATION",
            consent_granted=True,
            status="ACTIVE",
            data_scope="CONFERRED_DEGREE_ONLY",
        )
        c2 = StudentConsent(
            student_ref="STU-PH5-002",
            apaar_id="444455556666",
            purpose="EMPLOYMENT_VERIFICATION",
            consent_granted=False,
            status="WITHDRAWN",
            data_scope="CONFERRED_DEGREE_ONLY",
        )
        db.add_all([c1, c2])

        # Verifier Org
        org = VerifierOrganization(
            id="ORG-TCS-BGV",
            org_name="Tata Consultancy Services - Background Verification",
            org_type="CORPORATE_EMPLOYER",
            is_approved=True,
            contact_email="bgv@tcs-example.com",
        )
        db.add(org)

        # Alert
        alt = Alert(
            id="ALT-PH5-001",
            student_ref="STU-PH5-001",
            apaar_id="111122223333",
            alert_type="TEMPORAL_OVERLAP_CONFLICT",
            severity="HIGH",
            status="OPEN",
            title="Potential Concurrent Enrolment Flag",
            explanation="Concurrent enrolment observed across duplicate institute records.",
            supporting_record_ids=[e1.id],
        )
        db.add(alt)
        db.commit()

    tokens = {
        "admin": admin_token,
        "officer1": officer1_token,
        "officer2": officer2_token,
        "auditor": auditor_token,
        "verifier": verifier_token,
    }

    yield tokens, db_sessions

    settings.AUTH_REQUIRED = prev_auth
    settings.API_TOKEN_PRINCIPALS = prev_tokens


def test_ed25519_credential_issuance_and_asymmetric_verification(phase5_env):
    tokens, db_sessions = phase5_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    issue_payload = {
        "student_ref": "STU-PH5-001",
        "student_name": "Ananya Sharma",
        "institution_id": "INST-IITB",
        "institution_name": "Indian Institute of Technology Bombay",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-30",
        "apaar_id": "111122223333",
        "algorithm": "Ed25519",
    }
    resp = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["signature_algorithm"] == "Ed25519"
    assert data["public_key_id"] == ACTIVE_KEY_ID
    cert_id = data["certificate_id"]
    sig_hex = data["signature_hex"]
    assert sig_hex is not None and len(sig_hex) == 128  # 64 bytes Ed25519 hex

    # Verify directly via backend endpoint
    v_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "VALID"
    assert v_data["is_authentic"] is True
    assert v_data["signature_valid"] is True

    # Offline verification with public key from registry
    pubkey_resp = client.get(f"/api/v1/certificates/public-keys/{ACTIVE_KEY_ID}", headers=headers)
    assert pubkey_resp.status_code == 200
    pub_hex = pubkey_resp.json()["public_key_hex"]
    pubkey = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))

    with db_sessions() as db:
        cert = db.query(Certificate).filter(Certificate.certificate_id == cert_id).first()
        canonical_bytes = CertificateService.canonical_json(cert.payload_json)

    # Public key verify must succeed without throwing InvalidSignature
    pubkey.verify(bytes.fromhex(sig_hex), canonical_bytes)


def test_ed25519_tamper_detection(phase5_env):
    tokens, _ = phase5_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    issue_payload = {
        "student_ref": "STU-PH5-001",
        "student_name": "Ananya Sharma",
        "institution_id": "INST-IITB",
        "institution_name": "Indian Institute of Technology Bombay",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-30",
        "algorithm": "Ed25519",
    }
    cert_id = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers).json()["certificate_id"]

    # Alter payload (e.g., student name forged)
    tamper_resp = client.post(
        f"/api/v1/certificates/{cert_id}/simulate-tamper",
        json={"student_name": "Forged Attacker Name"},
        headers=headers,
    )
    assert tamper_resp.status_code == 200
    res = tamper_resp.json()["verification_result"]
    assert res["verification_status"] == "TAMPER_DETECTED"
    assert res["is_authentic"] is False
    assert res["signature_valid"] is False


def test_backward_compatibility_hmac_sha256(phase5_env):
    tokens, _ = phase5_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    # Issue legacy HMAC-SHA256 credential
    issue_payload = {
        "student_ref": "STU-PH5-001",
        "student_name": "Ananya Sharma",
        "institution_id": "INST-IITB",
        "institution_name": "Indian Institute of Technology Bombay",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2025-06-15",
        "completion_date": "2025-05-30",
        "algorithm": "HMAC-SHA256",
    }
    resp = client.post("/api/v1/certificates/issue", json=issue_payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["signature_algorithm"] == "HMAC-SHA256"
    assert data["public_key_id"] == LEGACY_HMAC_KEY_ID
    cert_id = data["certificate_id"]

    # Verify legacy credential still verifies cleanly
    v_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "VALID"
    assert v_data["is_authentic"] is True
    assert v_data["signature_valid"] is True


def test_credential_revocation_workflow_and_audit(phase5_env):
    tokens, db_sessions = phase5_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['admin']}"}

    cert_id = client.post("/api/v1/certificates/issue", json={
        "student_ref": "STU-PH5-001",
        "student_name": "Ananya Sharma",
        "institution_id": "INST-IITB",
        "institution_name": "Indian Institute of Technology Bombay",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-30",
    }, headers=headers).json()["certificate_id"]

    # Substantive reason required (>4 chars)
    short_resp = client.post(f"/api/v1/certificates/{cert_id}/revoke", json={"reason": "bad"}, headers=headers)
    assert short_resp.status_code == 422

    # Valid revocation
    revoke_resp = client.post(
        f"/api/v1/certificates/{cert_id}/revoke",
        json={"reason": "Degree conferred prematurely; coursework incomplete upon academic council re-audit."},
        headers=headers,
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "REVOKED"

    # Verify status lookup returns REVOKED (signature valid, but revoked)
    v_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "REVOKED"
    assert v_data["is_authentic"] is False
    assert v_data["signature_valid"] is True
    assert "coursework incomplete" in v_data["revocation_reason"]

    # Verify audit event
    with db_sessions() as db:
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "CERTIFICATE",
            AuditLog.entity_id == cert_id,
            AuditLog.action == "REVOKE_CREDENTIAL",
        ).first()
        assert audit is not None
        assert "coursework incomplete" in audit.details["reason"]


def test_public_key_registry_endpoints(phase5_env):
    tokens, _ = phase5_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['verifier']}"}

    resp = client.get("/api/v1/certificates/public-keys", headers=headers)
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    key_ids = [k["key_id"] for k in keys]
    assert ACTIVE_KEY_ID in key_ids
    assert LEGACY_HMAC_KEY_ID in key_ids

    # Query single key
    single_resp = client.get(f"/api/v1/certificates/public-keys/{ACTIVE_KEY_ID}", headers=headers)
    assert single_resp.status_code == 200
    assert single_resp.json()["algorithm"] == "Ed25519"

    # Nonexistent key
    nf_resp = client.get("/api/v1/certificates/public-keys/KEY-NONEXISTENT", headers=headers)
    assert nf_resp.status_code == 404


def test_credentials_role_authorization_and_scoping(phase5_env):
    tokens, _ = phase5_env
    client = TestClient(app)
    auditor_headers = {"Authorization": f"Bearer {tokens['auditor']}"}
    inst1_headers = {"Authorization": f"Bearer {tokens['officer1']}"}

    # Auditor cannot issue or revoke
    issue_payload = {
        "student_ref": "STU-PH5-001",
        "student_name": "Ananya Sharma",
        "institution_id": "INST-IITB",
        "institution_name": "Indian Institute of Technology Bombay",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Science & Engineering",
        "issue_date": "2026-06-15",
        "completion_date": "2026-05-30",
    }
    assert client.post("/api/v1/certificates/issue", json=issue_payload, headers=auditor_headers).status_code == 403

    # Inst1 officer can issue for INST-IITB
    inst_resp = client.post("/api/v1/certificates/issue", json=issue_payload, headers=inst1_headers)
    assert inst_resp.status_code == 201
    cert_id = inst_resp.json()["certificate_id"]

    # Inst1 officer cannot issue for INST-NITK
    wrong_inst_payload = dict(issue_payload, institution_id="INST-NITK")
    assert client.post("/api/v1/certificates/issue", json=wrong_inst_payload, headers=inst1_headers).status_code == 403

    # Inst2 officer cannot revoke cert of INST-IITB
    inst2_headers = {"Authorization": f"Bearer {tokens['officer2']}"}
    assert client.post(
        f"/api/v1/certificates/{cert_id}/revoke",
        json={"reason": "Attempting cross-institutional revocation."},
        headers=inst2_headers,
    ).status_code == 403


def test_verifier_portal_consent_gating_and_privacy(phase5_env):
    tokens, _ = phase5_env
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens['verifier']}"}

    # Verify student with ACTIVE consent
    active_resp = client.post("/api/v1/verifier/verify-credential", json={
        "student_ref": "STU-PH5-001",
        "verifier_org_id": "ORG-TCS-BGV",
    }, headers=headers)
    assert active_resp.status_code == 200
    active_data = active_resp.json()
    assert active_data["verified"] is True
    assert active_data["outcome"] == "MATCH_VERIFIED"
    assert active_data["student_name"] == "Ananya Sharma"
    assert "apaar_id" not in active_data  # Privacy protection: APAAR ID omitted

    # Verify student with WITHDRAWN consent
    withdrawn_resp = client.post("/api/v1/verifier/verify-credential", json={
        "student_ref": "STU-PH5-002",
        "verifier_org_id": "ORG-TCS-BGV",
    }, headers=headers)
    assert withdrawn_resp.status_code == 200
    w_data = withdrawn_resp.json()
    assert w_data["verified"] is False
    assert w_data["outcome"] == "CONSENT_WITHHELD"

    # Nonexistent student returns safe NO_MATCH
    nf_resp = client.post("/api/v1/verifier/verify-credential", json={
        "student_ref": "STU-NONEXISTENT",
        "verifier_org_id": "ORG-TCS-BGV",
    }, headers=headers)
    assert nf_resp.status_code == 200
    assert nf_resp.json()["outcome"] == "NO_MATCH"


def test_alert_review_workflow_scoping_and_audit(phase5_env):
    tokens, _ = phase5_env
    client = TestClient(app)
    admin_headers = {"Authorization": f"Bearer {tokens['admin']}"}
    auditor_headers = {"Authorization": f"Bearer {tokens['auditor']}"}

    # Auditor cannot review alert
    review_payload = {
        "decision": "CONFIRMED_CONFLICT",
        "note": "Documented duplicate concurrent enrolment verified by registrar.",
    }
    assert client.patch("/api/v1/alerts/ALT-PH5-001/review", json=review_payload, headers=auditor_headers).status_code == 403

    # Review with blank note fails with 422
    blank_payload = {"decision": "CONFIRMED_CONFLICT", "note": "   "}
    assert client.patch("/api/v1/alerts/ALT-PH5-001/review", json=blank_payload, headers=admin_headers).status_code == 422

    # Valid review
    rev_resp = client.patch("/api/v1/alerts/ALT-PH5-001/review", json=review_payload, headers=admin_headers)
    assert rev_resp.status_code == 200
    assert rev_resp.json()["status"] == "RESOLVED"
    assert rev_resp.json()["decision"] == "CONFIRMED_CONFLICT"

    # Review history contains the event
    hist_resp = client.get("/api/v1/alerts/ALT-PH5-001/history", headers=admin_headers)
    assert hist_resp.status_code == 200
    events = hist_resp.json()["events"]
    assert any(e["action"] == "REVIEW_DECISION" and e["decision"] == "CONFIRMED_CONFLICT" for e in events)

    # Reopen requires valid note
    reopen_resp = client.post(
        "/api/v1/alerts/ALT-PH5-001/reopen",
        json={"reason": "New clarifying evidence received from state directorate of technical education."},
        headers=admin_headers,
    )
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["status"] == "UNDER_REVIEW"
