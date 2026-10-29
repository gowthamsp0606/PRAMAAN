from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_
from typing import Optional
from app.database import get_db
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.audit import AuditLog
from app.models.intake import ApprovedIntake
from app.models.certificate import Certificate
from app.models.import_job import ImportJob
from app.schemas.dashboard import DashboardSummaryResponse
from app.security import Principal, get_current_principal, mask_sensitive_payload, enforce_institution_scope

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    institution_id: Optional[str] = Query(None, description="Optional filter by institution"),
    academic_year: Optional[str] = Query(None, description="Optional filter by academic year"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if principal.role == "institution_officer":
        institution_id = enforce_institution_scope(principal, institution_id)

    enrolment_query = db.query(Enrolment)
    alert_query = db.query(Alert)

    inst_id_val = institution_id if isinstance(institution_id, str) and institution_id.strip() else None
    acad_yr_val = academic_year if isinstance(academic_year, str) and academic_year.strip() else None

    if inst_id_val:
        enrolment_query = enrolment_query.filter(Enrolment.institution_id == inst_id_val)
    if acad_yr_val:
        enrolment_query = enrolment_query.filter(Enrolment.academic_year == acad_yr_val)

    if inst_id_val:
        total_students = db.query(func.count(func.distinct(Enrolment.student_ref))).filter(
            Enrolment.institution_id == inst_id_val
        ).scalar() or 0
        distinct_institutions = 1
    else:
        total_students = db.query(func.count(Student.student_ref)).scalar() or 0
        # AICTE approved institution directory or distinct enrolled institutions
        distinct_institutions = db.query(ApprovedIntake.institution_id).distinct().count() or db.query(Enrolment.institution_id).distinct().count()

    open_alerts = alert_query.filter(Alert.status.in_(["OPEN", "UNDER_REVIEW"])).count()
    records_requiring_review = alert_query.filter(Alert.reviewer_decision == None).count()
    potential_conflicts_count = alert_query.filter(Alert.alert_type == "TEMPORAL_OVERLAP_CONFLICT").count()

    # Severity distribution
    severities = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFORMATIONAL": 0}
    sev_rows = db.query(Alert.severity, func.count(Alert.id)).group_by(Alert.severity).all()
    for s, c in sev_rows:
        if s in severities:
            severities[s] = c

    # Certificate count
    if inst_id_val:
        total_certificates = db.query(Certificate).filter(Certificate.institution_id == inst_id_val).count()
    else:
        total_certificates = db.query(Certificate).count()

    total_enrolments = enrolment_query.count()
    valid_enrolments = enrolment_query.filter(
        func.trim(Enrolment.student_ref) != "",
        func.trim(Enrolment.apaar_id) != "",
        func.trim(Enrolment.institution_id) != "",
        func.trim(Enrolment.programme_id) != "",
        func.trim(Enrolment.academic_year) != "",
        func.trim(Enrolment.admission_cycle) != "",
        Enrolment.enrolment_status.in_(["Active", "Completed", "Withdrawn", "Suspended"]),
        or_(Enrolment.enrolment_end.is_(None), Enrolment.enrolment_end >= Enrolment.enrolment_start)
    ).count()

    # Dynamic validation pass rate reflecting import jobs when available, or enrolled records
    import_jobs_query = db.query(
        func.sum(ImportJob.total_rows),
        func.sum(ImportJob.accepted_rows),
    )
    if inst_id_val:
        import_jobs_query = import_jobs_query.filter(ImportJob.institution_id == inst_id_val)
    job_rows = import_jobs_query.first()

    if job_rows and job_rows[0] and job_rows[0] > 0:
        validation_pass_rate = round((float(job_rows[1] or 0) / float(job_rows[0])) * 100, 1)
    elif total_enrolments > 0:
        validation_pass_rate = round((valid_enrolments / total_enrolments) * 100, 1)
    else:
        validation_pass_rate = 100.0

    # Enrolment trends by academic year
    trends_raw = db.query(
        Enrolment.academic_year,
        func.count(Enrolment.id).label("total"),
        func.sum(case((Enrolment.enrolment_status == "Active", 1), else_=0)).label("active"),
        func.sum(case((Enrolment.enrolment_status == "Completed", 1), else_=0)).label("completed"),
        func.sum(case((Enrolment.enrolment_status == "Withdrawn", 1), else_=0)).label("withdrawn")
    ).group_by(Enrolment.academic_year).all()

    enrolment_trends = [
        {
            "academic_year": r[0],
            "total_enrolments": r[1],
            "active": r[2] or 0,
            "completed": r[3] or 0,
            "withdrawn": r[4] or 0
        }
        for r in trends_raw
    ]

    # Recent Audit Activity
    recent_logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(8).all()
    recent_activity = [
        {
            "id": log.id,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "action": log.action,
            "performed_by": log.performed_by,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "details": log.details
        }
        for log in recent_logs
    ]

    # Programme Admissions vs Approved Intake (Only for verified rules!)
    intake_rules = db.query(ApprovedIntake).filter(ApprovedIntake.rule_configured == True).all()
    programme_intake_data = []
    for rule in intake_rules:
        admitted = db.query(func.count(Enrolment.id)).filter(
            Enrolment.institution_id == rule.institution_id,
            Enrolment.programme_id == rule.programme_id,
            Enrolment.academic_year == rule.academic_year
        ).scalar() or 0

        programme_intake_data.append({
            "institution_id": rule.institution_id,
            "institution_name": rule.institution_name,
            "programme_name": rule.programme_name,
            "academic_year": rule.academic_year,
            "approved_intake": rule.approved_intake_seats,
            "new_admitted": admitted,
            "utilization_pct": round((admitted / rule.approved_intake_seats * 100), 1) if rule.approved_intake_seats else 0
        })

    response = {
        "total_students": total_students,
        "total_institutions": distinct_institutions,
        "total_enrolments": total_enrolments,
        "open_alerts": open_alerts,
        "records_requiring_review": records_requiring_review,
        "validation_pass_rate": validation_pass_rate,
        "potential_conflicts_count": potential_conflicts_count,
        "total_conflicts": potential_conflicts_count,
        "total_certificates": total_certificates,
        "total_alerts": open_alerts,
        "stats": {
            "total_students": total_students,
            "total_institutions": distinct_institutions,
            "total_enrolments": total_enrolments,
            "total_conflicts": potential_conflicts_count,
            "total_certificates": total_certificates,
            "total_alerts": open_alerts,
            "validation_pass_rate": validation_pass_rate,
        },
        "alert_severity_distribution": severities,
        "enrolment_trends": enrolment_trends,
        "recent_activity": recent_activity,
        "programme_admissions_vs_intake": programme_intake_data
    }
    if principal.role not in {"administrator", "prototype_admin"}:
        response = mask_sensitive_payload(response)
    return response
