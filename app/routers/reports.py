import csv
import io
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.reports_service import ReportsService
from app.security import Principal, enforce_institution_scope, get_current_principal, mask_sensitive_payload

router = APIRouter(prefix="/reports", tags=["Executive Reports"])

@router.get("/executive-summary")
def get_executive_reports(
    institution_id: str | None = Query(None),
    programme_id: str | None = Query(None),
    academic_year: str | None = Query(None),
    admission_cycle: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")
    institution_id = enforce_institution_scope(principal, institution_id)
    svc = ReportsService(db)
    report = svc.generate_executive_reports(
        institution_id=institution_id,
        programme_id=programme_id,
        academic_year=academic_year,
        admission_cycle=admission_cycle,
        start_date=start_date,
        end_date=end_date,
    )
    if principal.role not in {"administrator", "prototype_admin"}:
        report = mask_sensitive_payload(report)
    return report


@router.get("/executive-summary/export")
def export_executive_reports(
    institution_id: str | None = Query(None),
    programme_id: str | None = Query(None),
    academic_year: str | None = Query(None),
    admission_cycle: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")
    institution_id = enforce_institution_scope(principal, institution_id)
    report = ReportsService(db).generate_executive_reports(
        institution_id=institution_id,
        programme_id=programme_id,
        academic_year=academic_year,
        admission_cycle=admission_cycle,
        start_date=start_date,
        end_date=end_date,
    )
    if principal.role not in {"administrator", "prototype_admin"}:
        report = mask_sensitive_payload(report)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "record_type", "institution_id", "programme_id", "academic_year", "admission_cycle",
        "status", "approved_intake", "new_admissions", "total_active_students", "utilization_pct",
        "alert_id", "import_job_id", "row_number", "record_reference", "details",
    ])
    for item in report["intake_compliance_results"]:
        writer.writerow([
            "INTAKE_COMPLIANCE", item.get("institution_id"), item.get("programme_id"),
            item.get("academic_year"), item.get("admission_cycle"), item.get("compliance_status"),
            item.get("approved_intake"), item.get("new_admissions_count"),
            item.get("total_active_all_cohorts"), item.get("utilization_pct"), "", "", "", "",
            item.get("explanation") or item.get("summary"),
        ])
    for item in report["pending_cases"]:
        writer.writerow([
            "PENDING_REVIEW", institution_id or "", programme_id or "", academic_year or "",
            admission_cycle or "", item.get("status"), "", "", "", "", item.get("alert_id"),
            "", "", item.get("student_ref"), item.get("days_pending"),
        ])
    for item in report["import_validation_issues"]:
        writer.writerow([
            "IMPORT_VALIDATION", institution_id or "", programme_id or "", academic_year or "",
            admission_cycle or "", item.get("outcome"), "", "", "", "", "",
            item.get("import_job_id"), item.get("row_number"), item.get("record_reference"),
            json.dumps(item.get("validation_messages") or [], ensure_ascii=True),
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=apaar_sentinel_executive_report.csv"},
    )
