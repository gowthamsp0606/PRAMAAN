"""
DigiLocker Integration Adapter (Mock Prototype)
Simulates document publishing, URI discovery, and verification with National DigiLocker ecosystem.

PRODUCTION SPECIFICATION:
- Official Provider: Ministry of Electronics and IT (MeitY) / National e-Governance Division (NeGD)
- Production API: DigiLocker Issuer API v3.0 (OAuth 2.0 / MTLS)
- Data Standards: W3C Verifiable Credentials / MeitY XML Schema for Academic Awards
- Current Status: SIMULATED PROTOTYPE (Mock mode only; no official production connection claimed)
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid


class DigiLockerAdapter:
    IS_MOCK: bool = True
    ADAPTER_VERSION: str = "v3.0-mock"
    PROVIDER_NAME: str = "DigiLocker NAD (National Academic Depository) Gateway"

    @classmethod
    def push_academic_credential(
        cls,
        certificate_id: str,
        student_name: str,
        apaar_id: Optional[str],
        institution_id: str,
        institution_name: str,
        programme_name: str,
        completion_date: str,
        doc_type: str = "DEGREE_CERTIFICATE",
    ) -> Dict[str, Any]:
        """
        Simulate publishing an academic credential record to DigiLocker NAD repository.
        Returns mock DigiLocker URI and transaction reference.
        """
        txn_id = f"DL-TXN-{uuid.uuid4().hex[:10].upper()}"
        doc_uri = f"in.gov.digilocker.{institution_id.lower().replace('-', '.')}-{certificate_id}"

        return {
            "is_mock": True,
            "status": "PUSHED_TO_DIGILOCKER_MOCK",
            "transaction_id": txn_id,
            "digilocker_uri": doc_uri,
            "doc_type": doc_type,
            "certificate_id": certificate_id,
            "apaar_id_indexed": bool(apaar_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "Credential queued in simulated DigiLocker NAD repository (Mock Prototype).",
            "disclaimer": "PROTOTYPE ONLY — Not an official DigiLocker transmission.",
        }

    @classmethod
    def fetch_credential_status(cls, digilocker_uri: str) -> Dict[str, Any]:
        """Simulate status lookup of a published credential in DigiLocker repository."""
        return {
            "is_mock": True,
            "digilocker_uri": digilocker_uri,
            "status": "AVAILABLE",
            "sync_status": "SYNCHRONIZED_MOCK",
            "last_accessed": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "PROTOTYPE ONLY — Simulated DigiLocker NAD lookup.",
        }
