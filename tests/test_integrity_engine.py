import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.services.integrity_engine import TemporalIntegrityEngine, intervals_overlap

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()

def test_intervals_overlap_function():
    # 1. Non-overlapping completed -> active
    overlap, _, _, _ = intervals_overlap(
        date(2025, 8, 1), date(2026, 5, 31), "Completed",
        date(2026, 8, 1), None, "Active"
    )
    assert overlap is False

    # 2. Overlapping both active
    overlap, o_start, o_end, detail = intervals_overlap(
        date(2026, 7, 1), None, "Active",
        date(2026, 8, 1), None, "Active"
    )
    assert overlap is True
    assert o_start == date(2026, 8, 1)

    # 3. Withdrawn before new start
    overlap, _, _, _ = intervals_overlap(
        date(2025, 8, 1), date(2025, 11, 15), "Withdrawn",
        date(2025, 12, 1), None, "Active"
    )
    assert overlap is False

def test_scenario_a_legitimate_transfer(test_db):
    """
    Scenario A: A student attends College A from Aug 2025 to May 2026 (Completed),
    then attends College B in Aug 2026 (Active).
    Expected: No overlapping active enrolment alert.
    """
    s = Student(student_ref="STU-A", apaar_id="9999-0001", full_name="Student A")
    e1 = Enrolment(
        student_ref="STU-A", apaar_id="9999-0001", institution_id="COLLEGE-A",
        programme_id="BTECH-CSE", academic_year="2025-2026", admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1), enrolment_end=date(2026, 5, 31),
        enrolment_status="Completed"
    )
    e2 = Enrolment(
        student_ref="STU-A", apaar_id="9999-0001", institution_id="COLLEGE-B",
        programme_id="BTECH-CSE", academic_year="2026-2027", admission_cycle="Lateral 2026",
        enrolment_start=date(2026, 8, 1), enrolment_end=None,
        enrolment_status="Active"
    )
    test_db.add_all([s, e1, e2])
    test_db.commit()

    engine = TemporalIntegrityEngine(test_db)
    result = engine.evaluate_student("STU-A")

    assert result["status"] == "COMPLIANT_TRANSFER"
    assert len(result["alerts"]) == 0
    assert test_db.query(Alert).filter(Alert.student_ref == "STU-A").count() == 0

def test_scenario_b_overlapping_active_enrolments(test_db):
    """
    Scenario B: A student has an active record at College C starting July 2026
    and another active record at College D starting Aug 2026, both with no end dates.
    Expected: Generates a potential conflict alert (TEMPORAL_OVERLAP_CONFLICT, HIGH severity).
    """
    s = Student(student_ref="STU-B", apaar_id="9999-0002", full_name="Student B")
    e1 = Enrolment(
        student_ref="STU-B", apaar_id="9999-0002", institution_id="COLLEGE-C",
        programme_id="BTECH-AI", academic_year="2026-2027", admission_cycle="Regular 2026",
        enrolment_start=date(2026, 7, 1), enrolment_end=None,
        enrolment_status="Active"
    )
    e2 = Enrolment(
        student_ref="STU-B", apaar_id="9999-0002", institution_id="COLLEGE-D",
        programme_id="BTECH-ECE", academic_year="2026-2027", admission_cycle="Regular 2026",
        enrolment_start=date(2026, 8, 1), enrolment_end=None,
        enrolment_status="Active"
    )
    test_db.add_all([s, e1, e2])
    test_db.commit()

    engine = TemporalIntegrityEngine(test_db)
    result = engine.evaluate_student("STU-B")

    assert result["status"] == "REQUIRES_INVESTIGATION"
    assert len(result["alerts"]) == 1
    alert = result["alerts"][0]
    assert alert["alert_type"] == "TEMPORAL_OVERLAP_CONFLICT"
    assert alert["severity"] == "HIGH"
    assert "Concurrent active enrolment" in alert["explanation"] or "overlaps" in alert["explanation"]
    evidence = alert["evidence_summary"]
    assert evidence["rule_id"] == "TEMPORAL-OVERLAP-001"
    assert evidence["rule_version"]
    assert "institution_id" in evidence["triggered_fields"]
    assert evidence["recommended_action"]
    assert "9999-0002" not in str(evidence)

def test_scenario_c_documented_permitted_exception(test_db):
    """
    Scenario C: A student has overlapping records but one record contains an exception reference.
    Expected: Generates an exception-review alert (EXCEPTION_REVIEW_REQUIRED, MEDIUM severity).
    Does NOT automatically clear or declare compliant.
    """
    s = Student(student_ref="STU-C", apaar_id="9999-0003", full_name="Student C")
    e1 = Enrolment(
        student_ref="STU-C", apaar_id="9999-0003", institution_id="COLLEGE-E",
        programme_id="BTECH-MECH", academic_year="2025-2026", admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1), enrolment_end=None,
        enrolment_status="Active"
    )
    e2 = Enrolment(
        student_ref="STU-C", apaar_id="9999-0003", institution_id="COLLEGE-F",
        programme_id="DUAL-DEGREE", academic_year="2025-2026", admission_cycle="Joint 2025",
        enrolment_start=date(2025, 10, 1), enrolment_end=None,
        enrolment_status="Active",
        exception_ref="AICTE-EXC-2025-DUAL-04"
    )
    test_db.add_all([s, e1, e2])
    test_db.commit()

    engine = TemporalIntegrityEngine(test_db)
    result = engine.evaluate_student("STU-C")

    assert result["status"] == "EXCEPTION_REVIEW"
    assert len(result["alerts"]) == 1
    alert = result["alerts"][0]
    assert alert["alert_type"] == "EXCEPTION_REVIEW_REQUIRED"
    assert alert["severity"] == "MEDIUM"
    assert "AICTE-EXC-2025-DUAL-04" in alert["explanation"]

def test_duplicate_submission_detection(test_db):
    """
    Duplicate submission: same student, same institution, same programme, same cycle.
    Expected: DUPLICATE_SUBMISSION alert (LOW severity), not confused with temporal conflict.
    """
    s = Student(student_ref="STU-D", apaar_id="9999-0004", full_name="Student D")
    e1 = Enrolment(
        student_ref="STU-D", apaar_id="9999-0004", institution_id="COLLEGE-A",
        programme_id="BTECH-CSE", academic_year="2025-2026", admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1), enrolment_end=None, enrolment_status="Active",
        source_submission_id="SUB-1", record_version=1
    )
    e2 = Enrolment(
        student_ref="STU-D", apaar_id="9999-0004", institution_id="COLLEGE-A",
        programme_id="BTECH-CSE", academic_year="2025-2026", admission_cycle="Regular 2025",
        enrolment_start=date(2025, 8, 1), enrolment_end=None, enrolment_status="Active",
        source_submission_id="SUB-2", record_version=2
    )
    test_db.add_all([s, e1, e2])
    test_db.commit()

    engine = TemporalIntegrityEngine(test_db)
    result = engine.evaluate_student("STU-D")

    assert len(result["alerts"]) == 1
    alert = result["alerts"][0]
    assert alert["alert_type"] == "DUPLICATE_SUBMISSION"
    assert alert["severity"] == "LOW"
