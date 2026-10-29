import csv
import io
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Response
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from app.database import get_db
from app.admission_categories import normalize_admission_category, student_flags_for_admission_category
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.versioning import EnrolmentVersion
from app.models.import_job import ImportJob, ImportRowResult
from app.models.erp import StudentProfile
from app.schemas.student import StudentCreate, StudentResponse
from app.schemas.enrolment import EnrolmentResponse
from app.services.export_service import ExportService
from app.services.integrity_engine import (
    FAR_FUTURE_DATE,
    INTEGRITY_RULE_VERSION,
    TEMPORAL_OVERLAP_RULE_ID,
    TemporalIntegrityEngine,
    intervals_overlap,
)
from app.services.validation_service import ValidationService
from app.services.identity_service import IdentityLifecycleService, IdentityStatus
from app.services.audit_service import AuditService
from app.services.csv_import_service import StudentCsvImportService, safe_filename
from app.security import (
    Principal,
    canonicalize_institution_id,
    enforce_institution_scope,
    get_current_principal,
    mask_identifier,
    mask_sensitive_payload,
    require_student_institution,
)
from app.rate_limiter import rate_limit_csv_upload
from app.services.state_service import KNOWN_INSTITUTION_STATES

router = APIRouter(prefix="/students", tags=["Students"])
MAX_CSV_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CSV_ROWS = 10_000

@router.get("", response_model=Dict[str, Any])
def list_students(
    search: Optional[str] = Query(None, description="Search by student_ref, apaar_id, or name"),
    institution_id: Optional[str] = Query(None),
    state: Optional[str] = Query(None, description="Filter by state code"),
    programme_id: Optional[str] = Query(None),
    academic_year: Optional[str] = Query(None),
    enrolment_status: Optional[str] = Query(None),
    identity_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_id = enforce_institution_scope(principal, institution_id)
    query = db.query(Student)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (Student.student_ref.ilike(s)) |
            (Student.apaar_id.ilike(s)) |
            (Student.full_name.ilike(s))
        )

    if identity_status:
        query = query.filter(Student.identity_status == identity_status)

    target_state = principal.state if principal.role == "state_officer" else state

    if institution_id or programme_id or academic_year or enrolment_status or target_state:
        enrol_filters = []
        if institution_id:
            enrol_filters.append(Enrolment.institution_id == institution_id)
        if target_state:
            st_clean = target_state.upper().replace(" ", "_")
            state_inst_ids = [
                i_id for i_id, st in KNOWN_INSTITUTION_STATES.items()
                if st.upper().replace(" ", "_") == st_clean
            ]
            enrol_filters.append(Enrolment.institution_id.in_(state_inst_ids))
        if programme_id:
            enrol_filters.append(Enrolment.programme_id == programme_id)
        if academic_year:
            enrol_filters.append(Enrolment.academic_year == academic_year)
        if enrolment_status:
            enrol_filters.append(Enrolment.enrolment_status == enrolment_status)

        matching_refs = db.query(Enrolment.student_ref).filter(*enrol_filters).distinct().scalar_subquery()
        query = query.filter(Student.student_ref.in_(matching_refs))

    total = query.count()
    students = query.offset((page - 1) * limit).limit(limit).all()

    items = []
    for s in students:
        enrolment_query = db.query(Enrolment).filter(Enrolment.student_ref == s.student_ref)
        if principal.role == "institution_officer":
            enrolment_query = enrolment_query.filter(Enrolment.institution_id == institution_id)
        enrolment_count = enrolment_query.count()
        student_alerts = db.query(Alert).filter(
            Alert.student_ref == s.student_ref,
            Alert.status != "RESOLVED",
        ).all()
        if principal.role == "institution_officer":
            open_alerts_count = 0
            for alert in student_alerts:
                if not alert.supporting_record_ids:
                    continue
                scoped_ids = db.query(Enrolment.id).filter(
                    Enrolment.id.in_(alert.supporting_record_ids),
                    Enrolment.institution_id == institution_id,
                ).count()
                if scoped_ids == len(set(alert.supporting_record_ids)):
                    open_alerts_count += 1
        else:
            open_alerts_count = len(student_alerts)

        items.append({
            "student_ref": s.student_ref,
            "apaar_id": s.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(s.apaar_id),
            "full_name": s.full_name,
            "primary_institution_id": institution_id if principal.role == "institution_officer" else s.primary_institution_id,
            "identity_route": s.identity_route,
            "identity_status": s.identity_status,
            "nationality": s.nationality,
            "is_foreign_national": s.is_foreign_national,
            "is_nri": s.is_nri,
            "is_oci": s.is_oci,
            "enrolment_count": enrolment_count,
            "open_alerts_count": open_alerts_count,
            "created_at": s.created_at.isoformat() if s.created_at else None
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit if limit else 1
    }

@router.get("/import-jobs")
def list_import_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    institution_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if status and status not in {"PROCESSING", "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}:
        raise HTTPException(status_code=422, detail="Unsupported import-job status filter.")
    institution_id = enforce_institution_scope(principal, institution_id)
    query = db.query(ImportJob)
    if institution_id:
        query = query.filter(ImportJob.institution_id == institution_id)
    if status:
        query = query.filter(ImportJob.status == status)
    total = query.count()
    jobs = query.order_by(ImportJob.uploaded_at.desc(), ImportJob.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "items": [
            {
                "import_job_id": job.id,
                "institution_id": job.institution_id,
                "submitted_by": job.submitted_by,
                "filename": job.original_filename,
                "previous_job_id": job.previous_job_id,
                "status": job.status,
                "total_rows": job.total_rows,
                "accepted_rows": job.accepted_rows,
                "rejected_rows": job.rejected_rows,
                "review_rows": job.review_rows,
                "validation_summary": job.validation_summary,
                "error_summary": job.safe_error_summary,
                "uploaded_at": job.uploaded_at.isoformat() if job.uploaded_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
            for job in jobs
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit if limit else 1,
    }


@router.get("/import-jobs/{job_id}")
def get_import_job(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job or (principal.role == "institution_officer" and job.institution_id != principal.institution_id):
        raise HTTPException(status_code=404, detail="Import job not found.")
    return {
        "import_job_id": job.id,
        "institution_id": job.institution_id,
        "submitted_by": job.submitted_by,
        "filename": job.original_filename,
        "previous_job_id": job.previous_job_id,
        "status": job.status,
        "total_rows": job.total_rows,
        "accepted_rows": job.accepted_rows,
        "rejected_rows": job.rejected_rows,
        "review_rows": job.review_rows,
        "validation_summary": job.validation_summary,
        "error_summary": job.safe_error_summary,
        "uploaded_at": job.uploaded_at.isoformat() if job.uploaded_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.get("/import-jobs/{job_id}/rows")
def get_import_job_rows(
    job_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    outcome: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job or (principal.role == "institution_officer" and job.institution_id != principal.institution_id):
        raise HTTPException(status_code=404, detail="Import job not found.")
    if outcome and outcome not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
        raise HTTPException(status_code=422, detail="Unsupported import-row outcome filter.")
    query = db.query(ImportRowResult).filter(ImportRowResult.import_job_id == job.id)
    if outcome:
        query = query.filter(ImportRowResult.outcome == outcome)
    total = query.count()
    rows = query.order_by(ImportRowResult.row_number.asc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "import_job_id": job.id,
        "items": [
            {
                "row_result_id": row.id,
                "row_number": row.row_number,
                "previous_row_result_id": row.previous_row_result_id,
                "record_reference": row.record_reference,
                "outcome": row.outcome,
                "persisted": row.persisted,
                "issue_codes": row.issue_codes,
                "validation_messages": row.validation_messages,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/export-csv")
def export_students_csv(
    institution_id: Optional[str] = Query(None, description="Filter by institution code"),
    programme_id: Optional[str] = Query(None, description="Filter by programme"),
    search: Optional[str] = Query(None, description="Search by name, student_ref or apaar_id"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Export authorized student roster as CSV.
    Enforces institutional tenant isolation for college officers.
    """
    effective_inst = enforce_institution_scope(principal, institution_id)
    query = db.query(Student, StudentProfile, Enrolment).outerjoin(
        StudentProfile, StudentProfile.student_ref == Student.student_ref
    ).outerjoin(
        Enrolment, Enrolment.student_ref == Student.student_ref
    )
    if effective_inst:
        query = query.filter(Student.primary_institution_id == effective_inst)
    if programme_id:
        query = query.filter(Enrolment.programme_id == programme_id)
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (Student.full_name.ilike(s)) | (Student.student_ref.ilike(s)) | (Student.apaar_id.ilike(s))
        )

    results = query.order_by(Student.student_ref.asc()).limit(2000).all()
    headers = [
        "Student Ref", "Full Name", "APAAR ID", "Primary Institution", "Programme",
        "Department", "Roll Number", "Batch Year", "Semester", "Section",
        "Identity Status", "Admission Category", "Email", "Phone"
    ]
    rows = []
    seen_refs = set()
    for s, p, e in results:
        if s.student_ref in seen_refs:
            continue
        seen_refs.add(s.student_ref)
        rows.append([
            s.student_ref,
            s.full_name or "",
            s.apaar_id or "",
            s.primary_institution_id or "",
            (e.programme_name or e.programme_id if e else (p.department if p else "")) or "",
            (p.department if p else "") or "",
            (p.roll_number if p else "") or "",
            (p.batch_year if p else "") or "",
            (p.current_semester if p else "") or "",
            (p.section if p else "") or "",
            s.identity_status or "",
            (p.admission_category if p else "") or "",
            (p.college_email or p.personal_email if p else "") or "",
            (p.phone_number if p else "") or "",
        ])

    csv_data = ExportService.generate_csv(headers, rows)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="students_roster.csv"'},
    )


@router.get("/export-excel")
def export_students_excel(
    institution_id: Optional[str] = Query(None, description="Filter by institution code"),
    programme_id: Optional[str] = Query(None, description="Filter by programme"),
    search: Optional[str] = Query(None, description="Search by name, student_ref or apaar_id"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Export authorized student roster as professional Excel (.xlsx) workbook.
    """
    effective_inst = enforce_institution_scope(principal, institution_id)
    query = db.query(Student, StudentProfile, Enrolment).outerjoin(
        StudentProfile, StudentProfile.student_ref == Student.student_ref
    ).outerjoin(
        Enrolment, Enrolment.student_ref == Student.student_ref
    )
    if effective_inst:
        query = query.filter(Student.primary_institution_id == effective_inst)
    if programme_id:
        query = query.filter(Enrolment.programme_id == programme_id)
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (Student.full_name.ilike(s)) | (Student.student_ref.ilike(s)) | (Student.apaar_id.ilike(s))
        )

    results = query.order_by(Student.student_ref.asc()).limit(2000).all()
    headers = [
        "Student Ref", "Full Name", "APAAR ID", "Primary Institution", "Programme",
        "Department", "Roll Number", "Batch Year", "Semester", "Section",
        "Identity Status", "Admission Category", "Email", "Phone"
    ]
    rows = []
    seen_refs = set()
    for s, p, e in results:
        if s.student_ref in seen_refs:
            continue
        seen_refs.add(s.student_ref)
        rows.append([
            s.student_ref,
            s.full_name or "",
            s.apaar_id or "",
            s.primary_institution_id or "",
            (e.programme_name or e.programme_id if e else (p.department if p else "")) or "",
            (p.department if p else "") or "",
            (p.roll_number if p else "") or "",
            (p.batch_year if p else "") or "",
            (p.current_semester if p else "") or "",
            (p.section if p else "") or "",
            s.identity_status or "",
            (p.admission_category if p else "") or "",
            (p.college_email or p.personal_email if p else "") or "",
            (p.phone_number if p else "") or "",
        ])

    xlsx_bytes = ExportService.generate_excel("Student Roster", headers, rows)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="students_roster.xlsx"'},
    )


@router.get("/import-errors/{job_id}")
def download_import_errors_csv(
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download CSV error report for rows that failed import validation in a specific job.
    Includes row numbers, record references, and specific validation explanations.
    """
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found.")
    if principal.role == "institution_officer" and job.institution_id != principal.institution_id:
        raise HTTPException(status_code=404, detail="Import job not found.")

    failed_rows = db.query(ImportRowResult).filter(
        ImportRowResult.import_job_id == job_id,
        ImportRowResult.outcome != "ACCEPTED",
    ).order_by(ImportRowResult.row_number.asc()).all()

    headers = ["Row Number", "Student Reference", "Outcome", "Issue Codes", "Validation Details"]
    rows = []
    for r in failed_rows:
        msgs_list = []
        if isinstance(r.validation_messages, list):
            for m in r.validation_messages:
                if isinstance(m, dict):
                    fld = f"[{m.get('field', 'General')}] " if m.get('field') else ""
                    msgs_list.append(f"{fld}{m.get('message') or m.get('explanation') or m.get('code')}")
                else:
                    msgs_list.append(str(m))
            msgs = "; ".join(msgs_list)
        else:
            msgs = str(r.validation_messages or "")
        codes = ", ".join(r.issue_codes or []) if isinstance(r.issue_codes, list) else str(r.issue_codes or "")
        rows.append([r.row_number, r.record_reference or "", r.outcome, codes, msgs])

    csv_data = ExportService.generate_csv(headers, rows)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="import_errors_{job_id[:8]}.csv"'},
    )


@router.get("/{student_ref}")
def get_student_detail(
    student_ref: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_scope = principal.institution_id if principal.role == "institution_officer" else None
    require_student_institution(db, student_ref, institution_scope)
    student = db.query(Student).filter(Student.student_ref == student_ref).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    enrolment_query = db.query(Enrolment).filter(Enrolment.student_ref == student_ref)
    if institution_scope:
        enrolment_query = enrolment_query.filter(Enrolment.institution_id == institution_scope)
    enrolments = enrolment_query.order_by(Enrolment.enrolment_start.asc()).all()

    alerts = db.query(Alert).filter(Alert.student_ref == student_ref).all()
    versions_query = db.query(EnrolmentVersion).filter(EnrolmentVersion.student_ref == student_ref)
    if institution_scope:
        visible_record_ids = {enrolment.id for enrolment in enrolments}
        alerts = [
            alert for alert in alerts
            if alert.supporting_record_ids
            and set(alert.supporting_record_ids).issubset(visible_record_ids)
        ]
        versions_query = versions_query.filter(EnrolmentVersion.institution_id == institution_scope)
    versions = versions_query.order_by(EnrolmentVersion.created_at.desc()).all()

    evaluation = None
    if principal.role == "prototype_admin":
        evaluation = TemporalIntegrityEngine(db).evaluate_student(student_ref)

    if evaluation:
        integrity_status = evaluation.get("status")
        integrity_summary = evaluation.get("summary")
    elif institution_scope:
        integrity_status = "INSTITUTION_SCOPED"
        integrity_summary = "Cross-institution integrity details require reviewer access."
    else:
        unresolved_alerts = [alert for alert in alerts if alert.status != "RESOLVED"]
        if unresolved_alerts:
            integrity_status = "REQUIRES_INVESTIGATION"
            integrity_summary = f"{len(unresolved_alerts)} stored alert(s) remain unresolved; this read did not recalculate integrity."
        else:
            integrity_status = "NO_OPEN_ALERTS"
            integrity_summary = "No unresolved alert is currently stored; this read did not recalculate integrity."

    return {
        "student": {
            "student_ref": student.student_ref,
            "apaar_id": student.apaar_id if principal.role in {"administrator", "prototype_admin"} else mask_identifier(student.apaar_id),
            "full_name": student.full_name,
            "primary_institution_id": institution_scope or student.primary_institution_id,
            "identity_route": student.identity_route,
            "identity_status": student.identity_status,
            "nationality": student.nationality,
            "passport_ref": student.passport_ref if principal.role in {"administrator", "prototype_admin"} else None,
            "is_foreign_national": student.is_foreign_national,
            "is_nri": student.is_nri,
            "is_oci": student.is_oci,
            "created_at": student.created_at.isoformat() if student.created_at else None
        },
        "integrity_status": integrity_status,
        "integrity_summary": integrity_summary,
        "enrolments": [
            {
                "id": e.id,
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
                "record_version": e.record_version
            }
            for e in enrolments
        ],
        "alerts": [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "status": a.status,
                "title": a.title,
                "explanation": a.explanation,
                "evidence_summary": a.evidence_summary if principal.role in {"administrator", "prototype_admin"} else mask_sensitive_payload(a.evidence_summary),
                "confidence_score": a.confidence_score,
                "exception_ref": a.exception_ref,
                "reviewer_decision": a.reviewer_decision,
                "reviewer_note": a.reviewer_note,
                "reviewed_by": a.reviewed_by,
                "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None
            }
            for a in alerts
        ],
        "version_history": [
            {
                "id": v.id,
                "version_number": v.version_number,
                "institution_id": v.institution_id,
                "programme_id": v.programme_id,
                "enrolment_status": v.enrolment_status,
                "academic_year": v.academic_year,
                "changed_by": v.changed_by,
                "change_reason": v.change_reason,
                "diff_payload": v.diff_payload,
                "timestamp": v.created_at.isoformat() if v.created_at else None
            }
            for v in versions
        ]
    }


@router.patch("/{student_ref}/identity-status")
def update_student_identity_status(
    student_ref: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_scope = principal.institution_id if principal.role == "institution_officer" else None
    require_student_institution(db, student_ref, institution_scope)
    student = db.query(Student).filter(Student.student_ref == student_ref).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    new_status = payload.get("new_status")
    reason = payload.get("reason")
    if not new_status or not reason:
        raise HTTPException(status_code=400, detail="Missing required fields 'new_status' or 'reason'.")

    evidence_reference = payload.get("evidence_reference")
    new_apaar_id = payload.get("new_apaar_id")
    is_privileged = principal.role in {"administrator", "prototype_admin"}

    try:
        result = IdentityLifecycleService.update_student_identity(
            db=db,
            student=student,
            new_status=new_status,
            reason=reason,
            actor=principal.subject,
            evidence_reference=evidence_reference,
            new_apaar_id=new_apaar_id,
            is_privileged=is_privileged,
        )
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@router.get("/{student_ref}/versions")
def get_student_version_history(
    student_ref: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_scope = principal.institution_id if principal.role == "institution_officer" else None
    require_student_institution(db, student_ref, institution_scope)
    query = db.query(EnrolmentVersion).filter(EnrolmentVersion.student_ref == student_ref)
    if institution_scope:
        query = query.filter(EnrolmentVersion.institution_id == institution_scope)
    versions = query.order_by(EnrolmentVersion.created_at.desc()).all()

    return {
        "student_ref": student_ref,
        "total_versions": len(versions),
        "versions": [
            {
                "id": v.id,
                "enrolment_id": v.enrolment_id,
                "version_number": v.version_number,
                "institution_id": v.institution_id,
                "programme_id": v.programme_id,
                "enrolment_status": v.enrolment_status,
                "academic_year": v.academic_year,
                "changed_by": v.changed_by,
                "change_reason": v.change_reason,
                "diff_payload": v.diff_payload,
                "created_at": v.created_at.isoformat() if v.created_at else None
            }
            for v in versions
        ]
    }


@router.get("/{student_ref}/timeline")
def get_student_temporal_timeline(
    student_ref: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    institution_scope = principal.institution_id if principal.role == "institution_officer" else None
    require_student_institution(db, student_ref, institution_scope)
    student = db.query(Student.student_ref).filter(Student.student_ref == student_ref).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    enrolment_query = db.query(Enrolment).filter(Enrolment.student_ref == student_ref)
    if institution_scope:
        enrolment_query = enrolment_query.filter(Enrolment.institution_id == institution_scope)
    enrolments = enrolment_query.order_by(Enrolment.enrolment_start.asc(), Enrolment.id.asc()).all()

    pairwise_analysis = []
    for left_index, first in enumerate(enrolments):
        for second in enrolments[left_index + 1:]:
            overlaps, overlap_start, overlap_end, explanation = intervals_overlap(
                first.enrolment_start,
                first.enrolment_end,
                first.enrolment_status,
                second.enrolment_start,
                second.enrolment_end,
                second.enrolment_status,
            )
            pairwise_analysis.append({
                "record_ids": [first.id, second.id],
                "rule_id": TEMPORAL_OVERLAP_RULE_ID,
                "rule_version": INTEGRITY_RULE_VERSION,
                "overlaps": overlaps,
                "overlap_start": overlap_start.isoformat() if overlap_start else None,
                "overlap_end": (
                    "Ongoing" if overlap_end == FAR_FUTURE_DATE
                    else overlap_end.isoformat() if overlap_end else None
                ),
                "explanation": explanation,
                "compared_fields": {
                    "record_1": {
                        "institution_id": first.institution_id,
                        "programme_id": first.programme_id,
                        "start": first.enrolment_start.isoformat(),
                        "end": first.enrolment_end.isoformat() if first.enrolment_end else None,
                        "status": first.enrolment_status,
                    },
                    "record_2": {
                        "institution_id": second.institution_id,
                        "programme_id": second.programme_id,
                        "start": second.enrolment_start.isoformat(),
                        "end": second.enrolment_end.isoformat() if second.enrolment_end else None,
                        "status": second.enrolment_status,
                    },
                },
                "recommended_action": (
                    "Request documentation and reviewer assessment."
                    if overlaps else "No temporal conflict indicated by this pairwise rule."
                ),
            })

    return {
        "student_ref": student_ref,
        "rule_id": TEMPORAL_OVERLAP_RULE_ID,
        "rule_version": INTEGRITY_RULE_VERSION,
        "enrolments": [
            {
                "id": enrolment.id,
                "institution_id": enrolment.institution_id,
                "institution_name": enrolment.institution_name,
                "programme_id": enrolment.programme_id,
                "programme_name": enrolment.programme_name,
                "academic_year": enrolment.academic_year,
                "start": enrolment.enrolment_start.isoformat(),
                "end": enrolment.enrolment_end.isoformat() if enrolment.enrolment_end else None,
                "status": enrolment.enrolment_status,
            }
            for enrolment in enrolments
        ],
        "pairwise_analysis": pairwise_analysis,
        "status_transition_checks": [
            {
                "record_id": enrolment.id,
                "status": enrolment.enrolment_status,
                "recognized_status": enrolment.enrolment_status.lower() in {
                    "active", "completed", "withdrawn", "suspended"
                },
                "explanation": (
                    "Status is recognized by the current validation rules."
                    if enrolment.enrolment_status.lower() in {"active", "completed", "withdrawn", "suspended"}
                    else "Status is not recognized by the current validation rules; review the source record."
                ),
            }
            for enrolment in enrolments
        ],
    }

@router.post("", response_model=Dict[str, Any], status_code=201)
def create_student_with_enrolment(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if principal.role == "institution_officer" and payload.get("institution_id") != principal.institution_id:
        raise HTTPException(status_code=403, detail="Institution operators can only create records for their assigned institution.")
    student_ref = payload.get("student_ref")
    apaar_id = payload.get("apaar_id")
    full_name = payload.get("full_name")

    if not student_ref or not apaar_id or not full_name:
        raise HTTPException(status_code=400, detail="Missing student_ref, apaar_id, or full_name")

    # Validate schema
    validation_errors = ValidationService.validate_record(payload)
    critical_errors = [e for e in validation_errors if e["severity"] in ("CRITICAL", "ERROR")]
    if critical_errors:
        return {
            "success": False,
            "message": "Validation failed",
            "validation_errors": critical_errors
        }

    # Upsert student
    existing_student = db.query(Student).filter(Student.student_ref == student_ref).first()
    if not existing_student:
        category = normalize_admission_category(payload.get("seat_category", "General")) or "General"
        category_flags = student_flags_for_admission_category(category)
        is_fn = bool(payload.get("is_foreign_national", category_flags["is_foreign_national"]))
        init_status, init_route, init_nat = IdentityLifecycleService.derive_initial_identity(
            apaar_id=apaar_id,
            is_foreign_national=is_fn,
            is_historical=bool(payload.get("is_historical", False)),
            passport_ref=payload.get("passport_ref"),
        )
        student = Student(
            student_ref=student_ref,
            apaar_id=apaar_id,
            full_name=full_name,
            primary_institution_id=payload.get("institution_id"),
            identity_route=payload.get("identity_route", init_route),
            identity_status=payload.get("identity_status", init_status),
            nationality=payload.get("nationality", init_nat),
            passport_ref=payload.get("passport_ref"),
            is_foreign_national=is_fn,
            is_nri=bool(payload.get("is_nri", category_flags["is_nri"])),
            is_oci=bool(payload.get("is_oci", category_flags["is_oci"]))
        )
        db.add(student)
        db.flush()

    # Parse dates
    start_date = datetime.strptime(str(payload["enrolment_start"]).strip(), "%Y-%m-%d").date()
    end_date = None
    if payload.get("enrolment_end") and str(payload.get("enrolment_end")).strip():
        end_date = datetime.strptime(str(payload["enrolment_end"]).strip(), "%Y-%m-%d").date()

    enrolment = Enrolment(
        student_ref=student_ref,
        apaar_id=apaar_id,
        institution_id=payload["institution_id"],
        institution_name=payload.get("institution_name", payload["institution_id"]),
        programme_id=payload["programme_id"],
        programme_name=payload.get("programme_name", payload["programme_id"]),
        academic_year=payload["academic_year"],
        admission_cycle=payload.get("admission_cycle", "Regular 2025"),
        enrolment_start=start_date,
        enrolment_end=end_date,
        enrolment_status=payload.get("enrolment_status", "Active"),
        seat_category=normalize_admission_category(payload.get("seat_category", "General")) or "General",
        exception_ref=payload.get("exception_ref"),
        source_submission_id=payload.get("source_submission_id", "MANUAL-ENTRY"),
        record_version=int(payload.get("record_version", 1))
    )
    db.add(enrolment)
    db.flush()

    # Record Version 1 in EnrolmentVersion history
    v1 = EnrolmentVersion(
        enrolment_id=enrolment.id,
        student_ref=student_ref,
        version_number=1,
        institution_id=enrolment.institution_id,
        programme_id=enrolment.programme_id,
        enrolment_status=enrolment.enrolment_status,
        academic_year=enrolment.academic_year,
        changed_by="Institutional Operator (Console)",
        change_reason="Initial enrolment registration",
        diff_payload={"action": "INITIAL_RECORD", "seat_category": enrolment.seat_category}
    )
    db.add(v1)
    db.commit()

    # Run integrity engine on this student
    engine_svc = TemporalIntegrityEngine(db)
    evaluation = engine_svc.evaluate_student(student_ref)

    AuditService.log_event(
        db=db,
        entity_type="STUDENT",
        entity_id=student_ref,
        action="RECORD_CREATE",
        performed_by="Institutional Operator (Web Console)",
        details={"institution_id": payload["institution_id"], "programme_id": payload["programme_id"], "version": 1}
    )

    return {
        "success": True,
        "student_ref": student_ref,
        "enrolment_id": enrolment.id,
        "integrity_status": evaluation["status"],
        "alerts_generated": len(evaluation["alerts"])
    }

def _finalize_failed_import(db: Session, job_id: str, total_rows: int, safe_error: str) -> None:
    db.rollback()
    job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
    if not job:
        return
    job.status = "FAILED"
    job.total_rows = total_rows
    job.accepted_rows = 0
    job.rejected_rows = total_rows
    job.review_rows = 0
    job.safe_error_summary = safe_error
    job.validation_summary = {"error": safe_error}
    job.completed_at = datetime.utcnow()
    AuditService.log_event(
        db=db,
        entity_type="IMPORT_JOB",
        entity_id=job.id,
        action="CSV_IMPORT_FAILED",
        performed_by=job.submitted_by,
        details={"institution_id": job.institution_id, "status": job.status},
        commit=False,
    )
    db.commit()


@router.post("/upload", dependencies=[Depends(rate_limit_csv_upload)])
@router.post("/upload-csv", dependencies=[Depends(rate_limit_csv_upload)])
async def upload_students_csv(
    file: UploadFile = File(...),
    previous_job_id: Optional[str] = Form(None),
    preview: Optional[bool] = Form(False),
    dry_run: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    filename = safe_filename(file.filename)
    is_preview = bool(preview or dry_run)
    previous_job = None
    if previous_job_id:
        previous_job = db.query(ImportJob).filter(ImportJob.id == previous_job_id).first()
        if not previous_job:
            raise HTTPException(status_code=404, detail="Previous import job not found.")
        if principal.role == "institution_officer" and previous_job.institution_id != principal.institution_id:
            raise HTTPException(status_code=404, detail="Previous import job not found.")

    job = ImportJob(
        id=str(uuid.uuid4()),
        institution_id=principal.institution_id if principal.role == "institution_officer" else None,
        submitted_by=principal.subject,
        original_filename=filename,
        previous_job_id=previous_job.id if previous_job else None,
        status="PROCESSING",
        validation_summary={},
    )
    db.add(job)
    db.commit()
    job_id = job.id
    total_rows = 0

    try:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload a standard CSV file.")

        content = await file.read(MAX_CSV_UPLOAD_BYTES + 1)
        if len(content) > MAX_CSV_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="CSV upload exceeds the 10 MB limit.")
        try:
            try:
                decoded = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                decoded = content.decode("utf-8")
            text_stream = io.StringIO(decoded)
            reader = csv.DictReader(text_stream)
            headers = reader.fieldnames or []
            if any(not isinstance(header, str) for header in headers):
                raise HTTPException(status_code=400, detail="CSV contains invalid column headers.")
            normalized_headers = [header.strip().lstrip("\ufeff").lower() for header in headers]
            if len(normalized_headers) != len(set(normalized_headers)):
                raise HTTPException(status_code=400, detail="CSV contains duplicate or ambiguous column headers.")
            records = [
                {(k.lstrip("\ufeff") if isinstance(k, str) else k): v for k, v in row.items()}
                for row in reader
            ]
        except HTTPException:
            raise
        except (UnicodeDecodeError, csv.Error, ValueError):
            raise HTTPException(status_code=400, detail="Failed to parse CSV. Check encoding and CSV structure.")

        total_rows = len(records)
        if total_rows > MAX_CSV_ROWS:
            raise HTTPException(status_code=413, detail=f"CSV exceeds the {MAX_CSV_ROWS:,}-row limit.")

        if not records:
            _finalize_failed_import(db, job_id, 0, "CSV file contained no data rows.")
            return {
                "filename": filename,
                "import_job_id": job_id,
                "status": "FAILED",
                "total_rows": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "review_count": 0,
                "pass_rate_percent": 100.0,
                "error_count_by_severity": {},
                "field_errors": [],
                "dry_run": is_preview,
                "preview": is_preview,
                "message": "CSV file was empty.",
            }

        # Check required columns with alias support and optional institution inference
        allow_inferred = bool(principal.role == "institution_officer" and principal.institution_id)
        valid_headers, missing = ValidationService.validate_headers(headers, allow_inferred_institution=allow_inferred)
        if not valid_headers:
            raise HTTPException(status_code=400, detail=f"CSV missing mandatory column(s): {', '.join(missing)}.")

        # Batch submission ID for provenance tracking
        batch_submission_id = f"BATCH-{job_id[:8].upper()}-{datetime.utcnow().year}"

        # Map each row's aliases to canonical fields and apply default institution if appropriate
        default_inst = principal.institution_id if principal.role == "institution_officer" else None
        mapped_records = [
            ValidationService.map_csv_row(
                row,
                default_institution_id=default_inst,
                default_submission_id=batch_submission_id,
            )
            for row in records
        ]

        if principal.role == "institution_officer" and any(
            str(row.get("institution_id", "")).strip()
            and canonicalize_institution_id(str(row.get("institution_id", "")).strip()) != canonicalize_institution_id(principal.institution_id)
            for row in mapped_records
        ):
            raise HTTPException(status_code=403, detail="CSV contains rows outside the assigned institution.")

        institution_ids = {str(row.get("institution_id", "")).strip() for row in mapped_records if str(row.get("institution_id", "")).strip()}
        if principal.role != "institution_officer" and len(institution_ids) == 1:
            job.institution_id = next(iter(institution_ids))

        result = StudentCsvImportService(db).process(job, mapped_records, previous_job, dry_run=is_preview)
        rejected_count = result["rejected_count"]
        status_text = job.status
        if is_preview:
            message = (
                f"Preview completed: {result['accepted_count']} rows valid. "
                f"{rejected_count} rows invalid or flagged. No database changes were applied."
            )
        else:
            message = (
                f"Successfully ingested {result['accepted_count']} valid rows with version tracking. "
                f"{rejected_count} rows were not imported."
            )
        return {
            "filename": filename,
            "import_job_id": job_id,
            "job_id": job_id,
            "previous_job_id": job.previous_job_id,
            "status": status_text,
            "total_rows": result["total_rows"],
            "rows_received": result["total_rows"],
            "valid_rows": result.get("valid_rows", result["accepted_count"]),
            "accepted_count": result["accepted_count"],
            "rows_imported": result.get("rows_imported", result["accepted_count"] if not is_preview else 0),
            "updated_count": result.get("updated_count", 0),
            "duplicate_count": result.get("duplicate_count", 0),
            "rejected_count": rejected_count,
            "rows_rejected": rejected_count,
            "unprocessed_count": 0,
            "review_count": result["review_count"],
            "pass_rate_percent": result["pass_rate_percent"],
            "error_count_by_severity": result["error_count_by_severity"],
            "field_errors": result["field_errors"],
            "dry_run": is_preview,
            "preview": is_preview,
            "message": message,
        }
    except HTTPException as exc:
        _finalize_failed_import(db, job_id, total_rows, "Upload was rejected before import completion.")
        headers = dict(exc.headers or {})
        headers["X-Import-Job-Id"] = job_id
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc
    except Exception as exc:
        _finalize_failed_import(db, job_id, total_rows, "Unexpected import-processing error; accepted writes were rolled back.")
        raise HTTPException(
            status_code=500,
            detail="CSV import failed unexpectedly; no accepted rows from this job were committed.",
            headers={"X-Import-Job-Id": job_id},
        ) from exc
