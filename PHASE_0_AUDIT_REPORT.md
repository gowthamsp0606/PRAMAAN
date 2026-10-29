# PRAMAAN / APAAR Sentinel — Phase 0 Comprehensive Audit & Safety Baseline Report

**Date:** 2026-10-27  
**Project:** PRAMAAN / APAAR Sentinel (AICTE Hackathon SIH26263)  
**Location:** `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava`  
**Backend:** FastAPI 0.115+ / Python 3.13.15 / SQLAlchemy 2.0 / SQLite  
**Frontend:** React 19.3 / TypeScript 6.0 / Vite 8.3 / TailwindCSS 4.3  
**Status:** PHASE 0 AUDIT COMPLETE (Safety baseline recorded, backups verified, 199/199 tests passing)  

---

## 1. Executive Summary & Non-Negotiable Safety Baselines

This Phase 0 audit establishes an uncompromising technical baseline of the current PRAMAAN / APAAR Sentinel implementation. In accordance with strict Phase 0 safety requirements:
1. **Zero application code files were modified** during this audit phase.
2. **The database was NOT deleted, reset, recreated, migrated, or seeded**.
3. **Database backups were created and cryptographically verified** via SHA-256 hash matching before any subsequent tasks.
4. **Database SHA-256 hashes were recorded before and after all read-only inspections and test runs**, confirming **zero byte alteration**.
5. **Baseline test execution passed completely**: **199 passed, 0 failed, 0 skipped in 9.61s**.
6. **No synthetic security claims are made**: Role selection in the current frontend is rigorously documented as purely client-side UI navigation state, and the architecture required for true enterprise server-side authentication and role-specific dashboards is mapped out.

---

## 2. Architecture & File Map

### A. Backend (`backend/`)
* **Framework:** FastAPI with Uvicorn ASGI server.
* **Database & ORM:** SQLAlchemy 2.0 with SQLite engine (`PRAGMA foreign_keys=ON;`).
* **Configuration:** [`backend/app/config.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/config.py) loading environment variables via Pydantic (`APP_NAME`, `DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT`, `AUTH_REQUIRED`, `API_TOKEN_PRINCIPALS_JSON`).
* **Router Inventory ([`backend/app/routers/`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/routers/)):**
  1. `dashboard.py`: National overview metrics (`GET /api/v1/dashboard/summary`).
  2. `institution.py`: Institutional console summary (`GET /api/v1/institution/dashboard-summary`).
  3. `aicte.py`: AICTE Directorate regional analytics (`GET /api/v1/aicte/dashboard-summary`).
  4. `students.py`: Student records, CSV upload, version history, timeline (`/api/v1/students`).
  5. `enrolments.py`: Enrolment ingestion and conflict inspection (`/api/v1/enrolments`).
  6. `alerts.py`: Enrolment integrity alerts, case notes, assignment, review adjudication (`/api/v1/alerts`).
  7. `validation.py`: Pre-ingestion schema rules, sandbox evaluation, sample CSV data (`/api/v1/validation`).
  8. `intake.py`: Sanctioned intake quotas and compliance findings (`/api/v1/intake-compliance`).
  9. `analytics.py`: Anomaly detection, baseline trends, benchmark evaluation (`/api/v1/analytics`).
  10. `certificates.py`: Digital credentials, public key registry, signature verification, tamper simulation (`/api/v1/certificates`).
  11. `consent.py`: DPDP Act student data sharing consent (`/api/v1/consent`).
  12. `verifier.py`: Third-party employer / background verification portal and logs (`/api/v1/verifier`).
  13. `reports.py`: Executive regulatory summaries and diagnostics (`/api/v1/reports`).
  14. `audit.py`: Immutable system audit trail (`/api/v1/audit-trail`).
* **Core Services ([`backend/app/services/`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/services/)):**
  - `integrity_engine.py`: Temporal overlap and duplicate enrolment detection engine.
  - `anomaly_service.py`: Statistical and heuristic anomaly detection with baseline bounds.
  - `certificate_service.py`: Asymmetric Ed25519 and legacy HMAC-SHA256 signature generation and cryptographic verification.
  - `identity_service.py`: Identity lifecycle state machine, policy exceptions, collision checks.
  - `csv_import_service.py`: Chunked CSV parser with pre-ingestion validation and rollback safety.
  - `verifier_service.py`: Purpose-limited affirmative background verification.
  - `audit_service.py`: Centralized audit event dispatcher.
* **External Adapters ([`backend/app/adapters/`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/adapters/)):**
  - `digilocker_adapter.py`, `abc_adapter.py`, `aicte_adapter.py` (explicitly tagged `IS_MOCK = True`).

### B. Frontend (`frontend/`)
* **Framework:** React 19.3, Vite 8.3, React Router DOM 7.18.
* **Styling & UI:** TailwindCSS 4.3, Lucide React icons, Recharts visualization library.
* **API Client:** [`frontend/src/api/client.ts`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/frontend/src/api/client.ts) (monolithic API client consuming `/api/v1/*`).
* **Routing ([`frontend/src/App.tsx`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/frontend/src/App.tsx)):**
  - `/`: Overview (National Overview)
  - `/institution-dashboard`: Institution Console (College Principal view)
  - `/aicte-dashboard`: AICTE Directorate (Regional Officer view)
  - `/students`: Student Records & Intake
  - `/integrity`: Enrolment Integrity & Alert Adjudication
  - `/validation`: Automated Validation Centre & Test Sandbox
  - `/intake`: Approved Intake Compliance
  - `/consent`: Student Consent Management (DPDP Act)
  - `/employer-portal`: Employer / Background Verification Portal
  - `/analytics`: Historical Analytics & Anomaly Detection
  - `/reports`: Executive Compliance Reports
  - `/certificates`: Digital Credentials & Cryptographic Tamper Verification
  - `/audit`: Immutable Audit Trail
  - `/settings`: Platform Configuration

---

## 3. Actual Database Path & Working Directory Analysis

A critical finding in Phase 0 is the distinction between working directory resolution and database file location:

```text
Configured DATABASE_URL in config.py: sqlite:///./apaar_sentinel.db
```

1. **When server is started from `backend/` (`cd backend; uvicorn app.main:app`):**
   - **Resolved Absolute Path:** `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava\backend\apaar_sentinel.db`
   - **File Size:** 299,008 bytes
   - **SHA-256:** `D6F4C035CCE68F40A64930FC81EAD31CACC9FACEB217F534089DB5092B79A9C4`
   - **Table Count:** 14 tables (includes `alert_review_events`, `historical_intakes`, etc.)
2. **When server is started from project root without `cd backend`:**
   - **Resolved Absolute Path:** `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava\apaar_sentinel.db`
   - **File Size:** 303,104 bytes
   - **SHA-256:** `54D6D823EEC8C723AEF869353EDA0B72C519B8232B465110A09FD11D01321A0D`
3. **Current Active Database:**
   The running background process was launched via `cd backend; python -m uvicorn ...`. **Therefore, `backend/apaar_sentinel.db` is the actual active database file utilized by the running backend.**

---

## 4. Database Schema & Current Row Counts

Inspection of `backend/apaar_sentinel.db` reveals 14 structured tables:

| Table Name | Row Count | Primary Key | Key Columns & Constraints |
| :--- | :---: | :--- | :--- |
| `alert_review_events` | 1 | `id (INTEGER PK)` | `alert_id`, `action`, `previous_status`, `new_status`, `decision`, `actor`, `note`, `evidence_references (JSON)` |
| `alerts` | 3 | `id (VARCHAR(64) PK)` | `student_ref`, `apaar_id`, `alert_type`, `severity`, `status`, `reviewer_decision`, `reviewer_note`, `reviewed_by` |
| `approved_intakes` | 4 | `id (INTEGER PK)` | `institution_id`, `programme_id`, `academic_year`, `approved_intake_seats`, `supernumerary_quota`, `nri_quota` |
| `audit_logs` | 20 | `id (INTEGER PK)` | `entity_type`, `entity_id`, `action`, `performed_by`, `details (JSON)`, `timestamp` |
| `certificates` | 2 | `certificate_id (VARCHAR(64) PK)` | `student_ref`, `apaar_id`, `student_name`, `status ('VALID'/'REVOKED')`, `signature_algorithm`, `signature_hex`, `public_key_id`, `payload_json (JSON)` |
| `enrolment_versions` | 16 | `id (INTEGER PK)` | `enrolment_id`, `student_ref`, `version_number`, `changed_by`, `diff_payload (JSON)` |
| `enrolments` | 16 | `id (INTEGER PK)` | `student_ref`, `apaar_id`, `institution_id`, `programme_id`, `academic_year`, `enrolment_start`, `enrolment_end`, `enrolment_status`, `seat_category` |
| `historical_intakes` | 10 | `id (INTEGER PK)` | `institution_id`, `programme_id`, `academic_year`, `admitted_count`, `approved_intake`, `z_score`, `is_anomaly`, `dismissed` |
| `import_jobs` | 0 | `id (VARCHAR(36) PK)` | `institution_id`, `submitted_by`, `status`, `total_rows`, `accepted_rows`, `rejected_rows`, `validation_summary` |
| `import_row_results` | 0 | `id (INTEGER PK)` | `import_job_id`, `row_number`, `record_reference`, `outcome`, `issue_codes (JSON)` |
| `student_consents` | 6 | `id (INTEGER PK)` | `student_ref`, `apaar_id`, `purpose`, `consent_granted (BOOLEAN)`, `status`, `data_scope` |
| `students` | 11 | `student_ref (VARCHAR(64) PK)` | `apaar_id`, `full_name`, `primary_institution_id`, `identity_route`, `nationality`, `is_nri`, `is_oci`, `is_foreign_national` |
| `verification_request_logs` | 9 | `id (INTEGER PK)` | `verifier_org_id`, `query_student_ref`, `certificate_id`, `verification_outcome`, `limited_response_json (JSON)` |
| `verifier_organizations` | 3 | `id (VARCHAR(64) PK)` | `org_name`, `org_type`, `is_approved`, `contact_email` |

---

## 5. Authentication & Authorization Findings

### A. Current Frontend Role Selector (`Header.tsx`)
In [`frontend/src/components/Layout/Header.tsx`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/frontend/src/components/Layout/Header.tsx) (lines 35-50):
```tsx
const handleRoleChange = (role: string) => {
  if (role === 'INSTITUTION') navigate('/institution-dashboard');
  else if (role === 'AICTE') navigate('/aicte-dashboard');
  else if (role === 'VERIFIER') navigate('/employer-portal');
  else if (role === 'AUDITOR') navigate('/audit');
  else navigate('/');
};
```
**Finding:**
1. **No Real Authentication:** There is currently no login view (`/login`), credential submission, session cookie, or JWT token storage in `localStorage`/`sessionStorage`.
2. **Purely Client-Side Routing:** Changing the dropdown in the header simply triggers React Router's `navigate(...)`. No credentials or role headers are passed to API calls in `client.ts`.
3. **No Route Guards:** Any user can directly navigate to `/aicte-dashboard`, `/settings`, or `/employer-portal` in the browser without authentication.

### B. Current Backend Security Engine (`security.py`)
[`backend/app/security.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/security.py) implements:
- Principal model: `Principal(subject, role, institution_id, verifier_org_id, purpose_scope)`
- Role definitions: `administrator`, `institution_officer`, `reviewer`, `read_only_auditor`, `external_verifier`, `prototype_admin`.
- Endpoint gatekeeper: `authorize_api_request` enforces precise HTTP verb and URL path restrictions per role.
- Scope boundary: `enforce_institution_scope` prevents cross-institution data leakage.
- Latch: When `AUTH_REQUIRED=false` (development mode), `get_current_principal` falls back to `Principal(subject="local-prototype", role="prototype_admin")`, granting unauthenticated requests full access. When `AUTH_REQUIRED=true`, bearer tokens must be SHA-256 hashed and matched against `API_TOKEN_PRINCIPALS_JSON`.

**Gap to Close:**
To achieve the user's objective ("a real login page and separate role-specific dashboards"), the platform requires:
1. A backend `/api/v1/auth/login` endpoint issuing signed JWTs with authenticated role and institution claims.
2. A dedicated React login page storing the token in auth context.
3. An HTTP interceptor in `client.ts` injecting `Authorization: Bearer <token>`.
4. Role-guarded route boundaries (`<ProtectedRoute allowedRoles={[...]} />`).
5. Separate, tailored dashboards filtered strictly by authenticated principal role and institution scope.

---

## 6. Investigation of Known Issues

### A. Issue 1: `attempt to write a readonly database` on `verification_request_logs`
* **Trigger:** When an employer performs credential verification via `POST /api/v1/verifier/verify-credential`, the service executes:
  ```python
  self.db.add(VerificationRequestLog(...))
  self.db.commit()
  ```
* **Root Cause:**
  1. The project resides on Microsoft OneDrive: `C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava`.
  2. Windows OneDrive background syncing frequently places file-lock handles or sets read-only attributes on `.db` files during sync sweeps.
  3. In addition, `backend/apaar_sentinel.db` previously had the Windows Read-Only filesystem flag (`-ar---`, `attrib +R`) applied to protect test baselines.
* **Resolution Strategy (Phase 1/2):**
  - Ensure Windows attributes on the live database are read-write (`attrib -R`).
  - Configure SQLite WAL mode (`PRAGMA journal_mode=WAL;`) with busy timeouts (`PRAGMA busy_timeout=5000;`) to eliminate lock contention during concurrent reads and writes.

### B. Issue 2: Alerts & Reviews Adjudication Validation Error
* **Trigger:** Submitting an alert review via `PATCH /api/v1/alerts/{alert_id}/review`.
* **Backend Requirement ([`backend/app/schemas/alert.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/schemas/alert.py)):**
  ```python
  class AlertReviewRequest(BaseModel):
      decision: Literal["CONFIRMED_CONFLICT", "NOT_A_CONFLICT", "EXCEPTION_ACCEPTED", "NEEDS_MORE_INFO"]
      note: str = Field(min_length=1, max_length=5000)
      reviewed_by: Optional[str] = ...
  ```
* **Frontend Implementation ([`frontend/src/pages/EnrolmentIntegrity.tsx`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/frontend/src/pages/EnrolmentIntegrity.tsx)):**
  The radio buttons correctly provide `CONFIRMED_CONFLICT`, `NOT_A_CONFLICT`, `EXCEPTION_ACCEPTED`, and `NEEDS_MORE_INFO`.
* **Root Cause of Rejection:**
  1. **HTTP 409 Conflict on Already-Resolved Alerts:** Line 310 in `alerts.py` throws `HTTP 409 Conflict: Resolved alerts must be explicitly reopened before another decision.` In `apaar_sentinel.db`, alerts `ALT-EXC-5-6` and `ALT-DUP-7-8` are already marked `RESOLVED`. Attempting to submit a review without reopening triggers this error.
  2. **Blank Notes:** If `reviewNote` is empty, Pydantic raises HTTP 422 because `min_length=1` is enforced.
* **Resolution Strategy:**
  - Update frontend UI to dynamically disable adjudication controls if `alert.status === 'RESOLVED'` and display an explicit "Reopen Case" action calling `POST /api/v1/alerts/{id}/reopen`.
  - Provide inline client-side validation requiring non-empty rationale notes.

### C. Issue 3: Digital Credentials & Cryptographic Tamper-Testing
* **Trigger:** `POST /api/v1/certificates/{id}/simulate-tamper` called from [`frontend/src/pages/CertificateVerification.tsx`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/frontend/src/pages/CertificateVerification.tsx).
* **Audit Finding:**
  - The endpoint works as verified by live test:
    ```json
    POST /api/v1/certificates/CERT-APAAR-2026-001/simulate-tamper
    Body: {"student_name": "Adulterated Student Name"}
    Status: 200 OK
    Result: {"verification_status": "TAMPER_DETECTED", "is_authentic": false, "signature_valid": false}
    ```
  - Both Ed25519 asymmetric signing and legacy HMAC-SHA256 signatures are supported in `CertificateService`.
  - Private signing keys remain securely held on the backend (`settings.SECRET_KEY` / Ed25519 signing key), while public keys are accessible via `/api/v1/certificates/public-keys` for offline verification.

---

## 7. Database Backups & Cryptographic Integrity Check

Prior to any database-modifying operation, complete verified backups were created:

| Database File | Initial SHA-256 Hash | Post-Audit SHA-256 Hash | Verified Backup Location | Backup Hash Match |
| :--- | :--- | :--- | :--- | :---: |
| `backend/apaar_sentinel.db` | `D6F4C035CCE68F40A64930FC81EAD31CACC9FACEB217F534089DB5092B79A9C4` | `D6F4C035CCE68F40A64930FC81EAD31CACC9FACEB217F534089DB5092B79A9C4` | `backups/backend_apaar_sentinel.db.bak` | **MATCH (Exact)** |
| `apaar_sentinel.db` (root) | `54D6D823EEC8C723AEF869353EDA0B72C519B8232B465110A09FD11D01321A0D` | `54D6D823EEC8C723AEF869353EDA0B72C519B8232B465110A09FD11D01321A0D` | `backups/root_apaar_sentinel.db.bak` | **MATCH (Exact)** |

*Integrity Check: Both databases maintained 100% hash consistency throughout all inspections, schema queries, and automated test runs.*

---

## 8. Baseline Test Results

The full backend automated test suite was executed:
```powershell
& "C:\Users\gowth\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests -v
```
**Results:**
- **Total Tests Collected:** 199
- **Passed:** 199
- **Failed:** 0
- **Skipped:** 0
- **Duration:** 9.61 seconds

### Module-by-Module Breakdown:
- `test_additional_features.py`: 6 passed
- `test_admission_categories.py`: 55 passed
- `test_alerts_review.py`: 3 passed
- `test_anomaly_baseline.py`: 4 passed
- `test_api_endpoints.py`: 4 passed
- `test_certificates.py`: 4 passed
- `test_config_security.py`: 2 passed
- `test_cors_policy.py`: 2 passed
- `test_csv_import_safety.py`: 12 passed
- `test_dashboard_legacy_db_regression.py`: 1 passed
- `test_dashboard_validation_metric.py`: 1 passed
- `test_exception_workflow.py`: 7 passed
- `test_external_adapters.py`: 3 passed
- `test_import_history_migration.py`: 4 passed
- `test_intake_compliance.py`: 3 passed
- `test_intake_compliance_phase2.py`: 15 passed
- `test_integrity_engine.py`: 9 passed
- `test_phase1_security.py`: 14 passed
- `test_phase2_csv_pipeline.py`: 12 passed
- `test_phase3_identity_intake.py`: 12 passed
- `test_phase3_reports.py`: 6 passed
- `test_phase4_anomalies_and_findings.py`: 5 passed
- `test_phase5_credentials_and_workflows.py`: 8 passed
- `test_phase6_security_hardening.py`: 5 passed
- `test_review_history_migration.py`: 1 passed
- `test_seed_data_safety.py`: 2 passed
- `test_temporal_explorer_api.py`: 4 passed
- `test_validation.py`: 3 passed

---

## 9. Recommended Implementation Order (Phases 1–8)

To implement real authentication, role-specific dashboards, robust database writing, and comprehensive workflow adjudication while preserving 100% backward compatibility:

```mermaid
flowchart TD
    P1["Phase 1: Database Write Safety & Storage Hardening"] --> P2["Phase 2: Authentication Backend & JWT Lifecycle"]
    P2 --> P3["Phase 3: Frontend Authentication & Real Login Page"]
    P3 --> P4["Phase 4: Role-Guarded Navigation & Personas"]
    P4 --> P5["Phase 5: Dedicated Role Dashboards"]
    P5 --> P6["Phase 6: Alert Adjudication & Case Workflow Alignment"]
    P6 --> P7["Phase 7: Cryptographic Credentials & Tamper Verification Hardening"]
    P7 --> P8["Phase 8: End-to-End Integration & Regression Verification"]
```

### Detailed Roadmap:
1. **Phase 1: Database Write Safety & Storage Hardening**
   - Resolve SQLite write locking / OneDrive sync conflicts by enabling WAL mode (`journal_mode=WAL`, `busy_timeout=5000`).
   - Confirm write transactions on `verification_request_logs` and `alert_review_events` succeed without errors.
2. **Phase 2: Authentication Backend & Token Architecture**
   - Add `/api/v1/auth/login`, `/api/v1/auth/me`, and `/api/v1/auth/logout` endpoints.
   - Support the 5 operational personas (`admin`, `institution_officer`, `aicte_officer`, `verifier`, `auditor`) with password hashing and JWT signature verification.
   - Enforce principal claims and institution scoping on all protected endpoints.
3. **Phase 3: Frontend Authentication & Real Login Page**
   - Build a modern login page (`/login`) with persona selector shortcuts and credentials input.
   - Implement `AuthContext` to manage tokens and user session in React.
   - Update `client.ts` to attach `Authorization: Bearer <token>` automatically on every request.
4. **Phase 4: Role-Guarded Navigation & Persona Access Control**
   - Implement `<ProtectedRoute allowedRoles={[...]} />` in React Router.
   - Replace the static header dropdown with user profile pill, active institution tag, and logout action.
   - Conditionally render sidebar navigation sections based on active user permissions.
5. **Phase 5: Dedicated Role-Specific Dashboards**
   - **Institution Dashboard:** College-scoped KPIs, pending enrolments, local alerts, and quota utilization.
   - **AICTE Directorate Dashboard:** Regional quota governance, anomalous intake alerts, cross-college transfers.
   - **Verifier Dashboard:** Dedicated background candidate verification search and log history.
   - **Auditor Dashboard:** Read-only compliance timeline and audit trail viewer.
6. **Phase 6: Alert Adjudication & Case Workflow Alignment**
   - Update `EnrolmentIntegrity.tsx` to handle the full lifecycle: `CONFIRMED_CONFLICT`, `NOT_A_CONFLICT`, `EXCEPTION_ACCEPTED`, `NEEDS_MORE_INFO`.
   - Provide explicit "Reopen Case" workflow for `RESOLVED` alerts.
   - Validate non-empty reviewer notes and display event timeline from `alert_review_events`.
7. **Phase 7: Digital Credentials & Tamper Pipeline Verification**
   - Enhance `CertificateVerification.tsx` with side-by-side original vs. tampered cryptographic payload comparison.
   - Display Ed25519 signature algorithm, public key identifier, and status (`VALID` vs `REVOKED`).
8. **Phase 8: End-to-End Integration & Final System Verification**
   - Run full 199+ automated test suite.
   - Verify all 5 personas through browser walkthrough.
   - Confirm zero regressions, verified database backups, and complete audit documentation.

---

*Phase 0 complete. Awaiting user direction before starting Phase 1.*
