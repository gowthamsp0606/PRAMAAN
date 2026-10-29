from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any, Literal, Annotated
from datetime import datetime

EvidenceReference = Annotated[str, Field(min_length=1, max_length=256)]

class AlertReviewRequest(BaseModel):
    decision: Literal["CONFIRMED_CONFLICT", "NOT_A_CONFLICT", "EXCEPTION_ACCEPTED", "NEEDS_MORE_INFO"]
    note: str = Field(min_length=1, max_length=5000)
    reviewed_by: Optional[str] = Field(default="Demo Officer (AICTE-RO-102)", max_length=128)
    resolution_reason: Optional[str] = Field(default=None, max_length=5000)
    evidence_references: List[EvidenceReference] = Field(default_factory=list, max_length=20)


class AlertAssignmentRequest(BaseModel):
    assigned_to: Optional[str] = Field(default=None, max_length=128)
    actor: str = Field(default="Demo Reviewer", min_length=1, max_length=128, pattern=r".*\S.*")


class AlertNoteRequest(BaseModel):
    note: str = Field(min_length=1, max_length=5000)
    actor: str = Field(default="Demo Reviewer", min_length=1, max_length=128, pattern=r".*\S.*")
    evidence_references: List[EvidenceReference] = Field(default_factory=list, max_length=20)


class AlertClarificationRequest(AlertNoteRequest):
    pass


class AlertReopenRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=5000)
    actor: str = Field(default="Demo Reviewer", min_length=1, max_length=128, pattern=r".*\S.*")


class AlertReviewEventResponse(BaseModel):
    id: int
    alert_id: str
    action: str
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    decision: Optional[str] = None
    actor: str
    assigned_to: Optional[str] = None
    note: Optional[str] = None
    resolution_reason: Optional[str] = None
    evidence_references: List[str] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AlertResponse(BaseModel):
    id: str
    student_ref: str
    apaar_id: str
    alert_type: str
    severity: str
    status: str
    title: str
    explanation: str
    evidence_summary: Optional[Dict[str, Any]] = None
    confidence_score: Optional[float] = None
    supporting_record_ids: Optional[List[int]] = None
    exception_ref: Optional[str] = None
    reviewer_decision: Optional[str] = None
    reviewer_note: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
