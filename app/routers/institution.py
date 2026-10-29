from fastapi import APIRouter, Depends, Query, HTTPException, Body, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, Optional, List
from app.database import get_db
from app.models.enrolment import Enrolment
from app.models.student import Student
from app.models.alert import Alert
from app.models.intake import ApprovedIntake
from app.models.consent import StudentConsent
from app.security import Principal, enforce_institution_scope, mask_identifier, get_current_principal
from app.services.state_service import KNOWN_INSTITUTION_STATES, STATE_NAMES
from app.services.erp_service import ErpService

router = APIRouter(prefix="/institution", tags=["Institution Dashboard"])


@router.get("/list", response_model=Dict[str, Any])
def list_institutions(
    search: Optional[str] = Query(None, description="Search by institution name or code"),
    state: Optional[str] = Query(None, description="Filter by state name or code"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    academic_year: Optional[str] = Query("2025-2026"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Searchable, filterable directory of institutions across India.
    State officers automatically scoped to institutions in their jurisdiction.
    """
    # 1. Distinct institutions from ApprovedIntake
    query = db.query(
        ApprovedIntake.institution_id,
        ApprovedIntake.institution_name,
    ).distinct()

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (ApprovedIntake.institution_id.ilike(s)) |
            (ApprovedIntake.institution_name.ilike(s))
        )

    # State Scoping / Filtering
    target_state = principal.state if principal.role == "state_officer" else state
    if target_state:
        st_clean = target_state.upper().replace(" ", "_")
        matching_ids = [
            inst_id for inst_id, st in KNOWN_INSTITUTION_STATES.items()
            if st.upper().replace(" ", "_") == st_clean
        ]
        query = query.filter(ApprovedIntake.institution_id.in_(matching_ids))

    all_distinct = query.all()
    total = len(all_distinct)

    # Pagination
    offset = (page - 1) * limit
    paginated = all_distinct[offset : offset + limit]

    items = []
    for inst_id, inst_name in paginated:
        st_code = KNOWN_INSTITUTION_STATES.get(inst_id, "UNKNOWN")
        st_label = STATE_NAMES.get(st_code, st_code.replace("_", " ").title())

        # Total programmes and sanctioned seats
        intakes = db.query(ApprovedIntake).filter(
            ApprovedIntake.institution_id == inst_id,
            ApprovedIntake.academic_year == academic_year,
        ).all()
        sanctioned_seats = sum(r.approved_intake_seats for r in intakes)
        programmes_count = len(intakes)

        # Active students count
        active_students = db.query(Enrolment).filter(
            Enrolment.institution_id == inst_id,
            Enrolment.enrolment_status == "Active",
        ).count()

        items.append({
            "institution_id": inst_id,
            "institution_name": inst_name,
            "state": st_code,
            "state_label": st_label,
            "programmes_count": programmes_count,
            "sanctioned_seats": sanctioned_seats,
            "active_students": active_students,
            "utilization_pct": round((active_students / sanctioned_seats * 100), 1) if sanctioned_seats else 0.0,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit if limit else 1,
    }

@router.get("/dashboard-summary")
def get_institution_dashboard(
    institution_id: Optional[str] = Query(None, description="Current logged-in institution ID"),
    academic_year: Optional[str] = Query("2025-2026"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if principal.role == "institution_officer":
        institution_id = enforce_institution_scope(principal, institution_id)
    else:
        institution_id = institution_id or "INST-DELHI-DTU"

    target_inst_ids = [institution_id]
    if institution_id in ("INST-CHENNAI-SJCE", "INST-DEMO-01", "INST-CHENNAI-SJC"):
        target_inst_ids = ["INST-CHENNAI-SJCE", "INST-DEMO-01", "INST-CHENNAI-SJC"]

    # 1. Total student count in this institution
    inst_enrolments = db.query(Enrolment).filter(Enrolment.institution_id.in_(target_inst_ids))
    if academic_year:
        inst_enrolments = inst_enrolments.filter(Enrolment.academic_year == academic_year)

    enrolment_records = inst_enrolments.all()
    total_enrolments = len(enrolment_records)
    active_students = sum(1 for e in enrolment_records if e.enrolment_status == "Active")
    completed_students = sum(1 for e in enrolment_records if e.enrolment_status == "Completed")
    withdrawn_students = sum(1 for e in enrolment_records if e.enrolment_status == "Withdrawn")

    # 2. Approved Intake utilization for this college
    rules = db.query(ApprovedIntake).filter(
        ApprovedIntake.institution_id.in_(target_inst_ids),
        ApprovedIntake.academic_year == academic_year
    ).all()

    intake_status = []
    total_sanctioned = 0
    total_new_admitted = 0
    seen_progs = set()
    for r in rules:
        if r.programme_id in seen_progs:
            continue
        seen_progs.add(r.programme_id)
        admitted = db.query(func.count(Enrolment.id)).filter(
            Enrolment.institution_id.in_(target_inst_ids),
            Enrolment.programme_id == r.programme_id,
            Enrolment.academic_year == academic_year
        ).scalar() or 0
        total_sanctioned += r.approved_intake_seats
        total_new_admitted += admitted
        intake_status.append({
            "programme_id": r.programme_id,
            "programme_name": r.programme_name,
            "approved_seats": r.approved_intake_seats,
            "admitted_seats": admitted,
            "supernumerary_quota": r.supernumerary_quota,
            "nri_quota": r.nri_quota,
            "utilization_pct": round((admitted / r.approved_intake_seats * 100), 1) if r.approved_intake_seats else 0
        })

    # 3. Alerts involving this institution's students
    # Find student_refs belonging to this institution
    inst_student_refs = [e.student_ref for e in enrolment_records]
    inst_alerts = db.query(Alert).filter(Alert.student_ref.in_(inst_student_refs)).all() if inst_student_refs else []
    if principal.role == "institution_officer":
        visible_alerts = []
        for alert in inst_alerts:
            if not alert.supporting_record_ids:
                continue
            record_count = db.query(Enrolment.id).filter(
                Enrolment.id.in_(alert.supporting_record_ids),
                Enrolment.institution_id == institution_id,
            ).count()
            if record_count == len(set(alert.supporting_record_ids)):
                visible_alerts.append(alert)
        inst_alerts = visible_alerts

    open_alerts_count = sum(1 for a in inst_alerts if a.status != "RESOLVED")

    # 4. Consent coverage
    consented_count = db.query(StudentConsent).filter(
        StudentConsent.student_ref.in_(inst_student_refs),
        StudentConsent.consent_granted == True,
        StudentConsent.status == "ACTIVE"
    ).count() if inst_student_refs else 0

    return {
        "institution_id": institution_id,
        "institution_name": rules[0].institution_name if rules else "Delhi Technological University (Demo)",
        "academic_year": academic_year,
        "total_enrolments": total_enrolments,
        "active_students": active_students,
        "completed_students": completed_students,
        "withdrawn_students": withdrawn_students,
        "total_sanctioned_intake": total_sanctioned,
        "total_new_admitted": total_new_admitted,
        "overall_capacity_utilization": round((total_new_admitted / total_sanctioned * 100), 1) if total_sanctioned else 0,
        "open_integrity_signals": open_alerts_count,
        "consent_coverage_count": consented_count,
        "programmes": intake_status,
        "recent_alerts": [
            {
                "id": a.id,
                "student_ref": a.student_ref,
                "apaar_id": a.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(a.apaar_id),
                "title": a.title,
                "severity": a.severity,
                "status": a.status,
                "reviewer_decision": a.reviewer_decision
            }
            for a in inst_alerts[:5]
        ]
    }


# =============================================================================
# COLLEGE STUDENT ERP MANAGEMENT & WORKFLOW REVIEWS
# =============================================================================
@router.get("/students")
def get_institution_students_roster(
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    search: Optional[str] = Query(None, description="Search by name, student_ref, or APAAR ID"),
    department: Optional[str] = Query(None, description="Filter by department"),
    profile_status: Optional[str] = Query(None, description="Filter by profile status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve paginated roster of students belonging to the caller's institution.
    Enforces strict institutional boundary.
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    return ErpService.get_college_students_roster(
        db=db,
        institution_id=inst_id,
        search=search,
        department=department,
        profile_status=profile_status,
        page=page,
        page_size=page_size,
    )


@router.get("/students/{student_ref}")
def get_institution_student_detail(
    student_ref: str,
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve full 5-tab student record for college verification and academic administration.
    Enforces that student belongs to caller's institution.
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    return ErpService.get_college_student_detail(
        db=db,
        institution_id=inst_id,
        student_ref=student_ref,
    )


@router.post("/students/{student_ref}/review-profile")
def review_student_profile(
    student_ref: str,
    payload: Dict[str, Any] = Body(...),
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    College registrar reviews and approves/rejects a submitted student profile.
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    action = payload.get("action", "APPROVE")
    remarks = payload.get("remarks", "Approved by Admissions Cell")
    return ErpService.review_student_profile(
        db=db,
        institution_id=inst_id,
        student_ref=student_ref,
        action=action,
        remarks=remarks,
        reviewer=principal.subject,
    )


@router.post("/documents/{document_id}/verify")
def verify_student_document(
    document_id: int,
    payload: Dict[str, Any] = Body(...),
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    College registrar verifies or rejects an uploaded student document.
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    action = payload.get("action", "VERIFY")
    remarks = payload.get("remarks", "Document verified against institutional records.")
    return ErpService.verify_student_document(
        db=db,
        institution_id=inst_id,
        document_id=document_id,
        action=action,
        remarks=remarks,
        reviewer=principal.subject,
    )


@router.post("/students/{student_ref}/update-academic")
def update_student_academic(
    student_ref: str,
    payload: Dict[str, Any] = Body(...),
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    College faculty/registrar updates examination marks or attendance for a student course.
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    course_code = payload.get("course_code")
    if not course_code:
        raise HTTPException(status_code=400, detail="course_code is required.")

    return ErpService.update_academic_course_and_attendance(
        db=db,
        institution_id=inst_id,
        student_ref=student_ref,
        course_code=course_code,
        internal_marks=payload.get("internal_marks"),
        external_marks=payload.get("external_marks"),
        attended_classes=payload.get("attended_classes"),
        total_classes=payload.get("total_classes"),
        reviewer=principal.subject,
    )


@router.post("/internships/{internship_id}/review")
def review_student_internship(
    internship_id: int,
    payload: Dict[str, Any] = Body(...),
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    College coordinator reviews and approves/rejects an internship application.
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    action = payload.get("action", "APPROVE")
    feedback = payload.get("feedback", "Internship approved for academic credit.")
    return ErpService.review_internship(
        db=db,
        institution_id=inst_id,
        internship_id=internship_id,
        action=action,
        feedback=feedback,
        reviewer=principal.subject,
    )


@router.post("/clearances/{clearance_id}/review")
def review_no_due_clearance(
    clearance_id: int,
    payload: Dict[str, Any] = Body(...),
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Departmental head signs off on No Due clearance item (e.g., Library, Lab, Accounts).
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    action = payload.get("action", "APPROVE")
    remarks = payload.get("remarks", "No pending departmental dues.")
    return ErpService.review_no_due_clearance(
        db=db,
        institution_id=inst_id,
        clearance_id=clearance_id,
        action=action,
        remarks=remarks,
        reviewer=principal.subject,
    )


@router.post("/fees/record-payment")
def record_student_fee_payment(
    payload: Dict[str, Any] = Body(...),
    institution_id: Optional[str] = Query(None, description="Target institution ID"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Finance office records a verified student fee payment voucher.
    """
    inst_id = enforce_institution_scope(principal, institution_id or principal.institution_id or "INST-DELHI-DTU")
    obligation_id = int(payload.get("obligation_id", 0))
    amount = float(payload.get("amount", 0.0))
    payment_method = payload.get("payment_method", "Bank Challan")
    transaction_ref = payload.get("transaction_ref") or f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    receipt_number = payload.get("receipt_number") or f"RCPT-{inst_id[-3:]}-{datetime.now().strftime('%y%m%d%H%M')}"

    return ErpService.record_fee_payment(
        db=db,
        institution_id=inst_id,
        obligation_id=obligation_id,
        amount=amount,
        payment_method=payment_method,
        transaction_ref=transaction_ref,
        receipt_number=receipt_number,
        recorder=principal.subject,
    )

