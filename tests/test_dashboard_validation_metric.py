from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.enrolment import Enrolment
from app.models.student import Student


def test_dashboard_validation_rate_uses_enrolment_schema_rules():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with test_sessions() as db:
        db.add_all([
            Student(student_ref="VALID-1", apaar_id="MASK-1", full_name="Valid Demo"),
            Student(student_ref="INVALID-1", apaar_id="MASK-2", full_name="Invalid Demo"),
        ])
        db.flush()
        db.add_all([
            Enrolment(
                student_ref="VALID-1", apaar_id="MASK-1", institution_id="INST-1",
                programme_id="PROG-1", academic_year="2025-2026", admission_cycle="Regular",
                enrolment_start=date(2025, 8, 1), enrolment_status="Active",
            ),
            Enrolment(
                student_ref="INVALID-1", apaar_id="MASK-2", institution_id="INST-1",
                programme_id="PROG-1", academic_year="2025-2026", admission_cycle="Regular",
                enrolment_start=date(2025, 8, 1), enrolment_status="Unknown",
            ),
        ])
        db.commit()

    def override_get_db():
        db = test_sessions()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/dashboard/summary")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["validation_pass_rate"] == 50.0