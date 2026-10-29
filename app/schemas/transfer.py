from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional, List, Literal, Any
from datetime import date, datetime


class TransferInitiateRequest(BaseModel):
    student_ref: str = Field(..., min_length=1, max_length=64, description="Student reference ID")
    destination_institution_id: str = Field(..., min_length=1, max_length=64, description="Target institution ID")
    destination_institution_name: Optional[str] = Field(None, max_length=128)
    programme_id: str = Field(..., min_length=1, max_length=64, description="Academic programme code")
    programme_name: Optional[str] = Field(None, max_length=128)
    academic_year: str = Field(..., min_length=9, max_length=16, pattern=r"^20\d{2}-20\d{2}$", description="e.g. 2025-2026")
    requested_effective_date: Optional[date] = Field(None, description="Target effective date of migration")
    effective_date: Optional[date] = Field(None, description="Target effective date alias")
    source_institution_id: Optional[str] = Field(None, max_length=64, description="Source institution ID (defaults to officer's assigned institution)")
    source_institution_name: Optional[str] = Field(None, max_length=128)
    source_state: Optional[str] = Field(None, max_length=64)
    destination_state: Optional[str] = Field(None, max_length=64)
    transfer_reason: Optional[str] = Field(None, max_length=256)
    reason: Optional[str] = Field(None, max_length=256)


class TransferReleaseRequest(BaseModel):
    action: Literal["APPROVE", "REJECT", "RELEASE"] = Field(..., description="APPROVE release with NOC or REJECT transfer")
    reason: Optional[str] = Field(None, max_length=256, description="Official justification or rejection reason")
    noc_certificate_ref: Optional[str] = Field(None, max_length=64, description="Digital NOC / Transfer Certificate reference")
    noc_document_ref: Optional[str] = Field(None, max_length=64, description="Digital NOC / Transfer Certificate alias")


class TransferAdmitRequest(BaseModel):
    action: Literal["ADMIT", "REJECT"] = Field(..., description="ADMIT confirming matriculation or REJECT transfer")
    reason: Optional[str] = Field(None, max_length=256, description="Decision remarks")
    seat_category: Optional[str] = Field("General", max_length=64, description="Admission seat category at destination")


class TransferCancelRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=256, description="Cancellation reason")


class TransferResponse(BaseModel):
    id: str
    transfer_id: Optional[str] = None
    student_ref: str
    apaar_id: Optional[str] = None
    source_institution_id: str
    source_institution_name: Optional[str] = None
    destination_institution_id: str
    destination_institution_name: Optional[str] = None
    source_state: Optional[str] = None
    destination_state: Optional[str] = None
    programme_id: str
    programme_name: Optional[str] = None
    academic_year: str
    initiation_date: date
    requested_effective_date: date
    effective_date: Optional[date] = None
    status: str
    source_decision: Optional[str] = None
    source_decision_reason: Optional[str] = None
    source_decision_at: Optional[datetime] = None
    source_decision_by: Optional[str] = None
    destination_decision: Optional[str] = None
    destination_decision_reason: Optional[str] = None
    destination_decision_at: Optional[datetime] = None
    destination_decision_by: Optional[str] = None
    noc_certificate_ref: Optional[str] = None
    reviewer_notes: Optional[str] = None
    related_alert_id: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "id" in data and not data.get("transfer_id"):
                data["transfer_id"] = data["id"]
            if "requested_effective_date" in data and not data.get("effective_date"):
                data["effective_date"] = data["requested_effective_date"]
        elif hasattr(data, "id"):
            # SQLAlchemy model instance
            pass
        return data

    model_config = ConfigDict(from_attributes=True)


class TransferListResponse(BaseModel):
    items: List[TransferResponse]
    total: int
    page: int
    limit: int
