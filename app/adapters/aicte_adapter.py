"""
AICTE Approval Directory Integration Adapter (Mock Prototype)
Simulates institutional approval directory queries, sanctioned intake limits, and regulatory compliance syncing.

PRODUCTION SPECIFICATION:
- Official Provider: All India Council for Technical Education (AICTE)
- Production API: AICTE Approval Process Handbook Portal API (SOAP/REST)
- Current Status: SIMULATED PROTOTYPE (Mock mode only; no official production connection claimed)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


class AICTEApprovalAdapter:
    IS_MOCK: bool = True
    ADAPTER_VERSION: str = "v1.0-mock"
    PROVIDER_NAME: str = "AICTE Approval Process Handbook (APH) Regulatory Directory"

    @classmethod
    def fetch_approved_intake(
        cls,
        institution_id: str,
        programme_id: str,
        academic_year: str,
    ) -> Dict[str, Any]:
        """
        Simulate fetching sanctioned intake and supernumerary caps from AICTE directory.
        """
        return {
            "is_mock": True,
            "institution_id": institution_id,
            "programme_id": programme_id,
            "academic_year": academic_year,
            "approval_status": "APPROVED_MOCK",
            "sanctioned_intake": 120,
            "supernumerary_caps": {
                "EWS": 12,
                "TFW": 6,
                "KASHMIRI_MIGRANT": 2,
                "FOREIGN_NATIONAL": 18,
            },
            "approval_ref": f"AICTE-APH-{academic_year}-{institution_id[:6]}",
            "last_synced": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "PROTOTYPE ONLY — Simulated AICTE Approval Process Handbook query.",
        }

    @classmethod
    def verify_institution_standing(cls, institution_id: str) -> Dict[str, Any]:
        """Simulate institutional standing check against AICTE non-compliant/unapproved lists."""
        return {
            "is_mock": True,
            "institution_id": institution_id,
            "standing": "IN_GOOD_STANDING_MOCK",
            "is_autonomous": True,
            "nba_accredited": True,
            "naac_grade": "A+",
            "disclaimer": "PROTOTYPE ONLY — Simulated AICTE institutional accreditation standing.",
        }
