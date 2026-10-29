import pytest
from app.adapters.digilocker_adapter import DigiLockerAdapter
from app.adapters.abc_adapter import AcademicBankOfCreditsAdapter
from app.adapters.aicte_adapter import AICTEApprovalAdapter


def test_digilocker_adapter_mock_contracts():
    assert DigiLockerAdapter.IS_MOCK is True
    res = DigiLockerAdapter.push_academic_credential(
        certificate_id="CERT-TEST-001",
        student_name="Ananya Sharma",
        apaar_id="111122223333",
        institution_id="INST-IITB",
        institution_name="Indian Institute of Technology Bombay",
        programme_name="Computer Science",
        completion_date="2026-05-30",
    )
    assert res["is_mock"] is True
    assert res["status"] == "PUSHED_TO_DIGILOCKER_MOCK"
    assert "PROTOTYPE ONLY" in res["disclaimer"]
    assert res["digilocker_uri"].startswith("in.gov.digilocker.")

    status_res = DigiLockerAdapter.fetch_credential_status(res["digilocker_uri"])
    assert status_res["is_mock"] is True
    assert status_res["status"] == "AVAILABLE"


def test_academic_bank_of_credits_mock_contracts():
    assert AcademicBankOfCreditsAdapter.IS_MOCK is True
    credits_res = AcademicBankOfCreditsAdapter.query_student_credits("111122223333")
    assert credits_res["is_mock"] is True
    assert credits_res["query_status"] == "SUCCESS_MOCK"
    assert credits_res["total_credits_accumulated"] == 160.0

    dep_res = AcademicBankOfCreditsAdapter.deposit_academic_credits(
        apaar_id="111122223333",
        student_ref="STU-001",
        institution_id="INST-IITB",
        course_code="CS-401",
        credits_earned=4.0,
        academic_term="Autumn 2025",
    )
    assert dep_res["is_mock"] is True
    assert dep_res["deposit_status"] == "CREDITED_MOCK"


def test_aicte_approval_adapter_mock_contracts():
    assert AICTEApprovalAdapter.IS_MOCK is True
    intake_res = AICTEApprovalAdapter.fetch_approved_intake(
        institution_id="INST-IITB",
        programme_id="BTECH-CSE",
        academic_year="2025-2026",
    )
    assert intake_res["is_mock"] is True
    assert intake_res["sanctioned_intake"] == 120
    assert "EWS" in intake_res["supernumerary_caps"]

    standing_res = AICTEApprovalAdapter.verify_institution_standing("INST-IITB")
    assert standing_res["is_mock"] is True
    assert standing_res["standing"] == "IN_GOOD_STANDING_MOCK"
