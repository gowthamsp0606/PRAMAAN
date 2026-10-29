from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import date, datetime
from app.admission_categories import AdmissionCategory, normalize_admission_category

class EnrolmentBase(BaseModel):
    student_ref: str
    apaar_id: Optional[str] = None
    institution_id: str
    institution_name: Optional[str] = None
    programme_id: str
    programme_name: Optional[str] = None
    academic_year: str
    admission_cycle: str
    enrolment_start: date
    enrolment_end: Optional[date] = None
    enrolment_status: str  # Active, Completed, Withdrawn, Suspended
    seat_category: AdmissionCategory = AdmissionCategory.GENERAL
    exception_ref: Optional[str] = None
    source_submission_id: str = "API-INGEST"
    record_version: int = 1

    @field_validator("seat_category", mode="before")
    @classmethod
    def validate_seat_category(cls, value):
        normalized = normalize_admission_category(value)
        if normalized is None:
            raise ValueError("Unsupported admission category.")
        return normalized

class EnrolmentCreate(EnrolmentBase):
    pass

class EnrolmentResponse(EnrolmentBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
