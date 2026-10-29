from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.database import get_db
from app.models.alert import Alert
from app.models.enrolment import Enrolment
from app.models.review_event import AlertReviewEvent
from app.schemas.alert import (
    AlertAssignmentRequest,
    AlertClarificationRequest,
    AlertNoteRequest,
    AlertReopenRequest,
    AlertReviewRequest,
)
from app.services.integrity_engine import TemporalIntegrityEngine
from app.services.audit_service import AuditService
from app.services.export_service import ExportService
from app.security import Principal, get_current_principal, mask_identifier, mask_sensitive_payload
from app.rate_limiter import rate_limit_reevaluation

router = APIRouter(prefix="/alerts", tags=["Alerts & Enrolment Integrity"])

ALLOWED_STATUS_TRANSITIONS = {
    "OPEN": {"UNDER_REVIEW", "AWAITING_INFORMATION", "AWAITING_CLARIFICATION", "ESCALATED", "RESOLVED", "DISMISSED"},
    "UNDER_REVIEW": {"OPEN", "AWAITING_INFORMATION", "AWAITING_CLARIFICATION", "ESCALATED", "RESOLVED", "DISMISSED"},
    "AWAITING_INFORMATION": {"UNDER_REVIEW", "ESCALATED", "RESOLVED", "DISMISSED"},
    "AWAITING_CLARIFICATION": {"UNDER_REVIEW", "ESCALATED", "RESOLVED", "DISMISSED"},
    "ESCALATED": {"UNDER_REVIEW", "AWAITING_INFORMATION", "AWAITING_CLARIFICATION", "RESOLVED", "DISMISSED"},
    "RESOLVED": {"UNDER_REVIEW"},
    "DISMISSED": {"UNDER_REVIEW"},
}


def _append_case_event(
    db: Session,
    alert: Alert,
    action: str,
    actor: str,
    *,
    new_status: Optional[str] = None,
    decision: Optional[str] = None,
    assigned_to: Optional[str] = None,
    note: Optional[str] = None,
    resolution_reason: Optional[str] = None,
    evidence_references: Optional[List[str]] = None,
) -> AlertReviewEvent:
    previous_status = alert.status
    if new_status is not None:
        explicit_reopen = action == "REOPENED" and previous_status == "RESOLVED" and new_status == "UNDER_REVIEW"
        if not explicit_reopen and new_status != previous_status and new_status not in ALLOWED_STATUS_TRANSITIONS.get(previous_status, set()):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot transition alert from {previous_status} to {new_status}.",
            )
        alert.status = new_status

    event = AlertReviewEvent(
        alert_id=alert.id,
        action=action,
        previous_status=previous_status,
        new_status=alert.status if new_status is not None else None,
        decision=decision,
        actor=actor,
        assigned_to=assigned_to,
        note=note,
        resolution_reason=resolution_reason,
        evidence_references=evidence_references or [],
    )
    db.add(event)
    AuditService.log_event(
        db=db,
        entity_type="ALERT",
        entity_id=alert.id,
        action=action,
        performed_by=actor,
        details={
            "previous_status": previous_status,
            "new_status": alert.status if new_status is not None else None,
            "decision": decision,
            "assigned_to": assigned_to,
            "evidence_reference_count": len(evidence_references or []),
        },
        commit=False,
    )
    try:
        db.commit()
        db.refresh(event)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to persist alert review event.") from exc
    return event


def _case_history(db: Session, alert_id: str) -> List[AlertReviewEvent]:
    return db.query(AlertReviewEvent).filter(
        AlertReviewEvent.alert_id == alert_id
    ).order_by(AlertReviewEvent.created_at.asc(), AlertReviewEvent.id.asc()).all()


def _current_assignment(history: List[AlertReviewEvent]) -> Optional[str]:
    assignment = next((event for event in reversed(history) if event.action in {"ASSIGNED", "UNASSIGNED"}), None)
    return assignment.assigned_to if assignment else None

@router.get("", response_model=Dict[str, Any])
@router.get("/investigation-cases", response_model=Dict[str, Any])
def list_alerts(
    status: Optional[str] = Query(None, description="OPEN, UNDER_REVIEW, RESOLVED"),
    severity: Optional[str] = Query(None, description="HIGH, MEDIUM, LOW, INFORMATIONAL"),
    alert_type: Optional[str] = Query(None),
    student_ref: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query = db.query(Alert)

    if principal.role == "institution_officer":
        institution_student_refs = db.query(Enrolment.student_ref).filter(
            Enrolment.institution_id == principal.institution_id
        ).distinct().subquery()
        query = query.filter(Alert.student_ref.in_(institution_student_refs))

    if status:
        query = query.filter(Alert.status == status)
    if severity:
        query = query.filter(Alert.severity == severity)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)
    if student_ref:
        query = query.filter(Alert.student_ref == student_ref)

    total = query.count()
    alerts = query.order_by(Alert.created_at.desc()).all()
    if principal.role == "institution_officer":
        scoped_alerts = []
        for alert in alerts:
            if not alert.supporting_record_ids:
                continue
            visible_count = db.query(Enrolment.id).filter(
                Enrolment.id.in_(alert.supporting_record_ids),
                Enrolment.institution_id == principal.institution_id,
            ).count()
            if visible_count == len(set(alert.supporting_record_ids)):
                scoped_alerts.append(alert)
        alerts = scoped_alerts

    return {
        "total": total,
        "items": [
            {
                "id": a.id,
                "student_ref": a.student_ref,
                "apaar_id": a.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(a.apaar_id),
                "alert_type": a.alert_type,
                "severity": a.severity,
                "status": a.status,
                "title": a.title,
                "explanation": a.explanation,
                "evidence_summary": a.evidence_summary if principal.role in {"administrator", "prototype_admin"} else mask_sensitive_payload(a.evidence_summary),
                "confidence_score": a.confidence_score,
                "supporting_record_ids": a.supporting_record_ids,
                "exception_ref": a.exception_ref,
                "reviewer_decision": a.reviewer_decision,
                "reviewer_note": a.reviewer_note,
                "reviewed_by": a.reviewed_by,
                "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
                "assigned_to": _current_assignment(_case_history(db, a.id)),
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in alerts
        ]
    }


@router.get("/export-csv")
def export_alerts_csv(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export investigation cases and integrity alerts as CSV."""
    query = db.query(Alert)
    if principal.role == "institution_officer":
        inst_students = db.query(Enrolment.student_ref).filter(
            Enrolment.institution_id == principal.institution_id
        ).distinct().subquery()
        query = query.filter(Alert.student_ref.in_(inst_students))
    if status:
        query = query.filter(Alert.status == status)
    if severity:
        query = query.filter(Alert.severity == severity)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)

    alerts = query.order_by(Alert.created_at.desc()).limit(1000).all()
    headers = [
        "Case ID", "Student Ref", "APAAR ID", "Case Type", "Severity",
        "Status", "Title", "Explanation", "Confidence Score", "Reviewed By", "Created At"
    ]
    rows = [
        [
            a.id, a.student_ref, a.apaar_id or "", a.alert_type, a.severity,
            a.status, a.title, a.explanation, a.confidence_score or "",
            a.reviewed_by or "", a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
        ]
        for a in alerts
    ]
    csv_data = ExportService.generate_csv(headers, rows)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="investigation_cases.csv"'},
    )


@router.get("/export-excel")
def export_alerts_excel(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export investigation cases and integrity alerts as Excel (.xlsx)."""
    query = db.query(Alert)
    if principal.role == "institution_officer":
        inst_students = db.query(Enrolment.student_ref).filter(
            Enrolment.institution_id == principal.institution_id
        ).distinct().subquery()
        query = query.filter(Alert.student_ref.in_(inst_students))
    if status:
        query = query.filter(Alert.status == status)
    if severity:
        query = query.filter(Alert.severity == severity)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)

    alerts = query.order_by(Alert.created_at.desc()).limit(1000).all()
    headers = [
        "Case ID", "Student Ref", "APAAR ID", "Case Type", "Severity",
        "Status", "Title", "Explanation", "Confidence Score", "Reviewed By", "Created At"
    ]
    rows = [
        [
            a.id, a.student_ref, a.apaar_id or "", a.alert_type, a.severity,
            a.status, a.title, a.explanation, a.confidence_score or "",
            a.reviewed_by or "", a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
        ]
        for a in alerts
    ]
    xlsx_bytes = ExportService.generate_excel("Investigations", headers, rows)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="investigation_cases.xlsx"'},
    )


@router.get("/{alert_id}")
def get_alert_detail(
    alert_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")

    if principal.role == "institution_officer":
        if not alert.supporting_record_ids:
            raise HTTPException(status_code=404, detail="Alert not found.")
        visible_count = db.query(Enrolment.id).filter(
            Enrolment.id.in_(alert.supporting_record_ids),
            Enrolment.institution_id == principal.institution_id,
        ).count()
        if visible_count != len(set(alert.supporting_record_ids)):
            raise HTTPException(status_code=404, detail="Alert not found.")

    # Fetch supporting enrolment records
    supporting_enrolments = []
    if alert.supporting_record_ids:
        records = db.query(Enrolment).filter(Enrolment.id.in_(alert.supporting_record_ids)).all()
        supporting_enrolments = [
            {
                "id": r.id,
                "institution_id": r.institution_id,
                "institution_name": r.institution_name,
                "programme_id": r.programme_id,
                "programme_name": r.programme_name,
                "academic_year": r.academic_year,
                "admission_cycle": r.admission_cycle,
                "enrolment_start": r.enrolment_start.isoformat(),
                "enrolment_end": r.enrolment_end.isoformat() if r.enrolment_end else "Ongoing",
                "enrolment_status": r.enrolment_status,
                "seat_category": r.seat_category,
                "exception_ref": r.exception_ref,
                "source_submission_id": r.source_submission_id,
                "record_version": r.record_version
            }
            for r in records
        ]

    # Get student full timeline
    timeline_records = db.query(Enrolment).filter(
        Enrolment.student_ref == alert.student_ref
    ).order_by(Enrolment.enrolment_start.asc()).all()
    history = _case_history(db, alert.id)

    return {
        "alert": {
            "id": alert.id,
            "student_ref": alert.student_ref,
            "apaar_id": alert.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(alert.apaar_id),
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "status": alert.status,
            "title": alert.title,
            "explanation": alert.explanation,
            "evidence_summary": alert.evidence_summary if principal.role in {"administrator", "prototype_admin"} else mask_sensitive_payload(alert.evidence_summary),
            "confidence_score": alert.confidence_score,
            "supporting_record_ids": alert.supporting_record_ids,
            "exception_ref": alert.exception_ref,
            "reviewer_decision": alert.reviewer_decision,
            "reviewer_note": alert.reviewer_note,
            "reviewed_by": alert.reviewed_by,
            "reviewed_at": alert.reviewed_at.isoformat() if alert.reviewed_at else None,
            "assigned_to": _current_assignment(history),
            "created_at": alert.created_at.isoformat() if alert.created_at else None
        },
        "review_history": [
            {
                "id": event.id,
                "action": event.action,
                "previous_status": event.previous_status,
                "new_status": event.new_status,
                "decision": event.decision,
                "actor": event.actor,
                "assigned_to": event.assigned_to,
                "note": event.note,
                "resolution_reason": event.resolution_reason,
                "evidence_references": event.evidence_references,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in history
        ],
        "supporting_enrolments": supporting_enrolments,
        "student_timeline": [
            {
                "id": e.id,
                "institution_name": e.institution_name or e.institution_id,
                "programme_name": e.programme_name or e.programme_id,
                "enrolment_start": e.enrolment_start.isoformat(),
                "enrolment_end": e.enrolment_end.isoformat() if e.enrolment_end else "Ongoing",
                "enrolment_status": e.enrolment_status,
                "exception_ref": e.exception_ref
            }
            for e in timeline_records
        ]
    }

def _enforce_alert_mutation_access(alert: Alert, principal: Principal, db: Session):
    if principal.role in {"read_only_auditor", "external_verifier"}:
        raise HTTPException(status_code=403, detail="Your role is not authorized to modify alert records.")
    if principal.role == "institution_officer":
        if not alert.supporting_record_ids:
            raise HTTPException(status_code=404, detail="Alert not found.")
        visible_count = db.query(Enrolment.id).filter(
            Enrolment.id.in_(alert.supporting_record_ids),
            Enrolment.institution_id == principal.institution_id,
        ).count()
        if visible_count != len(set(alert.supporting_record_ids)):
            raise HTTPException(status_code=404, detail="Alert not found.")


@router.patch("/{alert_id}/review")
def review_alert(
    alert_id: str,
    payload: AlertReviewRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    valid_decisions = {
        "CONFIRMED_CONFLICT": "RESOLVED",
        "NOT_A_CONFLICT": "RESOLVED",
        "EXCEPTION_ACCEPTED": "RESOLVED",
        "NEEDS_MORE_INFO": "UNDER_REVIEW"
    }

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")

    _enforce_alert_mutation_access(alert, principal, db)

    if not payload.note.strip():
        raise HTTPException(status_code=422, detail="Reviewer note cannot be blank.")
    resulting_status = valid_decisions[payload.decision]
    if alert.status == "RESOLVED":
        raise HTTPException(status_code=409, detail="Resolved alerts must be explicitly reopened before another decision.")

    alert.reviewer_decision = payload.decision
    alert.reviewer_note = payload.note
    alert.reviewed_by = (
        payload.reviewed_by or "Demo Officer (AICTE-RO-102)"
        if principal.role == "prototype_admin"
        else principal.subject
    )
    alert.reviewed_at = datetime.utcnow()
    resolution_reason = payload.resolution_reason or (payload.note if resulting_status == "RESOLVED" else None)
    _append_case_event(
        db=db,
        alert=alert,
        action="REVIEW_DECISION",
        actor=alert.reviewed_by,
        new_status=resulting_status,
        decision=payload.decision,
        note=payload.note,
        resolution_reason=resolution_reason,
        evidence_references=payload.evidence_references,
    )

    return {
        "success": True,
        "alert_id": alert.id,
        "decision": alert.reviewer_decision,
        "status": alert.status,
        "reviewed_at": alert.reviewed_at.isoformat(),
        "reviewed_by": alert.reviewed_by,
        "message": "Review decision persisted and audit event logged."
    }


@router.get("/{alert_id}/history")
def get_alert_review_history(
    alert_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")

    if principal.role == "institution_officer":
        if not alert.supporting_record_ids:
            raise HTTPException(status_code=404, detail="Alert not found.")
        visible_count = db.query(Enrolment.id).filter(
            Enrolment.id.in_(alert.supporting_record_ids),
            Enrolment.institution_id == principal.institution_id,
        ).count()
        if visible_count != len(set(alert.supporting_record_ids)):
            raise HTTPException(status_code=404, detail="Alert not found.")

    history = _case_history(db, alert.id)
    return {
        "alert_id": alert.id,
        "assigned_to": _current_assignment(history),
        "events": [
            {
                "id": event.id,
                "action": event.action,
                "previous_status": event.previous_status,
                "new_status": event.new_status,
                "decision": event.decision,
                "actor": event.actor,
                "assigned_to": event.assigned_to,
                "note": event.note,
                "resolution_reason": event.resolution_reason,
                "evidence_references": event.evidence_references,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in history
        ],
    }


@router.patch("/{alert_id}/assignment")
def assign_alert(
    alert_id: str,
    payload: AlertAssignmentRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    _enforce_alert_mutation_access(alert, principal, db)
    assigned_to = payload.assigned_to.strip() if payload.assigned_to else None
    actor = payload.actor.strip() if principal.role == "prototype_admin" else principal.subject
    event = _append_case_event(
        db, alert, "ASSIGNED" if assigned_to else "UNASSIGNED", actor,
        assigned_to=assigned_to,
    )
    return {"success": True, "alert_id": alert.id, "assigned_to": assigned_to, "event_id": event.id}


@router.post("/{alert_id}/clarification")
def request_alert_clarification(
    alert_id: str,
    payload: AlertClarificationRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    _enforce_alert_mutation_access(alert, principal, db)
    if alert.status == "RESOLVED":
        raise HTTPException(status_code=409, detail="Reopen the resolved case before requesting clarification.")
    if not payload.note.strip():
        raise HTTPException(status_code=422, detail="Clarification request cannot be blank.")
    actor = payload.actor.strip() if principal.role == "prototype_admin" else principal.subject
    event = _append_case_event(
        db, alert, "CLARIFICATION_REQUESTED", actor,
        new_status="AWAITING_CLARIFICATION", note=payload.note,
        evidence_references=payload.evidence_references,
    )
    return {"success": True, "alert_id": alert.id, "status": alert.status, "event_id": event.id}


@router.post("/{alert_id}/notes")
def add_alert_note(
    alert_id: str,
    payload: AlertNoteRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    _enforce_alert_mutation_access(alert, principal, db)
    actor = payload.actor.strip() if principal.role == "prototype_admin" else principal.subject
    event = _append_case_event(
        db, alert, "NOTE_ADDED", actor, note=payload.note,
        evidence_references=payload.evidence_references,
    )
    return {"success": True, "alert_id": alert.id, "event_id": event.id}


@router.post("/{alert_id}/reopen")
def reopen_alert(
    alert_id: str,
    payload: AlertReopenRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    _enforce_alert_mutation_access(alert, principal, db)
    if alert.status != "RESOLVED":
        raise HTTPException(status_code=409, detail="Only resolved alerts can be reopened.")
    actor = payload.actor.strip() if principal.role == "prototype_admin" else principal.subject
    event = _append_case_event(
        db, alert, "REOPENED", actor, new_status="UNDER_REVIEW",
        note=payload.reason, resolution_reason=payload.reason,
    )
    return {"success": True, "alert_id": alert.id, "status": alert.status, "event_id": event.id}

@router.post("/re-evaluate", dependencies=[Depends(rate_limit_reevaluation)])
def trigger_reevaluation(db: Session = Depends(get_db)):
    engine_svc = TemporalIntegrityEngine(db)
    count = engine_svc.evaluate_all()
    return {"success": True, "evaluated_students": count, "message": f"Successfully re-evaluated {count} student profiles."}
