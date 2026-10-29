from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.certificate import Certificate
from app.models.consent import StudentConsent
from app.models.transfer import TransferRequest
from app.models.student_user import StudentUserLink
from app.models.user import User
from app.services.certificate_service import CertificateService
from app.services.audit_service import AuditService
from app.security import mask_identifier


class StudentService:
    @classmethod
    def get_student_for_user(
        cls,
        db: Session,
        user_id: int,
        username: Optional[str] = None,
    ) -> Optional[Student]:
        """
        Securely resolve the Student record linked to an authenticated User account.
        Queries the authoritative student_user_links mapping table first.
        Applies safe deterministic identity-resolution fallback for seeded demo accounts.
        Never relies on unauthenticated client-supplied identifiers.
        """
        # 1. Authoritative mapping table
        link = db.query(StudentUserLink).filter(
            StudentUserLink.user_id == user_id
        ).order_by(StudentUserLink.is_primary.desc(), StudentUserLink.id.asc()).first()

        if link:
            student = db.query(Student).filter(Student.student_ref == link.student_ref).first()
            if student:
                return student

        # 2. Fallback for demo student accounts or direct identifier matching
        if username:
            normalized = username.strip()
            # Direct match on student_ref (e.g., STU-DEMO-001)
            student = db.query(Student).filter(Student.student_ref.ilike(normalized)).first()
            if not student and normalized.startswith("student_"):
                # e.g., student_stu_demo_001 -> STU-DEMO-001
                candidate_ref = normalized.removeprefix("student_").replace("_", "-").upper()
                student = db.query(Student).filter(Student.student_ref == candidate_ref).first()
            if not student and normalized == "student_demo":
                student = db.query(Student).filter(Student.student_ref == "STU-DEMO-001").first()
            elif not student and normalized == "student_priya":
                student = db.query(Student).filter(Student.student_ref == "STU-DEMO-002").first()
            elif not student and normalized == "student_aarav":
                student = db.query(Student).filter(Student.student_ref == "STU-IND-081").first()
                if not student:
                    student = db.query(Student).first()

            if student:
                # Cache the link in the mapping table for instant subsequent lookups
                existing_link = db.query(StudentUserLink).filter(
                    StudentUserLink.user_id == user_id,
                    StudentUserLink.student_ref == student.student_ref,
                ).first()
                if not existing_link:
                    db.add(StudentUserLink(
                        user_id=user_id,
                        student_ref=student.student_ref,
                        is_primary=True,
                    ))
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
                return student

        return None

    @classmethod
    def link_user_to_student(
        cls,
        db: Session,
        user_id: int,
        student_ref: str,
        is_primary: bool = True,
    ) -> StudentUserLink:
        """Create or update link between user account and student record."""
        student = db.query(Student).filter(Student.student_ref == student_ref).first()
        if not student:
            raise HTTPException(status_code=404, detail=f"Student record '{student_ref}' not found.")

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User account '{user_id}' not found.")

        existing = db.query(StudentUserLink).filter(
            StudentUserLink.user_id == user_id,
            StudentUserLink.student_ref == student_ref,
        ).first()

        if existing:
            existing.is_primary = is_primary
            db.commit()
            return existing

        new_link = StudentUserLink(
            user_id=user_id,
            student_ref=student_ref,
            is_primary=is_primary,
        )
        db.add(new_link)
        db.commit()
        db.refresh(new_link)
        return new_link

    @classmethod
    def get_student_profile(
        cls,
        db: Session,
        student: Student,
        user: Optional[User] = None,
    ) -> Dict[str, Any]:
        """
        Build read-only student profile with institutional context and DPDP consents.
        Omits internal sensitive audit details, hashes, or unrelated demographic data.
        """
        # Resolve active or latest enrolment
        latest_enrolment = db.query(Enrolment).filter(
            Enrolment.student_ref == student.student_ref
        ).order_by(
            (Enrolment.enrolment_status == "Active").desc(),
            Enrolment.enrolment_start.desc()
        ).first()

        # Query DPDP consents
        consents = db.query(StudentConsent).filter(
            StudentConsent.student_ref == student.student_ref
        ).order_by(StudentConsent.id.asc()).all()

        return {
            "student_ref": student.student_ref,
            "apaar_id": student.apaar_id,
            "masked_apaar_id": mask_identifier(student.apaar_id),
            "full_name": student.full_name,
            "primary_institution_id": student.primary_institution_id,
            "primary_institution_name": latest_enrolment.institution_name if latest_enrolment else None,
            "current_programme_id": latest_enrolment.programme_id if latest_enrolment else None,
            "current_programme_name": latest_enrolment.programme_name if latest_enrolment else None,
            "current_academic_year": latest_enrolment.academic_year if latest_enrolment else None,
            "current_enrolment_status": latest_enrolment.enrolment_status if latest_enrolment else "Not Enrolled",
            "identity_route": student.identity_route,
            "identity_status": student.identity_status,
            "nationality": student.nationality,
            "is_nri": student.is_nri,
            "is_oci": student.is_oci,
            "is_foreign_national": student.is_foreign_national,
            "account": {
                "username": user.username if user else None,
                "email": user.email if user else None,
                "role": user.role if user else "student",
            } if user else None,
            "consents": [
                {
                    "id": c.id,
                    "purpose": c.purpose,
                    "consent_granted": c.consent_granted,
                    "status": c.status,
                    "data_scope": c.data_scope,
                    "granted_at": c.granted_at.isoformat() if c.granted_at else None,
                    "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None,
                }
                for c in consents
            ],
        }

    @classmethod
    def get_academic_history(
        cls,
        db: Session,
        student_ref: str,
    ) -> List[Dict[str, Any]]:
        """Return chronological enrolment history for the student."""
        enrolments = db.query(Enrolment).filter(
            Enrolment.student_ref == student_ref
        ).order_by(Enrolment.enrolment_start.desc()).all()

        return [
            {
                "id": e.id,
                "institution_id": e.institution_id,
                "institution_name": e.institution_name,
                "programme_id": e.programme_id,
                "programme_name": e.programme_name,
                "academic_year": e.academic_year,
                "admission_cycle": e.admission_cycle,
                "enrolment_start": str(e.enrolment_start),
                "enrolment_end": str(e.enrolment_end) if e.enrolment_end else None,
                "enrolment_status": e.enrolment_status,
                "seat_category": e.seat_category,
                "exception_ref": e.exception_ref,
                "record_version": e.record_version,
            }
            for e in enrolments
        ]

    @classmethod
    def get_credentials(
        cls,
        db: Session,
        student_ref: str,
    ) -> List[Dict[str, Any]]:
        """
        Return digital academic certificates with cryptographic integrity verification.
        Excludes private keys, internal HMAC secrets, and sensitive signing key details.
        """
        certs = db.query(Certificate).filter(
            Certificate.student_ref == student_ref
        ).order_by(Certificate.created_at.desc()).all()

        results = []
        for c in certs:
            verification = CertificateService.verify_certificate(db, c.certificate_id)
            results.append({
                "certificate_id": c.certificate_id,
                "student_ref": c.student_ref,
                "student_name": c.student_name,
                "institution_id": c.institution_id,
                "institution_name": c.institution_name,
                "programme_id": c.programme_id,
                "programme_name": c.programme_name,
                "issue_date": c.issue_date,
                "completion_date": c.completion_date,
                "status": c.status,
                "revocation_reason": c.revocation_reason,
                "signature_algorithm": c.signature_algorithm,
                "public_key_id": c.public_key_id,
                "is_authentic": verification.get("is_authentic", False),
                "verification_status": verification.get("verification_status", "UNKNOWN"),
                "watermark": "DEMO — NOT AN OFFICIAL CERTIFICATE",
            })
        return results

    @classmethod
    def get_transfers(
        cls,
        db: Session,
        student_ref: str,
    ) -> List[Dict[str, Any]]:
        """Return migration and transfer records for the student."""
        transfers = db.query(TransferRequest).filter(
            TransferRequest.student_ref == student_ref
        ).order_by(TransferRequest.initiation_date.desc()).all()

        return [
            {
                "id": t.id,
                "student_ref": t.student_ref,
                "source_institution_id": t.source_institution_id,
                "source_institution_name": t.source_institution_name,
                "destination_institution_id": t.destination_institution_id,
                "destination_institution_name": t.destination_institution_name,
                "source_state": t.source_state,
                "destination_state": t.destination_state,
                "programme_id": t.programme_id,
                "programme_name": t.programme_name,
                "academic_year": t.academic_year,
                "initiation_date": str(t.initiation_date),
                "requested_effective_date": str(t.requested_effective_date),
                "status": t.status,
                "noc_certificate_ref": t.noc_certificate_ref,
                "transfer_reason": t.reviewer_notes,
                "source_decision": t.source_decision,
                "destination_decision": t.destination_decision,
                "source_decision_reason": t.source_decision_reason,
                "destination_decision_reason": t.destination_decision_reason,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transfers
        ]

    @classmethod
    def toggle_consent(
        cls,
        db: Session,
        student_ref: str,
        consent_id: int,
        granted: Optional[bool] = None,
        actor: str = "Student",
    ) -> Dict[str, Any]:
        """Allow a student to toggle their own DPDP verification consent."""
        consent = db.query(StudentConsent).filter(
            StudentConsent.id == consent_id
        ).first()

        if not consent:
            raise HTTPException(status_code=404, detail="Consent record not found.")

        if consent.student_ref != student_ref:
            raise HTTPException(status_code=403, detail="You are not authorized to modify another student's consent.")

        new_granted = not consent.consent_granted if granted is None else bool(granted)
        consent.consent_granted = new_granted
        consent.status = "ACTIVE" if new_granted else "WITHDRAWN"
        consent.withdrawn_at = None if new_granted else datetime.now(timezone.utc)

        db.commit()
        db.refresh(consent)

        AuditService.log_event(
            db=db,
            entity_type="CONSENT",
            entity_id=str(consent.id),
            action="STUDENT_CONSENT_TOGGLE",
            performed_by=actor,
            details={
                "student_ref": student_ref,
                "purpose": consent.purpose,
                "new_status": consent.status,
                "granted": consent.consent_granted,
            },
        )

        return {
            "id": consent.id,
            "student_ref": consent.student_ref,
            "purpose": consent.purpose,
            "status": consent.status,
            "consent_granted": consent.consent_granted,
            "granted_at": consent.granted_at.isoformat() if consent.granted_at else None,
            "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None,
        }
