"""
Tamil Nadu University Management Information System (UMIS) / EMIS Integration Adapter
Simulates Tamil Nadu higher education student migration, NOC verification, and transcript validation.

ARCHITECTURAL NOTES:
- Government Authority: Tamil Nadu Department of Higher Education / Directorate of Technical Education (DOTE).
- Higher Education System (Colleges & Universities): UMIS (University Management Information System) is the authoritative
  state platform for university registrations, course examinations, NOC issuance, and college transfers.
- School Education System (K-12): EMIS (Educational Management Information System) is used for school tracking.
  For AICTE / Higher Education student transfers, UMIS is the designated state interface.
- Integration Status: BLOCKED_BY_EXTERNAL_ACCESS
  (Simulation / Mock prototype. Live integration requires production TNeGA API credentials and institutional mTLS).
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from app.adapters.state_transfer_provider import StateTransferSourceProvider


class TamilNaduUMISAdapter(StateTransferSourceProvider):
    provider_code: str = "TN_UMIS"
    provider_name: str = "Tamil Nadu University Management Information System (TN-UMIS)"
    is_mock: bool = True
    integration_status: str = "BLOCKED_BY_EXTERNAL_ACCESS"
    adapter_version: str = "v1.0-mock-prototype"

    def verify_student_clearance(
        self,
        apaar_id: str,
        institution_id: str,
        course_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verify student's migration and financial clearance from Tamil Nadu university / college.
        """
        is_tn_institution = any(keyword in institution_id.upper() for keyword in ["TRICHY", "NITT", "CHENNAI", "TN", "ANNA", "MADRAS"])
        has_valid_apaar = bool(apaar_id and len(apaar_id) >= 12)

        return {
            "provider": self.provider_code,
            "provider_name": self.provider_name,
            "is_mock": True,
            "integration_status": self.integration_status,
            "apaar_id": apaar_id,
            "institution_id": institution_id,
            "jurisdiction_match": is_tn_institution,
            "clearance_status": "CLEARED" if (is_tn_institution and has_valid_apaar) else "UNDER_REVIEW",
            "dues_outstanding_inr": 0.0,
            "disciplinary_records": [],
            "transfer_eligibility": True if is_tn_institution else False,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "regulatory_note": "Simulated TN-UMIS student clearance verification for prototype evaluation.",
        }

    def verify_transfer_certificate(
        self,
        tc_number: str,
        institution_id: str,
    ) -> Dict[str, Any]:
        """
        Verify authenticity of Transfer Certificate (TC) or No-Objection Certificate (NOC).
        """
        is_valid = bool(tc_number and (tc_number.startswith("NOC-") or tc_number.startswith("TC-TN-") or len(tc_number) >= 6))
        return {
            "provider": self.provider_code,
            "is_mock": True,
            "tc_number": tc_number,
            "institution_id": institution_id,
            "is_authentic": is_valid,
            "issuing_board": "Directorate of Technical Education (DOTE), Tamil Nadu",
            "issue_date": "2026-06-15",
            "validity": "VALID" if is_valid else "INVALID_OR_NOT_FOUND",
            "qr_verification_digest": f"TN-DOTE-VERIFY-{uuid.uuid4().hex[:12].upper()}" if is_valid else None,
        }

    def get_transcript_and_credits(
        self,
        apaar_id: str,
        institution_id: str,
    ) -> Dict[str, Any]:
        """
        Retrieve certified academic transcript and accumulated credit ledger from TN UMIS repository.
        """
        return {
            "provider": self.provider_code,
            "is_mock": True,
            "apaar_id": apaar_id,
            "institution_id": institution_id,
            "cumulative_gpa": 8.75,
            "completed_credits": 76.0,
            "curriculum_version": "TN-STATE-CBCS-2024",
            "proctor_verified": True,
            "credit_breakdown": {
                "core_theory": 44.0,
                "practical_lab": 16.0,
                "project_work": 8.0,
                "humanities_elective": 8.0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def reconcile_transfer_source(
        self,
        transfer_id: str,
        student_ref: str,
        apaar_id: Optional[str],
        source_institution_id: str,
        noc_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Comprehensive reconciliation of student transfer record against Tamil Nadu state registry.
        """
        safe_apaar = apaar_id or f"MOCK-APAAR-{student_ref}"
        clearance = self.verify_student_clearance(safe_apaar, source_institution_id)
        tc_check = self.verify_transfer_certificate(noc_ref or f"NOC-{source_institution_id}-AUTO", source_institution_id)
        transcript = self.get_transcript_and_credits(safe_apaar, source_institution_id)

        all_passed = clearance["clearance_status"] == "CLEARED" and tc_check["is_authentic"]

        return {
            "transfer_id": transfer_id,
            "student_ref": student_ref,
            "provider": self.provider_code,
            "provider_name": self.provider_name,
            "is_mock": True,
            "reconciliation_status": "SOURCE_VERIFIED" if all_passed else "FLAGGED_FOR_MANUAL_REVIEW",
            "reconciliation_score": 100.0 if all_passed else 70.0,
            "clearance_check": clearance,
            "noc_validation": tc_check,
            "transcript_summary": transcript,
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
            "recommendation": "Transfer release can proceed without state-level encumbrance." if all_passed else "Manual inspection of state clearance required.",
        }


# Global adapter instance
tn_umis_adapter = TamilNaduUMISAdapter()
