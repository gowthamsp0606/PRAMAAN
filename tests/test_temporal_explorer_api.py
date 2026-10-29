from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.enrolment import Enrolment
from app.models.student import Student


@pytest.fixture
def timeline_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        db.add_all([
            Student(student_ref="TRANSFER-1", apaar_id="MASK-1", full_name="Transfer Demo"),
            Student(student_ref="OVERLAP-1", apaar_id="MASK-2", full_name="Overlap Demo"),
        ])
        db.flush()
        db.add_all([
            Enrolment(
                student_ref="TRANSFER-1", apaar_id="MASK-1", institution_id="INST-A",
                programme_id="PROG-A", academic_year="2024-2025", admission_cycle="Regular",
                enrolment_start=date(2024, 8, 1), enrolment_end=date(2025, 5, 31),
                enrolment_status="Completed",
            ),
            Enrolment(
                student_ref="TRANSFER-1", apaar_id="MASK-1", institution_id="INST-B",
                programme_id="PROG-B", academic_year="2025-2026", admission_cycle="Transfer",
                enrolment_start=date(2025, 8, 1), enrolment_status="Active",
            ),
            Enrolment(
                student_ref="OVERLAP-1", apaar_id="MASK-2", institution_id="INST-C",
                programme_id="PROG-C", academic_year="2025-2026", admission_cycle="Regular",
                enrolment_start=date(2025, 7, 1), enrolment_status="Active",
            ),
            Enrolment(
                student_ref="OVERLAP-1", apaar_id="MASK-2", institution_id="INST-D",
                programme_id="PROG-D", academic_year="2025-2026", admission_cycle="Regular",
                enrolment_start=date(2025, 8, 1), enrolment_status="Active",
            ),
        ])
        db.commit()

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()


def test_temporal_explorer_explains_non_overlapping_transfer(timeline_client):
    response = timeline_client.get("/api/v1/students/TRANSFER-1/timeline")

    assert response.status_code == 200
    result = response.json()
    assert len(result["enrolments"]) == 2
    pair = result["pairwise_analysis"][0]
    assert pair["overlaps"] is False
    assert "before" in pair["explanation"]
    assert pair["rule_id"] == "TEMPORAL-OVERLAP-001"
    assert pair["compared_fields"]["record_1"]["institution_id"] == "INST-A"


def test_temporal_explorer_exposes_overlapping_active_periods(timeline_client):
    response = timeline_client.get("/api/v1/students/OVERLAP-1/timeline")

    assert response.status_code == 200
    pair = response.json()["pairwise_analysis"][0]
    assert pair["overlaps"] is True
    assert pair["overlap_start"] == "2025-08-01"
    assert pair["overlap_end"] == "Ongoing"
    assert pair["recommended_action"] == "Request documentation and reviewer assessment."