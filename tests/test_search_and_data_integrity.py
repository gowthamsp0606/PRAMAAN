import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.main import app
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.transfer import TransferRequest, TransferStatus
from app.models.alert import Alert
from app.models.certificate import Certificate
from app.models.intake import ApprovedIntake
from app.models.user import User
from app.services.auth_service import AuthService, TokenManager, PasswordHasher
from app.services.state_service import KNOWN_INSTITUTION_STATES, STATE_NAMES


def _create_auth_headers(db: Session, username: str = "admin", role: str = "administrator", **kwargs) -> dict:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        inst_id = kwargs.get("institution_id")
        if role == "state_officer" and not inst_id and kwargs.get("state"):
            inst_id = f"STATE-{kwargs.get('state')}"

        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=PasswordHasher.hash_password("DemoPassword@2026!"),
            full_name=f"Demo {username.title()}",
            role=role,
            role_category=kwargs.get("role_category", "NATIONAL_COORDINATOR"),
            institution_id=inst_id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    stu_ref = kwargs.get("student_ref")
    token, _, _ = TokenManager.create_access_token(user, student_ref=stu_ref)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded_db(db_sessions):
    db: Session = db_sessions()

    # 1. Institutions
    intakes = [
        ApprovedIntake(
            institution_id="INST-DELHI-DTU",
            institution_name="Delhi Technological University (Demo)",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science & Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=120,
        ),
        ApprovedIntake(
            institution_id="INST-TRICHY-NITT",
            institution_name="National Institute of Technology Tiruchirappalli (Demo)",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science & Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=100,
        ),
        ApprovedIntake(
            institution_id="INST-BLR-PES",
            institution_name="PES University Bengaluru (Demo)",
            programme_id="BTECH-CSE",
            programme_name="B.Tech Computer Science & Engineering",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            approved_intake_seats=150,
        ),
    ]
    for i in intakes:
        db.add(i)

    # 2. Students & Enrolments
    s1 = Student(
        student_ref="STU-SYN-001",
        apaar_id="9876-2026-0001",
        full_name="Aarav Sharma",
        primary_institution_id="INST-DELHI-DTU",
        identity_status="APAAR_VERIFIED",
    )
    s2 = Student(
        student_ref="STU-SYN-002",
        apaar_id="9876-2026-0002",
        full_name="Karthik Subramanian",
        primary_institution_id="INST-TRICHY-NITT",
        identity_status="APAAR_VERIFIED",
    )
    s3 = Student(
        student_ref="STU-SYN-003",
        apaar_id="9876-2026-0003",
        full_name="Varun Gowda",
        primary_institution_id="INST-BLR-PES",
        identity_status="PROVISIONAL",
    )
    db.add_all([s1, s2, s3])
    db.flush()

    e1 = Enrolment(
        student_ref="STU-SYN-001",
        apaar_id="9876-2026-0001",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_status="Active",
    )
    e2 = Enrolment(
        student_ref="STU-SYN-002",
        apaar_id="9876-2026-0002",
        institution_id="INST-TRICHY-NITT",
        institution_name="National Institute of Technology Tiruchirappalli (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_status="Active",
    )
    e3 = Enrolment(
        student_ref="STU-SYN-003",
        apaar_id="9876-2026-0003",
        institution_id="INST-BLR-PES",
        institution_name="PES University Bengaluru (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1),
        enrolment_status="Active",
    )
    db.add_all([e1, e2, e3])

    # 3. Transfer Request
    trf = TransferRequest(
        id="TRF-SYN-001",
        student_ref="STU-SYN-002",
        apaar_id="9876-2026-0002",
        source_institution_id="INST-TRICHY-NITT",
        source_institution_name="National Institute of Technology Tiruchirappalli (Demo)",
        destination_institution_id="INST-BLR-PES",
        destination_institution_name="PES University Bengaluru (Demo)",
        source_state="TAMIL_NADU",
        destination_state="KARNATAKA",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        academic_year="2025-2026",
        initiation_date=date(2026, 6, 1),
        requested_effective_date=date(2026, 7, 15),
        status=TransferStatus.PENDING_RELEASE,
        created_by="system_seeder",
    )
    db.add(trf)

    # 4. Alert
    alert = Alert(
        id="ALT-SYN-001",
        student_ref="STU-SYN-003",
        apaar_id="9876-2026-0003",
        alert_type="TEMPORAL_OVERLAP_CONFLICT",
        severity="HIGH",
        status="OPEN",
        title="Simultaneous dual active enrolment conflict detected",
        explanation="Synthetic test alert for temporal evaluation",
    )
    db.add(alert)

    # 5. Certificate
    cert = Certificate(
        certificate_id="CERT-SYN-001",
        student_ref="STU-SYN-001",
        apaar_id="9876-2026-0001",
        student_name="Aarav Sharma",
        institution_id="INST-DELHI-DTU",
        institution_name="Delhi Technological University (Demo)",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science & Engineering",
        issue_date="2026-05-30",
        completion_date="2026-05-15",
        status="VALID",
        signature_algorithm="Ed25519",
        signature_hex="abcdef123456",
        payload_json={"test": "claim"},
    )
    db.add(cert)

    # 6. Users across roles
    AuthService.seed_demo_users(db)
    db.commit()

    yield db
    db.close()


def test_global_search_across_categories(client, seeded_db):
    headers = _create_auth_headers(seeded_db, username="admin", role="administrator")

    # 1. Search student by name
    res = client.get("/api/v1/search?q=Aarav", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(s["title"] == "Aarav Sharma" for s in data["categories"]["students"])

    # 2. Search institution by name
    res_inst = client.get("/api/v1/search?q=Trichy", headers=headers)
    assert res_inst.status_code == 200
    inst_data = res_inst.json()
    assert any("Trichy" in i["title"] or "TRICHY" in i["id"] for i in inst_data["categories"]["institutions"])

    # 3. Search transfer by ID
    res_trf = client.get("/api/v1/search?q=TRF-SYN", headers=headers)
    assert res_trf.status_code == 200
    trf_data = res_trf.json()
    assert any(t["id"] == "TRF-SYN-001" for t in trf_data["categories"]["transfers"])

    # 4. Search credentials
    res_cert = client.get("/api/v1/search?q=CERT-SYN", headers=headers)
    assert res_cert.status_code == 200
    cert_data = res_cert.json()
    assert any(c["id"] == "CERT-SYN-001" for c in cert_data["categories"]["credentials"])


def test_search_scoping_student_role(client, seeded_db):
    # Student role only allowed to see their own records
    headers = _create_auth_headers(
        seeded_db,
        username="student_user_test",
        role="student",
        role_category="STUDENT",
    )
    user = seeded_db.query(User).filter(User.username == "student_user_test").first()
    if user:
        from app.models.student_user import StudentUserLink
        if not seeded_db.query(StudentUserLink).filter(StudentUserLink.user_id == user.id).first():
            seeded_db.add(StudentUserLink(user_id=user.id, student_ref="STU-SYN-001", is_primary=True))
            seeded_db.commit()

    # Re-issue token with linked student_ref
    token, _, _ = TokenManager.create_access_token(user, student_ref="STU-SYN-001")
    headers = {"Authorization": f"Bearer {token}"}

    # Query for own profile (Aarav) -> should match
    res_own = client.get("/api/v1/search?q=Aarav", headers=headers)
    assert res_own.status_code == 200
    assert len(res_own.json()["categories"]["students"]) == 1
    assert res_own.json()["categories"]["students"][0]["id"] == "STU-SYN-001"

    # Query for another student (Karthik) -> strictly scoped out (0 results)
    res_other = client.get("/api/v1/search?q=Karthik", headers=headers)
    assert res_other.status_code == 200
    assert len(res_other.json()["categories"]["students"]) == 0


def test_search_scoping_state_officer(client, seeded_db):
    # State officer for Tamil Nadu
    headers = _create_auth_headers(
        seeded_db,
        username="tn_officer_test",
        role="state_officer",
        role_category="STATE_OFFICER",
        state="TAMIL_NADU",
    )

    # Search institutions: should only return Tamil Nadu institutions
    res = client.get("/api/v1/search?q=INST", headers=headers)
    assert res.status_code == 200
    data = res.json()
    insts = data["categories"]["institutions"]
    assert all(i["metadata"]["state"] == "TAMIL_NADU" for i in insts if i["metadata"].get("state"))


def test_institution_list_endpoint(client, seeded_db):
    headers = _create_auth_headers(seeded_db, username="admin", role="administrator")

    # List all
    res = client.get("/api/v1/institution/list", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 3
    assert "items" in data

    # Filter by state
    res_tn = client.get("/api/v1/institution/list?state=TAMIL_NADU", headers=headers)
    assert res_tn.status_code == 200
    tn_data = res_tn.json()
    assert all(i["state"] == "TAMIL_NADU" for i in tn_data["items"])
    assert any("TRICHY" in i["institution_id"] for i in tn_data["items"])

    # Search by college text
    res_search = client.get("/api/v1/institution/list?search=PES", headers=headers)
    assert res_search.status_code == 200
    pes_data = res_search.json()
    assert any("PES" in i["institution_id"] for i in pes_data["items"])


def test_transfers_list_and_search_endpoint(client, seeded_db):
    headers = _create_auth_headers(seeded_db, username="admin", role="administrator")

    # Search transfer
    res = client.get("/api/v1/transfers?search=TRF-SYN-001", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "TRF-SYN-001"

    # Filter by status
    res_status = client.get("/api/v1/transfers?status=PENDING_RELEASE", headers=headers)
    assert res_status.status_code == 200
    assert res_status.json()["total"] >= 1

    # Filter by source state
    res_state = client.get("/api/v1/transfers?source_state=TAMIL_NADU", headers=headers)
    assert res_state.status_code == 200
    assert res_state.json()["total"] >= 1


def test_students_state_filter_endpoint(client, seeded_db):
    headers = _create_auth_headers(seeded_db, username="admin", role="administrator")

    # List students with state filter
    res_tn = client.get("/api/v1/students?state=TAMIL_NADU", headers=headers)
    assert res_tn.status_code == 200
    tn_data = res_tn.json()
    assert any(s["student_ref"] == "STU-SYN-002" for s in tn_data["items"])
    assert not any(s["student_ref"] == "STU-SYN-001" for s in tn_data["items"])


def test_zero_religion_and_caste_collection(seeded_db):
    """Ensure absolutely ZERO religion or caste columns exist in any table."""
    inspector = inspect(seeded_db.get_bind())
    tables = inspector.get_table_names()

    forbidden_keywords = ["religion", "caste", "religious", "faith", "creed", "subcaste"]

    for table in tables:
        columns = [c["name"].lower() for c in inspector.get_columns(table)]
        for kw in forbidden_keywords:
            matching = [col for col in columns if kw in col]
            assert not matching, (
                f"PRIVACY VIOLATION: Forbidden column(s) {matching} found in table '{table}'."
            )
