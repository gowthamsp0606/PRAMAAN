from fastapi import APIRouter, Depends, Body, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from app.database import get_db
from app.models.verifier import VerifierOrganization, VerificationRequestLog
from app.services.verifier_service import VerifierService
from app.security import Principal, get_current_principal, require_roles
from app.rate_limiter import rate_limit_verifier

router = APIRouter(prefix="/verifier", tags=["Employer & External Verification Portal"])

@router.get("/organizations")
def list_verifier_organizations(
    db: Session = Depends(get_db),
    _: Principal = Depends(require_roles("administrator", "external_verifier")),
):
    orgs = db.query(VerifierOrganization).all()
    return {
        "items": [
            {
                "id": o.id,
                "org_name": o.org_name,
                "org_type": o.org_type,
                "is_approved": o.is_approved,
                "contact_email": o.contact_email
            }
            for o in orgs
        ]
    }

@router.post("/verify-credential", dependencies=[Depends(rate_limit_verifier)])
def verify_candidate_credential(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("administrator", "external_verifier")),
):
    requested_org_id = payload.get("verifier_org_id")
    if principal.role == "external_verifier":
        if not principal.verifier_org_id:
            raise HTTPException(status_code=403, detail="No verifier organization is assigned to this principal.")
        if principal.purpose_scope != "EMPLOYMENT_VERIFICATION":
            raise HTTPException(status_code=403, detail="No employment-verification purpose is assigned to this principal.")
        if requested_org_id and requested_org_id != principal.verifier_org_id:
            raise HTTPException(status_code=403, detail="Verifier credentials cannot be used for another organization.")
        verifier_org_id = principal.verifier_org_id
    else:
        verifier_org_id = requested_org_id or "ORG-TCS-BGV"

    svc = VerifierService(db)
    result = svc.verify_candidate_credential(
        verifier_org_id=verifier_org_id,
        student_ref=payload.get("student_ref"),
        apaar_id=payload.get("apaar_id"),
        certificate_id=payload.get("certificate_id")
    )
    return result

@router.get("/logs")
def get_verification_logs(
    verifier_org_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles("administrator", "external_verifier")),
):
    query = db.query(VerificationRequestLog)
    if principal.role == "external_verifier":
        if not principal.verifier_org_id:
            raise HTTPException(status_code=403, detail="No verifier organization is assigned to this principal.")
        if verifier_org_id and verifier_org_id != principal.verifier_org_id:
            raise HTTPException(status_code=403, detail="Verifier credentials cannot read another organization's logs.")
        verifier_org_id = principal.verifier_org_id
    if verifier_org_id:
        query = query.filter(VerificationRequestLog.verifier_org_id == verifier_org_id)

    total = query.count()
    items = query.order_by(VerificationRequestLog.timestamp.desc()).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": log.id,
                "verifier_org_id": log.verifier_org_id,
                "verifier_org_name": log.verifier_org_name,
                "query_student_ref": log.query_student_ref,
                "query_apaar_id": None if principal.role == "external_verifier" else log.query_apaar_id,
                "certificate_id": log.certificate_id,
                "verification_outcome": log.verification_outcome,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "details": log.limited_response_json
            }
            for log in items
        ]
    }
