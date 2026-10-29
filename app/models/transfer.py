from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey, Index
from app.database import Base


class TransferStatus:
    PENDING_RELEASE = "PENDING_RELEASE"
    RELEASED = "RELEASED"
    PENDING_ADMISSION = "PENDING_ADMISSION"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

    ALL_STATUSES = {
        PENDING_RELEASE,
        RELEASED,
        PENDING_ADMISSION,
        UNDER_REVIEW,
        COMPLETED,
        REJECTED,
        CANCELLED,
    }


class TransferRequest(Base):
    __tablename__ = "transfer_requests"

    id = Column(String(64), primary_key=True, index=True)
    student_ref = Column(String(64), ForeignKey("students.student_ref"), nullable=False, index=True)
    apaar_id = Column(String(32), nullable=True, index=True)

    source_institution_id = Column(String(64), nullable=False, index=True)
    source_institution_name = Column(String(128), nullable=True)
    destination_institution_id = Column(String(64), nullable=False, index=True)
    destination_institution_name = Column(String(128), nullable=True)

    source_state = Column(String(64), nullable=True)
    destination_state = Column(String(64), nullable=True)

    source_enrolment_id = Column(Integer, nullable=True)
    programme_id = Column(String(64), nullable=False)
    programme_name = Column(String(128), nullable=True)
    academic_year = Column(String(16), nullable=False)

    initiation_date = Column(Date, nullable=False, default=date.today)
    requested_effective_date = Column(Date, nullable=False)

    status = Column(String(32), nullable=False, default=TransferStatus.PENDING_RELEASE, index=True)

    # Decisions
    source_decision = Column(String(32), nullable=True)  # APPROVED, REJECTED
    source_decision_reason = Column(String(256), nullable=True)
    source_decision_at = Column(DateTime, nullable=True)
    source_decision_by = Column(String(128), nullable=True)

    destination_decision = Column(String(32), nullable=True)  # ADMITTED, REJECTED
    destination_decision_reason = Column(String(256), nullable=True)
    destination_decision_at = Column(DateTime, nullable=True)
    destination_decision_by = Column(String(128), nullable=True)

    noc_certificate_ref = Column(String(64), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    related_alert_id = Column(String(64), nullable=True)

    created_by = Column(String(128), nullable=False)
    record_version = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_transfer_parties", "student_ref", "source_institution_id", "destination_institution_id", "status"),
    )
