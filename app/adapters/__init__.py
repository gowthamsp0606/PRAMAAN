"""
PRAMAAN / APAAR Sentinel — External Integration Adapters Package
Mock adapters for external national portals (DigiLocker, ABC, AICTE).

DISCLAIMER:
All adapters in this package operate in MOCK / SIMULATION mode for hackathon prototype evaluation.
They do NOT claim official government connectivity or production API credentials without authorized integration.
"""

from app.adapters.digilocker_adapter import DigiLockerAdapter
from app.adapters.abc_adapter import AcademicBankOfCreditsAdapter
from app.adapters.aicte_adapter import AICTEApprovalAdapter
from app.adapters.state_transfer_provider import StateTransferSourceProvider
from app.adapters.tamil_nadu_umis_adapter import TamilNaduUMISAdapter, tn_umis_adapter

__all__ = [
    "DigiLockerAdapter",
    "AcademicBankOfCreditsAdapter",
    "AICTEApprovalAdapter",
    "StateTransferSourceProvider",
    "TamilNaduUMISAdapter",
    "tn_umis_adapter",
]
