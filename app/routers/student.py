from fastapi import APIRouter, Depends, HTTPException, Query, Body, status, Response
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from app.database import get_db
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.user import User
from app.models.certificate import Certificate
from app.models.transfer import TransferRequest
from app.models.erp import StudentDocument
from app.services.student_service import StudentService
from app.services.erp_service import ErpService
from app.services.pdf_generator import PdfGeneratorService
from app.services.audit_service import AuditService
from app.security import Principal, get_current_principal

router = APIRouter(prefix="/student", tags=["Student Portal"])


def _resolve_authenticated_student(
    db: Session,
    principal: Principal,
    requested_ref: Optional[str] = None,
) -> Student:
    """
    Resolve and authorize the Student entity for the current principal.
    Strictly forbids Student A from accessing Student B's data.
    Never trusts client-provided identifiers for student principals.
    """
    if principal.role not in {"student", "administrator", "prototype_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API operation is restricted to authenticated students.",
        )

    if principal.role == "student":
        student = StudentService.get_student_for_user(
            db=db,
            user_id=principal.user_id,
            username=principal.subject,
        )
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No verified student record is associated with this user account.",
            )
        # Defense in depth: if client passed an explicit student_ref query param, assert ownership
        if requested_ref and requested_ref.strip().upper() != student.student_ref.upper():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You cannot inspect another student's records.",
            )
        return student

    # Administrators may view on behalf of a student using query param
    if requested_ref:
        student = db.query(Student).filter(Student.student_ref == requested_ref.strip()).first()
        if not student:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Student '{requested_ref}' not found.")
        return student

    # Default admin fallback to first student for diagnostics
    first_student = db.query(Student).first()
    if not first_student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No students exist in database.")
    return first_student


@router.get("/profile")
def get_student_profile(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve authenticated student profile, institutional affiliation, and DPDP consents.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    user = db.query(User).filter(User.id == principal.user_id).first() if principal.user_id else None
    return StudentService.get_student_profile(db, student, user)


@router.get("/academic-history")
def get_academic_history(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve chronological academic enrolment history for the authenticated student.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    history = StudentService.get_academic_history(db, student.student_ref)
    return {
        "student_ref": student.student_ref,
        "student_name": student.full_name,
        "total_enrolments": len(history),
        "enrolments": history,
    }


@router.get("/credentials")
def get_student_credentials(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve digital academic credentials and cryptographic verification status.
    Excludes private signing keys and internal server secrets.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    credentials = StudentService.get_credentials(db, student.student_ref)
    return {
        "student_ref": student.student_ref,
        "student_name": student.full_name,
        "total_credentials": len(credentials),
        "credentials": credentials,
    }


@router.get("/transfers")
def get_student_transfers(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve cross-institution transfer requests and migration decisions.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    transfers = StudentService.get_transfers(db, student.student_ref)
    return {
        "student_ref": student.student_ref,
        "student_name": student.full_name,
        "total_transfers": len(transfers),
        "transfers": transfers,
    }


@router.patch("/consent/{consent_id}/toggle")
def toggle_student_consent(
    consent_id: int,
    payload: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Allow authenticated student to toggle their own DPDP verification consent.
    """
    student = _resolve_authenticated_student(db, principal)
    granted = payload.get("consent_granted")
    return StudentService.toggle_consent(
        db=db,
        student_ref=student.student_ref,
        consent_id=consent_id,
        granted=granted,
        actor=principal.subject,
    )


# =============================================================================
# TAB 1: AICTE — STUDENT-SPECIFIC REGULATORY VIEW
# =============================================================================
@router.get("/aicte-view")
def get_student_aicte_view(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve authenticated student's AICTE regulatory view.
    Includes approved intake context, verification state, and dual-enrolment integrity checks.
    Strictly distinct from the AICTE National Administrative Dashboard.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    return ErpService.get_student_aicte_regulatory_view(db, student)


# =============================================================================
# TAB 2: STUDENT INFO (ERP PROFILE & DOCUMENTS)
# =============================================================================
@router.get("/erp-profile")
def get_student_erp_profile(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve authenticated student's comprehensive ERP profile.
    Combines personal contact info, addresses, and institutional affiliation.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    profile = ErpService.get_or_create_student_profile(db, student)
    return {
        "student_ref": student.student_ref,
        "full_name": student.full_name,
        "apaar_id": student.apaar_id,
        "identity_status": student.identity_status,
        "nationality": student.nationality,
        "primary_institution_id": student.primary_institution_id,
        "roll_number": profile.roll_number,
        "date_of_birth": profile.date_of_birth,
        "gender": profile.gender,
        "blood_group": profile.blood_group,
        "college_email": profile.college_email,
        "personal_email": profile.personal_email,
        "phone_number": profile.phone_number,
        "alternate_phone": profile.alternate_phone,
        "emergency_contact_name": profile.emergency_contact_name,
        "emergency_contact_phone": profile.emergency_contact_phone,
        "current_address": profile.current_address,
        "current_city": profile.current_city,
        "current_state": profile.current_state,
        "current_pincode": profile.current_pincode,
        "permanent_address": profile.permanent_address,
        "permanent_city": profile.permanent_city,
        "permanent_state": profile.permanent_state,
        "permanent_pincode": profile.permanent_pincode,
        "department": profile.department,
        "batch_year": profile.batch_year,
        "current_year": profile.current_year,
        "current_semester": profile.current_semester,
        "section": profile.section,
        "admission_category": profile.admission_category,
        "admission_date": profile.admission_date,
        "profile_status": profile.profile_status,
        "profile_completion_pct": profile.profile_completion_pct,
        "review_remarks": profile.review_remarks,
        "reviewed_by": profile.reviewed_by,
        "reviewed_at": profile.reviewed_at.isoformat() if profile.reviewed_at else None,
        "submitted_at": profile.submitted_at.isoformat() if profile.submitted_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@router.put("/erp-profile")
def update_student_erp_profile(
    payload: Dict[str, Any] = Body(...),
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Save draft edits for student-editable contact and address fields.
    Institution-controlled academic fields are protected from student mutation.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    is_admin = principal.role in {"administrator", "prototype_admin"}
    updated = ErpService.update_student_profile(
        db=db,
        student=student,
        payload=payload,
        actor=principal.subject,
        is_college_officer=is_admin,
    )
    return {
        "status": "SUCCESS",
        "message": "Student profile updated successfully.",
        "profile_completion_pct": updated.profile_completion_pct,
        "profile_status": updated.profile_status,
    }


@router.post("/submit-profile")
def submit_student_profile(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Submit completed profile for institutional registrar verification.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    submitted = ErpService.submit_profile_for_review(db, student, principal.subject)
    return {
        "status": "SUBMITTED",
        "message": "Profile submitted to institution admissions cell for verification.",
        "submitted_at": submitted.submitted_at.isoformat() if submitted.submitted_at else None,
        "profile_status": submitted.profile_status,
    }


@router.get("/documents")
def get_student_documents(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve student documents and institutional verification audit history.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    docs = ErpService.get_student_documents(db, student.student_ref)
    return {
        "student_ref": student.student_ref,
        "total_documents": len(docs),
        "documents": [
            {
                "id": d.id,
                "document_type": d.document_type,
                "document_title": d.document_title,
                "file_name": d.file_name,
                "file_url": d.file_url,
                "file_size_kb": d.file_size_kb,
                "status": d.status,
                "verification_remarks": d.verification_remarks,
                "verified_by": d.verified_by,
                "verified_at": d.verified_at.isoformat() if d.verified_at else None,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            }
            for d in docs
        ],
    }


@router.post("/documents")
def upload_student_document(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Register a newly uploaded student document for institutional review.
    """
    student = _resolve_authenticated_student(db, principal)
    doc_type = payload.get("document_type", "OTHER_CERTIFICATE")
    doc_title = payload.get("document_title", "Institutional Certificate")
    file_name = payload.get("file_name", "document.pdf")
    file_size_kb = int(payload.get("file_size_kb", 256))

    doc = ErpService.upload_student_document(
        db=db,
        student_ref=student.student_ref,
        document_type=doc_type,
        document_title=doc_title,
        file_name=file_name,
        file_size_kb=file_size_kb,
        actor=principal.subject,
    )
    return {
        "status": "SUCCESS",
        "message": "Document uploaded and queued for registrar verification.",
        "document_id": doc.id,
        "document_status": doc.status,
    }


# =============================================================================
# TAB 3: ACADEMICS (OVERVIEW, COURSES, ATTENDANCE, TIMETABLE, MATERIALS)
# =============================================================================
@router.get("/academics/overview")
def get_academics_overview(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Calculate and retrieve cumulative GPA, total earned credits, and attendance.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    return ErpService.get_academics_summary(db, student.student_ref)


@router.get("/academics/courses")
def get_academic_courses(
    semester: Optional[int] = Query(None, description="Optional semester filter (1-8)"),
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve subject-wise course registrations, internal/external examination marks, and grades.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    courses = ErpService.get_course_records(db, student.student_ref, semester=semester)
    return {
        "student_ref": student.student_ref,
        "semester_filter": semester,
        "total_courses": len(courses),
        "courses": courses,
    }


@router.get("/academics/attendance")
def get_academic_attendance(
    semester: Optional[int] = Query(None, description="Optional semester filter (1-8)"),
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve authoritative subject-wise attendance and shortage flags.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    records = ErpService.get_attendance_records(db, student.student_ref, semester=semester)
    return {
        "student_ref": student.student_ref,
        "semester_filter": semester,
        "records": records,
    }


@router.get("/academics/timetable")
def get_academic_timetable(
    semester: int = Query(5, description="Semester schedule"),
    section: str = Query("A", description="Section batch"),
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve weekly timetable slots for the student's current cohort.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    inst_id = student.primary_institution_id or "INST-DELHI-DTU"
    slots = ErpService.get_timetable(db, institution_id=inst_id, semester=semester, section=section)
    return {
        "institution_id": inst_id,
        "semester": semester,
        "section": section,
        "schedule": slots,
    }


@router.get("/academics/materials")
def get_academic_materials(
    semester: int = Query(5, description="Semester materials"),
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve lecture notes, course outlines, and reference documents.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    inst_id = student.primary_institution_id or "INST-DELHI-DTU"
    materials = ErpService.get_course_materials(db, institution_id=inst_id, semester=semester)
    return {
        "institution_id": inst_id,
        "semester": semester,
        "materials": materials,
    }


# =============================================================================
# TAB 4: STUDENT SERVICES (INTERNSHIPS, PLACEMENT, FEES, NO DUE)
# =============================================================================
@router.get("/services/internships")
def get_student_internships(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve student internships and industrial training history.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    internships = ErpService.get_internships(db, student.student_ref)
    return {
        "student_ref": student.student_ref,
        "total_internships": len(internships),
        "internships": [
            {
                "id": i.id,
                "company_name": i.company_name,
                "role_title": i.role_title,
                "location": i.location,
                "start_date": i.start_date,
                "end_date": i.end_date,
                "stipend_amount": i.stipend_amount,
                "mentor_name": i.mentor_name,
                "mentor_email": i.mentor_email,
                "status": i.status,
                "offer_letter_url": i.offer_letter_url,
                "completion_cert_url": i.completion_cert_url,
                "review_feedback": i.review_feedback,
                "reviewed_by": i.reviewed_by,
                "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None,
                "milestone_summary": i.milestone_summary,
            }
            for i in internships
        ],
    }


@router.post("/services/internships")
def apply_internship(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Submit an internship application for college coordinator review.
    Students cannot approve their own internships.
    """
    student = _resolve_authenticated_student(db, principal)
    inst_id = student.primary_institution_id or "INST-DELHI-DTU"
    internship = ErpService.apply_for_internship(
        db=db,
        student_ref=student.student_ref,
        institution_id=inst_id,
        payload=payload,
        actor=principal.subject,
    )
    return {
        "status": "SUCCESS",
        "message": "Internship submitted and awaiting college coordinator review.",
        "internship_id": internship.id,
        "internship_status": internship.status,
    }


@router.get("/services/placement-readiness")
def get_placement_readiness(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve placement readiness scores, coding ratings, and skill certificates.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    return ErpService.get_placement_readiness(db, student.student_ref)


@router.get("/services/fees")
def get_student_fees(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve semester-wise statutory fee obligations, verified receipts, and outstanding dues.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    return ErpService.get_fee_obligations_and_payments(db, student.student_ref)


@router.get("/services/no-due")
def get_no_due_status(
    student_ref: Optional[str] = Query(None, description="Optional override for administrators only"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Retrieve active No Due form and departmental clearance status.
    """
    student = _resolve_authenticated_student(db, principal, student_ref)
    return ErpService.get_no_due_status(db, student.student_ref)


@router.post("/services/no-due")
def initiate_no_due_request(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Initiate a departmental No Due clearance request.
    Requires multi-department sign-off (Library, Labs, Accounts, Hostel).
    """
    student = _resolve_authenticated_student(db, principal)
    inst_id = student.primary_institution_id or "INST-DELHI-DTU"
    reason = payload.get("reason", "Semester Clearance")
    academic_year = payload.get("academic_year", "2025-2026")

    req = ErpService.initiate_no_due_request(
        db=db,
        student_ref=student.student_ref,
        institution_id=inst_id,
        reason=reason,
        academic_year=academic_year,
        actor=principal.subject,
    )
    return {
        "status": "INITIATED",
        "message": "No Due clearance request initiated across all departments.",
        "request_id": req.id,
        "overall_status": req.overall_status,
    }


# =============================================================================
# DOWNLOADS: CERTIFICATES, TRANSCRIPTS & BOND EFFECT CERTIFICATES
# =============================================================================
@router.get("/certificates")
def list_student_certificates(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """List authenticated student's issued degree/credential certificates."""
    student = _resolve_authenticated_student(db, principal)
    certs = db.query(Certificate).filter(Certificate.student_ref == student.student_ref).all()
    return [
        {
            "certificate_id": c.certificate_id,
            "student_ref": c.student_ref,
            "apaar_id": c.apaar_id,
            "student_name": c.student_name,
            "institution_name": c.institution_name,
            "programme_name": c.programme_name,
            "issue_date": c.issue_date,
            "status": c.status,
            "signature_algorithm": c.signature_algorithm,
            "public_key_id": c.public_key_id,
        }
        for c in certs
    ]


@router.get("/certificates/{certificate_id}/download")
def download_student_certificate(
    certificate_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download authenticated student's official digital credential PDF.
    Strictly verifies ownership: students can only download their own credentials.
    """
    student = _resolve_authenticated_student(db, principal)
    cert = db.query(Certificate).filter(
        Certificate.certificate_id == certificate_id,
        Certificate.student_ref == student.student_ref,
    ).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found or not owned by student.")

    cert_dict = {
        "certificate_id": cert.certificate_id,
        "student_ref": cert.student_ref,
        "student_name": cert.student_name,
        "apaar_id": cert.apaar_id or "N/A",
        "institution_id": cert.institution_id,
        "institution_name": cert.institution_name,
        "programme_name": cert.programme_name,
        "completion_date": cert.completion_date,
        "issue_date": cert.issue_date,
        "status": cert.status,
        "signature_algorithm": cert.signature_algorithm,
        "public_key_id": cert.public_key_id,
        "signature_hex": cert.signature_hex,
    }

    pdf_bytes = PdfGeneratorService.generate_certificate_pdf(
        certificate_data=cert_dict,
        institution_name=cert.institution_name,
    )

    AuditService.log_event(
        db=db,
        entity_type="CERTIFICATE",
        entity_id=certificate_id,
        action="STUDENT_CERTIFICATE_DOWNLOAD",
        performed_by=principal.subject,
        details={"student_ref": student.student_ref, "bytes": len(pdf_bytes)},
    )

    filename = f"certificate_{certificate_id.replace('/', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf",
        },
    )


@router.get("/transcripts/{semester}/download")
def download_student_transcript(
    semester: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download authenticated student's official semester academic transcript as a PDF.
    """
    student = _resolve_authenticated_student(db, principal)
    profile = ErpService.get_or_create_student_profile(db, student)
    courses = ErpService.get_course_records(db, student.student_ref, semester=semester if semester > 0 else None)
    summary = ErpService.get_academics_summary(db, student.student_ref)

    enrolment = db.query(Enrolment).filter(Enrolment.student_ref == student.student_ref).first()
    programme_name = (enrolment.programme_name if enrolment else None) or (enrolment.programme_id if enrolment else None) or profile.department or "Bachelor of Technology"

    student_data = {
        "full_name": student.full_name,
        "student_ref": student.student_ref,
        "apaar_id": student.apaar_id or "N/A",
        "roll_number": profile.roll_number or student.student_ref,
        "department": profile.department or "Engineering",
        "programme": programme_name,
        "batch_year": profile.batch_year or "2023-2027",
        "current_semester": semester if semester > 0 else (profile.current_semester or 5),
        "institution_name": "St. Joseph's College of Engineering, Chennai" if "SJCE" in (student.primary_institution_id or "") else "Academic Institution",
    }

    pdf_bytes = PdfGeneratorService.generate_transcript_pdf(
        student_data=student_data,
        courses=courses,
        semester=semester if semester > 0 else profile.current_semester,
        summary_data=summary,
        institution_name=student_data["institution_name"],
    )

    AuditService.log_event(
        db=db,
        entity_type="TRANSCRIPT",
        entity_id=f"{student.student_ref}-SEM{semester}",
        action="TRANSCRIPT_DOWNLOAD",
        performed_by=principal.subject,
        details={"student_ref": student.student_ref, "semester": semester, "bytes": len(pdf_bytes)},
    )

    filename = f"transcript_{student.student_ref}_sem{semester}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf",
        },
    )


@router.get("/transfers/{transfer_id}/bond-effect-certificate")
def download_bond_effect_certificate(
    transfer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download official 'Bond Effect Certificate' certifying study bond clearance
    and non-encumbrance for student transfer mobility.
    """
    student = _resolve_authenticated_student(db, principal)
    transfer = db.query(TransferRequest).filter(
        TransferRequest.id == transfer_id,
        TransferRequest.student_ref == student.student_ref,
    ).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer request not found for this student.")

    profile = ErpService.get_or_create_student_profile(db, student)
    student_data = {
        "full_name": student.full_name,
        "student_ref": student.student_ref,
        "apaar_id": student.apaar_id or "N/A",
        "roll_number": profile.roll_number or student.student_ref,
        "department": profile.department or "Engineering",
        "programme": student.programme_id or "Bachelor of Technology",
        "institution_name": transfer.source_institution_id,
    }

    transfer_data = {
        "id": transfer.id,
        "source_institution_id": transfer.source_institution_id,
        "destination_institution_id": transfer.destination_institution_id,
        "status": transfer.status,
        "noc_certificate_ref": transfer.noc_certificate_ref,
    }

    inst_display_name = "St. Joseph's College of Engineering, Chennai" if "SJCE" in transfer.source_institution_id else transfer.source_institution_id
    pdf_bytes = PdfGeneratorService.generate_bond_effect_certificate_pdf(
        student_data=student_data,
        transfer_data=transfer_data,
        institution_name=inst_display_name,
    )

    AuditService.log_event(
        db=db,
        entity_type="TRANSFER_BOND_CERTIFICATE",
        entity_id=transfer_id,
        action="BOND_EFFECT_CERTIFICATE_DOWNLOAD",
        performed_by=principal.subject,
        details={"transfer_id": transfer_id, "student_ref": student.student_ref, "bytes": len(pdf_bytes)},
    )

    filename = f"bond_effect_certificate_{transfer_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf",
        },
    )


@router.get("/documents/{document_id}/download")
def download_student_document(
    document_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Download authenticated student's uploaded or verified institutional document.
    """
    student = _resolve_authenticated_student(db, principal)
    doc = db.query(StudentDocument).filter(
        StudentDocument.id == document_id,
        StudentDocument.student_ref == student.student_ref,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Student document not found.")

    profile = ErpService.get_or_create_student_profile(db, student)
    doc_dict = {
        "certificate_id": f"DOC-{doc.id}",
        "student_name": student.full_name,
        "student_ref": student.student_ref,
        "apaar_id": student.apaar_id or "N/A",
        "institution_name": "St. Joseph's College of Engineering, Chennai" if "SJCE" in (student.primary_institution_id or "") else "Academic Institution",
        "programme_name": doc.document_title or doc.document_type,
        "issue_date": doc.uploaded_at.strftime("%Y-%m-%d") if doc.uploaded_at else "2026-01-01",
        "completion_date": doc.verified_at.strftime("%Y-%m-%d") if doc.verified_at else None,
        "status": doc.status,
        "signature_algorithm": "SHA256-RSA",
        "public_key_id": "INSTITUTIONAL-SEAL-KEY-01",
        "signature_hex": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }

    pdf_bytes = PdfGeneratorService.generate_certificate_pdf(
        certificate_data=doc_dict,
        institution_name=doc_dict["institution_name"],
    )

    filename = f"document_{doc.id}_{doc.document_type.lower()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf",
        },
    )

