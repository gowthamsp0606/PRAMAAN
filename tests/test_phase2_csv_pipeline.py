import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import app
from app.models.enrolment import Enrolment
from app.models.import_job import ImportJob
from app.models.student import Student


@pytest.fixture
def test_client(isolate_database_for_tests):
    _engine, session_factory = isolate_database_for_tests
    yield TestClient(app), session_factory


CSV_HEADER = (
    "student_ref,apaar_id,full_name,institution_id,institution_name,programme_id,"
    "programme_name,academic_year,admission_cycle,enrolment_start,enrolment_end,"
    "enrolment_status,seat_category,source_submission_id\n"
)


def upload(client: TestClient, csv_text: str, *, filename: str = "batch.csv", preview: bool = False, dry_run: bool = False, previous_job_id: str = None):
    data = {}
    if preview:
        data["preview"] = "true"
    if dry_run:
        data["dry_run"] = "true"
    if previous_job_id:
        data["previous_job_id"] = previous_job_id

    return client.post(
        "/api/v1/students/upload-csv",
        files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
        data=data or None,
    )


# 1. Valid CSV import
def test_valid_csv_import(test_client):
    client, sessions = test_client
    row = (
        "STU-P2-001,9876-5432-0001,Alice Smith,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,2026-05-31,Active,General,BATCH-P2-01\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "COMPLETED"
    assert data["total_rows"] == 1
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 0
    assert data["pass_rate_percent"] == 100.0

    with sessions() as db:
        assert db.query(Student).filter(Student.student_ref == "STU-P2-001").count() == 1
        assert db.query(Enrolment).filter(Enrolment.student_ref == "STU-P2-001").count() == 1


# 2. Empty CSV
def test_empty_csv(test_client):
    client, _ = test_client
    res = upload(client, CSV_HEADER, filename="empty.csv")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "FAILED"
    assert data["total_rows"] == 0
    assert data["accepted_count"] == 0


# 3. Missing required columns
def test_missing_required_columns(test_client):
    client, _ = test_client
    # Missing enrolment_status column
    bad_header = "student_ref,apaar_id,institution_id,programme_id,academic_year,enrolment_start\n"
    bad_row = "STU-P2-002,9876-5432-0002,INST-A,PROG-CS,2025-2026,2025-08-01\n"
    res = upload(client, bad_header + bad_row)
    assert res.status_code == 400
    assert "missing mandatory column" in res.json()["detail"].lower()


# 4. Duplicate column headers
def test_duplicate_column_headers(test_client):
    client, _ = test_client
    duplicate_header = "student_ref,apaar_id,student_ref\nA,B,C\n"
    res = upload(client, duplicate_header)
    assert res.status_code == 400
    assert "duplicate or ambiguous" in res.json()["detail"].lower()


# 5. UTF-8 BOM handling
def test_utf8_bom_handling(test_client):
    client, sessions = test_client
    row = (
        "STU-BOM-001,9876-5432-0003,Bom Student,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-BOM\n"
    )
    bom_content = (CSV_HEADER + row).encode("utf-8-sig")
    res = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("bom.csv", bom_content, "text/csv")},
    )
    assert res.status_code == 200
    assert res.json()["accepted_count"] == 1


# 6. Malformed CSV
def test_malformed_csv(test_client):
    client, _ = test_client
    res = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("corrupt.csv", b"\xff\xfe\xfa\x00\x00", "text/csv")},
    )
    assert res.status_code == 400


# 7. Invalid row values (invalid date and unrecognized status)
def test_invalid_row_values(test_client):
    client, _ = test_client
    row = (
        "STU-VAL-BAD,9876-5432-0004,Bad Row,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,not-a-date,,NonExistentStatus,General,BATCH-01\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200
    data = res.json()
    assert data["rejected_count"] == 1
    assert data["accepted_count"] == 0
    codes = {issue["rule_id"] for issue in data["field_errors"]}
    assert "VAL-DAT-001" in codes or "VAL-STA-001" in codes


# 8. Missing APAAR IDs
def test_missing_apaar_id_is_rejected(test_client):
    client, sessions = test_client
    row = (
        "STU-NO-APAAR,,No Apaar,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-01\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200
    data = res.json()
    assert data["rejected_count"] == 1
    assert data["accepted_count"] == 0
    assert any(e["rule_id"] == "VAL-REQ-001" and e["field"] == "apaar_id" for e in data["field_errors"])


# 9. Duplicate APAAR IDs inside one upload (in-batch collision across different student_refs)
def test_in_batch_apaar_collision(test_client):
    client, sessions = test_client
    row1 = (
        "STU-COLL-1,9876-5432-8888,Student One,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-01\n"
    )
    row2 = (
        "STU-COLL-2,9876-5432-8888,Student Two,INST-A,Institution A,PROG-EC,Electronics,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-01\n"
    )
    res = upload(client, CSV_HEADER + row1 + row2)
    assert res.status_code == 200
    data = res.json()
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 1
    assert any(e["rule_id"] == "VAL-APAAR-COLLISION" for e in data["field_errors"])


# 10. Existing student conflicts (same student_ref with differing APAAR ID)
def test_existing_student_apaar_conflict(test_client):
    client, sessions = test_client
    row1 = (
        "STU-EXIST-01,9876-5432-1111,Initial Student,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-01\n"
    )
    res1 = upload(client, CSV_HEADER + row1)
    assert res1.status_code == 200

    row2 = (
        "STU-EXIST-01,9876-5432-9999,Conflicting Student,INST-A,Institution A,PROG-EC,Electronics,"
        "2026-2027,Regular 2026,2026-08-01,,Active,General,BATCH-02\n"
    )
    res2 = upload(client, CSV_HEADER + row2)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["rejected_count"] == 1
    assert any(e["rule_id"] == "VAL-ID-CONFLICT" for e in data2["field_errors"])


# 11. Duplicate enrolments
def test_duplicate_enrolment_rejection(test_client):
    client, sessions = test_client
    row = (
        "STU-DUP-ENR,9876-5432-2222,Dup Student,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-01\n"
    )
    res1 = upload(client, CSV_HEADER + row)
    assert res1.status_code == 200
    assert res1.json()["accepted_count"] == 1

    res2 = upload(client, CSV_HEADER + row)
    assert res2.status_code == 200
    assert res2.json()["accepted_count"] == 0
    assert res2.json()["rejected_count"] == 1
    assert any(e["rule_id"] == "VAL-DUP-001" for e in res2.json()["field_errors"])


# 12. Institution-scoped duplicate behavior
def test_institution_scoped_duplicate(test_client):
    client, sessions = test_client
    # In-batch duplicate within institution
    row = (
        "STU-INST-DUP,9876-5432-3333,Scoped Student,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-01\n"
    )
    res = upload(client, CSV_HEADER + row + row)
    assert res.status_code == 200
    assert res.json()["accepted_count"] == 1
    assert res.json()["rejected_count"] == 1


# 13. Invalid admission categories
def test_invalid_admission_category(test_client):
    client, _ = test_client
    row = (
        "STU-CAT-BAD,9876-5432-4444,Cat Student,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,,Active,UnsupportedCategoryXYZ,BATCH-01\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200
    data = res.json()
    assert data["rejected_count"] == 1
    assert any(e["rule_id"] == "VAL-CAT-001" for e in data["field_errors"])


# 14. Invalid date ranges (chronological inversion)
def test_invalid_date_range_chronological_inversion(test_client):
    client, _ = test_client
    row = (
        "STU-INV-DATE,9876-5432-5555,Date Student,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2026-08-01,2025-08-01,Completed,General,BATCH-01\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200
    data = res.json()
    assert data["rejected_count"] == 1
    assert any(e["rule_id"] == "VAL-DAT-003" for e in data["field_errors"])


# 15. Import preview behavior (dry-run / preview mode commits zero student or enrolment records)
def test_import_preview_mode(test_client):
    client, sessions = test_client
    row = (
        "STU-PREVIEW-01,9876-5432-6666,Preview Student,INST-A,Institution A,PROG-CS,Computer Science,"
        "2025-2026,Regular 2025,2025-08-01,2026-05-31,Active,General,BATCH-PREVIEW\n"
    )
    res = upload(client, CSV_HEADER + row, preview=True)
    assert res.status_code == 200
    data = res.json()
    assert data["dry_run"] is True
    assert data["preview"] is True
    assert data["accepted_count"] == 1
    assert "Preview completed" in data["message"]

    # Verify database was NOT modified
    with sessions() as db:
        assert db.query(Student).filter(Student.student_ref == "STU-PREVIEW-01").first() is None
        assert db.query(Enrolment).filter(Enrolment.student_ref == "STU-PREVIEW-01").first() is None
        # But import job was created with status PREVIEW
        job = db.query(ImportJob).filter(ImportJob.id == data["import_job_id"]).first()
        assert job is not None
        assert job.status == "PREVIEW"


# 16. Successful transactional import
def test_successful_transactional_import(test_client):
    client, sessions = test_client
    row = (
        "STU-TX-01,9876-5432-7777,Tx Student,INST-TX,Institution TX,PROG-TX,Programme TX,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-TX\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200
    with sessions() as db:
        stu = db.query(Student).filter(Student.student_ref == "STU-TX-01").first()
        enr = db.query(Enrolment).filter(Enrolment.student_ref == "STU-TX-01").first()
        assert stu is not None
        assert enr is not None
        assert stu.primary_institution_id == "INST-TX"


# 17. Rollback after a forced failure
def test_rollback_after_forced_failure(test_client, monkeypatch):
    client, sessions = test_client
    from sqlalchemy.orm.session import Session
    original_commit = Session.commit
    fail_trigger = 0

    def fail_commit(self):
        nonlocal fail_trigger
        fail_trigger += 1
        if fail_trigger == 2:
            raise RuntimeError("Database connection interrupted during batch flush")
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", fail_commit)
    row = (
        "STU-ROLLBACK-01,9876-5432-9991,Rollback Student,INST-A,Institution A,PROG-CS,CS,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-RB\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 500
    assert "no accepted rows from this job were committed" in res.json()["detail"]

    with sessions() as db:
        assert db.query(Student).filter(Student.student_ref == "STU-ROLLBACK-01").first() is None
        assert db.query(Enrolment).filter(Enrolment.student_ref == "STU-ROLLBACK-01").first() is None


# 18. Repeated import/retry behavior
def test_repeated_import_idempotent_job_tracking(test_client):
    client, sessions = test_client
    row = (
        "STU-RETRY-01,9876-5432-9992,Retry Student,INST-A,Institution A,PROG-CS,CS,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-RETRY\n"
    )
    first = upload(client, CSV_HEADER + row)
    assert first.status_code == 200
    first_job_id = first.json()["import_job_id"]

    # Second upload referencing first_job_id
    second = upload(client, CSV_HEADER + row, previous_job_id=first_job_id)
    assert second.status_code == 200
    data2 = second.json()
    assert data2["previous_job_id"] == first_job_id
    assert data2["accepted_count"] == 0
    assert data2["rejected_count"] == 1


# 19. Import-job status and summary counts
def test_import_job_status_and_summary_counts(test_client):
    client, _ = test_client
    row_valid = (
        "STU-CNT-01,9876-5432-9993,Valid Student,INST-A,Institution A,PROG-CS,CS,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-CNT\n"
    )
    row_invalid = (
        ",,Missing Fields,,,,,,,,,\n"
    )
    res = upload(client, CSV_HEADER + row_valid + row_invalid)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "COMPLETED_WITH_ERRORS"
    assert data["total_rows"] == 2
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 1
    assert data["error_count_by_severity"]["CRITICAL"] >= 1


# 20. Import-history retrieval
def test_import_history_retrieval(test_client):
    client, _ = test_client
    row = (
        "STU-HIST-01,9876-5432-9994,Hist Student,INST-A,Institution A,PROG-CS,CS,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-HIST\n"
    )
    res = upload(client, CSV_HEADER + row)
    job_id = res.json()["import_job_id"]

    history_res = client.get(f"/api/v1/students/import-jobs/{job_id}")
    assert history_res.status_code == 200
    h_data = history_res.json()
    assert h_data["import_job_id"] == job_id
    assert h_data["total_rows"] == 1
    assert h_data["accepted_rows"] == 1

    rows_res = client.get(f"/api/v1/students/import-jobs/{job_id}/rows")
    assert rows_res.status_code == 200
    assert len(rows_res.json()["items"]) == 1


# 21. Sensitive identifier masking
def test_sensitive_identifier_masking_in_validation(test_client):
    client, _ = test_client
    # Row with APAAR ID format warning
    row = (
        "STU-MASK-01,987654321000,Mask Student,INST-A,Institution A,PROG-CS,CS,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-MASK\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200
    job_id = res.json()["import_job_id"]

    rows_res = client.get(f"/api/v1/students/import-jobs/{job_id}/rows")
    assert rows_res.status_code == 200
    messages = rows_res.json()["items"][0]["validation_messages"]
    for msg in messages:
        # Full raw APAAR or 12 digit pattern should not appear unmasked in message
        assert "987654321000" not in msg["message"]


# 22. Existing endpoint compatibility
def test_existing_student_endpoints_compatible(test_client):
    client, _ = test_client
    row = (
        "STU-COMPAT-01,9876-5432-9995,Compat Student,INST-A,Institution A,PROG-CS,CS,"
        "2025-2026,Regular 2025,2025-08-01,,Active,General,BATCH-COMPAT\n"
    )
    res = upload(client, CSV_HEADER + row)
    assert res.status_code == 200

    stu_res = client.get("/api/v1/students/STU-COMPAT-01")
    assert stu_res.status_code == 200
    stu_data = stu_res.json()
    assert stu_data["student"]["student_ref"] == "STU-COMPAT-01"
    assert len(stu_data["enrolments"]) == 1
    assert stu_data["enrolments"][0]["programme_id"] == "PROG-CS"


# 23. Test database isolation from the original demo database
def test_database_isolation_rejects_demo_db(tmp_path):
    from sqlalchemy import text
    import pytest

    # Use the forbidden filename in a disposable directory so the listener fires
    # without opening backend/apaar_sentinel.db.
    forbidden_url = f"sqlite:///{(tmp_path / 'apaar_sentinel.db').as_posix()}"
    demo_engine = create_engine(forbidden_url)
    with pytest.raises(RuntimeError) as exc_info:
        with demo_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    assert "SAFETY VIOLATION" in str(exc_info.value)
    demo_engine.dispose()
