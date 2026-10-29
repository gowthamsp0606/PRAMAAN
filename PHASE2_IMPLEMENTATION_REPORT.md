# PRAMAAN / APAAR Sentinel — Phase 2 Implementation Report

**Project:** PRAMAAN / APAAR Sentinel (AICTE Hackathon SIH26263)  
**Phase:** Phase 2 — Backend Data Ingestion & Integrity Foundation  
**Date:** 2026-10-26  
**Status:** COMPLETE  

---

## 1. Executive Summary

Phase 2 establishes a reliable, fully isolated, and tested backend data-ingestion and integrity foundation for the PRAMAAN / APAAR Sentinel platform. All non-negotiable safety rules were strictly adhered to:
- The persistent demo database (`backend/apaar_sentinel.db`) remained **100% untouched and unmodified**.
- The frontend codebase (`frontend/`) remained **100% untouched**.
- Automated test database isolation was architected and verified with centralized pytest fixtures (`backend/tests/conftest.py`) and an active SQLAlchemy engine safety listener that immediately rejects any attempt by tests to touch `apaar_sentinel.db`.
- The CSV ingestion pipeline was upgraded with UTF-8 BOM stripping, header schema enforcement, in-batch and database collision detection, transactional rollback on error, preview/dry-run execution mode (`preview=true`/`dry_run=true`), and idempotent repeat import tracking.
- The backend test suite was expanded with 23 new Phase 2 test cases (`backend/tests/test_phase2_csv_pipeline.py`), bringing the total test suite to **120 tests**, all of which pass cleanly in 30.01s with **0 failures and 0 skipped**.

---

## 2. Files Changed

| File | Status | Description of Changes |
| :--- | :--- | :--- |
| `backend/tests/conftest.py` | Created | Centralized pytest test isolation fixture creating isolated temporary SQLite databases per test, seeding fixtures via `init_db_and_seed()`, enabling SQLite foreign keys, and attaching a safety check that throws `RuntimeError` if any test attempts to query or mutate `apaar_sentinel.db`. |
| `backend/app/database.py` | Modified | Added connection event listener enforcing `PRAGMA foreign_keys=ON;` on SQLite engines to guarantee relational integrity. |
| `backend/app/models/student.py` | Verified & Preserved | Preserved exact schema parity with `apaar_sentinel.db` (`apaar_id` non-nullable, removed premature unmigrated columns). |
| `backend/app/models/enrolment.py` | Verified & Preserved | Preserved non-nullable `apaar_id` matching `apaar_sentinel.db`. |
| `backend/app/services/validation_service.py` | Modified | Added `validate_headers` class method checking mandatory CSV headers. Updated `validate_record` with standard 12-digit APAAR format validation (`VAL-APAAR-FMT-001`), contextual error messages for foreign nationals and historical records, and header BOM stripping. |
| `backend/app/services/csv_import_service.py` | Modified | Added `dry_run: bool = False` support (generates `ImportJob` with `PREVIEW` status and `ImportRowResult` records without committing student/enrolment entities). Added in-batch identity collision detection (`VAL-ID-CONFLICT`, `VAL-APAAR-COLLISION`). Added database conflict and name-mismatch detection (`VAL-ID-CONFLICT`, `VAL-APAAR-COLLISION`, `VAL-ID-NAME-MISMATCH`). |
| `backend/app/routers/students.py` | Modified | Extended `upload_students_csv` endpoint to accept `preview` and `dry_run` Form flags. Added header validation check rejecting missing required columns with HTTP 400. Added UTF-8 BOM stripping across headers and row keys. Added preview status response payload. |
| `backend/app/seed_data.py` | Modified | Added `db.flush()` between student and enrolment insertions to respect foreign key ordering constraints when `PRAGMA foreign_keys=ON;` is active. |
| `backend/tests/test_phase2_csv_pipeline.py` | Created | Added 23 end-to-end automated tests covering all Phase 2 requirements. |
| `backend/README.md` | Modified | Updated documentation detailing Phase 2 database isolation, test execution, and CSV pipeline features. |

---

## 3. Features Completed

### A. Database and Pytest Isolation
- **Safety Engine Interceptor**: `@event.listens_for(Engine, "before_cursor_execute")` checks the engine database URL. If `apaar_sentinel.db` is targeted during test execution, it immediately raises a `RuntimeError` with `SAFETY VIOLATION`.
- **Per-Test Isolated Database**: Every test operates on a dedicated temporary database created in `tmp_path`.
- **Foreign Key Enforcement**: Both the application database engine and test engines execute `PRAGMA foreign_keys=ON;` on connect.
- **Fixture Seeding**: Test fixtures initialize clean schemas via `Base.metadata.create_all()` and seed demo data without touching or relying on the real database file.

### B. Reliable CSV Import Pipeline
- **File Validation**:
  - Maximum upload size: 10 MB (`MAX_CSV_UPLOAD_BYTES = 10 * 1024 * 1024`), returns HTTP 413.
  - Maximum row count: 10,000 rows (`MAX_CSV_ROWS = 10_000`), returns HTTP 413.
  - Mandatory column check: `student_ref`, `institution_id`, `programme_id`, `academic_year`, `enrolment_start`, `enrolment_status` are checked before row parsing. Missing headers return HTTP 400.
  - Duplicate or ambiguous headers: Detected and rejected with HTTP 400.
  - UTF-8 & UTF-8 BOM Handling: Safely handles `utf-8-sig` byte sequences and strips leading `\ufeff` characters from headers and dictionary row keys.
  - Malformed inputs: Decodes safely, rejecting invalid binary or corrupted data with HTTP 400.
  - Empty files: Handled cleanly; 0-byte or 0-row files return an import summary with status `FAILED` and `total_rows: 0`.

- **Row-Level Validation**:
  - Validates required fields, date formats (ISO 8601 `YYYY-MM-DD`), chronological sanity (`enrolment_end >= enrolment_start`), enrolment statuses (`Active`, `Completed`, `Withdrawn`, `Suspended`), academic-year span format (`YYYY-YYYY`), and admission categories (`General`, `SC`, `ST`, `OBC`, `EWS`, `NRI`, `OCI`, `Foreign-National`, `Supernumerary-TFW`).
  - Syntactic APAAR validation: 12-digit format check (`VAL-APAAR-FMT-001`, WARNING).
  - Explicit error reporting: Every issue records row number, field name, severity (`CRITICAL`, `ERROR`, `WARNING`, `INFO`), record reference, explanation, and suggested correction.

- **Duplicate and Collision Handling**:
  - In-batch duplicate tuples (`student_ref`, `institution_id`, `programme_id`, `start_date`) are flagged `VAL-DUP-001` (CRITICAL).
  - In-batch APAAR collisions (different student references sharing the same APAAR ID) are flagged `VAL-APAAR-COLLISION` (CRITICAL).
  - In-batch student reference conflicts (same student reference with differing APAAR IDs) are flagged `VAL-ID-CONFLICT` (CRITICAL).
  - Database identity conflicts (existing student reference with differing APAAR ID in DB) are flagged `VAL-ID-CONFLICT` (CRITICAL).
  - Registered APAAR collisions against other students in the database are flagged `VAL-APAAR-COLLISION` (CRITICAL).
  - Student name discrepancies between uploaded records and existing database records generate `VAL-ID-NAME-MISMATCH` warnings without silent merges.

- **Safe Execution & Preview Mode**:
  - Supports `preview=true` or `dry_run=true`: Validates all rows, creates an `ImportJob` with status `PREVIEW` and individual `ImportRowResult` entries for review, while committing zero changes to `students` or `enrolments`.
  - Transactional rollback: Import processing flushes entities and commits in one transaction. Any database interruption rolls back all entity writes, marks the job as `FAILED`, and records safe error logs without exposing sensitive student identifiers.
  - Repeat upload safety: Resubmitting identical records or resubmitting previously accepted enrolments prevents duplicate records and tracks linkages via `previous_job_id`.

---

## 4. API Routes Added or Changed

| Route | Method | Change Description |
| :--- | :--- | :--- |
| `/api/v1/students/upload-csv` | `POST` | Added optional Form parameters: `preview: bool = False`, `dry_run: bool = False`. Added mandatory column check returning HTTP 400 on missing headers. Added UTF-8 BOM normalization. Added `dry_run` and `preview` boolean indicators in the JSON response payload. All existing return keys (`filename`, `import_job_id`, `previous_job_id`, `status`, `total_rows`, `accepted_count`, `rejected_count`, `review_count`, `pass_rate_percent`, `error_count_by_severity`, `field_errors`, `message`) remain 100% backward compatible. |
| `/api/v1/students/import-jobs/{job_id}` | `GET` | Fully compatible; retrieves jobs in `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED`, and `PREVIEW` statuses. |
| `/api/v1/students/import-jobs/{job_id}/rows` | `GET` | Fully compatible; paginates individual row outcomes, validation messages, and masked issue codes. |

---

## 5. Database and Migration Changes

- **Schema Parity**: The database schema and SQLAlchemy models are in 100% agreement. No destructive changes were made to existing tables.
- **Alembic Revision Chain**: Remains at `20261026_01` (composite index `idx_enrolment_duplicate_lookup` on `enrolments`). No new migration is required for Phase 2.
- **Foreign Key Constraints**: SQLite foreign key constraints are enforced via `PRAGMA foreign_keys=ON;` on all connections.

---

## 6. Exact Test Commands Executed

```powershell
# Set backend module path
$env:PYTHONPATH = "backend"

# Run the full automated test suite
python -m pytest backend/tests -v
```

### Automated Test Results

- **Total Tests Collected:** 120
- **Total Tests Passed:** 120
- **Total Tests Failed:** 0
- **Total Tests Skipped:** 0
- **Execution Time:** ~30.01 seconds

### Test Breakdown by Module

| Module | Count | Status |
| :--- | :---: | :---: |
| `test_phase2_csv_pipeline.py` (New Phase 2 Suite) | 23 | **23 passed** |
| `test_csv_import_safety.py` | 11 | **11 passed** |
| `test_validation.py` | 4 | **4 passed** |
| `test_admission_categories.py` | 16 | **16 passed** |
| `test_intake_compliance_phase2.py` | 21 | **21 passed** |
| `test_phase1_security.py` | 10 | **10 passed** |
| `test_additional_features.py` | 6 | **6 passed** |
| `test_api_endpoints.py` | 5 | **5 passed** |
| `test_integrity_engine.py` | 5 | **5 passed** |
| `test_phase3_reports.py` | 3 | **3 passed** |
| `test_temporal_explorer_api.py` | 2 | **2 passed** |
| `test_config_security.py` | 2 | **2 passed** |
| `test_cors_policy.py` | 2 | **2 passed** |
| `test_exception_workflow.py` | 2 | **2 passed** |
| `test_certificates.py` | 1 | **1 passed** |
| `test_alerts_review.py` | 1 | **1 passed** |
| `test_anomaly_baseline.py` | 1 | **1 passed** |
| `test_dashboard_validation_metric.py` | 1 | **1 passed** |
| `test_import_history_migration.py` | 1 | **1 passed** |
| `test_review_history_migration.py` | 1 | **1 passed** |
| `test_intake_compliance.py` | 1 | **1 passed** |
| `test_seed_data_safety.py` | 1 | **1 passed** |
| **Total** | **120** | **120 passed (100%)** |

---

## 7. Verifications & Confirmations

- **Demo Database Integrity**: `backend/apaar_sentinel.db` was inspected before and after test runs.
  - File size: `299,008 bytes` (identical)
  - Last write timestamp: `Mon Oct 26 22:33:28 2026` (unmodified)
- **Frontend Codebase Status**: The `frontend/` directory was **not modified** in any way.
- **Security & Privacy**: No personal student information or raw credentials were introduced. Identifiers in import summaries and row error messages are masked.
- **External Integration Claims**: No claims of live connection to government or external services (DigiLocker, ABC, APAAR, AICTE) are made. Mock adapters remain transparently labeled as prototypes.

---

## 8. Instructions for Running Backend and Tests

### Run Backend
```powershell
cd backend
$env:ENVIRONMENT = "development"
$env:DATABASE_URL = "sqlite:///./apaar_sentinel.db"
$env:ALLOW_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
python -m uvicorn app.main:app --reload
```

### Run Tests
```powershell
cd backend
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -v
```

---

## 9. Important Limitations & Next Steps (Phase 3 Roadmap)

1. **Identity Lifecycle & Nullable APAAR IDs (Phase 3)**:
   - In accordance with project instructions, `Student.apaar_id` and `Enrolment.apaar_id` remain non-nullable in Phase 2 to preserve database integrity and backward compatibility.
   - Phase 3 will introduce the formal identity transition lifecycle (`HISTORICAL_NO_APAAR`, `PENDING_APAAR`, `FOREIGN_NATIONAL_EXEMPT`, `VERIFIED_APAAR`) via an Alembic migration and dedicated identity resolution workflow.
2. **Asymmetric Digital Signatures**:
   - Certificate verification currently uses shared-secret HMAC for demonstration purposes. Transition to asymmetric PKI (Ed25519/RSA) with public verifier keys is scheduled for future security hardening.
3. **Institutional Intake Aggregate Imports**:
   - Current CSV ingestion processes student-level enrolment rosters. Programme-level aggregate intake quota CSV imports can be introduced in subsequent iterations.
