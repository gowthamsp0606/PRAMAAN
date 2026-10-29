from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.verifier import VerifierOrganization, VerificationRequestLog
from app.models.consent import StudentConsent
from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.certificate import Certificate

class VerifierService:
    def __init__(self, db: Session):
        self.db = db

    def verify_candidate_credential(
        self,
        verifier_org_id: str,
        student_ref: Optional[str] = None,
        apaar_id: Optional[str] = None,
        certificate_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # 1. Check if Verifier Organization is authorized
        org = self.db.query(VerifierOrganization).filter(VerifierOrganization.id == verifier_org_id).first()
        org_name = org.org_name if org else "Unregistered Employer / Verifier"

        if not org or not org.is_approved:
            self._log_request(
                org_id=verifier_org_id,
                org_name=org_name,
                student_ref=student_ref,
                apaar_id=apaar_id,
                cert_id=certificate_id,
                outcome="UNAUTHORIZED_VERIFIER",
                payload={"error": "Verifier organization not registered or approval suspended."}
            )
            return {
                "verified": False,
                "outcome": "UNAUTHORIZED_VERIFIER",
                "message": "Organization not authorized to perform regulatory or employment credential checks."
            }

        # 2. Locate student / certificate
        cert = None
        if certificate_id:
            cert = self.db.query(Certificate).filter(Certificate.certificate_id == certificate_id).first()
            if cert:
                student_ref = cert.student_ref
                apaar_id = cert.apaar_id

        student = None
        if student_ref:
            student = self.db.query(Student).filter(Student.student_ref == student_ref).first()
        elif apaar_id:
            student = self.db.query(Student).filter(Student.apaar_id == apaar_id).first()

        if not student:
            self._log_request(
                org_id=verifier_org_id,
                org_name=org_name,
                student_ref=student_ref,
                apaar_id=apaar_id,
                cert_id=certificate_id,
                outcome="NO_MATCH",
                payload={"match": False}
            )
            return {
                "verified": False,
                "outcome": "NO_MATCH",
                "message": "No student profile found matching provided identification attributes."
            }

        # 3. Privacy & DPDP Consent Gate
        consent = self.db.query(StudentConsent).filter(
            StudentConsent.student_ref == student.student_ref,
            StudentConsent.purpose == "EMPLOYMENT_VERIFICATION"
        ).order_by(StudentConsent.granted_at.desc(), StudentConsent.id.desc()).first()

        if not consent or not consent.consent_granted or consent.status != "ACTIVE":
            outcome = "CONSENT_REQUIRED" if consent is None else "CONSENT_WITHHELD"
            self._log_request(
                org_id=verifier_org_id,
                org_name=org_name,
                student_ref=student.student_ref,
                apaar_id=student.apaar_id,
                cert_id=certificate_id,
                outcome=outcome,
                payload={"consent_status": "MISSING" if consent is None else consent.status}
            )
            return {
                "verified": False,
                "outcome": outcome,
                "message": (
                    "Student has withdrawn sharing consent under DPDP Act protocols. Verification halted."
                    if consent is not None
                    else "Current purpose-specific consent is required. Verification halted."
                )
            }

        # 4. Check for revocation
        if cert and cert.status == "REVOKED":
            self._log_request(
                org_id=verifier_org_id,
                org_name=org_name,
                student_ref=student.student_ref,
                apaar_id=student.apaar_id,
                cert_id=certificate_id,
                outcome="RECORD_REVOKED",
                payload={"revoked": True}
            )
            return {
                "verified": False,
                "outcome": "RECORD_REVOKED",
                "message": "Academic credential was officially cancelled or revoked by the issuing institution."
            }

        # 5. Purpose-limited affirmative response (Limited Yes/No with minimal attributes)
        enrolment = self.db.query(Enrolment).filter(Enrolment.student_ref == student.student_ref).first()
        limited_data = {
            "verified": True,
            "outcome": "MATCH_VERIFIED",
            "student_name": student.full_name,
            "institution_name": enrolment.institution_name if enrolment else "Recognized AICTE Institution",
            "programme_name": enrolment.programme_name if enrolment else "Sanctioned Curriculum",
            "academic_status": enrolment.enrolment_status if enrolment else "Active",
            "conferred_date": cert.completion_date if cert else (str(enrolment.enrolment_end) if enrolment and enrolment.enrolment_end else "Ongoing"),
            "purpose_scope": "EMPLOYMENT_BACKGROUND_CHECK_ONLY"
        }

        self._log_request(
            org_id=verifier_org_id,
            org_name=org_name,
            student_ref=student.student_ref,
            apaar_id=student.apaar_id,
            cert_id=certificate_id,
            outcome="MATCH_VERIFIED",
            payload=limited_data
        )

        return limited_data

    def _log_request(self, org_id: str, org_name: str, student_ref: Optional[str], apaar_id: Optional[str], cert_id: Optional[str], outcome: str, payload: Dict[str, Any]):
        log = VerificationRequestLog(
            verifier_org_id=org_id,
            verifier_org_name=org_name,
            query_student_ref=student_ref,
            query_apaar_id=None,
            certificate_id=cert_id,
            verification_outcome=outcome,
            limited_response_json=payload
        )
        try:
            self.db.add(log)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
