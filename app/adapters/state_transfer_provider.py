from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class StateTransferSourceProvider(ABC):
    """
    Standard interface for state-level higher education portal adapters
    (e.g., Tamil Nadu UMIS, Maharashtra MahaDBT, Delhi Higher Ed Portal).
    """

    @property
    @abstractmethod
    def provider_code(self) -> str:
        """State or agency code (e.g., 'TN_UMIS', 'MH_HE')."""
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Descriptive provider name."""
        pass

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        """True if operating in simulated mock mode without live production credentials."""
        pass

    @property
    @abstractmethod
    def integration_status(self) -> str:
        """Integration readiness status: 'OPERATIONAL', 'MOCK_SIMULATED', or 'BLOCKED_BY_EXTERNAL_ACCESS'."""
        pass

    @abstractmethod
    def verify_student_clearance(
        self,
        apaar_id: str,
        institution_id: str,
        course_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verify student's migration and financial clearance from source institution.
        """
        pass

    @abstractmethod
    def verify_transfer_certificate(
        self,
        tc_number: str,
        institution_id: str,
    ) -> Dict[str, Any]:
        """
        Verify authenticity and issuance of institutional Transfer Certificate / NOC.
        """
        pass

    @abstractmethod
    def get_transcript_and_credits(
        self,
        apaar_id: str,
        institution_id: str,
    ) -> Dict[str, Any]:
        """
        Retrieve certified academic transcript and accumulated credit ledger from state repository.
        """
        pass

    @abstractmethod
    def reconcile_transfer_source(
        self,
        transfer_id: str,
        student_ref: str,
        apaar_id: Optional[str],
        source_institution_id: str,
        noc_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Comprehensive reconciliation of transfer against state higher ed records.
        """
        pass
