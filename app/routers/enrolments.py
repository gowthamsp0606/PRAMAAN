from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from app.database import get_db
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.schemas.enrolment import EnrolmentCreate, EnrolmentResponse
from app.services.integrity_engine import TemporalIntegrityEngine
from app.security import Principal, enforce_institution_scope, mask_identifier, mask_sensitive_payload, get_current_principal

router = APIRouter(prefix="/enrolments", tags=["Enrolments"])

@router.get("", response_model=Dict[str, Any])
def list_enrolments(
    student_ref: Optional[str] = Query(None),
    institution_id: Optional[str] = Query(None),
    programme_id: Optional[str] = Query(None),
    enrolment_status: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_id = enforce_institution_scope(principal, institution_id)
    query = db.query(Enrolment)

    if student_ref:
        query = query.filter(Enrolment.student_ref == student_ref)
    if institution_id:
        query = query.filter(Enrolment.institution_id == institution_id)
    if programme_id:
        query = query.filter(Enrolment.programme_id == programme_id)
    if enrolment_status:
        query = query.filter(Enrolment.enrolment_status == enrolment_status)
    if academic_year:
        query = query.filter(Enrolment.academic_year == academic_year)

    total = query.count()
    items = query.order_by(Enrolment.enrolment_start.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "items": [
            {
                "id": e.id,
                "student_ref": e.student_ref,
                "apaar_id": e.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(e.apaar_id),
                "institution_id": e.institution_id,
                "institution_name": e.institution_name,
                "programme_id": e.programme_id,
                "programme_name": e.programme_name,
                "academic_year": e.academic_year,
                "admission_cycle": e.admission_cycle,
                "enrolment_start": e.enrolment_start.isoformat(),
                "enrolment_end": e.enrolment_end.isoformat() if e.enrolment_end else None,
                "enrolment_status": e.enrolment_status,
                "seat_category": e.seat_category,
                "exception_ref": e.exception_ref,
                "source_submission_id": e.source_submission_id,
                "record_version": e.record_version,
                "created_at": e.created_at.isoformat() if e.created_at else None
            }
            for e in items
        ],
        "total": total,
        "page": page,
        "limit": limit
    }


@router.get("/conflicts", response_model=Dict[str, Any])
def list_enrolment_conflicts(
    institution_id: Optional[str] = Query(None),
    programme_id: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    conflict_type: Optional[str] = Query(None, description="DUPLICATE_SUBMISSION, CONCURRENT_ENROLMENT, EXCEPTION_REVIEW_REQUIRED"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    scoped_inst = enforce_institution_scope(principal, institution_id)
    query = db.query(Alert).filter(Alert.status != "RESOLVED")

    if conflict_type:
        query = query.filter(Alert.alert_type == conflict_type)

    alerts = query.order_by(Alert.created_at.desc()).all()
    matching_alerts = []

    for alert in alerts:
        records = []
        if alert.supporting_record_ids:
            records = db.query(Enrolment).filter(Enrolment.id.in_(alert.supporting_record_ids)).all()

        # Institution scoping
        if scoped_inst:
            if not any(r.institution_id == scoped_inst for r in records):
                continue
            if principal.role == "institution_officer":
                # Only show if all records belong to the scoped institution or mask accordingly
                record_insts = {r.institution_id for r in records}
                if not record_insts.issubset({scoped_inst}):
                    continue

        if programme_id and not any(r.programme_id == programme_id for r in records):
            continue
        if academic_year and not any(r.academic_year == academic_year for r in records):
            continue

        evidence = alert.evidence_summary
        if principal.role not in {"administrator", "prototype_admin"}:
            evidence = mask_sensitive_payload(evidence)

        matching_alerts.append({
            "alert_id": alert.id,
            "conflict_type": alert.alert_type,
            "severity": alert.severity,
            "title": alert.title,
            "explanation": alert.explanation,
            "student_ref": alert.student_ref,
            "confidence_score": alert.confidence_score,
            "evidence_summary": evidence,
            "supporting_record_ids": alert.supporting_record_ids or [],
            "status": alert.status,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        })

    total = len(matching_alerts)
    paginated = matching_alerts[(page - 1) * limit : page * limit]
    return {
        "items": paginated,
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("", response_model=EnrolmentResponse, status_code=201)
def create_enrolment(
    payload: EnrolmentCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if principal.role == "institution_officer" and payload.institution_id != principal.institution_id:
        raise HTTPException(status_code=403, detail="Institution operators can only create records for their assigned institution.")
    enrolment = Enrolment(
        student_ref=payload.student_ref,
        apaar_id=payload.apaar_id,
        institution_id=payload.institution_id,
        institution_name=payload.institution_name or payload.institution_id,
        programme_id=payload.programme_id,
        programme_name=payload.programme_name or payload.programme_id,
        academic_year=payload.academic_year,
        admission_cycle=payload.admission_cycle,
        enrolment_start=payload.enrolment_start,
        enrolment_end=payload.enrolment_end,
        enrolment_status=payload.enrolment_status,
        seat_category=payload.seat_category,
        exception_ref=payload.exception_ref,
        source_submission_id=payload.source_submission_id,
        record_version=payload.record_version
    )
    db.add(enrolment)
    db.commit()
    db.refresh(enrolment)

    # Re-evaluate student's integrity
    engine_svc = TemporalIntegrityEngine(db)
    engine_svc.evaluate_student(payload.student_ref)

    response = EnrolmentResponse.model_validate(enrolment)
    if principal.role not in {"administrator", "prototype_admin"}:
        response = response.model_copy(update={"apaar_id": mask_identifier(response.apaar_id)})
    return response
