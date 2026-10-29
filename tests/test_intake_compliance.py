import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.enrolment import Enrolment
from app.models.intake import ApprovedIntake
from app.services.intake_service import IntakeComplianceService

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()

def test_intake_dimensions_separation(test_db):
    """
    Verifies that total active enrolment across multiple cohorts
    is NEVER confused with single-year intake limits.
    """
    # Configure rule: 60 approved seats for 2025-2026
    rule = ApprovedIntake(
        institution_id="INST-TEST",
        institution_name="Test Institute",
        programme_id="BTECH-CSE",
        programme_name="B.Tech Computer Science",
        academic_year="2025-2026",
        admission_cycle="Regular 2025",
        approved_intake_seats=60,
        supernumerary_quota=3,
        nri_quota=9,
        rule_configured=True
    )
    test_db.add(rule)

    # 40 new students admitted in 2025-2026
    for i in range(40):
        test_db.add(Enrolment(
            student_ref=f"STU-2025-{i}",
            apaar_id=f"9999-25-{i}",
            institution_id="INST-TEST",
            programme_id="BTECH-CSE",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            enrolment_start=date(2025, 8, 1),
            enrolment_status="Active",
            seat_category="General"
        ))

    # 120 senior students from 2023 and 2024 cohorts still active
    for i in range(120):
        test_db.add(Enrolment(
            student_ref=f"STU-SENIOR-{i}",
            apaar_id=f"9999-SN-{i}",
            institution_id="INST-TEST",
            programme_id="BTECH-CSE",
            academic_year="2024-2025",
            admission_cycle="Regular 2024",
            enrolment_start=date(2024, 8, 1),
            enrolment_status="Active",
            seat_category="General"
        ))

    test_db.commit()

    svc = IntakeComplianceService(test_db)
    report = svc.evaluate_programme_intake("INST-TEST", "BTECH-CSE", "2025-2026", "Regular 2025")

    # New admissions: 40, approved intake: 60 -> COMPLIANT!
    # Total active across all cohorts: 160 (which is larger than 60, but MUST NOT trigger non-compliance!)
    assert report["new_admissions_count"] == 40
    assert report["approved_intake"] == 60
    assert report["total_active_all_cohorts"] == 160
    assert report["compliance_status"] == "COMPLIANT"
