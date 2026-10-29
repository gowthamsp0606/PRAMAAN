from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApprovedIntakeRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution_id: str = Field(min_length=1, max_length=64)
    institution_name: Optional[str] = Field(default=None, max_length=128)
    programme_id: str = Field(min_length=1, max_length=64)
    programme_name: Optional[str] = Field(default=None, max_length=128)
    academic_year: str = Field(pattern=r"^20\d{2}-20\d{2}$", min_length=9, max_length=9)
    admission_cycle: str = Field(min_length=1, max_length=32)
    approved_intake_seats: int = Field(ge=0)
    supernumerary_quota: Optional[int] = Field(default=None, ge=0)
    nri_quota: Optional[int] = Field(default=None, ge=0)
    rule_id: str = Field(min_length=1, max_length=64)
    rule_source: str = Field(min_length=1, max_length=128)
    effective_date: date
    rule_configured: bool = False

    @model_validator(mode="after")
    def validate_academic_year(self):
        start, end = self.academic_year.split("-")
        if int(end) != int(start) + 1:
            raise ValueError("academic_year must contain consecutive years, for example 2025-2026.")
        return self