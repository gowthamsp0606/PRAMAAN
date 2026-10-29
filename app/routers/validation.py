import csv
import io
from fastapi import APIRouter, Depends, Body, Response
from typing import Dict, Any, List
from app.services.validation_service import ValidationService

router = APIRouter(prefix="/validation", tags=["Automated Validation Centre"])

@router.get("/rules")
def get_validation_rules():
    return {
        "rules": [
            {
                "rule_id": "VAL-REQ-001",
                "name": "Mandatory Schema Attributes",
                "severity": "CRITICAL",
                "description": "Ensures essential educational attributes (student_ref, apaar_id, institution_id, programme_id, academic_year, enrolment_start, status) are non-empty.",
                "scope": "Pre-ingestion Schema Gate"
            },
            {
                "rule_id": "VAL-DAT-001",
                "name": "ISO-8601 Date Parsing",
                "severity": "ERROR",
                "description": "Verifies enrolment_start conforms to standard ISO-8601 YYYY-MM-DD representation.",
                "scope": "Temporal Pre-condition"
            },
            {
                "rule_id": "VAL-DAT-002",
                "name": "ISO-8601 End Date Parsing",
                "severity": "ERROR",
                "description": "Verifies enrolment_end conforms to standard ISO-8601 YYYY-MM-DD representation if provided.",
                "scope": "Temporal Pre-condition"
            },
            {
                "rule_id": "VAL-DAT-003",
                "name": "Chronological Inversion Check",
                "severity": "CRITICAL",
                "description": "Ensures enrolment completion/withdrawal date is strictly on or after enrolment start date.",
                "scope": "Temporal Integrity"
            },
            {
                "rule_id": "VAL-STA-001",
                "name": "Permitted Status Enum",
                "severity": "ERROR",
                "description": "Restricts enrolment_status to sanctioned states: Active, Completed, Withdrawn, Suspended.",
                "scope": "State Transition Model"
            },
            {
                "rule_id": "VAL-FMT-001",
                "name": "Academic Year Standard Format",
                "severity": "WARNING",
                "description": "Checks that academic year conforms to standard four-digit span format (e.g. 2025-2026).",
                "scope": "Institutional Metadata"
            },
            {
                "rule_id": "VAL-DUP-001",
                "name": "Batch Duplicate Row Detection",
                "severity": "CRITICAL",
                "description": "Identifies exact duplicate student-institution-programme rows within the same submission batch.",
                "scope": "Batch Ingestion Hygiene"
            },
            {
                "rule_id": "VAL-PRV-001",
                "name": "Data Source Provenance Tracking",
                "severity": "WARNING",
                "description": "Ensures source_submission_id is attached for end-to-end institutional audit traceability.",
                "scope": "Data Governance"
            },
            {
                "rule_id": "VAL-CAT-001",
                "name": "Supported Admission Category",
                "severity": "ERROR",
                "description": "Requires seat_category to be one of General, SC, ST, OBC, EWS, NRI, OCI, Foreign-National, or Supernumerary-TFW.",
                "scope": "Admission Category Data Quality"
            },
            {
                "rule_id": "VAL-CAT-002",
                "name": "Admission Category and Identity Flags",
                "severity": "ERROR",
                "description": "Rejects explicit false NRI, OCI, or foreign-national classification flags when the matching admission category is selected.",
                "scope": "Admission Classification Consistency"
            }
        ]
    }

@router.post("/test-record")
def test_record_validation(record: Dict[str, Any] = Body(...)):
    errors = ValidationService.validate_record(record)
    has_critical_or_error = any(e["severity"] in ("CRITICAL", "ERROR") for e in errors)
    return {
        "is_valid": not has_critical_or_error,
        "errors": errors,
        "error_count": len(errors),
        "status": "PASS" if not has_critical_or_error else "FAIL"
    }

@router.get("/export-errors-csv")
def export_validation_errors_csv():
    # Return standard CSV of active validation baseline
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rule ID", "Rule Name", "Severity", "Field Scope", "Description", "Standard Remedy"])
    rules = get_validation_rules()["rules"]
    for r in rules:
        writer.writerow([r["rule_id"], r["name"], r["severity"], r["scope"], r["description"], "Remediate format or provide required educational metadata"])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sentinel_validation_diagnostics.csv"}
    )

@router.get("/sample-csv-data")
def get_sample_csv_template():
    return {
        "headers": [
            "student_ref", "apaar_id", "full_name", "institution_id", "institution_name",
            "programme_id", "programme_name", "academic_year", "admission_cycle",
            "enrolment_start", "enrolment_end", "enrolment_status", "seat_category",
            "exception_ref", "source_submission_id", "record_version"
        ],
        "example_rows": [
            {
                "student_ref": "STU-DEMO-101",
                "apaar_id": "9876-5432-1101",
                "full_name": "Siddharth Menon",
                "institution_id": "INST-DELHI-DTU",
                "institution_name": "Delhi Technological University (Demo)",
                "programme_id": "BTECH-CSE",
                "programme_name": "B.Tech Computer Science & Engineering",
                "academic_year": "2025-2026",
                "admission_cycle": "Regular 2025",
                "enrolment_start": "2025-08-01",
                "enrolment_end": "",
                "enrolment_status": "Active",
                "seat_category": "General",
                "exception_ref": "",
                "source_submission_id": "SUB-TEST-IMPORT-01",
                "record_version": "1"
            },
            {
                "student_ref": "STU-DEMO-102",
                "apaar_id": "9876-5432-1102",
                "full_name": "Neha Kulkarni",
                "institution_id": "INST-PUNE-COEP",
                "institution_name": "COEP Technological University (Demo)",
                "programme_id": "BTECH-ECE",
                "programme_name": "B.Tech Electronics & Communication",
                "academic_year": "2025-2026",
                "admission_cycle": "Regular 2025",
                "enrolment_start": "2025-08-01",
                "enrolment_end": "",
                "enrolment_status": "Active",
                "seat_category": "NRI",
                "exception_ref": "",
                "source_submission_id": "SUB-TEST-IMPORT-01",
                "record_version": "1"
            }
        ]
    }
