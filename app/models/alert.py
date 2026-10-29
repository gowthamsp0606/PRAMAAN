from sqlalchemy import Column, String, DateTime, Float, Text, JSON
from datetime import datetime
from app.database import Base

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(64), primary_key=True, index=True)
    student_ref = Column(String(64), nullable=False, index=True)
    apaar_id = Column(String(32), nullable=False, index=True)
    alert_type = Column(String(64), nullable=False, index=True)
    # Types: TEMPORAL_OVERLAP_CONFLICT, EXCEPTION_REVIEW_REQUIRED, DUPLICATE_SUBMISSION, INTAKE_ANOMALY
    severity = Column(String(16), nullable=False, default="MEDIUM")  # HIGH, MEDIUM, LOW, INFORMATIONAL
    status = Column(String(32), nullable=False, default="OPEN", index=True)  # OPEN, UNDER_REVIEW, RESOLVED
    title = Column(String(256), nullable=False)
    explanation = Column(Text, nullable=False)
    evidence_summary = Column(JSON, nullable=True)
    confidence_score = Column(Float, nullable=True)  # Defensible score e.g. 0.95 or None
    supporting_record_ids = Column(JSON, nullable=True)  # List of enrolment IDs
    exception_ref = Column(String(64), nullable=True)
    
    # Review workflow fields
    reviewer_decision = Column(String(64), nullable=True)
    # Decisions: Confirmed conflict, Not a conflict, Exception accepted, Needs more information
    reviewer_note = Column(Text, nullable=True)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
