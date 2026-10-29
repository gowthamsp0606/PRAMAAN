from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime, date

class StudentBase(BaseModel):
    student_ref: str
    apaar_id: Optional[str] = None
    full_name: str
    primary_institution_id: Optional[str] = None
    identity_status: Optional[str] = "APAAR_VERIFIED"
    identity_route: Optional[str] = "AADHAAR_APAAR"

class StudentCreate(StudentBase):
    pass

class StudentResponse(StudentBase):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    enrolment_count: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)
