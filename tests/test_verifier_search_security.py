"""
Regression Test Suite for External Verifier Search & Authorization Security
Verifies:
1. External verifier cannot discover students via search (0 student results).
2. External verifier can only search/discover credentials where student has an ACTIVE EMPLOYMENT_VERIFICATION consent.
3. Credentials for students with WITHDRAWN consent are strictly excluded.
4. Identifier masking is applied to student identifiers returned in verifier search snippets.
5. Verifiers cannot access raw student directories, detail records, transfers, or alerts (HTTP 403 Forbidden).
6. Verifier verify-credential endpoint strictly blocks verification if consent is withdrawn.
"""

import pytest
from datetime import datetime, timedelta, date, timezone
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.main import app
from app.models.user import User
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.certificate import Certificate
from app.models.consent import StudentConsent
from app.models.verifier import VerifierOrganization
from app.services.auth_service import TokenManager
from app.services.certificate_service import ACTIVE_KEY_ID


@pytest.fixture
def verifier_test_env(db_sessions):
    db: Session = db_sessions()
    try:
        # Seed Verifier Org
        org = VerifierOrganization(
            id="ORG-TCS-BGV",
            org_name="TCS Talent Verification Hub",
            org_type="EMPLOYER",
            is_approved=True,
            contact_email="bgv@tcs.example.com",
        )
        db.add(org)
        db.flush()

        # Seed Verifier User
        verifier_user = User(
            username="tcs_verifier",
            email="verifier@tcs.example.com",
            password_hash="testhash",
            full_name="TCS BGV Officer",
            role="external_verifier",
            role_category="BGV VERIFIER",
            verifier_org_id="ORG-TCS-BGV",
            purpose_scope="EMPLOYMENT_VERIFICATION",
            is_active=True,
        )
        db.add(verifier_user)
        db.flush()

        # Student 1: With ACTIVE Consent
        stu_active = Student(
            student_ref="STU-CONSENT-ACTIVE",
            apaar_id="9876-2026-1001",
            full_name="Candidate Active Consent",
            primary_institution_id="INST-DELHI-DTU",
            identity_route="AADHAAR_APAAR",
            identity_status="APAAR_VERIFIED",
            nationality="Indian",
        )
        # Student 2: With WITHDRAWN Consent
        stu_withdrawn = Student(
            student_ref="STU-CONSENT-WITHDRAWN",
            apaar_id="9876-2026-1002",
            full_name="Candidate Withdrawn Consent",
            primary_institution_id="INST-DELHI-DTU",
            identity_route="AADHAAR_APAAR",
            identity_status="APAAR_VERIFIED",
            nationality="Indian",
        )
        db.add_all([stu_active, stu_withdrawn])
        db.flush()
        db.add(Enrolment(
            student_ref="STU-CONSENT-ACTIVE",
            apaar_id="9876-2026-1001",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science",
            academic_year="2022-2026",
            admission_cycle="Autumn",
            enrolment_start=date(2022, 8, 1),
            enrolment_end=date(2026, 5, 30),
            enrolment_status="Active",
            seat_category="General",
        ))
        db.add(StudentConsent(
            student_ref="STU-CONSENT-ACTIVE",
            apaar_id="9876-2026-1001",
            purpose="EMPLOYMENT_VERIFICATION",
            consent_granted=True,
            status="ACTIVE",
            data_scope="NAME_PROGRAMME_COMPLETION_ONLY",
            granted_at=datetime.now(timezone.utc) - timedelta(days=10),
        ))
        db.add(Certificate(
            certificate_id="CERT-CONSENT-ACTIVE",
            student_ref="STU-CONSENT-ACTIVE",
            apaar_id="9876-2026-1001",
            student_name="Candidate Active Consent",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science",
            issue_date="2026-05-30",
            completion_date="2026-05-15",
            status="VALID",
            signature_algorithm="Ed25519",
            signature_hex="dummyhex1",
            public_key_id=ACTIVE_KEY_ID,
            payload_json={},
        ))

        # Student 2: With WITHDRAWN Consent
        db.add(Enrolment(
            student_ref="STU-CONSENT-WITHDRAWN",
            apaar_id="9876-2026-1002",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science",
            academic_year="2022-2026",
            admission_cycle="Autumn",
            enrolment_start=date(2022, 8, 1),
            enrolment_end=date(2026, 5, 30),
            enrolment_status="Active",
            seat_category="General",
        ))
        db.add(StudentConsent(
            student_ref="STU-CONSENT-WITHDRAWN",
            apaar_id="9876-2026-1002",
            purpose="EMPLOYMENT_VERIFICATION",
            consent_granted=False,
            status="WITHDRAWN",
            data_scope="NAME_PROGRAMME_COMPLETION_ONLY",
            granted_at=datetime.now(timezone.utc) - timedelta(days=30),
            withdrawn_at=datetime.now(timezone.utc) - timedelta(days=5),
        ))
        db.add(Certificate(
            certificate_id="CERT-CONSENT-WITHDRAWN",
            student_ref="STU-CONSENT-WITHDRAWN",
            apaar_id="9876-2026-1002",
            student_name="Candidate Withdrawn Consent",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science",
            issue_date="2026-05-30",
            completion_date="2026-05-15",
            status="VALID",
            signature_algorithm="Ed25519",
            signature_hex="dummyhex2",
            public_key_id=ACTIVE_KEY_ID,
            payload_json={},
        ))

        db.commit()
        db.refresh(verifier_user)
        verifier_token, _, _ = TokenManager.create_access_token(verifier_user)
        client = TestClient(app)
        return client, verifier_token
    finally:
        db.close()


def test_external_verifier_cannot_search_students(verifier_test_env):
    client, token = verifier_test_env
    headers = {"Authorization": f"Bearer {token}"}

    # Direct student search
    res = client.get("/api/v1/search?q=Candidate&type=student", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["categories"]["students"]) == 0, "Verifier must receive 0 student records"


def test_external_verifier_consent_gate_in_credential_search(verifier_test_env):
    client, token = verifier_test_env
    headers = {"Authorization": f"Bearer {token}"}

    # Search credentials
    res = client.get("/api/v1/search?q=Candidate&type=credential", headers=headers)
    assert res.status_code == 200
    data = res.json()
    creds = data["categories"]["credentials"]

    # CERT-CONSENT-ACTIVE must be visible
    active_cert_ids = [c["id"] for c in creds]
    assert "CERT-CONSENT-ACTIVE" in active_cert_ids, "Candidate with active consent must be visible"

    # CERT-CONSENT-WITHDRAWN must NOT be visible
    assert "CERT-CONSENT-WITHDRAWN" not in active_cert_ids, "Candidate with withdrawn consent must NOT be visible"

    # Verify student_ref is masked in metadata (e.g. **************TIVE)
    active_cred = next(c for c in creds if c["id"] == "CERT-CONSENT-ACTIVE")
    assert "*" in active_cred["metadata"]["student_ref"], "Student reference must be masked for verifier"


def test_external_verifier_forbidden_from_restricted_endpoints(verifier_test_env):
    client, token = verifier_test_env
    headers = {"Authorization": f"Bearer {token}"}

    # Attempting to access students directory
    res_stu = client.get("/api/v1/students", headers=headers)
    assert res_stu.status_code == 403

    # Attempting to access transfers
    res_trf = client.get("/api/v1/transfers", headers=headers)
    assert res_trf.status_code == 403

    # Attempting to access alerts
    res_alt = client.get("/api/v1/alerts", headers=headers)
    assert res_alt.status_code == 403

    # Attempting to access certificates list
    res_cert = client.get("/api/v1/certificates", headers=headers)
    assert res_cert.status_code == 403


def test_external_verifier_verification_consent_enforcement(verifier_test_env):
    client, token = verifier_test_env
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Verification of active consent candidate -> MATCH_VERIFIED
    res_active = client.post("/api/v1/verifier/verify-credential", json={
        "verifier_org_id": "ORG-TCS-BGV",
        "student_ref": "STU-CONSENT-ACTIVE",
        "certificate_id": "CERT-CONSENT-ACTIVE",
    }, headers=headers)
    assert res_active.status_code == 200
    assert res_active.json()["verified"] is True
    assert res_active.json()["outcome"] == "MATCH_VERIFIED"

    # 2. Verification of withdrawn consent candidate -> CONSENT_WITHHELD
    res_withdrawn = client.post("/api/v1/verifier/verify-credential", json={
        "verifier_org_id": "ORG-TCS-BGV",
        "student_ref": "STU-CONSENT-WITHDRAWN",
        "certificate_id": "CERT-CONSENT-WITHDRAWN",
    }, headers=headers)
    assert res_withdrawn.status_code == 200
    assert res_withdrawn.json()["verified"] is False
    assert res_withdrawn.json()["outcome"] == "CONSENT_WITHHELD"
