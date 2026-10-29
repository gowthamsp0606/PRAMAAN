# PRAMAAN / APAAR Sentinel — Phase 1 Report: SQLite Write Failure Repair & Storage Hardening

**Date:** 2026-10-27  
**Project:** PRAMAAN / APAAR Sentinel (AICTE Hackathon SIH26263)  
**Location:** `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava`  
**Phase:** Phase 1 — SQLite Write Failure Repair & Storage Hardening  
**Status:** COMPLETE & VERIFIED (202/202 backend tests passing)  

---

## 1. Executive Summary

During Phase 1, the failure `sqlite3.OperationalError: attempt to write a readonly database` on `INSERT INTO verification_request_logs (...)` was systematically investigated, diagnosed at the OS filesystem and SQLite engine levels, corrected, and verified against both isolated disposable databases and live endpoints.

### Key Deliverables Completed:
1. **Root Cause Identified:** The database file had previously been marked with the Windows filesystem ReadOnly attribute (`attrib +R`), and the parent directory is located within a cloud-synced Microsoft OneDrive folder where concurrent file-indexing and default SQLite `DELETE` journal mode caused lock contention and write rejections.
2. **Safe Code & Configuration Corrections:**
   - In [`backend/app/database.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/database.py): Added an automated user write-permission check (`stat.S_IWRITE`) for the SQLite database file and configured `PRAGMA busy_timeout=5000;` on all connections to gracefully await lock clearance during concurrent reads/writes and OneDrive sync sweeps.
   - In [`backend/app/services/verifier_service.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/services/verifier_service.py): Hardened `_log_request` so that database write failures invoke `self.db.rollback()` before re-raising, preventing session corruption while strictly ensuring errors are not swallowed.
3. **Data Preservation & Safety Baselines:**
   - All existing student records (11), certificates (2), enrolments (16), alerts (3), historical intakes (10), and audit logs (20) remain intact.
   - Legacy SQLite compatibility (`identity_status` in-memory `TEMP VIEW`) was preserved.
   - Verified backups exist in `backups/backend_apaar_sentinel.db.bak` and `backups/root_apaar_sentinel.db.bak`.
4. **Test Suite Verification:**
   - 3 new write safety tests added in [`backend/tests/test_phase1_sqlite_write_safety.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/tests/test_phase1_sqlite_write_safety.py) (insert/commit/readback, rollback verification, error propagation).
   - Full test suite: **202 passed, 0 failed, 0 skipped in 9.55s**.

---

## 2. Root Cause Analysis & Diagnostic Verification (Tasks 1–7)

### A. Current File Attributes & Windows Access Permissions (Task 1)
- **Path:** `backend\apaar_sentinel.db`
- **File Mode:** `-a----` (Archive, ReadOnly flag cleared)
- **Owner / ACLs:**
  ```text
  IdentityReference: Gowtham\gowth -> FullControl (Allow)
  IdentityReference: BUILTIN\Administrators -> FullControl (Allow)
  IdentityReference: NT AUTHORITY\SYSTEM -> FullControl (Allow)
  IdentityReference: Gowtham\CodexSandboxUsers -> ReadAndExecute, Synchronize (Allow)
  ```
- **Finding:** The file ACL grants full control to the running user (`gowtham\gowth`). However, in earlier phases, the file was set to Read-Only (`attrib +R`, `Mode: -ar---`) to protect test baselines, which caused SQLite's Windows VFS (`winOs`) to open the handle with read-only flags, failing any subsequent write transaction with `SQLITE_READONLY` (error code 8).

### B. Parent Directory Writability (Task 2)
- **Parent Directory:** `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava\backend`
- **Test:** Created and removed `.write_test.tmp` in `backend/`.
- **Result:** Parent directory is **fully writable** by the application process.

### C. Resolved Database Path (Task 3 & 6)
- **Configured `DATABASE_URL`:** `sqlite:///./apaar_sentinel.db` in `backend/app/config.py`.
- **Backend Working Directory:** `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava\backend` (server started via `cd backend; uvicorn ...`).
- **Resolved Absolute Path:** `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava\backend\apaar_sentinel.db`.
- **Verification:** The backend connects to `backend\apaar_sentinel.db` (299,008 bytes, 14 tables). The root file `apaar_sentinel.db` is an unreferenced duplicate.

### D. SQLAlchemy Connection Configuration & URI Options (Task 4)
- Current connect args: `{"check_same_thread": False}`.
- No `mode=ro` or `immutable=1` URI query parameters are present in `DATABASE_URL`.
- Connection pooling uses SQLAlchemy `QueuePool` / `SingletonThreadPool` depending on engine configuration.

### E. Role of OneDrive Synchronization & File Locking (Task 5)
- The workspace resides inside a Microsoft OneDrive synchronized tree: `C:\Users\gowth\OneDrive\...`.
- OneDrive's background sync engine periodically locks files or creates brief handle contentions when `.db`, `.db-wal`, or `.db-shm` files are accessed or modified.
- In default SQLite rollback journal mode (`PRAGMA journal_mode=delete`), write operations require exclusive database locks. Without a busy timeout, any brief conflict during sync triggers immediate failure.
- **Remediation:** Setting `PRAGMA busy_timeout=5000;` instructs SQLite to wait up to 5,000ms for locks to release before raising an error.

---

## 3. Applied Corrections (Task 8, 10, 11, 12)

### File 1: [`backend/app/database.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/database.py)
1. **User Write Permission Guard:** Added an owner-specific write bit check (`stat.S_IWRITE`) at engine creation so that if the database file was checked out or flagged as read-only by an external process, the owner process ensures write permission without granting open access to other Windows users.
2. **Connection Pragmas:**
   ```python
   @event.listens_for(engine, "connect")
   def set_sqlite_pragma(dbapi_connection, connection_record):
       cursor = dbapi_connection.cursor()
       cursor.execute("PRAGMA foreign_keys=ON")
       cursor.execute("PRAGMA busy_timeout=5000")
       try:
           cols = [c[1] for c in cursor.execute("PRAGMA table_info(students)").fetchall()]
           if cols and "identity_status" not in cols:
               col_str = ", ".join(cols)
               cursor.execute(f"CREATE TEMP VIEW IF NOT EXISTS students AS SELECT {col_str}, 'APAAR_VERIFIED' AS identity_status FROM main.students")
       except Exception:
           pass
       cursor.close()
   ```

### File 2: [`backend/app/services/verifier_service.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/services/verifier_service.py)
Hardened `_log_request` so database errors trigger clean session rollbacks and propagate transparently:
```python
def _log_request(self, org_id: str, org_name: str, student_ref: Optional[str], apaar_id: Optional[str], cert_id: Optional[str], outcome: str, payload: Dict[str, Any]):
    log = VerificationRequestLog(
        verifier_org_id=org_id,
        verifier_org_name=org_name,
        query_student_ref=student_ref,
        query_apaar_id=None,
        certificate_id=cert_id,
        verification_outcome=outcome,
        limited_response_json=payload
    )
    try:
        self.db.add(log)
        self.db.commit()
    except Exception:
        self.db.rollback()
        raise
```

---

## 4. Test Verification Results

### A. Dedicated Write Safety Test Module
**File:** [`backend/tests/test_phase1_sqlite_write_safety.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/tests/test_phase1_sqlite_write_safety.py)

| Test Name | Focus Area | Status |
| :--- | :--- | :---: |
| `test_verification_request_logs_insert_commit_and_readback` | Real insert, commit and readback of verification log | **PASSED** |
| `test_verification_logging_rolls_back_on_failure` | Session rollback on simulated database failure | **PASSED** |
| `test_verification_logging_does_not_swallow_database_errors` | Exception propagation without silent error suppression | **PASSED** |

### B. Live API Credential Verification Test
Executed candidate verification via FastAPI TestClient against live routes:
```json
POST /api/v1/verifier/verify-credential
Body: { "verifier_org_id": "ORG-TCS-BGV", "certificate_id": "CERT-APAAR-2026-001" }
Status: 200 OK
Response: {
  "verified": true,
  "outcome": "MATCH_VERIFIED",
  "student_name": "Aarav Sharma",
  "institution_name": "Delhi Technological University (Demo)",
  "programme_name": "B.Tech Computer Science & Engineering",
  "academic_status": "Completed",
  "conferred_date": "2026-05-31",
  "purpose_scope": "EMPLOYMENT_BACKGROUND_CHECK_ONLY"
}
```
- Verification Request Log readback: `GET /api/v1/verifier/logs?verifier_org_id=ORG-TCS-BGV` returned count **10** (log recorded successfully).

### C. Live HTTP Endpoint Sanity Checks
- `GET http://127.0.0.1:8000/health` -> **HTTP 200 OK**
- `GET http://127.0.0.1:8000/api/v1/dashboard/summary` -> **HTTP 200 OK**
- `GET http://127.0.0.1:8000/api/v1/certificates` -> **HTTP 200 OK**
- `GET http://127.0.0.1:8000/api/v1/reports/executive-summary` -> **HTTP 200 OK**
- `GET http://127.0.0.1:8000/api/v1/verifier/logs` -> **HTTP 200 OK**

### D. Full Automated Test Suite Execution
```powershell
& "C:\Users\gowth\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests -v
```
**Results:**
- **Total Tests Collected:** 202
- **Passed:** 202
- **Failed:** 0
- **Skipped:** 0
- **Duration:** 9.55 seconds

---

## 5. Backup Information & Integrity Baseline

Verified backups remain intact:
- `backups/backend_apaar_sentinel.db.bak` (Verified SHA-256: `D6F4C035CCE68F40A64930FC81EAD31CACC9FACEB217F534089DB5092B79A9C4`)
- `backups/root_apaar_sentinel.db.bak` (Verified SHA-256: `54D6D823EEC8C723AEF869353EDA0B72C519B8232B465110A09FD11D01321A0D`)

---

## 6. Unresolved Issues & Next Steps

1. **Phase 1 Complete:** The SQLite write failure is completely repaired; verification request logging operates reliably with full rollback safety and without swallowed exceptions.
2. **Next Steps (Phase 2):** Authentication backend & JWT lifecycle to support real login, user sessions, and authenticated role-specific dashboard routing.

*Phase 1 complete. Stopping as instructed.*
