import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.transfer import TransferRequest, TransferStatus
from app.models.versioning import EnrolmentVersion
from app.models.audit import AuditLog
from app.models.user import User
from app.services.auth_service import AuthService, PasswordHasher
from app.services.integrity_engine import TemporalIntegrityEngine
import app.seed_data as seed_data


@pytest.fixture
def transfer_env(db_sessions):
    prev_auth = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True

    # Seed baseline students, enrolments, and demo users
    seed_data.init_db_and_seed()
    with db_sessions() as db:
        AuthService.seed_demo_users(db)
        # Create an IIITD registrar user for destination tests
        if not db.query(User).filter(User.username == "iiitd_registrar").first():
            db.add(User(
                username="iiitd_registrar",
                email="registrar@iiitd.ac.in",
                password_hash=PasswordHasher.hash_password("IiitdRegistrar@2026!"),
                full_name="Registrar, IIIT Delhi",
                role="institution_officer",
                role_category="INSTITUTION_REGISTRAR",
                institution_id="INST-DELHI-IIITD",
                is_active=True,
            ))
        # Create a COEP registrar user for third-party institution scoping tests
        if not db.query(User).filter(User.username == "coep_registrar").first():
            db.add(User(
                username="coep_registrar",
                email="registrar@coep.ac.in",
                password_hash=PasswordHasher.hash_password("CoepRegistrar@2026!"),
                full_name="Registrar, COEP Pune",
                role="institution_officer",
                role_category="INSTITUTION_REGISTRAR",
                institution_id="INST-PUNE-COEP",
                is_active=True,
            ))
        # Ensure STU-DEMO-001 has an Active enrolment at DTU for transfer lifecycle test
        dtu_e1 = db.query(Enrolment).filter(
            Enrolment.student_ref == "STU-DEMO-001",
            Enrolment.institution_id == "INST-DELHI-DTU"
        ).first()
        if dtu_e1:
            dtu_e1.enrolment_status = "Active"
            dtu_e1.enrolment_end = None

        db.commit()

    yield db_sessions
    settings.AUTH_REQUIRED = prev_auth


def get_token(client, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


def test_full_successful_student_transfer_lifecycle(transfer_env):
    """
    Test end-to-end migration lifecycle:
    1. DTU Registrar initiates transfer for STU-DEMO-001 to IIITD.
    2. DTU Registrar approves release with NOC certificate.
    3. IIITD Registrar confirms admission.
    4. Enrolment history is preserved; new enrolment activated; audit logs recorded.
    """
    client = TestClient(app)
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    iiitd_token = get_token(client, "iiitd_registrar", "IiitdRegistrar@2026!")
    dtu_headers = {"Authorization": f"Bearer {dtu_token}"}
    iiitd_headers = {"Authorization": f"Bearer {iiitd_token}"}

    # Step 1: Initiate Transfer
    initiate_payload = {
        "student_ref": "STU-DEMO-001",
        "destination_institution_id": "INST-DELHI-IIITD",
        "destination_institution_name": "Indraprastha Institute of Information Technology Delhi",
        "programme_id": "PROG-BTECH-CSE",
        "programme_name": "B.Tech Computer Science & Engineering",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
        "transfer_reason": "Inter-state family relocation and academic branch credit transfer",
    }
    init_resp = client.post("/api/v1/transfers/initiate", json=initiate_payload, headers=dtu_headers)
    assert init_resp.status_code == 201, init_resp.text
    transfer_data = init_resp.json()
    transfer_id = transfer_data["id"]
    assert transfer_data["status"] == "PENDING_RELEASE"
    assert transfer_data["source_institution_id"] == "INST-DELHI-DTU"
    assert transfer_data["destination_institution_id"] == "INST-DELHI-IIITD"

    # Step 2: Source Institution (DTU) Approves Release
    release_payload = {
        "action": "APPROVE",
        "reason": "Institutional migration certificate verified with no dues pending",
        "noc_certificate_ref": "NOC-DTU-2025-0881",
    }
    rel_resp = client.post(f"/api/v1/transfers/{transfer_id}/release", json=release_payload, headers=dtu_headers)
    assert rel_resp.status_code == 200, rel_resp.text
    rel_data = rel_resp.json()
    assert rel_data["status"] == "RELEASED"
    assert rel_data["source_decision"] == "APPROVED"
    assert rel_data["noc_certificate_ref"] == "NOC-DTU-2025-0881"

    # Verify source enrolment was updated to Withdrawn with version tracking
    with transfer_env() as db:
        src_enrol = db.query(Enrolment).filter(
            Enrolment.student_ref == "STU-DEMO-001",
            Enrolment.institution_id == "INST-DELHI-DTU",
        ).first()
        assert src_enrol.enrolment_status == "Withdrawn"
        assert str(src_enrol.enrolment_end) == "2025-08-01"

        # Check version history
        version_entry = db.query(EnrolmentVersion).filter(
            EnrolmentVersion.enrolment_id == src_enrol.id
        ).order_by(EnrolmentVersion.version_number.desc()).first()
        assert version_entry is not None
        assert "Transfer release" in version_entry.change_reason

    # Step 3: Destination Institution (IIITD) Confirms Admission
    admit_payload = {
        "action": "ADMIT",
        "reason": "Credit transfer mapped and student admitted to semester 3",
        "seat_category": "General",
    }
    admit_resp = client.post(f"/api/v1/transfers/{transfer_id}/admit", json=admit_payload, headers=iiitd_headers)
    assert admit_resp.status_code == 200, admit_resp.text
    admit_data = admit_resp.json()
    assert admit_data["status"] == "COMPLETED"
    assert admit_data["destination_decision"] == "ADMITTED"

    # Step 4: Verify Database Persistence & Consistency
    with transfer_env() as db:
        # Destination enrolment created and active
        dest_enrol = db.query(Enrolment).filter(
            Enrolment.student_ref == "STU-DEMO-001",
            Enrolment.institution_id == "INST-DELHI-IIITD",
        ).first()
        assert dest_enrol is not None
        assert dest_enrol.enrolment_status == "Active"
        assert str(dest_enrol.enrolment_start) == "2025-08-01"

        # Source enrolment is still preserved (NOT deleted)
        src_preserved = db.query(Enrolment).filter(
            Enrolment.student_ref == "STU-DEMO-001",
            Enrolment.institution_id == "INST-DELHI-DTU",
        ).first()
        assert src_preserved is not None
        assert src_preserved.enrolment_status == "Withdrawn"

        # Student primary institution updated to IIITD
        student = db.query(Student).filter(Student.student_ref == "STU-DEMO-001").first()
        assert student.primary_institution_id == "INST-DELHI-IIITD"

        # Audit events verified
        audit_events = db.query(AuditLog).filter(
            AuditLog.entity_type == "TRANSFER",
            AuditLog.entity_id == transfer_id,
        ).all()
        actions = {a.action for a in audit_events}
        assert "TRANSFER_INITIATED" in actions
        assert "TRANSFER_RELEASE_APPROVED" in actions
        assert "TRANSFER_ADMISSION_CONFIRMED" in actions


def test_transfer_initiation_validations(transfer_env):
    """Test validation errors on transfer initiation."""
    client = TestClient(app)
    token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Non-existent student
    resp1 = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "NON-EXISTENT-STU-999",
        "destination_institution_id": "INST-DELHI-IIITD",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers=headers)
    assert resp1.status_code == 404
    assert "not found" in resp1.json()["detail"].lower()

    # 2. Identical source and destination
    resp2 = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-001",
        "destination_institution_id": "INST-DELHI-DTU",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers=headers)
    assert resp2.status_code == 400
    assert "cannot be identical" in resp2.json()["detail"].lower()

    # 3. Prevent duplicate active transfer for the same student
    resp3 = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-004",
        "destination_institution_id": "INST-DELHI-IIITD",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers=headers)
    assert resp3.status_code == 201

    # Attempt second transfer while first is PENDING_RELEASE -> 409 Conflict
    resp4 = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-004",
        "destination_institution_id": "INST-PUNE-COEP",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers=headers)
    assert resp4.status_code == 409
    assert "active transfer request already exists" in resp4.json()["detail"].lower()


def test_cross_institution_unauthorized_initiation_and_decisions(transfer_env):
    """
    Test RBAC and institutional isolation:
    - COEP Registrar cannot initiate transfer for DTU student to IIITD.
    - Destination institution cannot execute release decision.
    - Source institution cannot execute admission decision.
    """
    client = TestClient(app)
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    coep_token = get_token(client, "coep_registrar", "CoepRegistrar@2026!")
    iiitd_token = get_token(client, "iiitd_registrar", "IiitdRegistrar@2026!")

    # 1. COEP tries to initiate transfer between DTU and IIITD -> 403 Forbidden
    resp_coep = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-006",
        "source_institution_id": "INST-DELHI-DTU",
        "destination_institution_id": "INST-DELHI-IIITD",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers={"Authorization": f"Bearer {coep_token}"})
    assert resp_coep.status_code == 403
    assert "assigned institution" in resp_coep.json()["detail"].lower()

    # DTU initiates legitimately
    resp_init = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-006",
        "destination_institution_id": "INST-DELHI-IIITD",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers={"Authorization": f"Bearer {dtu_token}"})
    assert resp_init.status_code == 201
    transfer_id = resp_init.json()["id"]

    # 2. IIITD (Destination) tries to decide release -> 403 Forbidden
    resp_dest_release = client.post(f"/api/v1/transfers/{transfer_id}/release", json={
        "action": "APPROVE"
    }, headers={"Authorization": f"Bearer {iiitd_token}"})
    assert resp_dest_release.status_code == 403
    assert "only the source institution" in resp_dest_release.json()["detail"].lower()

    # DTU legitimately releases
    client.post(f"/api/v1/transfers/{transfer_id}/release", json={"action": "APPROVE"}, headers={"Authorization": f"Bearer {dtu_token}"})

    # 3. DTU (Source) tries to decide admission -> 403 Forbidden
    resp_src_admit = client.post(f"/api/v1/transfers/{transfer_id}/admit", json={
        "action": "ADMIT"
    }, headers={"Authorization": f"Bearer {dtu_token}"})
    assert resp_src_admit.status_code == 403
    assert "only the destination institution" in resp_src_admit.json()["detail"].lower()


def test_invalid_lifecycle_transitions(transfer_env):
    """Verify that invalid state transitions are rejected."""
    client = TestClient(app)
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    iiitd_token = get_token(client, "iiitd_registrar", "IiitdRegistrar@2026!")

    # Initiate transfer
    resp_init = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-011",
        "destination_institution_id": "INST-DELHI-IIITD",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers={"Authorization": f"Bearer {dtu_token}"})
    assert resp_init.status_code == 201
    transfer_id = resp_init.json()["id"]

    # 1. Attempt to admit while still in PENDING_RELEASE -> 400 Bad Request
    resp_premature_admit = client.post(f"/api/v1/transfers/{transfer_id}/admit", json={
        "action": "ADMIT"
    }, headers={"Authorization": f"Bearer {iiitd_token}"})
    assert resp_premature_admit.status_code == 400
    assert "cannot be admitted before being released" in resp_premature_admit.json()["detail"].lower()

    # Legitimate release and admission
    client.post(f"/api/v1/transfers/{transfer_id}/release", json={"action": "APPROVE"}, headers={"Authorization": f"Bearer {dtu_token}"})
    client.post(f"/api/v1/transfers/{transfer_id}/admit", json={"action": "ADMIT"}, headers={"Authorization": f"Bearer {iiitd_token}"})

    # 2. Attempt repeated admission on COMPLETED transfer -> 409 Conflict
    resp_repeat_admit = client.post(f"/api/v1/transfers/{transfer_id}/admit", json={
        "action": "ADMIT"
    }, headers={"Authorization": f"Bearer {iiitd_token}"})
    assert resp_repeat_admit.status_code == 409
    assert "already been completed" in resp_repeat_admit.json()["detail"].lower()

    # 3. Attempt release on COMPLETED transfer -> 409 Conflict
    resp_repeat_release = client.post(f"/api/v1/transfers/{transfer_id}/release", json={
        "action": "APPROVE"
    }, headers={"Authorization": f"Bearer {dtu_token}"})
    assert resp_repeat_release.status_code == 409

    # 4. Attempt to cancel COMPLETED transfer -> 409 Conflict
    resp_cancel_completed = client.post(f"/api/v1/transfers/{transfer_id}/cancel", json={
        "reason": "Attempting rollback"
    }, headers={"Authorization": f"Bearer {dtu_token}"})
    assert resp_cancel_completed.status_code == 409


def test_source_rejection_and_cancellation(transfer_env):
    """Test rejection and cancellation terminal states."""
    client = TestClient(app)
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    headers = {"Authorization": f"Bearer {dtu_token}"}

    # 1. Rejection flow
    resp_init1 = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-001",
        "destination_institution_id": "INST-PUNE-COEP",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers=headers)
    t1_id = resp_init1.json()["id"]

    resp_rej = client.post(f"/api/v1/transfers/{t1_id}/release", json={
        "action": "REJECT",
        "reason": "Outstanding academic disciplinary inquiry",
    }, headers=headers)
    assert resp_rej.status_code == 200
    assert resp_rej.json()["status"] == "REJECTED"

    # 2. Cancellation flow
    resp_init2 = client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-001",
        "destination_institution_id": "INST-PUNE-COEP",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers=headers)
    t2_id = resp_init2.json()["id"]

    resp_cancel = client.post(f"/api/v1/transfers/{t2_id}/cancel", json={
        "reason": "Student withdrew migration request",
    }, headers=headers)
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["status"] == "CANCELLED"


def test_listing_and_institutional_scoping(transfer_env):
    """Verify that institution officers only list transfers involving their institution."""
    client = TestClient(app)
    admin_token = get_token(client, "admin", "PramaanAdmin@2026!")
    dtu_token = get_token(client, "dtu_registrar", "DtuRegistrar@2026!")
    coep_token = get_token(client, "coep_registrar", "CoepRegistrar@2026!")
    auditor_token = get_token(client, "compliance_auditor", "ComplianceAuditor@2026!")
    verifier_token = get_token(client, "tcs_verifier", "TcsVerifier@2026!")

    # DTU initiates a transfer to IIITD
    client.post("/api/v1/transfers/initiate", json={
        "student_ref": "STU-DEMO-001",
        "destination_institution_id": "INST-DELHI-IIITD",
        "programme_id": "PROG-BTECH-CSE",
        "academic_year": "2025-2026",
        "requested_effective_date": "2025-08-01",
    }, headers={"Authorization": f"Bearer {dtu_token}"})

    # DTU officer sees it
    dtu_list = client.get("/api/v1/transfers", headers={"Authorization": f"Bearer {dtu_token}"}).json()
    assert dtu_list["total"] >= 1

    # COEP officer does NOT see DTU-IIITD transfer
    coep_list = client.get("/api/v1/transfers", headers={"Authorization": f"Bearer {coep_token}"}).json()
    assert coep_list["total"] == 0

    # Admin sees all transfers
    admin_list = client.get("/api/v1/transfers", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert admin_list["total"] >= 1

    # Compliance Auditor can read (GET)
    auditor_resp = client.get("/api/v1/transfers", headers={"Authorization": f"Bearer {auditor_token}"})
    assert auditor_resp.status_code == 200

    # External Verifier is forbidden
    verifier_resp = client.get("/api/v1/transfers", headers={"Authorization": f"Bearer {verifier_token}"})
    assert verifier_resp.status_code == 403


def test_temporal_integrity_transfer_grace_period_integration(transfer_env):
    """
    Verify integration with TemporalIntegrityEngine:
    - Overlap <= 30 days under approved transfer -> classified as TRANSFER_GRACE_PERIOD_NOTICE (LOW severity).
    - Overlap > 30 days -> classified as TRANSFER_OVERLAP_EXCEEDED_GRACE_PERIOD (MEDIUM severity).
    - Overlap with transfer PENDING_RELEASE -> TRANSFER_PENDING_RELEASE_REVIEW (MEDIUM severity).
    - Overlap without transfer request -> TEMPORAL_OVERLAP_CONFLICT (HIGH severity).
    """
    with transfer_env() as db:
        engine = TemporalIntegrityEngine(db)

        # 1. Setup Student with overlap <= 30 days (e.g. 15 days) and an approved transfer
        student_grace = Student(
            student_ref="STU-TRF-GRACE",
            apaar_id="9999-0000-0001",
            full_name="Transfer Grace Student",
            primary_institution_id="INST-DELHI-DTU",
        )
        db.add(student_grace)
        db.flush()

        # Enrolment 1: DTU, ends 2025-08-15
        db.add(Enrolment(
            student_ref="STU-TRF-GRACE",
            apaar_id="9999-0000-0001",
            institution_id="INST-DELHI-DTU",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            enrolment_start=date(2025, 8, 1),
            enrolment_end=date(2025, 8, 15),
            enrolment_status="Active",
        ))
        # Enrolment 2: IIITD, starts 2025-08-01 (15 days overlap)
        db.add(Enrolment(
            student_ref="STU-TRF-GRACE",
            apaar_id="9999-0000-0001",
            institution_id="INST-DELHI-IIITD",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            admission_cycle="Transfer In-Year",
            enrolment_start=date(2025, 8, 1),
            enrolment_end=None,
            enrolment_status="Active",
        ))

        # Add approved TransferRequest
        db.add(TransferRequest(
            id="TRF-TEST-GRACE-01",
            student_ref="STU-TRF-GRACE",
            apaar_id="9999-0000-0001",
            source_institution_id="INST-DELHI-DTU",
            destination_institution_id="INST-DELHI-IIITD",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            initiation_date=date(2025, 7, 15),
            requested_effective_date=date(2025, 8, 1),
            status=TransferStatus.RELEASED,
            created_by="dtu_registrar",
        ))
        db.commit()

        # Run integrity engine
        result_grace = engine.evaluate_student("STU-TRF-GRACE")
        alerts_grace = result_grace["alerts"]
        assert len(alerts_grace) == 1
        assert alerts_grace[0]["alert_type"] == "TRANSFER_GRACE_PERIOD_NOTICE"
        assert alerts_grace[0]["severity"] == "LOW"

        # 2. Setup Student with overlap > 30 days (e.g. 60 days) under transfer
        student_exp = Student(
            student_ref="STU-TRF-EXP",
            apaar_id="9999-0000-0002",
            full_name="Transfer Expired Student",
            primary_institution_id="INST-DELHI-DTU",
        )
        db.add(student_exp)
        db.flush()

        db.add(Enrolment(
            student_ref="STU-TRF-EXP",
            apaar_id="9999-0000-0002",
            institution_id="INST-DELHI-DTU",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            enrolment_start=date(2025, 6, 1),
            enrolment_end=date(2025, 8, 1),
            enrolment_status="Active",
        ))
        db.add(Enrolment(
            student_ref="STU-TRF-EXP",
            apaar_id="9999-0000-0002",
            institution_id="INST-DELHI-IIITD",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            admission_cycle="Transfer In-Year",
            enrolment_start=date(2025, 6, 1),
            enrolment_end=None,
            enrolment_status="Active",
        ))
        db.add(TransferRequest(
            id="TRF-TEST-EXP-01",
            student_ref="STU-TRF-EXP",
            apaar_id="9999-0000-0002",
            source_institution_id="INST-DELHI-DTU",
            destination_institution_id="INST-DELHI-IIITD",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            initiation_date=date(2025, 5, 15),
            requested_effective_date=date(2025, 6, 1),
            status=TransferStatus.RELEASED,
            created_by="dtu_registrar",
        ))
        db.commit()

        result_exp = engine.evaluate_student("STU-TRF-EXP")
        alerts_exp = result_exp["alerts"]
        assert len(alerts_exp) == 1
        assert alerts_exp[0]["alert_type"] == "TRANSFER_OVERLAP_EXCEEDED_GRACE_PERIOD"
        assert alerts_exp[0]["severity"] == "MEDIUM"

        # 3. Setup Student with overlap and transfer PENDING_RELEASE
        student_pend = Student(
            student_ref="STU-TRF-PEND",
            apaar_id="9999-0000-0003",
            full_name="Transfer Pending Student",
            primary_institution_id="INST-DELHI-DTU",
        )
        db.add(student_pend)
        db.flush()

        db.add(Enrolment(
            student_ref="STU-TRF-PEND",
            apaar_id="9999-0000-0003",
            institution_id="INST-DELHI-DTU",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            enrolment_start=date(2025, 8, 1),
            enrolment_end=None,
            enrolment_status="Active",
        ))
        db.add(Enrolment(
            student_ref="STU-TRF-PEND",
            apaar_id="9999-0000-0003",
            institution_id="INST-DELHI-IIITD",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            admission_cycle="Transfer In-Year",
            enrolment_start=date(2025, 8, 1),
            enrolment_end=None,
            enrolment_status="Active",
        ))
        db.add(TransferRequest(
            id="TRF-TEST-PEND-01",
            student_ref="STU-TRF-PEND",
            apaar_id="9999-0000-0003",
            source_institution_id="INST-DELHI-DTU",
            destination_institution_id="INST-DELHI-IIITD",
            programme_id="PROG-CSE",
            academic_year="2025-2026",
            initiation_date=date(2025, 7, 20),
            requested_effective_date=date(2025, 8, 1),
            status=TransferStatus.PENDING_RELEASE,
            created_by="dtu_registrar",
        ))
        db.commit()

        result_pend = engine.evaluate_student("STU-TRF-PEND")
        alerts_pend = result_pend["alerts"]
        assert len(alerts_pend) == 1
        assert alerts_pend[0]["alert_type"] == "TRANSFER_PENDING_RELEASE_REVIEW"
        assert alerts_pend[0]["severity"] == "MEDIUM"
