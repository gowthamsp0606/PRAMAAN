"""
Academic Bank of Credits (ABC) Integration Adapter (Mock Prototype)
Simulates academic credit accumulation, transfer verification, and ledger queries.

PRODUCTION SPECIFICATION:
- Official Provider: University Grants Commission (UGC) / Ministry of Education (MoE)
- Production API: ABC National Credit Exchange API (REST / JSON-LD)
- Credit Framework: National Higher Education Qualifications Framework (NHEQF)
- Current Status: SIMULATED PROTOTYPE (Mock mode only; no official production connection claimed)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import uuid


class AcademicBankOfCreditsAdapter:
    IS_MOCK: bool = True
    ADAPTER_VERSION: str = "v2.1-mock"
    PROVIDER_NAME: str = "Academic Bank of Credits (ABC) National Repository"

    @classmethod
    def query_student_credits(cls, apaar_id: str) -> Dict[str, Any]:
        """
        Simulate querying student's accumulated academic credits across registered institutions.
        """
        return {
            "is_mock": True,
            "apaar_id": apaar_id,
            "query_status": "SUCCESS_MOCK",
            "total_credits_accumulated": 160.0,
            "credits_by_domain": {
                "Major Core": 80.0,
                "Minor / Elective": 32.0,
                "Skill Enhancement": 24.0,
                "Interdisciplinary": 24.0,
            },
            "participating_institutions_count": 1,
            "last_reconciliation": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "PROTOTYPE ONLY — Simulated Academic Bank of Credits response.",
        }

    @classmethod
    def deposit_academic_credits(
        cls,
        apaar_id: str,
        student_ref: str,
        institution_id: str,
        course_code: str,
        credits_earned: float,
        academic_term: str,
    ) -> Dict[str, Any]:
        """
        Simulate depositing verified earned credits into student's national ABC account.
        """
        deposit_id = f"ABC-DEP-{uuid.uuid4().hex[:8].upper()}"
        return {
            "is_mock": True,
            "deposit_id": deposit_id,
            "apaar_id": apaar_id,
            "student_ref": student_ref,
            "institution_id": institution_id,
            "course_code": course_code,
            "credits_earned": credits_earned,
            "academic_term": academic_term,
            "deposit_status": "CREDITED_MOCK",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "PROTOTYPE ONLY — Simulated credit deposit transaction.",
        }
