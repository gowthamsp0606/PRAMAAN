from datetime import date
from app.services.validation_service import ValidationService

def test_missing_required_fields():
    record = {
        "student_ref": "STU-VAL-001",
        "apaar_id": "",
        "institution_id": "INST-A"
        # missing programme_id, academic_year, enrolment_start, status
    }
    errors = ValidationService.validate_record(record)
    missing_fields = {e["field"] for e in errors if e["rule_id"] == "VAL-REQ-001"}
    assert "apaar_id" in missing_fields
    assert "programme_id" in missing_fields
    assert "academic_year" in missing_fields
    assert "enrolment_start" in missing_fields

def test_chronological_inversion():
    record = {
        "student_ref": "STU-VAL-002",
        "apaar_id": "9876-0002",
        "institution_id": "INST-A",
        "programme_id": "BTECH-CSE",
        "academic_year": "2025-2026",
        "admission_cycle": "Regular",
        "enrolment_start": "2026-05-01",
        "enrolment_end": "2025-05-01",  # Earlier than start date!
        "enrolment_status": "Active"
    }
    errors = ValidationService.validate_record(record)
    inversion_errors = [e for e in errors if e["rule_id"] == "VAL-DAT-003"]
    assert len(inversion_errors) == 1
    assert inversion_errors[0]["severity"] == "CRITICAL"

def test_invalid_status():
    record = {
        "student_ref": "STU-VAL-003",
        "apaar_id": "9876-0003",
        "institution_id": "INST-A",
        "programme_id": "BTECH-CSE",
        "academic_year": "2025-2026",
        "admission_cycle": "Regular",
        "enrolment_start": "2025-08-01",
        "enrolment_status": "Graduated_Unknown_Status"
    }
    errors = ValidationService.validate_record(record)
    status_errors = [e for e in errors if e["rule_id"] == "VAL-STA-001"]
    assert len(status_errors) == 1

def test_dataset_validation_with_batch_duplicate():
    rows = [
        {
            "student_ref": "STU-001",
            "apaar_id": "9999-001",
            "institution_id": "INST-A",
            "programme_id": "CSE",
            "academic_year": "2025-2026",
            "admission_cycle": "Regular",
            "enrolment_start": "2025-08-01",
            "enrolment_status": "Active",
            "source_submission_id": "SUB-1"
        },
        {
            # Exact duplicate of row 1
            "student_ref": "STU-001",
            "apaar_id": "9999-001",
            "institution_id": "INST-A",
            "programme_id": "CSE",
            "academic_year": "2025-2026",
            "admission_cycle": "Regular",
            "enrolment_start": "2025-08-01",
            "enrolment_status": "Active",
            "source_submission_id": "SUB-2"
        }
    ]
    summary = ValidationService.validate_dataset(rows)
    assert summary["total_records"] == 2
    assert summary["rejected_count"] >= 1
    dup_errors = [e for e in summary["errors"] if e["rule_id"] == "VAL-DUP-001"]
    assert len(dup_errors) == 1
