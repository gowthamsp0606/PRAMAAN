import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.models.alert import Alert


def test_review_history_migration_preserves_alert_rows(tmp_path):
    database_path = tmp_path / "existing-records.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Alert.__table__.create(bind=engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(Alert(
            id="ALT-MIGRATION-001",
            student_ref="STU-MIGRATION-001",
            apaar_id="MASKED-MIGRATION-001",
            alert_type="TEMPORAL_OVERLAP_CONFLICT",
            severity="MEDIUM",
            status="OPEN",
            title="Existing alert",
            explanation="Must remain available after migration.",
        ))
        db.commit()
    engine.dispose()

    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["ENVIRONMENT"] = "development"
    project_root = Path(__file__).resolve().parents[1]
    for _ in range(2):
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
    table_names = inspect(migrated_engine).get_table_names()
    with sessionmaker(bind=migrated_engine)() as db:
        assert db.query(Alert).filter(Alert.id == "ALT-MIGRATION-001").count() == 1
    migrated_engine.dispose()

    assert "alert_review_events" in table_names
    assert "alembic_version" in table_names