from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Index
from datetime import datetime
from app.database import Base

class Enrolment(Base):
    __tablename__ = "enrolments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_ref = Column(String(64), ForeignKey("students.student_ref"), nullable=False, index=True)
    apaar_id = Column(String(32), nullable=True, index=True)
    institution_id = Column(String(64), nullable=False, index=True)
    institution_name = Column(String(128), nullable=True)
    programme_id = Column(String(64), nullable=False, index=True)
    programme_name = Column(String(128), nullable=True)
    academic_year = Column(String(16), nullable=False, index=True)
    admission_cycle = Column(String(32), nullable=False)
    enrolment_start = Column(Date, nullable=False)
    enrolment_end = Column(Date, nullable=True)
    enrolment_status = Column(String(32), nullable=False, index=True)  # Active, Completed, Withdrawn, Suspended
    seat_category = Column(String(32), nullable=False, default="General")
    exception_ref = Column(String(64), nullable=True)
    source_submission_id = Column(String(64), nullable=False, default="INIT-SEED")
    record_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_enrolment_temporal", "student_ref", "enrolment_start", "enrolment_end", "enrolment_status"),
        Index("idx_enrolment_duplicate_lookup", "student_ref", "institution_id", "programme_id", "enrolment_start"),
    )
