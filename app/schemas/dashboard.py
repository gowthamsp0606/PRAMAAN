from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class DashboardSummaryResponse(BaseModel):
    total_students: int
    total_institutions: int
    total_enrolments: Optional[int] = None
    open_alerts: int
    records_requiring_review: int
    validation_pass_rate: float
    potential_conflicts_count: int
    total_conflicts: Optional[int] = None
    total_certificates: Optional[int] = None
    total_alerts: Optional[int] = None
    stats: Optional[Dict[str, Any]] = None
    alert_severity_distribution: Dict[str, int]
    enrolment_trends: List[Dict[str, Any]]
    recent_activity: List[Dict[str, Any]]
    programme_admissions_vs_intake: List[Dict[str, Any]]
