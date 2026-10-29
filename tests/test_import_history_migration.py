import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.enrolment import Enrolment
from app.models.student import Student
from app.models.import_job import ImportJob, ImportRowResult


def test_import_history_migration_preserves_existing_rows(tmp_path):
    database_path = tmp_path / "legacy-schema.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    new_tables = {ImportJob.__table__, ImportRowResult.__table__}
    legacy_tables = [table for table in Base.metadata.sorted_tables if table not in new_tables]
    Base.metadata.create_all(bind=engine, tables=legacy_tables)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(Student(
            student_ref="STU-MIGRATION-PRESERVE",
            apaar_id="MASKED-MIGRATION-REF",
            full_name="Migration Fixture",
        ))
        db.flush()
        db.add(Enrolment(
            student_ref="STU-MIGRATION-PRESERVE",
            apaar_id="MASKED-MIGRATION-REF",
            institution_id="INST-MIGRATION",
            programme_id="PROG-MIGRATION",
            academic_year="2025-2026",
            admission_cycle="Regular 2025",
            enrolment_start=date(2025, 8, 1),
            enrolment_status="Active",
        ))
        db.commit()
    engine.dispose()

    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["ENVIRONMENT"] = "development"
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    migrated_engine = create_engine(database_url)
    migrated_sessions = sessionmaker(bind=migrated_engine)
    table_names = set(inspect(migrated_engine).get_table_names())
    with migrated_sessions() as db:
        assert db.query(Student).filter(Student.student_ref == "STU-MIGRATION-PRESERVE").count() == 1
        assert db.query(Enrolment).filter(Enrolment.student_ref == "STU-MIGRATION-PRESERVE").count() == 1
    migrated_engine.dispose()

    assert "import_jobs" in table_names
    assert "import_row_results" in table_names
    assert "alembic_version" in table_names