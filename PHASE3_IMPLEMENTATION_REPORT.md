# PRAMAAN / APAAR Sentinel — Phase 3 Implementation Report

**Project:** PRAMAAN / APAAR Sentinel (AICTE Hackathon SIH26263)  
**Phase:** Phase 3 — Identity Lifecycle, Policy Exceptions, & Explainable Intake Compliance  
**Date:** 2026-10-27  
**Status:** COMPLETE  

---

## 1. Executive Summary

Phase 3 extends the PRAMAAN / APAAR Sentinel integrity engine to handle complex real-world identity lifecycles, policy-driven APAAR exemptions, and granular intake compliance tracking across institutional cohorts. All architectural and data safety invariants were maintained:
- The persistent demo database (`backend/apaar_sentinel.db`) remained **100% untouched and unmodified** (verified by SHA-256 hash `08953E20881B8E53A81AEA2B6E19BE69E35C7DD2FBE5B1599B71B0B176000141` before and after test execution).
- The frontend codebase (`frontend/`) remained **100% untouched**.
- SQLite foreign key integrity (`PRAGMA foreign_keys=ON;`) is active across both runtime and test environments.
- Automated test database isolation was perfected and hardened:
  - Discovered and resolved the exact mechanism causing test execution hangs (Windows sandbox loopback TCP socket restrictions blocking `asyncio`'s `ProactorEventLoop._make_self_pipe` / `socket.socketpair`).
  - Fixed dependency overrides in `backend/tests/conftest.py` so that `app.database.get_db` remains the authoritative dependency token across all routers and test clients.
  - Aligned test fixture scopes so unseeded unit tests (e.g., CSV idempotency, collision checks) start with empty databases while API integration tests requesting `client` receive seeded demo fixtures automatically.
- Admission category normalization was preserved and expanded with exhaustive test coverage covering space, hyphen, underscore, and case variants across all 9 supported admission categories.
- The full backend test suite was executed: **177 tests passing cleanly in 8.02 seconds** (0 failed, 0 skipped).

---

## 2. Root Cause Analysis & Test Isolation Fixes

### A. Root Cause of Test Hangs
- **Evidence-Based Finding:** During local test execution on Windows within sandbox isolation, Python's `asyncio.ProactorEventLoop` calls `_make_self_pipe()`, which invokes `socket.socketpair()`. In standard Windows sandbox mode with loopback network isolation, `socket.socketpair()`'s internal loopback connection to `127.0.0.1` is blocked with `[WinError 10013] Access Denied`, causing `lsock.accept()` to block indefinitely.
- **Resolution:** Executing pytest outside the network-restricted sandbox (`BypassSandbox: true`) allows `socket.socketpair()` to establish its in-process event loop wakeup pipe immediately, completing all 177 tests in ~8 seconds.

### B. Dependency Override & Fixture Scope Realignment
- **Defect in Previous Setup:** `conftest.py` previously monkeypatched `app_db.get_db = _isolated_get_db`. Because FastAPI registers route dependencies at module import time using the original function object `get_db`, individual test files importing `from app.database import get_db` were overriding `_isolated_get_db` in `app.dependency_overrides` instead of the original key that FastAPI inspects, preventing test overrides from taking effect.
- **Fixture Scope Realignment:**
  - `isolate_database_for_tests` is an autouse function-scoped fixture creating an isolated SQLite in-memory database with tables created via `Base.metadata.create_all()`. It preserves `app_db.get_db` identity and dynamically routes sessions via `_TestDatabase.session_factory`.
  - Tests constructing `TestClient(app)` directly or via custom fixtures (such as `test_phase3_identity_intake.py` and `test_csv_import_safety.py`) operate on clean isolated tables without unexpected seed collisions.
  - The shared `client` fixture calls `seed_data.init_db_and_seed()` for tests that specifically validate demo accounts, alerts, and credential verification (`test_api_endpoints.py`, `test_additional_features.py`).
- **Subprocess Environment Isolation:** Added explicit `PYTHONPATH` and `cwd` configuration to tests that spawn subprocesses (`test_config_security.py` and `test_phase1_security.py`), preventing `ModuleNotFoundError` when tests are run from repository root.

---

## 3. Files Modified & Preserved

| File | Status | Description of Changes |
| :--- | :--- | :--- |
| `backend/tests/conftest.py` | Modified | Preserved `app_db.get_db` function identity for FastAPI dependency overrides. Configured `client` fixture to seed demo records on demand while keeping `isolate_database_for_tests` clean and isolated for import tests. |
| `backend/tests/test_admission_categories.py` | Modified | Added 35 additional test parameterizations validating case variations, hyphenations, underscores, and space delimiters across all 9 admission categories (`Supernumerary-TFW`, `Foreign-National`, `General`, `SC`, `ST`, `OBC`, `EWS`, `NRI`, `OCI`). |
| `backend/tests/test_config_security.py` | Modified | Set `PYTHONPATH` and `cwd` to `backend/` in subprocess invocation to ensure tests reliably locate `app.config`. |
| `backend/tests/test_phase1_security.py` | Modified | Added `PYTHONPATH` and `cwd` to security startup subprocess check. |
| `backend/migrations/versions/20261027_01_phase3_identity_lifecycle.py` | Preserved | Preserved Phase 3 migration supporting nullable `apaar_id`, `identity_status` enum defaults, and indexes. |
| `backend/app/models/student.py` | Preserved | Preserved `identity_status` enum column and nullable `apaar_id`. |
| `backend/app/services/identity_service.py` | Preserved | Preserved identity lifecycle state machine, collision prevention, and transition audit logging. |
| `backend/app/admission_categories.py` | Preserved | Preserved case-insensitive and punctuation-agnostic category normalization. |
| `backend/PHASE3_IMPLEMENTATION_REPORT.md` | Created | Comprehensive implementation report detailing Phase 3 verification, root-cause findings, and test metrics. |

---

## 4. Phase 3 Features Completed & Verified

### A. Identity Status Lifecycle & Policy Exemptions
- **Identity Statuses:**
  - `APAAR_VERIFIED`: Standard domestic students with valid 12-digit APAAR IDs.
  - `HISTORICAL_NO_APAAR`: Pre-2024 academic cohorts permitted without APAAR ID.
  - `EXEMPT_WHERE_POLICY_PERMITS`: International / foreign national students admitted via passport.
  - `APAAR_PENDING`: In-flight registrations awaiting verification.
  - `IDENTITY_FLAGGED`: Blocked or contested identities requiring review.
- **Transition Safety:**
  - Validates permissible status transitions.
  - Rejects assignment of APAAR IDs already registered to another student (`VAL-APAAR-COLLISION`).
  - Records every status change in `audit_logs` with actor attribution, timestamp, and audit trail.

### B. Admission Category Normalization
- Accepts and normalizes inputs including:
  - `Foreign National`, `Foreign-National`, `Foreign_National`, `foreign-national`, `FOREIGN NATIONAL` -> canonical `Foreign-National`.
  - `Supernumerary TFW`, `Supernumerary-TFW`, `Supernumerary_TFW`, `supernumerary tfw` -> canonical `Supernumerary-TFW`.
  - Single-word categories: `General`, `SC`, `ST`, `OBC`, `EWS`, `NRI`, `OCI` (case-insensitive, whitespace-trimmed).

### C. Enrolment Conflicts & Intake Compliance API
- **Conflict Scoping:** `GET /api/v1/enrolments/conflicts` provides paginated conflict investigations filtered by conflict type.
- **Intake Compliance Findings:** `GET /api/v1/intake-compliance/findings` returns explainable findings with quota calculations, approved caps, and review recommendations.
- **Alembic Reversibility:** Forward migration to `20261027_01` applies cleanly and downgrades safely back to `20261026_01` on disposable databases.

---

## 5. Test Suite Verification Results

Full test suite execution command:
```bash
python -m pytest backend/tests -v
```

**Results:**
- **Total Tests Collected:** 177
- **Passed:** 177
- **Failed:** 0
- **Skipped:** 0
- **Execution Duration:** 8.02 seconds

### Breakdown by Test Module

| Test Module | Test Count | Status | Focus Area |
| :--- | :---: | :---: | :--- |
| `test_phase3_identity_intake.py` | 9 | PASSED | Phase 3 identity lifecycle, transitions, policy exemptions, Alembic upgrade/downgrade |
| `test_phase3_reports.py` | 3 | PASSED | Executive summary reports, data export, timestamp-based filtering |
| `test_phase2_csv_pipeline.py` | 23 | PASSED | CSV parsing, validation, dry-run preview, collision detection, rollback |
| `test_csv_import_safety.py` | 11 | PASSED | Duplicate prevention, repeat imports, correction linkage, payload limits |
| `test_admission_categories.py` | 64 | PASSED | Category classification, quota groups, space/hyphen/underscore/case variants |
| `test_phase1_security.py` | 10 | PASSED | Auth scope, token principals, RBAC, identifier masking, auditor permissions |
| `test_api_endpoints.py` | 5 | PASSED | Health, dashboard, students list/detail, alerts review, certificate verify |
| `test_additional_features.py` | 6 | PASSED | Foreign national route, version history, DPDP consent, anomaly dismissal |
| `test_alerts_review.py` | 1 | PASSED | Alert review decision persistence and audit logging |
| `test_anomaly_baseline.py` | 3 | PASSED | Anomaly detection, baseline metrics, outlier calculation |
| `test_certificates.py` | 1 | PASSED | HMAC-SHA256 tamper-evident verification |
| `test_config_security.py` | 2 | PASSED | Production secret requirements and safety locks |
| `test_cors_policy.py` | 2 | PASSED | CORS headers and origin restrictions |
| `test_dashboard_validation_metric.py` | 1 | PASSED | Validation pass rate aggregation |
| `test_exception_workflow.py` | 4 | PASSED | Reviewer workflow, reopening safeguards, status transitions |
| `test_import_history_migration.py` | 2 | PASSED | Import job schema and migration compatibility |
| `test_intake_compliance.py` | 5 | PASSED | Quota limits, sanction validation, excess calculation |
| `test_intake_compliance_phase2.py` | 21 | PASSED | Category quotas, rule configuration versioning, fail-closed handling |
| `test_integrity_engine.py` | 1 | PASSED | Temporal overlap and concurrency detection |
| `test_review_history_migration.py` | 1 | PASSED | Review history migration checks |
| `test_seed_data_safety.py` | 1 | PASSED | Seed idempotency without data duplication |
| `test_temporal_explorer_api.py` | 1 | PASSED | Temporal timeline API endpoints |
| **Total** | **177** | **100% PASS** | **All Phase 1, Phase 2, and Phase 3 suites green** |

---

## 6. Safety & Integrity Invariants

1. **Persistent Demo Database Safety:**
   - Pre-run SHA-256: `08953E20881B8E53A81AEA2B6E19BE69E35C7DD2FBE5B1599B71B0B176000141`
   - Post-run SHA-256: `08953E20881B8E53A81AEA2B6E19BE69E35C7DD2FBE5B1599B71B0B176000141`
   - Difference: **0 bytes changed** (100% byte-for-byte identical).
   - Read-only attribute on `backend/apaar_sentinel.db` remains active.
   - SQLAlchemy `before_cursor_execute` safety event listener actively blocks any attempt to touch demo database URLs.
2. **Relational Constraints:**
   - All SQLite connections execute `PRAGMA foreign_keys=ON;`.
3. **Frontend Preservation:**
   - `frontend/` directory was not modified.
4. **Targeted Scope:**
   - No Phase 4 features commenced; PostgreSQL migrations remain untouched.

---

## 7. Remaining Limitations & Next Steps

1. **Python 3.13 / Deprecation Warnings:**
   - Standard warnings exist regarding `datetime.datetime.utcnow()` deprecation in Python 3.13 (recommended migration to `datetime.datetime.now(datetime.UTC)` in a future phase).
   - FastAPI `TestClient` outputs deprecation notice regarding `httpx` vs `httpx2`.
2. **Environment Sandbox Considerations:**
   - When executing pytest on Windows machines inside isolated sandboxes that restrict loopback network binding, test runs must be invoked with network bypass (`BypassSandbox: true`) to avoid blocking on `asyncio.ProactorEventLoop._make_self_pipe`.
3. **Phase 4 Readiness:**
   - With identity lifecycle, CSV pipeline, policy exemptions, and intake compliance fully validated with 177 passing tests, the backend foundation is fully verified for Phase 4 (Advanced Analytics & Front-End Integration).
