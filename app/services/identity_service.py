from typing import Optional, Tuple, Dict, Any, List
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.student import Student
from app.services.audit_service import AuditService


class IdentityStatus:
    APAAR_VERIFIED = "APAAR_VERIFIED"
    APAAR_PENDING = "APAAR_PENDING"
    HISTORICAL_NO_APAAR = "HISTORICAL_NO_APAAR"
    ALTERNATIVE_ID_PENDING_VERIFICATION = "ALTERNATIVE_ID_PENDING_VERIFICATION"
    EXEMPT_WHERE_POLICY_PERMITS = "EXEMPT_WHERE_POLICY_PERMITS"

    ALL = {
        APAAR_VERIFIED,
        APAAR_PENDING,
        HISTORICAL_NO_APAAR,
        ALTERNATIVE_ID_PENDING_VERIFICATION,
        EXEMPT_WHERE_POLICY_PERMITS,
    }


# Permitted transition graph
VALID_TRANSITIONS: Dict[str, set[str]] = {
    IdentityStatus.HISTORICAL_NO_APAAR: {
        IdentityStatus.APAAR_PENDING,
        IdentityStatus.APAAR_VERIFIED,
        IdentityStatus.EXEMPT_WHERE_POLICY_PERMITS,
    },
    IdentityStatus.APAAR_PENDING: {
        IdentityStatus.APAAR_VERIFIED,
        IdentityStatus.ALTERNATIVE_ID_PENDING_VERIFICATION,
        IdentityStatus.HISTORICAL_NO_APAAR,
    },
    IdentityStatus.ALTERNATIVE_ID_PENDING_VERIFICATION: {
        IdentityStatus.APAAR_VERIFIED,
        IdentityStatus.EXEMPT_WHERE_POLICY_PERMITS,
        IdentityStatus.APAAR_PENDING,
    },
    IdentityStatus.EXEMPT_WHERE_POLICY_PERMITS: {
        IdentityStatus.APAAR_VERIFIED,
        IdentityStatus.ALTERNATIVE_ID_PENDING_VERIFICATION,
    },
    IdentityStatus.APAAR_VERIFIED: {
        IdentityStatus.APAAR_PENDING,
        IdentityStatus.ALTERNATIVE_ID_PENDING_VERIFICATION,
    },
}


class IdentityLifecycleService:
    """
    Manages student identity states, provenance rules, and explainable transition auditing.
    Preserves historical pre-APAAR records and international student policy routes.
    """

    @staticmethod
    def derive_initial_identity(
        apaar_id: Optional[str] = None,
        is_foreign_national: bool = False,
        is_historical: bool = False,
        passport_ref: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """
        Derives (identity_status, identity_route, nationality) for a new student record.
        """
        clean_apaar = str(apaar_id).strip() if apaar_id and str(apaar_id).strip() else None

        if is_foreign_national:
            status = (
                IdentityStatus.EXEMPT_WHERE_POLICY_PERMITS
                if passport_ref and str(passport_ref).strip()
                else IdentityStatus.ALTERNATIVE_ID_PENDING_VERIFICATION
            )
            route = "PASSPORT_INTERNATIONAL"
            nationality = "International"
        elif not clean_apaar:
            if is_historical:
                status = IdentityStatus.HISTORICAL_NO_APAAR
                route = "HISTORICAL_LEGACY"
            else:
                status = IdentityStatus.APAAR_PENDING
                route = "AADHAAR_APAAR"
            nationality = "Indian"
        else:
            status = IdentityStatus.APAAR_VERIFIED
            route = "AADHAAR_APAAR"
            nationality = "Indian"

        return status, route, nationality

    @staticmethod
    def validate_transition(
        current_status: str,
        new_status: str,
        is_privileged: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates whether transitioning from current_status to new_status is permitted.
        """
        if new_status not in IdentityStatus.ALL:
            return False, f"Unknown identity status '{new_status}'. Permitted: {', '.join(sorted(IdentityStatus.ALL))}."

        if current_status == new_status:
            return True, None

        permitted = VALID_TRANSITIONS.get(current_status, set())
        if new_status not in permitted and not is_privileged:
            return False, (
                f"Transition from '{current_status}' to '{new_status}' is not permitted by identity policy. "
                f"Allowed target states: {', '.join(sorted(permitted)) or 'None'}."
            )

        # Regressing from APAAR_VERIFIED requires privileged administrative role
        if current_status == IdentityStatus.APAAR_VERIFIED and not is_privileged:
            return False, "Reverting a verified APAAR status requires privileged administrator authority."

        return True, None

    @classmethod
    def update_student_identity(
        cls,
        db: Session,
        student: Student,
        new_status: str,
        reason: str,
        actor: str,
        evidence_reference: Optional[str] = None,
        new_apaar_id: Optional[str] = None,
        is_privileged: bool = False,
    ) -> Dict[str, Any]:
        """
        Applies a validated identity transition to a Student entity and records an audit log.
        """
        old_status = student.identity_status
        is_valid, error_msg = cls.validate_transition(old_status, new_status, is_privileged=is_privileged)
        if not is_valid:
            raise ValueError(error_msg)

        if new_apaar_id is not None:
            clean_new_apaar = str(new_apaar_id).strip() or None
            if clean_new_apaar:
                # Check uniqueness against other students
                collision = db.query(Student).filter(
                    Student.apaar_id == clean_new_apaar,
                    Student.student_ref != student.student_ref
                ).first()
                if collision:
                    raise ValueError(f"APAAR ID '{clean_new_apaar}' is already assigned to student '{collision.student_ref}'.")
            student.apaar_id = clean_new_apaar

        student.identity_status = new_status
        db.flush()

        AuditService.log_event(
            db=db,
            entity_type="STUDENT",
            entity_id=student.student_ref,
            action="IDENTITY_STATUS_UPDATED",
            performed_by=actor,
            details={
                "previous_status": old_status,
                "new_status": new_status,
                "reason": reason,
                "evidence_reference": evidence_reference,
                "institution_id": student.primary_institution_id,
            },
            commit=True,
        )

        return {
            "student_ref": student.student_ref,
            "previous_status": old_status,
            "current_status": new_status,
            "apaar_id": student.apaar_id,
            "updated_at": datetime.utcnow().isoformat(),
        }
