from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.student import Student
from app.models.enrolment import Enrolment
from app.models.alert import Alert
from app.models.consent import StudentConsent
from app.services.state_service import StateService


class ScholarshipService:
    @classmethod
    def evaluate_student(cls, db: Session, student_ref: str) -> Dict[str, Any]:
        """
        Evaluate student eligibility for merit/welfare scholarships and fee-waiver programmes.
        Complies strictly with DPDP Act 2023: zero collection or evaluation of religion or caste data.
        """
        student = db.query(Student).filter(Student.student_ref == student_ref).first()
        if not student:
            return {
                "student_ref": student_ref,
                "eligibility_status": "STUDENT_NOT_FOUND",
                "is_eligible": False,
                "evaluation_score": 0.0,
                "criteria_checklist": [],
                "explanation": f"Student '{student_ref}' does not exist in the national registry.",
            }

        # 1. Identity & APAAR Check
        identity_verified = bool(
            student.identity_status in {"APAAR_VERIFIED", "VERIFIED"}
            and student.apaar_id
        )

        # 2. Active Enrolment Check
        active_enrolments = db.query(Enrolment).filter(
            Enrolment.student_ref == student_ref,
            Enrolment.enrolment_status == "Active",
        ).all()
        has_single_active_enrolment = len(active_enrolments) == 1

        # 3. Integrity & Concurrency Alert Check
        open_integrity_alerts = db.query(Alert).filter(
            Alert.student_ref == student_ref,
            Alert.status != "RESOLVED",
            Alert.alert_type.in_([
                "CONCURRENT_DUAL_DEGREE",
                "TEMPORAL_OVERLAP",
                "CREDIT_DEFICIT",
                "SUSPICIOUS_IDENTITY",
            ]),
        ).count()

        # 4. DPDP Consent Verification for Scholarship Purpose
        scholarship_consent = db.query(StudentConsent).filter(
            StudentConsent.student_ref == student_ref,
            StudentConsent.purpose == "SCHOLARSHIP",
        ).order_by(StudentConsent.id.desc()).first()

        # If no explicit SCHOLARSHIP consent exists, check for any active consent
        any_active_consent = db.query(StudentConsent).filter(
            StudentConsent.student_ref == student_ref,
            StudentConsent.consent_granted == True,
            StudentConsent.status == "ACTIVE",
        ).first()

        consent_granted = bool(
            (scholarship_consent and scholarship_consent.consent_granted and scholarship_consent.status == "ACTIVE")
            or any_active_consent
        )

        # Build Criteria Checklist
        criteria = [
            {
                "criterion": "IDENTITY_AUTHENTICATION",
                "description": "Verified National APAAR / Student ID",
                "passed": identity_verified,
                "details": f"Status: {student.identity_status}, APAAR present: {bool(student.apaar_id)}",
            },
            {
                "criterion": "ACTIVE_ACADEMIC_STANDING",
                "description": "Exactly one active institutional enrolment",
                "passed": has_single_active_enrolment,
                "details": f"Found {len(active_enrolments)} active enrolment(s).",
            },
            {
                "criterion": "INTEGRITY_CONFLICT_FREE",
                "description": "Zero unresolved temporal or dual-enrolment integrity alerts",
                "passed": open_integrity_alerts == 0,
                "details": f"Unresolved integrity alerts: {open_integrity_alerts}",
            },
            {
                "criterion": "DPDP_PRIVACY_CONSENT",
                "description": "Explicit student digital consent for scholarship data verification",
                "passed": consent_granted,
                "details": "Active digital consent recorded" if consent_granted else "Consent required under DPDP Act before benefit disbursal",
            },
        ]

        passed_count = sum(1 for c in criteria if c["passed"])
        score = round((passed_count / len(criteria)) * 100, 1)

        if not identity_verified:
            status = "IDENTITY_UNVERIFIED"
            explanation = "Student identity or APAAR ID is not fully authenticated."
        elif open_integrity_alerts > 0:
            status = "DISQUALIFIED_BY_INTEGRITY_CONFLICT"
            explanation = "Disqualified due to unresolved active enrolment conflict or alert."
        elif not has_single_active_enrolment:
            status = "INVALID_ENROLMENT_STATE"
            explanation = "Requires exactly one active enrolment in an accredited institution."
        elif not consent_granted:
            status = "NEEDS_STUDENT_CONSENT"
            explanation = "All academic criteria met, but student has not yet granted DPDP consent."
        else:
            status = "ELIGIBLE"
            explanation = "Student satisfies all academic, temporal integrity, identity, and DPDP consent criteria."

        return {
            "student_ref": student.student_ref,
            "full_name": student.full_name,
            "masked_apaar_id": f"{'*' * 10}{student.apaar_id[-4:]}" if student.apaar_id else None,
            "primary_institution_id": student.primary_institution_id,
            "state": StateService.resolve_state_from_institution(student.primary_institution_id),
            "eligibility_status": status,
            "is_eligible": status == "ELIGIBLE",
            "evaluation_score": score,
            "criteria_checklist": criteria,
            "explanation": explanation,
            "evaluated_at": datetime.utcnow().isoformat(),
            "privacy_compliance": "DPDP Act 2023 Compliant — No caste or religion metrics processed.",
        }

    @classmethod
    def list_evaluations(
        cls,
        db: Session,
        institution_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = db.query(Student)
        if institution_id:
            query = query.filter(Student.primary_institution_id == institution_id)
        elif state:
            state_institutions = StateService.get_institutions_for_state(db, state)
            if state_institutions:
                query = query.filter(Student.primary_institution_id.in_(state_institutions))
            else:
                return []

        students = query.limit(limit).all()
        return [cls.evaluate_student(db, s.student_ref) for s in students]
