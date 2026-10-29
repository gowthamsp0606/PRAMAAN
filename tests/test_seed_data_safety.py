from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.seed_data as seed_data
from app.database import Base
from app.models.student import Student


def test_seed_does_not_delete_or_duplicate_existing_data(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    test_sessions = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    monkeypatch.setattr(seed_data, "engine", test_engine)
    monkeypatch.setattr(seed_data, "SessionLocal", test_sessions)

    seed_data.init_db_and_seed()
    with test_sessions() as db:
        seeded_count = db.query(Student).count()
        assert seeded_count == 11
        db.add(Student(student_ref="KEEP-EXISTING", apaar_id="MASKED-REF", full_name="Existing Demo"))
        db.commit()

    seed_data.init_db_and_seed()

    with test_sessions() as db:
        assert db.query(Student).count() == seeded_count + 1
        assert db.query(Student).filter(Student.student_ref == "KEEP-EXISTING").one()
    test_engine.dispose()