from fastapi import APIRouter, Depends, Query, Body, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import Optional, List, Dict, Any
from app.config import settings
from app.database import get_db
from app.models.enrolment import Enrolment
from app.models.intake import HistoricalIntake
from app.services.anomaly_service import HistoricalAnomalyService
from app.services.audit_service import AuditService
from app.security import Principal, get_current_principal, enforce_institution_scope

router = APIRouter(prefix="/analytics", tags=["Historical Analytics & Anomaly Detection"])

@router.get("/enrolment-trends")
def get_enrolment_trends(
    institution_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_id = enforce_institution_scope(principal, institution_id)

    query = db.query(
        Enrolment.academic_year,
        func.count(Enrolment.id).label("total"),
        func.sum(case((Enrolment.enrolment_status == "Active", 1), else_=0)).label("active"),
        func.sum(case((Enrolment.enrolment_status == "Completed", 1), else_=0)).label("completed"),
        func.sum(case((Enrolment.enrolment_status == "Withdrawn", 1), else_=0)).label("withdrawn")
    )
    if institution_id:
        query = query.filter(Enrolment.institution_id == institution_id)

    trends = query.group_by(Enrolment.academic_year).order_by(Enrolment.academic_year.asc()).all()

    return {
        "institution_id": institution_id,
        "trends": [
            {
                "academic_year": r[0],
                "total": r[1],
                "active": r[2] or 0,
                "completed": r[3] or 0,
                "withdrawn": r[4] or 0
            }
            for r in trends
        ]
    }

@router.get("/anomalies")
def get_anomalies(
    institution_id: Optional[str] = Query(None),
    programme_id: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    dismissed: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_id = enforce_institution_scope(principal, institution_id)

    svc = HistoricalAnomalyService(db)
    anomalies = svc.get_all_anomalies(
        institution_id=institution_id,
        programme_id=programme_id,
        academic_year=academic_year,
        dismissed=dismissed,
    )
    return {"total_anomalies": len(anomalies), "items": anomalies}

@router.get("/findings")
def get_explainable_findings(
    institution_id: Optional[str] = Query(None),
    finding_type: Optional[str] = Query(None, description="HISTORICAL_DEVIATION, TEMPORAL_CONFLICT, IDENTITY_INCONSISTENCY"),
    severity: Optional[str] = Query(None, description="CRITICAL, HIGH, MEDIUM, LOW, INFO"),
    is_statistical: Optional[bool] = Query(None, description="Filter for statistical anomalies vs deterministic rule conflicts"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Unified Explainable Findings API (APAAR-FUSE Foundation):
    Clearly distinguishes statistical anomalies (Z-score / IQR) from deterministic rule findings.
    """
    institution_id = enforce_institution_scope(principal, institution_id)

    svc = HistoricalAnomalyService(db)
    return svc.get_explainable_findings(
        institution_id=institution_id,
        finding_type=finding_type,
        severity=severity,
        is_statistical=is_statistical,
    )

@router.patch("/anomalies/{anomaly_id}/dismiss")
def dismiss_anomaly(
    anomaly_id: int,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    # Role validation: read-only auditor or external verifier cannot dismiss findings
    if principal.role in {"read_only_auditor", "external_verifier"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your current role is not authorized to dismiss anomaly findings."
        )

    item = db.query(HistoricalIntake).filter(HistoricalIntake.id == anomaly_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Historical record {anomaly_id} not found.")

    if principal.role == "institution_officer":
        enforce_institution_scope(principal, item.institution_id)

    reason = payload.get("reason")
    if not reason or not isinstance(reason, str) or len(reason.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A substantive justification of at least 5 characters is mandatory for dismissing an anomaly."
        )

    # Prevent caller-supplied identity spoofing: if bearer principal is non-prototype, force subject
    if principal.subject and principal.subject != "local-prototype":
        dismissed_by = principal.subject
    else:
        dismissed_by = payload.get("dismissed_by") or settings.DEMO_REVIEWER

    svc = HistoricalAnomalyService(db)
    try:
        res = svc.dismiss_anomaly(anomaly_id, reason.strip(), dismissed_by)
        AuditService.log_event(
            db=db,
            entity_type="ANOMALY",
            entity_id=str(anomaly_id),
            action="DISMISS_ANOMALY",
            performed_by=dismissed_by,
            details={"reason": reason.strip(), "institution_id": item.institution_id}
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/historical/{institution_id}/{programme_id}")
def get_historical_trends_for_programme(
    institution_id: str,
    programme_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if principal.role == "institution_officer":
        enforce_institution_scope(principal, institution_id)

    svc = HistoricalAnomalyService(db)
    return svc.get_historical_trends(institution_id, programme_id)

@router.get("/benchmark-evaluation")
def get_benchmark_evaluation(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    svc = HistoricalAnomalyService(db)
    return svc.compute_synthetic_benchmark_metrics()
