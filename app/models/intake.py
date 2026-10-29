from sqlalchemy import Column, Integer, String, Date, Boolean, Float, Text, DateTime
from datetime import datetime
from app.database import Base

class ApprovedIntake(Base):
    __tablename__ = "approved_intakes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    institution_id = Column(String(64), nullable=False, index=True)
    institution_name = Column(String(128), nullable=False)
    programme_id = Column(String(64), nullable=False, index=True)
    programme_name = Column(String(128), nullable=False)
    academic_year = Column(String(16), nullable=False, index=True)
    admission_cycle = Column(String(32), nullable=False)
    approved_intake_seats = Column(Integer, nullable=False)
    supernumerary_quota = Column(Integer, nullable=True)
    nri_quota = Column(Integer, nullable=True)
    rule_id = Column(String(64), nullable=False, default="AICTE-APH-2025-CH4")
    rule_source = Column(String(128), nullable=False, default="AICTE Approval Process Handbook (Demo Model)")
    effective_date = Column(String(16), nullable=False, default="2025-04-01")
    rule_configured = Column(Boolean, default=False)

class HistoricalIntake(Base):
    __tablename__ = "historical_intakes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    institution_id = Column(String(64), nullable=False, index=True)
    institution_name = Column(String(128), nullable=False)
    programme_id = Column(String(64), nullable=False, index=True)
    programme_name = Column(String(128), nullable=False)
    academic_year = Column(String(16), nullable=False)
    admitted_count = Column(Integer, nullable=False)
    approved_intake = Column(Integer, nullable=False)
    z_score = Column(Float, nullable=True)
    pct_change = Column(Float, nullable=True)
    is_anomaly = Column(Boolean, default=False)
    ground_truth = Column(String(32), default="NORMAL")  # NORMAL, ANOMALY
    anomaly_explanation = Column(Text, nullable=True)
    
    # Visible Anomaly Methods (YoY Z-score + Peer College IQR)
    iqr_status = Column(String(32), default="WITHIN_IQR")  # WITHIN_IQR, OUTLIER_HIGH, OUTLIER_LOW
    peer_group_iqr_diff = Column(Float, default=0.0)
    
    # Reviewer Dismissal Workflow
    dismissed = Column(Boolean, default=False)
    dismissed_by = Column(String(128), nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
    dismissal_reason = Column(Text, nullable=True)
