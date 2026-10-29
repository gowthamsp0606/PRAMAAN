import pytest
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.consent import StudentConsent
from app.models.transfer import TransferRequest, TransferStatus
from app.models.intake import ApprovedIntake, HistoricalIntake
from app.models.user import User
from app.services.auth_service import AuthService, PasswordHasher
from app.adapters.tamil_nadu_umis_adapter import tn_umis_adapter, TamilNaduUMISAdapter
from app.services.state_service import StateService
from app.services.scholarship_service import ScholarshipService
import app.seed_data as seed_data


@pytest.fixture
def master_env(db_sessions):
    prev_auth = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = True

    seed_data.init_db_and_seed()
    with db_sessions() as db:
        AuthService.seed_demo_users(db)

        # Seed sample intake records for state compliance
        if not db.query(ApprovedIntake).filter(ApprovedIntake.institution_id == "INST-DELHI-DTU").first():
            db.add(ApprovedIntake(
                institution_id="INST-DELHI-DTU",
                institution_name="Delhi Technological University",
                programme_id="BTECH-CSE",
                programme_name="Computer Science",
                academic_year="2025-2026",
                admission_cycle="Regular",
                approved_intake_seats=120,
            ))
            db.add(ApprovedIntake(
                institution_id="INST-TRICHY-NITT",
                institution_name="National Institute of Technology, Trichy",
                programme_id="BTECH-ECE",
                programme_name="Electronics and Communication",
                academic_year="2025-2026",
                admission_cycle="Regular",
                approved_intake_seats=100,
            ))
        if not db.query(HistoricalIntake).filter(HistoricalIntake.institution_id == "INST-TRICHY-NITT").first():
            db.add(HistoricalIntake(
                institution_id="INST-TRICHY-NITT",
                institution_name="National Institute of Technology, Trichy",
                programme_id="BTECH-ECE",
                programme_name="Electronics and Communication",
                academic_year="2025-2026",
                admitted_count=98,
                approved_intake=100,
            ))

        # Seed a sample transfer involving TN institution
        if not db.query(TransferRequest).filter(TransferRequest.id == "TRF-TN-TEST-01").first():
            db.add(TransferRequest(
                id="TRF-TN-TEST-01",
                student_ref="STU-DEMO-001",
                apaar_id="9876-5432-1001",
                source_institution_id="INST-TRICHY-NITT",
                source_institution_name="National Institute of Technology, Trichy",
                destination_institution_id="INST-DELHI-DTU",
                destination_institution_name="Delhi Technological University",
                source_state="TAMIL_NADU",
                destination_state="DELHI",
                programme_id="BTECH-CSE",
                programme_name="Computer Science and Engineering",
                academic_year="2025-2026",
                initiation_date=date(2026, 6, 1),
                requested_effective_date=date(2026, 7, 15),
                status=TransferStatus.RELEASED,
                noc_certificate_ref="NOC-INST-TRICHY-NITT-0001",
                created_by="tn_state_officer",
            ))

        # Seed an alert for STU-DEMO-001 (whose primary institution is INST-DELHI-DTU)
        if not db.query(Alert).filter(Alert.id == "ALT-STATE-TEST-01").first():
            db.add(Alert(
                id="ALT-STATE-TEST-01",
                student_ref="STU-DEMO-001",
                apaar_id="9876-5432-1001",
                alert_type="TEMPORAL_OVERLAP_CONFLICT",
                severity="HIGH",
                title="Simulated overlap warning",
                explanation="Simulated overlap warning for state dashboard testing",
                status="OPEN",
            ))

        db.commit()

    yield TestClient(app)
    settings.AUTH_REQUIRED = prev_auth


def _login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_state_official_authentication_and_claims(master_env):
    """Verify state education officials authenticate with correct role and state claims."""
    headers_delhi = _login(master_env, "delhi_state_officer", "DelhiOfficer@2026!")
    resp_me = master_env.get("/api/v1/auth/me", headers=headers_delhi)
    assert resp_me.status_code == 200
    user_info = resp_me.json()
    assert user_info["role"] == "state_officer"
    assert user_info["role_category"] == "STATE_EDUCATION_OFFICIAL"

    headers_tn = _login(master_env, "tn_state_officer", "TnOfficer@2026!")
    resp_tn_me = master_env.get("/api/v1/auth/me", headers=headers_tn)
    assert resp_tn_me.status_code == 200
    assert resp_tn_me.json()["role"] == "state_officer"


def test_state_dashboard_summary_and_cross_state_isolation(master_env):
    """Verify state education officials can access their state dashboard and are blocked from cross-state data."""
    headers_delhi = _login(master_env, "delhi_state_officer", "DelhiOfficer@2026!")

    # 1. Access own state dashboard (Delhi)
    resp = master_env.get("/api/v1/state/dashboard-summary", headers=headers_delhi)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state_code"] == "DELHI"
    assert "metrics" in data
    assert "transfer_metrics" in data
    assert data["institutions_count"] >= 1

    # 2. Cross-state attempt: Delhi officer tries to request TAMIL_NADU
    resp_cross = master_env.get("/api/v1/state/dashboard-summary?state=TAMIL_NADU", headers=headers_delhi)
    assert resp_cross.status_code == 403
    assert "Cross-state access denied" in resp_cross.json()["detail"]


def test_state_institutions_and_compliance(master_env):
    """Verify state-level institution monitoring and intake quota compliance endpoints."""
    headers_tn = _login(master_env, "tn_state_officer", "TnOfficer@2026!")

    # Institutions in Tamil Nadu
    resp_insts = master_env.get("/api/v1/state/institutions", headers=headers_tn)
    assert resp_insts.status_code == 200
    inst_list = resp_insts.json()
    assert isinstance(inst_list, list)
    for inst in inst_list:
        assert inst["state"] == "TAMIL_NADU"

    # State compliance overview
    resp_comp = master_env.get("/api/v1/state/compliance", headers=headers_tn)
    assert resp_comp.status_code == 200
    comp = resp_comp.json()
    assert comp["state"] == "TAMIL_NADU"
    assert "quota_compliance_rate" in comp
    assert "over_admission_incidents" in comp


def test_state_transfers_and_alerts_scoping(master_env):
    """Verify state transfers and alerts are scoped to institutions within the state jurisdiction."""
    headers_delhi = _login(master_env, "delhi_state_officer", "DelhiOfficer@2026!")

    # State transfers
    resp_trf = master_env.get("/api/v1/state/transfers", headers=headers_delhi)
    assert resp_trf.status_code == 200
    transfers = resp_trf.json()
    assert isinstance(transfers, list)
    # The seeded transfer TRF-TN-TEST-01 has destination INST-DELHI-DTU, so it should be in Delhi transfers (INBOUND)
    matching = [t for t in transfers if t["transfer_id"] == "TRF-TN-TEST-01"]
    assert len(matching) == 1
    assert matching[0]["direction"] == "INBOUND"

    # State alerts
    resp_alerts = master_env.get("/api/v1/state/alerts", headers=headers_delhi)
    assert resp_alerts.status_code == 200
    alerts = resp_alerts.json()
    assert isinstance(alerts, list)


def test_state_official_read_only_and_forbidden_write(master_env):
    """Verify state officers cannot execute state-modifying write operations (POST, PATCH)."""
    headers_delhi = _login(master_env, "delhi_state_officer", "DelhiOfficer@2026!")

    # Attempt to initiate a transfer
    resp = master_env.post(
        "/api/v1/transfers/initiate",
        json={
            "student_ref": "STU-DEMO-001",
            "source_institution_id": "INST-DELHI-DTU",
            "destination_institution_id": "INST-DELHI-IIITD",
            "programme_id": "BTECH-CSE",
            "academic_year": "2025-2026",
            "requested_effective_date": "2026-08-01",
        },
        headers=headers_delhi,
    )
    assert resp.status_code == 403
    assert "not permitted" in resp.json()["detail"].lower()


def test_tamil_nadu_umis_adapter_unit():
    """Unit test for Tamil Nadu UMIS / DOTE adapter simulation."""
    adapter = TamilNaduUMISAdapter()
    assert adapter.provider_code == "TN_UMIS"
    assert adapter.is_mock is True
    assert adapter.integration_status == "BLOCKED_BY_EXTERNAL_ACCESS"

    # Student clearance check
    clearance = adapter.verify_student_clearance("9876-5432-1001", "INST-TRICHY-NITT")
    assert clearance["is_mock"] is True
    assert clearance["clearance_status"] == "CLEARED"
    assert clearance["transfer_eligibility"] is True

    # TC verification
    tc_res = adapter.verify_transfer_certificate("NOC-INST-TRICHY-NITT-0001", "INST-TRICHY-NITT")
    assert tc_res["is_authentic"] is True
    assert tc_res["validity"] == "VALID"

    # Source reconciliation
    recon = adapter.reconcile_transfer_source(
        transfer_id="TRF-TN-TEST-01",
        student_ref="STU-DEMO-001",
        apaar_id="9876-5432-1001",
        source_institution_id="INST-TRICHY-NITT",
        noc_ref="NOC-INST-TRICHY-NITT-0001",
    )
    assert recon["reconciliation_status"] == "SOURCE_VERIFIED"
    assert recon["reconciliation_score"] == 100.0


def test_transfer_reconcile_source_endpoint(master_env):
    """Test the API endpoint for reconciling a transfer against source state registries."""
    headers_admin = _login(master_env, "admin", "PramaanAdmin@2026!")

    resp = master_env.get("/api/v1/transfers/TRF-TN-TEST-01/reconcile-source", headers=headers_admin)
    assert resp.status_code == 200
    data = resp.json()
    assert data["transfer_id"] == "TRF-TN-TEST-01"
    assert data["reconciliation_status"] == "SOURCE_VERIFIED"
    assert "clearance_check" in data
    assert "noc_validation" in data


def test_scholarship_evaluation_service(master_env):
    """Verify scholarship eligibility evaluation, DPDP consent enforcement, and privacy rules."""
    headers_admin = _login(master_env, "admin", "PramaanAdmin@2026!")

    # 1. Single student evaluation
    resp = master_env.get("/api/v1/scholarship/evaluations/STU-DEMO-001", headers=headers_admin)
    assert resp.status_code == 200
    data = resp.json()
    assert data["student_ref"] == "STU-DEMO-001"
    assert "criteria_checklist" in data
    assert "privacy_compliance" in data
    assert "No caste or religion metrics processed" in data["privacy_compliance"]

    # Verify no religion or caste in response payload
    resp_keys = set(data.keys())
    assert "caste" not in resp_keys
    assert "religion" not in resp_keys
    assert "category" not in resp_keys

    # 2. List scholarship evaluations
    resp_list = master_env.get("/api/v1/scholarship/evaluations?institution_id=INST-DELHI-DTU", headers=headers_admin)
    assert resp_list.status_code == 200
    assert isinstance(resp_list.json(), list)


def test_scholarship_endpoints_role_scoping(master_env):
    """Verify institution officer cannot view evaluations of another institution."""
    headers_inst = _login(master_env, "dtu_registrar", "DtuRegistrar@2026!")

    # DTU registrar requests DTU evaluations -> OK
    resp_own = master_env.get("/api/v1/scholarship/evaluations?institution_id=INST-DELHI-DTU", headers=headers_inst)
    assert resp_own.status_code == 200

    # DTU registrar requests IIITD evaluations -> 403 Forbidden
    resp_cross = master_env.get("/api/v1/scholarship/evaluations?institution_id=INST-DELHI-IIITD", headers=headers_inst)
    assert resp_cross.status_code == 403
