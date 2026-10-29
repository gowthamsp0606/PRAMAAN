from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.intake import ApprovedIntake
from app.services.intake_service import IntakeComplianceService
from app.security import Principal, enforce_institution_scope, get_current_principal
from app.schemas.intake import ApprovedIntakeRuleRequest
from app.services.audit_service import AuditService

router = APIRouter(prefix="/intake-compliance", tags=["Intake Compliance"])

@router.get("")
def get_intake_compliance(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    svc = IntakeComplianceService(db)
    reports = svc.get_all_compliance_reports()
    if principal.role == "institution_officer":
        reports = [report for report in reports if report["institution_id"] == principal.institution_id]
    return {
        "total_rules": len(reports),
        "reports": reports
    }


@router.get("/findings")
def get_intake_compliance_findings(
    institution_id: Optional[str] = Query(None),
    programme_id: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    compliance_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    scoped_inst = enforce_institution_scope(principal, institution_id)
    svc = IntakeComplianceService(db)
    reports = svc.get_all_compliance_reports()

    if scoped_inst:
        reports = [r for r in reports if r["institution_id"] == scoped_inst]
    if programme_id:
        reports = [r for r in reports if r["programme_id"] == programme_id]
    if academic_year:
        reports = [r for r in reports if r["academic_year"] == academic_year]
    if compliance_status:
        reports = [r for r in reports if r["compliance_status"] == compliance_status]

    findings = []
    for r in reports:
        findings.append({
            "rule_id": r.get("rule_id", "UNCONFIGURED"),
            "rule_source": r.get("rule_source"),
            "effective_date": r.get("effective_date"),
            "institution_id": r["institution_id"],
            "institution_name": r.get("institution_name", r["institution_id"]),
            "programme_id": r["programme_id"],
            "programme_name": r.get("programme_name", r["programme_id"]),
            "academic_year": r["academic_year"],
            "admission_cycle": r.get("admission_cycle"),
            "compliance_status": r["compliance_status"],
            "approved_intake": r.get("approved_intake"),
            "new_admissions_count": r.get("new_admissions_count"),
            "regular_admitted": r.get("regular_admitted"),
            "supernumerary_admitted": r.get("supernumerary_admitted"),
            "nri_admitted": r.get("nri_admitted"),
            "oci_admitted": r.get("oci_admitted"),
            "foreign_national_admitted": r.get("foreign_national_admitted"),
            "explanation": r.get("explanation"),
            "summary": r.get("summary"),
            "review_recommended": r["compliance_status"] in {"NON_COMPLIANT_OVER_ADMISSION", "QUOTA_DISCREPANCY", "NEEDS_REVIEW", "AMBIGUOUS_RULE"},
        })

    return {
        "total_findings": len(findings),
        "findings": findings
    }


@router.get("/{institution_id}/{programme_id}")
def get_programme_intake_detail(
    institution_id: str,
    programme_id: str,
    academic_year: str = Query("2025-2026"),
    admission_cycle: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    enforce_institution_scope(principal, institution_id)
    svc = IntakeComplianceService(db)
    report = svc.evaluate_programme_intake(
        institution_id=institution_id,
        programme_id=programme_id,
        academic_year=academic_year,
        admission_cycle=admission_cycle
    )
    return report


@router.get("/{institution_id}/{programme_id}/rule-history")
def get_programme_rule_history(
    institution_id: str,
    programme_id: str,
    academic_year: str = Query(...),
    admission_cycle: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    enforce_institution_scope(principal, institution_id)
    query = db.query(ApprovedIntake).filter(
        ApprovedIntake.institution_id == institution_id,
        ApprovedIntake.programme_id == programme_id,
        ApprovedIntake.academic_year == academic_year,
    )
    if admission_cycle is not None:
        query = query.filter(ApprovedIntake.admission_cycle == admission_cycle)
    versions = query.order_by(ApprovedIntake.admission_cycle.asc(), ApprovedIntake.effective_date.asc(), ApprovedIntake.id.asc()).all()
    return {
        "institution_id": institution_id,
        "programme_id": programme_id,
        "academic_year": academic_year,
        "admission_cycle": admission_cycle,
        "versions": [
            {
                "rule_id": rule.rule_id,
                "rule_source": rule.rule_source,
                "effective_date": rule.effective_date,
                "admission_cycle": rule.admission_cycle,
                "approved_intake_seats": rule.approved_intake_seats,
                "supernumerary_quota": rule.supernumerary_quota,
                "nri_quota": rule.nri_quota,
                "rule_configured": rule.rule_configured,
            }
            for rule in versions
        ],
    }

@router.post("/rules", status_code=201)
def configure_intake_rule(
    payload: ApprovedIntakeRuleRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if principal.role in {"read_only_auditor", "external_verifier"}:
        raise HTTPException(
            status_code=403,
            detail="Your role is not authorized to configure intake compliance rules.",
        )
    if principal.role == "institution_officer":
        enforce_institution_scope(principal, payload.institution_id)

    scope = db.query(ApprovedIntake).filter(
        ApprovedIntake.institution_id == payload.institution_id,
        ApprovedIntake.programme_id == payload.programme_id,
        ApprovedIntake.academic_year == payload.academic_year,
        ApprovedIntake.admission_cycle == payload.admission_cycle,
    )
    configured_rules = scope.filter(ApprovedIntake.rule_configured.is_(True)).all()

    same_rule = next((rule for rule in configured_rules if (
        rule.rule_id == payload.rule_id
        and rule.rule_source == payload.rule_source
        and rule.effective_date == payload.effective_date.isoformat()
        and rule.approved_intake_seats == payload.approved_intake_seats
        and rule.supernumerary_quota == payload.supernumerary_quota
        and rule.nri_quota == payload.nri_quota
        and rule.rule_configured == payload.rule_configured
    )), None)
    if same_rule:
        return {
            "success": True,
            "rule_id": same_rule.rule_id,
            "message": "The configured intake rule already matches this request.",
        }

    if payload.rule_configured:
        for previous in configured_rules:
            previous.rule_configured = False

    rule = ApprovedIntake(
        institution_id=payload.institution_id,
        institution_name=payload.institution_name or payload.institution_id,
        programme_id=payload.programme_id,
        programme_name=payload.programme_name or payload.programme_id,
        academic_year=payload.academic_year,
        admission_cycle=payload.admission_cycle,
        approved_intake_seats=payload.approved_intake_seats,
        supernumerary_quota=payload.supernumerary_quota,
        nri_quota=payload.nri_quota,
        rule_id=payload.rule_id,
        rule_source=payload.rule_source,
        effective_date=payload.effective_date.isoformat(),
        rule_configured=payload.rule_configured,
    )
    db.add(rule)
    AuditService.log_event(
        db=db,
        entity_type="INTAKE_RULE",
        entity_id=f"{payload.institution_id}:{payload.programme_id}:{payload.academic_year}:{payload.admission_cycle}",
        action="INTAKE_RULE_VERSION_CREATED",
        performed_by=principal.subject,
        details={
            "rule_id": payload.rule_id,
            "rule_source": payload.rule_source,
            "effective_date": payload.effective_date.isoformat(),
            "previous_rule_ids": [item.rule_id for item in configured_rules],
            "rule_configured": payload.rule_configured,
        },
        commit=False,
    )
    try:
        db.commit()
        db.refresh(rule)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to persist intake rule version.")

    return {
        "success": True,
        "rule_id": rule.rule_id,
        "rule_configured": rule.rule_configured,
        "history_preserved": bool(configured_rules),
        "message": (
            "Intake rule version recorded; previous values were preserved."
            if payload.rule_configured
            else "Unconfigured rule draft recorded; active rule remains unchanged."
        ),
    }
