from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import Principal, get_current_principal, enforce_state_scope
from app.services.state_service import StateService
from app.services.export_service import ExportService
from app.models.alert import Alert
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.erp import StudentProfile
from app.models.intake import ApprovedIntake


router = APIRouter(prefix="/state", tags=["State Education Official"])


@router.get("/dashboard-summary")
def get_state_dashboard_summary(
    state: Optional[str] = Query(None, description="State jurisdiction code (e.g. DELHI, TAMIL_NADU, MAHARASHTRA)"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Get aggregated state-level education dashboard summary.
    Enforces state-level data isolation: state officers can only view their own state.
    """
    effective_state = enforce_state_scope(principal, state)
    return StateService.get_state_dashboard_summary(db=db, state=effective_state)


@router.get("/institutions")
def list_state_institutions(
    state: Optional[str] = Query(None, description="State jurisdiction code"),
    search: Optional[str] = Query(None, description="Search institution by name or code"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    List institutions within the officer's state jurisdiction with student counts,
    active enrolments, open alerts, and intake compliance summary.
    Supports search, filtering, and pagination.
    """
    effective_state = enforce_state_scope(principal, state)
    items = StateService.get_state_institutions(db=db, state=effective_state)
    if search:
        s = search.strip().lower()
        items = [i for i in items if s in i.get("institution_id", "").lower() or s in i.get("institution_name", "").lower()]
    
    total = len(items)
    start_idx = (page - 1) * limit
    paginated_items = items[start_idx : start_idx + limit]
    return {
        "items": paginated_items,
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/institutions/{institution_id}/students")
def get_state_institution_students(
    institution_id: str,
    programme_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    state: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    List authorized students for an institution within the officer's state jurisdiction.
    """
    effective_state = enforce_state_scope(principal, state)
    state_institutions = StateService.get_institutions_for_state(db, effective_state)
    if institution_id not in state_institutions:
        raise HTTPException(
            status_code=403,
            detail=f"Institution '{institution_id}' is outside your state jurisdiction ({effective_state}).",
        )

    query = db.query(Student, StudentProfile, Enrolment).outerjoin(
        StudentProfile, StudentProfile.student_ref == Student.student_ref
    ).outerjoin(
        Enrolment, Enrolment.student_ref == Student.student_ref
    ).filter(Student.primary_institution_id == institution_id)

    if programme_id:
        query = query.filter(Enrolment.programme_id == programme_id)
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (Student.full_name.ilike(s)) | (Student.student_ref.ilike(s)) | (Student.apaar_id.ilike(s))
        )

    total = query.count()
    results = query.order_by(Student.student_ref.asc()).offset((page - 1) * limit).limit(limit).all()

    items = []
    seen = set()
    for s, p, e in results:
        if s.student_ref in seen:
            continue
        seen.add(s.student_ref)
        items.append({
            "student_ref": s.student_ref,
            "full_name": s.full_name,
            "apaar_id": s.apaar_id,
            "programme_id": e.programme_id if e else (p.department if p else None),
            "institution_id": s.primary_institution_id,
            "department": p.department if p else None,
            "current_semester": p.current_semester if p else 1,
            "batch_year": p.batch_year if p else None,
            "identity_status": s.identity_status,
        })

    return {
        "institution_id": institution_id,
        "state": effective_state,
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/export-csv")
def export_state_summary_csv(
    state: Optional[str] = Query(None, description="State jurisdiction code"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export state institutions and capacity compliance as CSV."""
    effective_state = enforce_state_scope(principal, state)
    items = StateService.get_state_institutions(db=db, state=effective_state)
    headers = [
        "Institution ID", "Institution Name", "State", "Total Students",
        "Active Enrolments", "Open Alerts", "Approved Intake", "Actual Enrolled", "Compliance Status"
    ]
    rows = [
        [
            i.get("institution_id", ""),
            i.get("institution_name", i.get("institution_id", "")),
            effective_state,
            i.get("total_students", 0),
            i.get("active_enrolments", 0),
            i.get("open_alerts", 0),
            i.get("approved_intake_total", 0),
            i.get("actual_intake_total", 0),
            i.get("compliance_status", ""),
        ]
        for i in items
    ]
    csv_data = ExportService.generate_csv(headers, rows)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="state_{effective_state.lower()}_report.csv"'},
    )


@router.get("/export-excel")
def export_state_summary_excel(
    state: Optional[str] = Query(None, description="State jurisdiction code"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export state institutions and capacity compliance as Excel (.xlsx)."""
    effective_state = enforce_state_scope(principal, state)
    items = StateService.get_state_institutions(db=db, state=effective_state)
    headers = [
        "Institution ID", "Institution Name", "State", "Total Students",
        "Active Enrolments", "Open Alerts", "Approved Intake", "Actual Enrolled", "Compliance Status"
    ]
    rows = [
        [
            i.get("institution_id", ""),
            i.get("institution_name", i.get("institution_id", "")),
            effective_state,
            i.get("total_students", 0),
            i.get("active_enrolments", 0),
            i.get("open_alerts", 0),
            i.get("approved_intake_total", 0),
            i.get("actual_intake_total", 0),
            i.get("compliance_status", ""),
        ]
        for i in items
    ]
    xlsx_bytes = ExportService.generate_excel(f"{effective_state} Directorate", headers, rows)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="state_{effective_state.lower()}_report.xlsx"'},
    )


@router.get("/transfers")
def list_state_transfers(
    state: Optional[str] = Query(None, description="State jurisdiction code"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    List student transfers involving institutions in the state (inbound, outbound, and intra-state).
    """
    effective_state = enforce_state_scope(principal, state)
    return StateService.get_state_transfers(db=db, state=effective_state)


@router.get("/compliance")
def get_state_compliance_overview(
    state: Optional[str] = Query(None, description="State jurisdiction code"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Get state-level quota, intake compliance, and over-admission audit overview.
    """
    effective_state = enforce_state_scope(principal, state)
    return StateService.get_state_compliance_overview(db=db, state=effective_state)


@router.get("/alerts")
def list_state_alerts(
    state: Optional[str] = Query(None, description="State jurisdiction code"),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    List unresolved and critical integrity alerts for institutions within the state jurisdiction.
    """
    effective_state = enforce_state_scope(principal, state)
    state_institutions = StateService.get_institutions_for_state(db, effective_state)
    if not state_institutions:
        return []

    state_students = db.query(Student.student_ref).filter(
        Student.primary_institution_id.in_(state_institutions)
    ).distinct().scalar_subquery()
    query = db.query(Alert).filter(Alert.student_ref.in_(state_students))
    if status_filter:
        query = query.filter(Alert.status == status_filter)
    alerts = query.order_by(Alert.created_at.desc()).all()

    return [
        {
            "id": a.id,
            "student_ref": a.student_ref,
            "apaar_id": a.apaar_id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "explanation": a.explanation,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]
