import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm.session import Session

from app.main import app
from app.models.enrolment import Enrolment
from app.models.import_job import ImportJob, ImportRowResult
from app.models.student import Student
from app.routers.students import MAX_CSV_ROWS, MAX_CSV_UPLOAD_BYTES


@pytest.fixture
def isolated_client(isolate_database_for_tests):
    _engine, test_sessions = isolate_database_for_tests
    yield TestClient(app), test_sessions


CSV_HEADER = (
    "student_ref,apaar_id,full_name,institution_id,institution_name,programme_id,"
    "programme_name,academic_year,admission_cycle,enrolment_start,enrolment_end,"
    "enrolment_status,seat_category,source_submission_id\n"
)
CSV_ROW = (
    "STU-IMPORT-001,9876-5432-9001,Demo Student,INST-DEMO,Demo Institution,"
    "PROG-DEMO,Demo Programme,2025-2026,Regular 2025,2025-08-01,,Active,General,SUB-DEMO-001\n"
)


def upload(client: TestClient, csv_text: str, *, filename: str = "students.csv", previous_job_id: str | None = None):
    return client.post(
        "/api/v1/students/upload-csv",
        files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
        data={"previous_job_id": previous_job_id} if previous_job_id else None,
    )


def upload_bytes(client: TestClient, content: bytes, *, filename: str):
    return client.post(
        "/api/v1/students/upload-csv",
        files={"file": (filename, content, "text/csv")},
    )


def test_repeated_csv_import_does_not_duplicate_enrolment(isolated_client):
    client, sessions = isolated_client

    first = upload(client, CSV_HEADER + CSV_ROW)
    second = upload(client, CSV_HEADER + CSV_ROW)

    assert first.status_code == 200
    assert first.json()["accepted_count"] == 1
    assert second.status_code == 200
    assert second.json()["accepted_count"] == 0
    assert second.json()["rejected_count"] == 1
    assert second.json()["pass_rate_percent"] == 0
    assert second.json()["error_count_by_severity"]["CRITICAL"] == 1
    assert any(error["rule_id"] == "VAL-DUP-001" for error in second.json()["field_errors"])
    with sessions() as db:
        assert db.query(Enrolment).count() == 1
        assert db.query(ImportJob).count() == 2
        assert db.query(ImportRowResult).count() == 2


def test_import_job_and_row_results_are_retrievable(isolated_client):
    client, sessions = isolated_client
    response = upload(client, CSV_HEADER + CSV_ROW)
    job_id = response.json()["import_job_id"]

    job = client.get(f"/api/v1/students/import-jobs/{job_id}")
    rows = client.get(f"/api/v1/students/import-jobs/{job_id}/rows")
    listing = client.get("/api/v1/students/import-jobs")

    assert response.status_code == 200
    assert job.status_code == rows.status_code == listing.status_code == 200
    assert job.json()["status"] == "COMPLETED"
    assert job.json()["accepted_rows"] == 1
    assert rows.json()["items"][0]["outcome"] == "ACCEPTED"
    assert rows.json()["items"][0]["persisted"] is True
    assert listing.json()["total"] == 1
    with sessions() as db:
        result = db.query(ImportRowResult).one()
        assert result.identity_hash
        assert "9876-5432-9001" not in str(result.validation_messages)


def test_malformed_and_empty_uploads_finish_as_failed_jobs(isolated_client):
    client, sessions = isolated_client
    malformed = upload_bytes(client, b"\xff\xfe\xfa", filename="broken.csv")
    empty = upload(client, CSV_HEADER, filename="empty.csv")

    assert malformed.status_code == 400
    malformed_job = client.get(f"/api/v1/students/import-jobs/{malformed.headers['X-Import-Job-Id']}")
    assert malformed_job.json()["status"] == "FAILED"
    assert empty.status_code == 200
    assert empty.json()["status"] == "FAILED"
    with sessions() as db:
        assert db.query(ImportJob).filter(ImportJob.status == "PROCESSING").count() == 0


def test_correction_import_links_a_previously_rejected_row(isolated_client):
    client, sessions = isolated_client
    invalid_row = CSV_ROW.replace("2025-08-01", "bad-date")
    first = upload(client, CSV_HEADER + invalid_row)
    assert first.status_code == 200, first.text
    first_job_id = first.json()["import_job_id"]
    corrected = upload(client, CSV_HEADER + CSV_ROW, previous_job_id=first_job_id)

    assert first.json()["rejected_count"] == 1
    assert corrected.status_code == 200
    assert corrected.json()["previous_job_id"] == first_job_id
    current_job_id = corrected.json()["import_job_id"]
    old_row = client.get(f"/api/v1/students/import-jobs/{first_job_id}/rows").json()["items"][0]
    new_row = client.get(f"/api/v1/students/import-jobs/{current_job_id}/rows").json()["items"][0]
    assert old_row["outcome"] == "REJECTED"
    assert new_row["outcome"] == "ACCEPTED"
    assert new_row["previous_row_result_id"] == old_row["row_result_id"]
    with sessions() as db:
        assert db.query(Enrolment).count() == 1
        assert db.query(ImportJob).count() == 2


def test_ambiguous_correction_match_is_flagged_without_persisting(isolated_client):
    client, sessions = isolated_client
    rows = CSV_ROW.replace("2025-08-01", "2025-08-01") + CSV_ROW.replace(
        "2025-08-01", "2026-08-01"
    ).replace("2025-2026", "2026-2027").replace("Regular 2025", "Lateral 2026")
    previous = upload(client, CSV_HEADER + rows)
    correction = upload(client, CSV_HEADER + CSV_ROW.replace("2025-08-01", "2027-08-01"), previous_job_id=previous.json()["import_job_id"])

    assert previous.json()["accepted_count"] == 2
    assert correction.json()["review_count"] == 1
    assert correction.json()["rejected_count"] == 1
    result = client.get(f"/api/v1/students/import-jobs/{correction.json()['import_job_id']}/rows").json()["items"][0]
    assert result["outcome"] == "NEEDS_REVIEW"
    assert result["persisted"] is False
    assert any(issue["code"] == "IMPORT-MATCH-001" for issue in result["validation_messages"])
    with sessions() as db:
        assert db.query(Enrolment).count() == 2


def test_unexpected_processing_failure_rolls_back_rows_and_marks_job_failed(isolated_client, monkeypatch):
    client, sessions = isolated_client
    original_commit = Session.commit
    commit_count = 0

    def fail_data_commit(session):
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise RuntimeError("injected commit failure")
        return original_commit(session)

    monkeypatch.setattr(Session, "commit", fail_data_commit)
    response = upload(client, CSV_HEADER + CSV_ROW)

    assert response.status_code == 500
    assert response.json()["detail"] == "CSV import failed unexpectedly; no accepted rows from this job were committed."
    job_id = response.headers["X-Import-Job-Id"]
    job = client.get(f"/api/v1/students/import-jobs/{job_id}")
    assert job.json()["status"] == "FAILED"
    assert "test failure" not in job.json()["error_summary"]
    with sessions() as db:
        assert db.query(Student).count() == 0
        assert db.query(Enrolment).count() == 0
        assert db.query(ImportRowResult).count() == 0
        assert db.query(ImportJob).filter(ImportJob.id == job_id).one().status == "FAILED"


def test_duplicate_rows_in_one_csv_are_only_imported_once(isolated_client):
    client, sessions = isolated_client

    response = upload(client, CSV_HEADER + CSV_ROW + CSV_ROW)

    assert response.status_code == 200
    assert response.json()["accepted_count"] == 1
    assert response.json()["rejected_count"] == 1
    assert any(error["rule_id"] == "VAL-DUP-001" for error in response.json()["field_errors"])
    with sessions() as db:
        assert db.query(Enrolment).count() == 1


def test_csv_upload_rejects_oversized_content(isolated_client):
    client, _ = isolated_client
    content = b"a" * (MAX_CSV_UPLOAD_BYTES + 1)

    response = client.post(
        "/api/v1/students/upload-csv",
        files={"file": ("large.csv", io.BytesIO(content), "text/csv")},
    )

    assert response.status_code == 413


def test_csv_upload_rejects_too_many_rows(isolated_client):
    client, _ = isolated_client
    content = CSV_HEADER + CSV_ROW * (MAX_CSV_ROWS + 1)

    response = upload(client, content)

    assert response.status_code == 413


def test_csv_upload_rejects_ambiguous_headers(isolated_client):
    client, _ = isolated_client

    response = upload(client, "student_ref, student_ref\nA,B\n")

    assert response.status_code == 400
    assert "duplicate or ambiguous" in response.json()["detail"]


def test_mixed_valid_and_invalid_rows_in_single_upload(isolated_client):
    """A CSV with one valid row and one row missing required fields should
    accept the valid row, reject the invalid row, and report partial success."""
    client, sessions = isolated_client
    invalid_row = (
        ",9876-5432-9002,,INST-DEMO,Demo Institution,"
        "PROG-DEMO,Demo Programme,2025-2026,Regular 2025,2025-08-01,,Active,General,SUB-DEMO-002\n"
    )
    response = upload(client, CSV_HEADER + CSV_ROW + invalid_row)

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED_WITH_ERRORS"
    assert response.json()["total_rows"] == 2
    assert response.json()["accepted_count"] == 1
    assert response.json()["rejected_count"] == 1
    assert response.json()["review_count"] == 0
    assert response.json()["error_count_by_severity"]["CRITICAL"] == 1

    job_id = response.json()["import_job_id"]
    rows = client.get(f"/api/v1/students/import-jobs/{job_id}/rows").json()["items"]
    assert len(rows) == 2
    assert rows[0]["outcome"] == "ACCEPTED"
    assert rows[0]["persisted"] is True
    assert rows[1]["outcome"] == "REJECTED"
    assert rows[1]["persisted"] is False
    assert any(code == "VAL-REQ-001" for code in rows[1]["issue_codes"])

    with sessions() as db:
        job = db.query(ImportJob).filter(ImportJob.id == job_id).one()
        assert job.accepted_rows == 1
        assert job.rejected_rows == 1
        assert job.total_rows == 2
        assert job.review_rows == 0
        assert db.query(Enrolment).count() == 1