from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, Optional
from app.database import get_db
from app.models.enrolment import Enrolment
from app.models.student import Student
from app.models.alert import Alert
from app.models.intake import ApprovedIntake
from app.models.certificate import Certificate
from app.services.reports_service import ReportsService
from app.security import Principal, get_current_principal, mask_sensitive_payload

router = APIRouter(prefix="/aicte", tags=["AICTE Regional Officer Dashboard"])

@router.get("/dashboard-summary")
def get_aicte_dashboard(
    region: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    total_institutions = db.query(ApprovedIntake.institution_id).distinct().count() or db.query(Enrolment.institution_id).distinct().count()
    total_students = db.query(Student).count()
    total_enrolments = db.query(Enrolment).count()
    total_certificates = db.query(Certificate).count()

    # Alerts breakdown
    all_alerts = db.query(Alert).all()
    open_alerts = sum(1 for a in all_alerts if a.status in ["OPEN", "UNDER_REVIEW"])
    resolved_alerts = sum(1 for a in all_alerts if a.status == "RESOLVED")
    high_severity = sum(1 for a in all_alerts if a.severity == "HIGH")
    temporal_conflicts = sum(1 for a in all_alerts if a.alert_type == "TEMPORAL_OVERLAP_CONFLICT")

    # Executive reports
    reports_svc = ReportsService(db)
    reports_data = reports_svc.generate_executive_reports()

    # Institutional compliance overview
    rules = db.query(ApprovedIntake).filter(ApprovedIntake.rule_configured == True).all()
    over_intake_count = len(reports_data["excess_intake_colleges"])

    response = {
        "officer_role": "AICTE Regional Directorate (Northern & Western Oversight)",
        "jurisdiction": region or "All Registered Regional Directorates",
        "total_institutions": total_institutions,
        "total_students": total_students,
        "total_enrolments": total_enrolments,
        "total_certificates": total_certificates,
        "open_investigations": open_alerts,
        "resolved_investigations": resolved_alerts,
        "critical_temporal_conflicts": high_severity,
        "potential_conflicts_count": temporal_conflicts,
        "total_conflicts": temporal_conflicts,
        "non_compliant_colleges": over_intake_count,
        "pending_reviews_by_severity": reports_data["pendency_by_severity"],
        "excess_intake_colleges": reports_data["excess_intake_colleges"],
        "duplicate_enrolment_cases": reports_data["duplicate_enrolment_cases"],
        "region_distribution": reports_data["region_wise_enrolments"],
        "monthly_summary": reports_data["monthly_summary"]
    }
    if principal.role not in {"administrator", "prototype_admin"}:
        response = mask_sensitive_payload(response)
    return response
