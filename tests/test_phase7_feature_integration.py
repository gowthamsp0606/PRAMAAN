import csv
import io
import pytest
from datetime import date
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.certificate import Certificate
from app.models.consent import StudentConsent
from app.models.enrolment import Enrolment
from app.models.student import Student
from app.models.verifier import VerifierOrganization, VerificationRequestLog
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.intake import ApprovedIntake
from app.services.auth_service import AuthService
from app.services.identity_service import IdentityStatus
from app.services.certificate_service import ACTIVE_KEY_ID

CSV_HEADER = (
    "student_ref,apaar_id,full_name,institution_id,institution_name,programme_id,"
    "programme_name,academic_year,admission_cycle,enrolment_start,enrolment_end,"
    "enrolment_status,seat_category,admission_category,passport_number\n"
)


@pytest.fixture
def phase7_env(db_sessions):
    """Clean isolated test database environment seeded with users, institutions, and baseline demo records."""
    prev_auth = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True

    with db_sessions() as db:
        # 1. Seed demo authentication accounts
        AuthService.seed_demo_users(db)

        # 2. Seed verified institutions & verifier organizations
        org_tcs = VerifierOrganization(
            id="ORG-TCS-BGV",
            org_name="Tata Consultancy Services - Background Verification",
            org_type="CORPORATE_EMPLOYER",
            is_approved=True,
            contact_email="bgv@tcs-example.com",
        )
        db.add(org_tcs)

        # 3. Seed Students & Enrolments across two distinct institutions
        dtu_stu = Student(
            student_ref="STU-DTU-001",
            apaar_id="1000-2000-3001",
            full_name="Aarav Sharma",
            primary_institution_id="INST-DELHI-DTU",
            nationality="Indian",
            identity_status=IdentityStatus.APAAR_VERIFIED,
        )
        iit_stu = Student(
            student_ref="STU-IITB-001",
            apaar_id="1000-2000-3002",
            full_name="Bhavna Patel",
            primary_institution_id="INST-IITB",
            nationality="Indian",
            identity_status=IdentityStatus.APAAR_VERIFIED,
        )
        db.add_all([dtu_stu, iit_stu])
        db.flush()

        dtu_enrol = Enrolment(
            student_ref="STU-DTU-001",
            apaar_id="1000-2000-3001",
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University",
            programme_id="BTECH-CSE",
            programme_name="Computer Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            seat_category="General",
            enrolment_start=date(2025, 8, 1),
            enrolment_status="Active",
        )
        iit_enrol = Enrolment(
            student_ref="STU-IITB-001",
            apaar_id="1000-2000-3002",
            institution_id="INST-IITB",
            institution_name="Indian Institute of Technology Bombay",
            programme_id="BTECH-CSE",
            programme_name="Computer Science & Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            seat_category="General",
            enrolment_start=date(2025, 8, 1),
            enrolment_status="Active",
        )
        db.add_all([dtu_enrol, iit_enrol])

        # 4. Seed Approved Intake Rules
        rule_dtu = ApprovedIntake(
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University",
            programme_id="BTECH-CSE",
            programme_name="Computer Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=120,
            nri_quota=10,
            supernumerary_quota=5,
        )
        rule_iit = ApprovedIntake(
            institution_id="INST-IITB",
            institution_name="Indian Institute of Technology Bombay",
            programme_id="BTECH-CSE",
            programme_name="Computer Science & Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=100,
            nri_quota=5,
            supernumerary_quota=5,
        )
        db.add_all([rule_dtu, rule_iit])

        # 5. Seed Consents
        c_active = StudentConsent(
            student_ref="STU-DTU-001",
            apaar_id="1000-2000-3001",
            purpose="EMPLOYMENT_VERIFICATION",
            consent_granted=True,
            status="ACTIVE",
            data_scope="CONFERRED_DEGREE_ONLY",
        )
        c_withdrawn = StudentConsent(
            student_ref="STU-IITB-001",
            apaar_id="1000-2000-3002",
            purpose="EMPLOYMENT_VERIFICATION",
            consent_granted=False,
            status="WITHDRAWN",
            data_scope="CONFERRED_DEGREE_ONLY",
        )
        db.add_all([c_active, c_withdrawn])

        # 6. Seed Alerts
        alert_dtu = Alert(
            id="ALT-INT-001",
            student_ref="STU-DTU-001",
            apaar_id="1000-2000-3001",
            alert_type="TEMPORAL_OVERLAP_CONFLICT",
            severity="HIGH",
            status="OPEN",
            title="Potential Dual Enrolment Overlap",
            explanation="Concurrent active enrolment recorded at two institutes.",
            supporting_record_ids=[dtu_enrol.id],
        )
        db.add(alert_dtu)

        db.commit()

    yield db_sessions

    settings.AUTH_REQUIRED = prev_auth


def get_token(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


# ==============================================================================
# Feature 1: Student Record Upload and CSV Validation
# ==============================================================================
def test_feature_1_student_record_upload_and_csv_validation(phase7_env):
    """Verify CSV validation rules, success/error contracts, persistence, and RBAC rejection."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    verifier_token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")

    # 1. Valid CSV upload
    clean_header = (
        "student_ref,apaar_id,full_name,institution_id,institution_name,programme_id,"
        "programme_name,academic_year,admission_cycle,enrolment_start,enrolment_end,"
        "enrolment_status,seat_category,source_submission_id\n"
    )
    valid_csv = (
        "STU-CSV-001,9000-1000-2001,Kavita Rao,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
        "Computer Engineering,2025-2026,Regular 2025,2025-08-01,2026-05-31,Active,General,BATCH-2026-01\n"
    )
    resp = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("batch_valid.csv", (clean_header + valid_csv).encode("utf-8"), "text/csv")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["total_rows"] == 1
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 0
    assert data["pass_rate_percent"] == 100.0

    # Verify persistence by querying student endpoint (simulate page refresh)
    stu_resp = client.get("/api/v1/students/STU-CSV-001", headers={"Authorization": f"Bearer {admin_token}"})
    assert stu_resp.status_code == 200
    assert stu_resp.json()["student"]["full_name"] == "Kavita Rao"

    # 2. Malformed CSV (missing mandatory columns returns HTTP 400 Bad Request)
    malformed_csv = "student_ref,full_name\nSTU-BAD,Bad Format\n"
    bad_resp = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("batch_bad.csv", malformed_csv.encode("utf-8"), "text/csv")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bad_resp.status_code == 400
    assert "Missing" in bad_resp.json()["detail"] or "column" in bad_resp.json()["detail"].lower()

    # 3. Unauthorized role (external_verifier) cannot upload CSV
    unauth_resp = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("batch_unauth.csv", (clean_header + valid_csv).encode("utf-8"), "text/csv")},
        headers={"Authorization": f"Bearer {verifier_token}"},
    )
    assert unauth_resp.status_code == 403


# ==============================================================================
# Feature 2: Missing and Duplicate APAAR ID Handling
# ==============================================================================
def test_feature_2_missing_and_duplicate_apaar_id_handling(phase7_env):
    """Verify rejection of missing APAAR ID for contemporary domestic students and duplicate ID collision."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")

    # 1. Contemporary domestic student without APAAR ID is rejected
    missing_apaar_row = (
        "STU-NO-APAAR,,Suresh Sharma,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
        "Computer Engineering,2025-2026,Regular 2025,2025-08-01,,Active,General,General,\n"
    )
    resp = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("missing_apaar.csv", (CSV_HEADER + missing_apaar_row).encode("utf-8"), "text/csv")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rejected_count"] == 1
    assert data["accepted_count"] == 0
    rule_ids = [err.get("rule_id") or err.get("code") for err in data.get("field_errors", [])]
    assert "VAL-REQ-001" in rule_ids

    # 2. Duplicate APAAR ID collision on identity status update
    # STU-IITB-001 already has '1000-2000-3002'
    # First create a legacy student without APAAR
    hist_row = (
        "STU-HIST-DUP,,Old Student,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
        "Computer Engineering,2021-2022,Regular 2021,2021-08-01,,Active,General,General,\n"
    )
    client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("hist_dup.csv", (CSV_HEADER + hist_row).encode("utf-8"), "text/csv")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Attempt to assign the existing APAAR ID of STU-IITB-001
    collision_resp = client.patch(
        "/api/v1/students/STU-HIST-DUP/identity-status",
        json={
            "new_status": IdentityStatus.APAAR_VERIFIED,
            "reason": "Resolving legacy record with APAAR",
            "new_apaar_id": "1000-2000-3002",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert collision_resp.status_code == 422
    assert "already assigned to student" in collision_resp.json()["detail"]


# ==============================================================================
# Feature 3: Legacy Records and Documented Identity Exceptions
# ==============================================================================
def test_feature_3_legacy_records_and_documented_identity_exceptions(phase7_env):
    """Verify historical pre-2024 and foreign national exceptions, transitions, and audit records."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")

    # 1. Historical pre-2024 record without APAAR ID
    hist_row = (
        "STU-LEGACY-01,,Vikramaditya Rao,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
        "Computer Engineering,2021-2022,Regular 2021,2021-08-01,,Active,General,General,\n"
    )
    resp_hist = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("legacy.csv", (CSV_HEADER + hist_row).encode("utf-8"), "text/csv")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_hist.status_code == 200
    assert resp_hist.json()["accepted_count"] == 1

    # Check status is HISTORICAL_NO_APAAR
    stu_hist = client.get("/api/v1/students/STU-LEGACY-01", headers={"Authorization": f"Bearer {admin_token}"})
    assert stu_hist.json()["student"]["identity_status"] == IdentityStatus.HISTORICAL_NO_APAAR

    # 2. Foreign national student with passport
    fn_row = (
        "STU-FN-01,,Jean Dupont,INST-DELHI-DTU,Delhi Technological University,BTECH-CSE,"
        "Computer Engineering,2025-2026,Regular 2025,2025-08-01,,Active,General,Foreign National,FRA-P-998811\n"
    )
    resp_fn = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("foreign.csv", (CSV_HEADER + fn_row).encode("utf-8"), "text/csv")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_fn.status_code == 200
    assert resp_fn.json()["accepted_count"] == 1

    stu_fn = client.get("/api/v1/students/STU-FN-01", headers={"Authorization": f"Bearer {admin_token}"})
    assert stu_fn.json()["student"]["identity_status"] == IdentityStatus.EXEMPT_WHERE_POLICY_PERMITS

    # 3. Status transition to APAAR_PENDING
    trans_resp = client.patch(
        "/api/v1/students/STU-LEGACY-01/identity-status",
        json={
            "new_status": IdentityStatus.APAAR_PENDING,
            "reason": "Applied for APAAR card at college registration camp",
            "evidence_reference": "CAMP-ACK-2026-90",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert trans_resp.status_code == 200
    assert trans_resp.json()["current_status"] == IdentityStatus.APAAR_PENDING

    # Persistence verification (refresh simulation)
    stu_refreshed = client.get("/api/v1/students/STU-LEGACY-01", headers={"Authorization": f"Bearer {admin_token}"})
    assert stu_refreshed.json()["student"]["identity_status"] == IdentityStatus.APAAR_PENDING


# ==============================================================================
# Feature 4: Institution-Scoped Student Records
# ==============================================================================
def test_feature_4_institution_scoped_student_records(phase7_env):
    """Verify that institution officers are strictly scoped to their assigned institution."""
    client = TestClient(app)
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")

    # DTU registrar queries students
    dtu_resp = client.get("/api/v1/students", headers={"Authorization": f"Bearer {dtu_token}"})
    assert dtu_resp.status_code == 200
    dtu_items = dtu_resp.json()["items"]
    # All items must belong to INST-DELHI-DTU
    assert len(dtu_items) > 0
    for item in dtu_items:
        assert item["primary_institution_id"] == "INST-DELHI-DTU"
    # Ensure STU-IITB-001 is NOT visible to DTU registrar
    assert not any(item["student_ref"] == "STU-IITB-001" for item in dtu_items)

    # DTU registrar attempting cross-institution query is rejected with HTTP 403
    cross_resp = client.get("/api/v1/students?institution_id=INST-IITB", headers={"Authorization": f"Bearer {dtu_token}"})
    assert cross_resp.status_code == 403

    # Admin can view all students
    admin_resp = client.get("/api/v1/students", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_resp.status_code == 200
    refs = [item["student_ref"] for item in admin_resp.json()["items"]]
    assert "STU-DTU-001" in refs
    assert "STU-IITB-001" in refs


# ==============================================================================
# Feature 5: Enrolment and Approved-Intake Compliance
# ==============================================================================
def test_feature_5_enrolment_and_approved_intake_compliance(phase7_env):
    """Verify intake compliance calculation, capacity utilization metrics, and scoping."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    verifier_token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")

    # Admin queries intake compliance findings
    findings_resp = client.get("/api/v1/intake-compliance/findings", headers={"Authorization": f"Bearer {admin_token}"})
    assert findings_resp.status_code == 200
    data = findings_resp.json()
    assert "total_findings" in data
    assert "findings" in data
    assert isinstance(data["findings"], list)

    # DTU registrar findings are strictly scoped to DTU
    dtu_findings_resp = client.get("/api/v1/intake-compliance/findings", headers={"Authorization": f"Bearer {dtu_token}"})
    assert dtu_findings_resp.status_code == 200
    for f in dtu_findings_resp.json()["findings"]:
        assert f["institution_id"] == "INST-DELHI-DTU"

    # Verifier cannot access intake compliance
    assert client.get("/api/v1/intake-compliance/findings", headers={"Authorization": f"Bearer {verifier_token}"}).status_code == 403


# ==============================================================================
# Feature 6: Alerts and Review Adjudication
# ==============================================================================
def test_feature_6_alerts_and_review_adjudication(phase7_env):
    """Verify alert listing, adjudication schema validation, decision options, and state update."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    auditor_token = get_token(client, "compliance_auditor", "ComplianceAuditor@2026!")

    # 1. Invalid decision payload rejected with 422
    bad_dec_resp = client.patch(
        "/api/v1/alerts/ALT-INT-001/review",
        json={"decision": "DISMISS_INVALID_OPTION", "note": "Valid explanation."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bad_dec_resp.status_code == 422

    # 2. Blank note rejected with 422
    blank_note_resp = client.patch(
        "/api/v1/alerts/ALT-INT-001/review",
        json={"decision": "CONFIRMED_CONFLICT", "note": "    "},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert blank_note_resp.status_code == 422

    # 3. Read-only auditor cannot adjudicate
    unauth_resp = client.patch(
        "/api/v1/alerts/ALT-INT-001/review",
        json={"decision": "CONFIRMED_CONFLICT", "note": "Legitimate decision attempt."},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert unauth_resp.status_code == 403

    # 4. Valid adjudication with accepted enum (CONFIRMED_CONFLICT)
    adj_resp = client.patch(
        "/api/v1/alerts/ALT-INT-001/review",
        json={
            "decision": "CONFIRMED_CONFLICT",
            "note": "Documented concurrent enrolment confirmed through university registrar audit.",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adj_resp.status_code == 200
    res_data = adj_resp.json()
    assert res_data["status"] == "RESOLVED"
    assert res_data["decision"] == "CONFIRMED_CONFLICT"

    # 5. Persisted state verified upon query
    alert_query = client.get("/api/v1/alerts/ALT-INT-001", headers={"Authorization": f"Bearer {admin_token}"})
    assert alert_query.status_code == 200
    alert_detail = alert_query.json()["alert"]
    assert alert_detail["status"] == "RESOLVED"
    assert alert_detail["reviewer_decision"] == "CONFIRMED_CONFLICT"


# ==============================================================================
# Feature 7: Review Decision History and Audit Trail
# ==============================================================================
def test_feature_7_review_decision_history_and_audit_trail(phase7_env):
    """Verify that alert adjudication persists immutable event timeline and system audit logs."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")

    # Adjudicate the alert
    client.patch(
        "/api/v1/alerts/ALT-INT-001/review",
        json={
            "decision": "EXCEPTION_ACCEPTED",
            "note": "Credit transfer arrangement documented by AICTE approved MoU.",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Query alert review history
    hist_resp = client.get("/api/v1/alerts/ALT-INT-001/history", headers={"Authorization": f"Bearer {admin_token}"})
    assert hist_resp.status_code == 200
    events = hist_resp.json()["events"]
    assert len(events) >= 1
    latest_event = events[0]
    assert latest_event["action"] == "REVIEW_DECISION"
    assert latest_event["decision"] == "EXCEPTION_ACCEPTED"
    assert "Credit transfer arrangement" in latest_event["note"]

    # Query audit trail
    audit_resp = client.get("/api/v1/audit-trail", headers={"Authorization": f"Bearer {admin_token}"})
    assert audit_resp.status_code == 200
    trail_items = audit_resp.json()["items"]
    assert any(
        item["entity_id"] == "ALT-INT-001" and item["action"] == "REVIEW_DECISION"
        for item in trail_items
    )


# ==============================================================================
# Feature 8: Digital Credential Issuance
# ==============================================================================
def test_feature_8_digital_credential_issuance(phase7_env):
    """Verify Ed25519 credential issuance, signature generation, contract, and RBAC."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    auditor_token = get_token(client, "compliance_auditor", "ComplianceAuditor@2026!")
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")

    issue_payload = {
        "student_ref": "STU-DTU-001",
        "student_name": "Aarav Sharma",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Engineering",
        "issue_date": "2026-06-30",
        "completion_date": "2026-05-31",
        "apaar_id": "1000-2000-3001",
        "algorithm": "Ed25519",
    }

    # 1. Auditor cannot issue credentials
    assert client.post("/api/v1/certificates/issue", json=issue_payload, headers={"Authorization": f"Bearer {auditor_token}"}).status_code == 403

    # 2. DTU registrar cannot issue for IIT Bombay
    wrong_inst_payload = dict(issue_payload, institution_id="INST-IITB")
    assert client.post("/api/v1/certificates/issue", json=wrong_inst_payload, headers={"Authorization": f"Bearer {dtu_token}"}).status_code == 403

    # 3. Successful issuance by DTU Registrar
    issue_resp = client.post("/api/v1/certificates/issue", json=issue_payload, headers={"Authorization": f"Bearer {dtu_token}"})
    assert issue_resp.status_code == 201
    data = issue_resp.json()
    assert data["success"] is True
    assert data["signature_algorithm"] == "Ed25519"
    assert data["public_key_id"] == ACTIVE_KEY_ID
    assert len(data["signature_hex"]) == 128  # 64 bytes in hex
    cert_id = data["certificate_id"]

    # 4. Verify persistence in DB
    cert_list = client.get("/api/v1/certificates", headers={"Authorization": f"Bearer {dtu_token}"})
    assert cert_list.status_code == 200
    items = cert_list.json()["items"]
    assert any(c["certificate_id"] == cert_id and c["status"] == "VALID" for c in items)


# ==============================================================================
# Feature 9: Credential Verification and Revocation
# ==============================================================================
def test_feature_9_credential_verification_and_revocation(phase7_env):
    """Verify signature verification, revocation workflow with substantive reason, and revoked status."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")

    # Issue certificate
    issue_payload = {
        "student_ref": "STU-DTU-001",
        "student_name": "Aarav Sharma",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Engineering",
        "issue_date": "2026-06-30",
        "completion_date": "2026-05-31",
        "algorithm": "Ed25519",
    }
    cert_id = client.post("/api/v1/certificates/issue", json=issue_payload, headers={"Authorization": f"Bearer {admin_token}"}).json()["certificate_id"]

    # 1. Verification returns VALID
    v_resp = client.get(f"/api/v1/certificates/{cert_id}/verify", headers={"Authorization": f"Bearer {admin_token}"})
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["verification_status"] == "VALID"
    assert v_data["is_authentic"] is True
    assert v_data["signature_valid"] is True

    # 2. Revocation with trivial reason is rejected (must be > 4 characters)
    bad_rev = client.post(f"/api/v1/certificates/{cert_id}/revoke", json={"reason": "err"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert bad_rev.status_code == 422

    # 3. Valid revocation
    rev_resp = client.post(
        f"/api/v1/certificates/{cert_id}/revoke",
        json={"reason": "Degree recalled due to academic disciplinary board finding."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["status"] == "REVOKED"

    # 4. Verification of revoked credential shows REVOKED status with signature still valid
    v_after = client.get(f"/api/v1/certificates/{cert_id}/verify", headers={"Authorization": f"Bearer {admin_token}"})
    assert v_after.status_code == 200
    v_after_data = v_after.json()
    assert v_after_data["verification_status"] == "REVOKED"
    assert v_after_data["is_authentic"] is False
    assert v_after_data["signature_valid"] is True
    assert "academic disciplinary board" in v_after_data["revocation_reason"]


# ==============================================================================
# Feature 10: Tamper Detection
# ==============================================================================
def test_feature_10_tamper_detection(phase7_env, db_sessions):
    """Verify non-destructive tamper simulation detects altered payload and keeps database intact."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")

    # Issue certificate
    issue_payload = {
        "student_ref": "STU-DTU-001",
        "student_name": "Aarav Sharma",
        "institution_id": "INST-DELHI-DTU",
        "institution_name": "Delhi Technological University",
        "programme_id": "BTECH-CSE",
        "programme_name": "Computer Engineering",
        "issue_date": "2026-06-30",
        "completion_date": "2026-05-31",
        "algorithm": "Ed25519",
    }
    cert_id = client.post("/api/v1/certificates/issue", json=issue_payload, headers={"Authorization": f"Bearer {admin_token}"}).json()["certificate_id"]

    # Tamper simulation endpoint
    tamper_resp = client.post(
        f"/api/v1/certificates/{cert_id}/simulate-tamper",
        json={"student_name": "Malicious Tampered Name"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert tamper_resp.status_code == 200
    tamper_result = tamper_resp.json()["verification_result"]
    assert tamper_result["verification_status"] == "TAMPER_DETECTED"
    assert tamper_result["is_authentic"] is False
    assert tamper_result["signature_valid"] is False

    # Check that database record was NOT mutated (non-destructive)
    with db_sessions() as db:
        cert_in_db = db.query(Certificate).filter(Certificate.certificate_id == cert_id).first()
        assert cert_in_db.payload_json["student_name"] == "Aarav Sharma"
        assert cert_in_db.status == "VALID"

    # Routine verify on original credential remains VALID
    clean_v = client.get(f"/api/v1/certificates/{cert_id}/verify", headers={"Authorization": f"Bearer {admin_token}"})
    assert clean_v.status_code == 200
    assert clean_v.json()["verification_status"] == "VALID"


# ==============================================================================
# Feature 11: Verification Request Audit Logging
# ==============================================================================
def test_feature_11_verification_request_audit_logging(phase7_env, db_sessions):
    """Verify that background verification queries write into verification_request_logs and are viewable."""
    client = TestClient(app)
    verifier_token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")

    # Verifier performs credential verification query
    verify_resp = client.post(
        "/api/v1/verifier/verify-credential",
        json={"student_ref": "STU-DTU-001", "verifier_org_id": "ORG-TCS-BGV"},
        headers={"Authorization": f"Bearer {verifier_token}"},
    )
    assert verify_resp.status_code == 200

    # Query verification logs
    logs_resp = client.get("/api/v1/verifier/logs", headers={"Authorization": f"Bearer {verifier_token}"})
    assert logs_resp.status_code == 200
    logs = logs_resp.json()["items"]
    assert len(logs) >= 1
    latest_log = logs[0]
    assert latest_log["verifier_org_id"] == "ORG-TCS-BGV"
    assert latest_log["query_student_ref"] == "STU-DTU-001"
    assert latest_log["verification_outcome"] == "MATCH_VERIFIED"

    # Check persistence directly in DB
    with db_sessions() as db:
        log_entry = db.query(VerificationRequestLog).filter(
            VerificationRequestLog.query_student_ref == "STU-DTU-001",
            VerificationRequestLog.verifier_org_id == "ORG-TCS-BGV",
        ).first()
        assert log_entry is not None


# ==============================================================================
# Feature 12: Authorized Verification Access
# ==============================================================================
def test_feature_12_authorized_verification_access(phase7_env):
    """Verify consent checking (active vs withdrawn) and privacy masking during verification."""
    client = TestClient(app)
    verifier_token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")

    # 1. Student with ACTIVE consent -> MATCH_VERIFIED
    active_resp = client.post(
        "/api/v1/verifier/verify-credential",
        json={"student_ref": "STU-DTU-001", "verifier_org_id": "ORG-TCS-BGV"},
        headers={"Authorization": f"Bearer {verifier_token}"},
    )
    assert active_resp.status_code == 200
    active_data = active_resp.json()
    assert active_data["verified"] is True
    assert active_data["outcome"] == "MATCH_VERIFIED"
    assert active_data["student_name"] == "Aarav Sharma"
    # Privacy safeguard: Sensitive APAAR ID must NOT be leaked
    assert "apaar_id" not in active_data

    # 2. Student with WITHDRAWN consent -> CONSENT_WITHHELD
    withdrawn_resp = client.post(
        "/api/v1/verifier/verify-credential",
        json={"student_ref": "STU-IITB-001", "verifier_org_id": "ORG-TCS-BGV"},
        headers={"Authorization": f"Bearer {verifier_token}"},
    )
    assert withdrawn_resp.status_code == 200
    withdrawn_data = withdrawn_resp.json()
    assert withdrawn_data["verified"] is False
    assert withdrawn_data["outcome"] == "CONSENT_WITHHELD"

    # 3. Nonexistent student -> safe NO_MATCH
    nf_resp = client.post(
        "/api/v1/verifier/verify-credential",
        json={"student_ref": "STU-DOES-NOT-EXIST", "verifier_org_id": "ORG-TCS-BGV"},
        headers={"Authorization": f"Bearer {verifier_token}"},
    )
    assert nf_resp.status_code == 200
    assert nf_resp.json()["outcome"] == "NO_MATCH"


# ==============================================================================
# Feature 13: Reports and Report Exports
# ==============================================================================
def test_feature_13_reports_and_report_exports(phase7_env):
    """Verify executive report summary metrics, institution scoping, and CSV export streaming."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    auditor_token = get_token(client, "compliance_auditor", "ComplianceAuditor@2026!")
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    verifier_token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")

    # 1. Admin queries executive summary
    rep_resp = client.get("/api/v1/reports/executive-summary", headers={"Authorization": f"Bearer {admin_token}"})
    assert rep_resp.status_code == 200
    rep_data = rep_resp.json()
    assert "intake_compliance_results" in rep_data
    assert "pending_cases" in rep_data
    assert "import_validation_issues" in rep_data

    # 2. Compliance auditor has access under read-only auditor role
    auditor_rep = client.get("/api/v1/reports/executive-summary", headers={"Authorization": f"Bearer {auditor_token}"})
    assert auditor_rep.status_code == 200

    # 3. DTU registrar is restricted from executive-level reports (least privilege enforcement)
    dtu_rep = client.get("/api/v1/reports/executive-summary", headers={"Authorization": f"Bearer {dtu_token}"})
    assert dtu_rep.status_code == 403

    # 4. CSV Export returns valid text/csv format
    export_resp = client.get("/api/v1/reports/executive-summary/export", headers={"Authorization": f"Bearer {admin_token}"})
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers["content-type"]
    assert "attachment; filename=" in export_resp.headers["content-disposition"]
    csv_text = export_resp.text
    assert "record_type,institution_id,programme_id" in csv_text

    # 5. Verifier cannot access reports
    assert client.get("/api/v1/reports/executive-summary", headers={"Authorization": f"Bearer {verifier_token}"}).status_code == 403


# ==============================================================================
# Feature 14: Dashboard Summaries and Filtering
# ==============================================================================
def test_feature_14_dashboard_summaries_and_filtering(phase7_env):
    """Verify dashboard summary metrics, institution filtering, and academic year breakdown."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")

    # 1. Admin summary
    summary_resp = client.get("/api/v1/dashboard/summary", headers={"Authorization": f"Bearer {admin_token}"})
    assert summary_resp.status_code == 200
    data = summary_resp.json()
    assert data["total_students"] >= 2
    assert data["open_alerts"] >= 1
    assert "HIGH" in data["alert_severity_distribution"]

    # 2. Summary filtered by institution
    filtered_resp = client.get("/api/v1/dashboard/summary?institution_id=INST-DELHI-DTU", headers={"Authorization": f"Bearer {admin_token}"})
    assert filtered_resp.status_code == 200
    dtu_data = filtered_resp.json()
    assert dtu_data["total_students"] >= 1

    # 3. Summary filtered by academic year
    year_resp = client.get("/api/v1/dashboard/summary?academic_year=2025-2026", headers={"Authorization": f"Bearer {admin_token}"})
    assert year_resp.status_code == 200

    # 4. Institution officer queries institution-specific dashboard endpoint
    dtu_summary = client.get("/api/v1/institution/dashboard-summary", headers={"Authorization": f"Bearer {dtu_token}"})
    assert dtu_summary.status_code == 200
    dtu_json = dtu_summary.json()
    assert dtu_json["institution_id"] == "INST-DELHI-DTU"
    assert dtu_json["total_enrolments"] >= 1
    assert dtu_json["active_students"] >= 1


# ==============================================================================
# Feature 15: Authentication and Role-Specific Navigation
# ==============================================================================
def test_feature_15_authentication_and_role_specific_navigation(phase7_env):
    """Verify login authentication across all 5 roles, invalid credential rejection, and token revocation."""
    client = TestClient(app)

    roles_and_credentials = [
        ("admin", "PramaanAdmin@2026!", "administrator"),
        ("aicte_reviewer", "AicteReviewer@2026!", "reviewer"),
        ("dtu_registrar", "DtuRegistrar@2026!", "institution_officer"),
        ("tcs_verifier", "TcsVerifier@2026!", "external_verifier"),
        ("compliance_auditor", "ComplianceAuditor@2026!", "read_only_auditor"),
    ]

    expected_dashboard_routes = {
        "administrator": "/admin-dashboard",
        "reviewer": "/aicte-dashboard",
        "institution_officer": "/institution-dashboard",
        "external_verifier": "/employer-portal",
        "read_only_auditor": "/auditor-dashboard",
    }

    for username, password, expected_role in roles_and_credentials:
        login_resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert login_resp.status_code == 200, f"Login failed for {username}"
        body = login_resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["user"]["role"] == expected_role
        assert body["user"]["dashboard_route"] == expected_dashboard_routes[expected_role]
        token = body["access_token"]

        # Verify /auth/me returns identity
        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == username
        assert me_resp.json()["role"] == expected_role

    # Invalid password rejected
    bad_resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "WrongPassword@2026!"})
    assert bad_resp.status_code == 401
    assert "Invalid username" in bad_resp.json()["detail"]

    # Unknown username rejected
    bad_user = client.post("/api/v1/auth/login", json={"username": "unknown_user", "password": "AnyPassword123!"})
    assert bad_user.status_code == 401

    # Logout revokes token
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    logout_resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {admin_token}"})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # Token cannot be reused after logout
    recheck_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert recheck_resp.status_code == 401
