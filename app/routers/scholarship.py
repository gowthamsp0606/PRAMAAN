from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import Principal, get_current_principal, enforce_institution_scope, enforce_state_scope
from app.services.scholarship_service import ScholarshipService


router = APIRouter(prefix="/scholarship", tags=["Scholarships and Welfare"])


@router.get("/evaluations")
def list_scholarship_evaluations(
    institution_id: Optional[str] = Query(None, description="Filter by institution ID"),
    state: Optional[str] = Query(None, description="Filter by state jurisdiction"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    List scholarship eligibility evaluations for students.
    Enforces role-based institution and state data scoping.
    Strictly DPDP compliant: evaluates academic merit, integrity, and consent without caste/religion data.
    """
    if principal.role == "institution_officer":
        effective_inst = enforce_institution_scope(principal, institution_id)
        return ScholarshipService.list_evaluations(db=db, institution_id=effective_inst, limit=limit)
    elif principal.role == "state_officer":
        effective_state = enforce_state_scope(principal, state)
        return ScholarshipService.list_evaluations(db=db, state=effective_state, limit=limit)
    else:
        return ScholarshipService.list_evaluations(db=db, institution_id=institution_id, state=state, limit=limit)


@router.get("/evaluations/{student_ref}")
def get_student_scholarship_evaluation(
    student_ref: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Evaluate single student's scholarship eligibility with explainable criteria breakdown.
    """
    evaluation = ScholarshipService.evaluate_student(db, student_ref)
    if evaluation.get("eligibility_status") == "STUDENT_NOT_FOUND":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student '{student_ref}' not found.",
        )

    # Scoping check
    if principal.role == "institution_officer":
        enforce_institution_scope(principal, evaluation.get("primary_institution_id"))
    elif principal.role == "state_officer":
        enforce_state_scope(principal, evaluation.get("state"))
    elif principal.role == "student":
        if principal.student_ref and principal.student_ref != student_ref:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view another student's evaluation.")

    return evaluation
