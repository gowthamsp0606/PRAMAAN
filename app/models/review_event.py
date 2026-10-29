from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text

from app.database import Base


class AlertReviewEvent(Base):
    __tablename__ = "alert_review_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(64), ForeignKey("alerts.id"), nullable=False, index=True)
    action = Column(String(32), nullable=False, index=True)
    previous_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=True)
    decision = Column(String(64), nullable=True)
    actor = Column(String(128), nullable=False)
    assigned_to = Column(String(128), nullable=True)
    note = Column(Text, nullable=True)
    resolution_reason = Column(Text, nullable=True)
    evidence_references = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_alert_review_event_history", "alert_id", "created_at", "id"),
    )