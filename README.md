# APAAR Sentinel Backend

FastAPI prototype for student enrolment integrity, CSV ingestion, anomaly review, consent-aware verifier workflows, certificate checks, and audit history. The existing SQLite database is retained; application startup only calls SQLAlchemy `create_all` for missing tables and does not migrate or reset existing tables.

## Setup and Run

Requirements: Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ENVIRONMENT = "development"
$env:DATABASE_URL = "sqlite:///./apaar_sentinel.db"
$env:ALLOW_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
uvicorn app.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. OpenAPI is at `/docs`, ReDoc at `/redoc`, and process health at `/health`. The default database URL is `sqlite:///./apaar_sentinel.db`; set `DATABASE_URL` to use another SQLAlchemy-supported database.

Configuration is read from process environment variables; `.env.example` documents the supported names, but this app does not load `.env` files automatically. Export values in the shell or use an approved deployment environment loader. `ENVIRONMENT=production` is intentionally rejected until API authentication and authorization are implemented. The production guard also requires a non-default `SECRET_KEY` of at least 32 characters. Set `ALLOW_ORIGINS` to the exact comma-separated frontend origins; development defaults permit only localhost ports used by Vite.

Phase 1 API authentication is opt-in for local compatibility. With `AUTH_REQUIRED=true`, all `/api/v1` routes require `Authorization: Bearer <token>`; `/health` remains public. Configure `API_TOKEN_PRINCIPALS_JSON` as a JSON object whose keys are SHA-256 hex digests of bearer tokens and whose values contain `subject`, `role`, and optional `institution_id` or `verifier_org_id`. External-verifier principals must also have `purpose_scope: "EMPLOYMENT_VERIFICATION"`. Supported roles are `administrator`, `institution_officer`, `reviewer`, `read_only_auditor`, and `external_verifier`. Generate the digest out of band with `python -c "import hashlib; print(hashlib.sha256(b'<token>').hexdigest())"`; do not put raw bearer tokens in source control or `VITE_` frontend variables. When `AUTH_REQUIRED=false`, unauthenticated calls receive a privileged `prototype_admin` principal for local compatibility, so this mode is not suitable for untrusted environments. Token issuance/expiry/rotation and rate limiting are not implemented. Production mode remains blocked.

## API Contract

All `/api/v1` routes require a configured bearer principal when `AUTH_REQUIRED=true`; `/health` remains public. When `AUTH_REQUIRED=false`, unauthenticated requests receive a privileged `prototype_admin` compatibility principal. This mode is for trusted local development only. The current React frontend has no login or secure token transport, so it cannot call the API when authentication is required; do not embed a token in frontend source or a `VITE_` variable.

| Method | Route | Request | Response / behavior |
| --- | --- | --- | --- |
| GET | `/health` | None | Process status, service name, version, and `environment=prototype`. Does not check database health. |
| GET | `/api/v1/dashboard/summary` | Optional `institution_id`, `academic_year` query parameters | Student/institution counts, open alerts, review count, enrolment validation pass rate, severity counts, trends, recent audit events, configured intake summaries. |
| GET | `/api/v1/students` | Optional `search`, `institution_id`, `programme_id`, `academic_year`, `enrolment_status`, `page` (default 1), `limit` (1–100, default 50) | `{items,total,page,limit,total_pages}`. Non-admin principals receive a masked APAAR ID; institution officers are scoped to their assigned institution. |
| GET | `/api/v1/students/{student_ref}` | Student reference | Student data, ordered enrolments, stored/recomputed integrity status, alerts, and version history. Non-admin roles receive masked APAAR ID and no passport reference; institution officers receive only institution-scoped enrolments/alerts/versions. Authenticated reads do not recompute integrity. |
| GET | `/api/v1/students/{student_ref}/versions` | Student reference | Version entries and diff payloads. |
| GET | `/api/v1/students/{student_ref}/timeline` | Student reference | Ordered enrolment fields, status recognition checks, and pairwise temporal analysis including dates, statuses, institutions/programmes, overlap result, rule ID/version, explanation, and recommended action. Does not include APAAR ID. |
| POST | `/api/v1/students` | JSON student/enrolment fields; requires `student_ref`, `apaar_id`, `full_name`, and enrolment fields consumed by the route | `success`, `student_ref`, `enrolment_id`, integrity status, and alert count. Validation failures may return HTTP 200 with `success=false`; this legacy behavior is retained. |
| POST | `/api/v1/students/upload-csv` | `multipart/form-data`, field name `file`; `.csv`, maximum 10 MiB and 10,000 data rows | Partial import. Returns filename, total/accepted/rejected counts, pass rate, severity counts, up to 50 field errors, and message. Duplicate student/institution/programme/start-date tuples are rejected; existing matching enrolments are not inserted again. |
| GET | `/api/v1/enrolments` | Optional student/institution/programme/status/year; `page` and `limit` (1–100) | Paginated enrolment records. Response currently includes APAAR ID. |
| POST | `/api/v1/enrolments` | `EnrolmentCreate` JSON schema | Creates an enrolment, then evaluates student integrity; returns `EnrolmentResponse`. |
| GET | `/api/v1/alerts` | Optional `status`, `severity`, `alert_type`, `student_ref` | `{total,items}` with explanation, evidence, supporting IDs, and reviewer fields. |
| GET | `/api/v1/alerts/{alert_id}` | Alert ID | Alert, supporting enrolments, and student timeline. |
| PATCH | `/api/v1/alerts/{alert_id}/review` | JSON `{decision,note,reviewed_by?,resolution_reason?,evidence_references?}`; decisions: `CONFIRMED_CONFLICT`, `NOT_A_CONFLICT`, `EXCEPTION_ACCEPTED`, `NEEDS_MORE_INFO` | Saves the latest decision and an append-only review event plus audit event in one transaction. Resolved alerts return 409 until explicitly reopened. With auth required, actor identity comes from the principal; caller `reviewed_by` is honored only in prototype compatibility mode. |
| GET | `/api/v1/alerts/{alert_id}/history` | Alert ID | `{alert_id,assigned_to,events}`. Events preserve action, previous/new status, decision, actor, assignment, notes, resolution reason, evidence references, and timestamp. |
| PATCH | `/api/v1/alerts/{alert_id}/assignment` | JSON `{assigned_to,actor?}`; `assigned_to: null` unassigns | Returns `{success,alert_id,assigned_to,event_id}` and appends an assignment event and audit event transactionally. Authenticated actor is principal-bound. |
| POST | `/api/v1/alerts/{alert_id}/clarification` | JSON `{note,actor?,evidence_references?}` | Moves an eligible case to `AWAITING_CLARIFICATION`; returns `{success,alert_id,status,event_id}`. Authenticated actor is principal-bound. |
| POST | `/api/v1/alerts/{alert_id}/notes` | JSON `{note,actor?,evidence_references?}` | Appends a reviewer note/evidence-reference event without changing case status. Authenticated actor is principal-bound. |
| POST | `/api/v1/alerts/{alert_id}/reopen` | JSON `{reason,actor?}` | Reopens only a `RESOLVED` alert into `UNDER_REVIEW`; returns 409 otherwise. The reason is recorded in review history and audit metadata. Authenticated actor is principal-bound. |
| POST | `/api/v1/alerts/re-evaluate` | None | Re-evaluates all student histories; returns evaluated student count. |
| GET | `/api/v1/validation/rules` | None | Configured validation rules. |
| POST | `/api/v1/validation/test-record` | JSON record dictionary | `{is_valid,errors,error_count,status}`. |
| GET | `/api/v1/validation/sample-csv-data` | None | Student CSV headers and fictional example rows. |
| GET | `/api/v1/validation/export-errors-csv` | None | Downloads validation-rule reference CSV (not an import-specific error report). |
| GET | `/api/v1/analytics/enrolment-trends` | None | Enrolment counts by academic year and status. |
| GET | `/api/v1/analytics/anomalies` | None | Flagged historical-intake records, counts, z-score, explanation, and dismissal state. |
| GET | `/api/v1/analytics/historical/{institution_id}/{programme_id}` | Institution and programme IDs | Year-by-year counts plus baseline values, mean, standard deviation, range, sample size, latest deviation, method, and explanation. A flagged latest row is excluded from its own baseline. |
| PATCH | `/api/v1/analytics/anomalies/{anomaly_id}/dismiss` | JSON `{reason?,dismissed_by?}` | Persists reviewer dismissal and audit event. Actor is not authenticated. |
| GET | `/api/v1/analytics/benchmark-evaluation` | None | Metrics against the stored synthetic `ground_truth` labels; these are not real-world performance claims. |
| GET | `/api/v1/intake-compliance` | None | Reports for configured intake rules. |
| GET | `/api/v1/intake-compliance/{institution_id}/{programme_id}` | Optional `academic_year`, `admission_cycle` | One programme intake evaluation. Cycle is never substituted; omitted cycle is allowed only when the matching active rule is unique. |
| GET | `/api/v1/intake-compliance/{institution_id}/{programme_id}/rule-history` | Required `academic_year`, optional `admission_cycle` | Returns prior/current rule rows, cycle, limits, source, rule ID/version and effective date. |
| POST | `/api/v1/intake-compliance/rules` | Typed JSON with institution/programme/year/cycle, approved count, optional explicit category quotas, `rule_id`, `rule_source`, `effective_date`, and `rule_configured` | Appends a rule version and retains old values; when a configured revision is activated, earlier configured rows for that exact scope are marked inactive. Unconfigured drafts do not deactivate the active rule. No quota/source/date defaults are fabricated. |
| GET | `/api/v1/certificates` | None | Certificate list. APAAR ID is masked for non-admin principals; institution officers are restricted to assigned-institution certificates. |
| GET | `/api/v1/certificates/{certificate_id}` | Certificate ID | Certificate payload and prototype disclaimer. Non-admin principals receive masked APAAR ID and no raw signature hex. |
| GET | `/api/v1/certificates/{certificate_id}/verify` | Certificate ID | HMAC payload-integrity result and audit event. Non-admin principals receive masked APAAR ID and no raw signature hex. HMAC is a shared-secret demo mechanism, not a publicly verifiable asymmetric signature and not proof of APAAR identity. |
| POST | `/api/v1/certificates/{certificate_id}/simulate-tamper` | JSON payload fields to alter | Demonstration-only tamper check. Do not expose as a production operation. |
| GET | `/api/v1/audit-trail` | Optional `entity_type`, `action`, `limit` (1–200, default 50) | `{total,items}`. Audit details may contain sensitive references and need authenticated access controls. |
| GET | `/api/v1/consent/student/{student_ref}` | Student reference | Student name and consent records; APAAR ID is masked for non-admin principals. |
| POST | `/api/v1/consent` | JSON `student_ref`, optional `purpose`, `consent_granted`, `data_scope` | Admin-only when authentication is enabled. Consent provenance/signature is not verified. |
| PATCH | `/api/v1/consent/{consent_id}/toggle` | JSON optional `consent_granted` | Admin-only when authentication is enabled; writes an audit event with the existing fixed actor label. |
| GET | `/api/v1/verifier/organizations` | None | Verifier organizations. |
| POST | `/api/v1/verifier/verify-credential` | JSON `verifier_org_id`, and one of `student_ref`, `apaar_id`, `certificate_id` | Consent- and organization-aware prototype verification result. With auth enabled, the verifier organization comes from the token and a conflicting body ID is rejected; the body ID remains for local prototype compatibility. |
| GET | `/api/v1/verifier/logs` | Optional `verifier_org_id`, `limit` (1–200) | Admins may filter all logs; external verifiers are restricted to the organization bound to their token. APAAR query values are omitted for external verifiers. |
| GET | `/api/v1/institution/dashboard-summary` | Optional `institution_id`, optional `academic_year` | Institution-level counts, intake summaries, alerts, and consent coverage. Institution officers are bound to the token institution; other authorized roles may select the requested institution. |
| GET | `/api/v1/aicte/dashboard-summary` | Optional `region` | Aggregate oversight data. Region is currently a display filter, not an access boundary. |
| GET | `/api/v1/reports/executive-summary` | None | Executive report aggregates. |

FastAPI returns input validation errors as HTTP 422 and route-specific errors use `{ "detail": "..." }`. CSV parsing and size errors use 400/413. Some legacy validation outcomes use HTTP 200 with an application-level `success` flag; clients must inspect the response body.

### Review Workflow Example

```http
PATCH /api/v1/alerts/ALT-OVL-12/assignment
Content-Type: application/json

{"assigned_to":"Reviewer 17","actor":"Supervisor 2"}
```

```json
{"success":true,"alert_id":"ALT-OVL-12","assigned_to":"Reviewer 17","event_id":1}
```

```http
POST /api/v1/alerts/ALT-OVL-12/clarification
Content-Type: application/json

{"note":"Please provide the transfer letter.","actor":"Reviewer 17","evidence_references":["DOC-REF-77"]}
```

```json
{"success":true,"alert_id":"ALT-OVL-12","status":"AWAITING_CLARIFICATION","event_id":2}
```

`PATCH /api/v1/alerts/{alert_id}/review` preserves the prior request fields and accepts optional `resolution_reason` and `evidence_references`. A resolved alert cannot receive another decision until `POST /api/v1/alerts/{alert_id}/reopen` records a non-empty reason. Review history is available from both the alert detail response and `GET /api/v1/alerts/{alert_id}/history`.

Allowed status transitions are `OPEN -> UNDER_REVIEW | AWAITING_CLARIFICATION | ESCALATED | RESOLVED`, `UNDER_REVIEW -> OPEN | AWAITING_CLARIFICATION | ESCALATED | RESOLVED`, `AWAITING_CLARIFICATION -> UNDER_REVIEW | ESCALATED | RESOLVED`, and `ESCALATED -> UNDER_REVIEW | AWAITING_CLARIFICATION | RESOLVED`. `RESOLVED` can only move to `UNDER_REVIEW` through the explicit reopen endpoint. `NEEDS_MORE_INFO` on the review endpoint retains the legacy `UNDER_REVIEW` mapping; the clarification endpoint sets `AWAITING_CLARIFICATION`.

## CSV Import

The existing uploader accepts student-level CSV only. Required columns are `student_ref`, `apaar_id`, `institution_id`, `programme_id`, `academic_year`, `admission_cycle`, `enrolment_start`, and `enrolment_status`. The sample header endpoint includes optional descriptive, seat-category, provenance, and version columns. Valid rows are committed as a partial-success batch; invalid/duplicate rows are skipped. The current import does not support institution-level aggregate CSVs. Row-level response errors are limited to the first 50 issues, while all row outcomes are stored in import history.

The browser/API UI can download a starter file from `/api/v1/validation/sample-csv-data`. Re-importing an identical student/institution/programme/start-date tuple no longer creates a second enrolment. A correction request may include `previous_job_id`; matching uses an HMAC-derived key for `(student_ref, institution_id, programme_id)`, not row number or raw APAAR ID. A unique prior row is linked. Multiple prior matches, or a prior accepted match, are marked `NEEDS_REVIEW` and are not silently overwritten or duplicated. Institution/programme changes are not auto-linked and require manual review.

Historical standard deviation currently uses the population formula (variance divided by the number of baseline observations). When the newest historical record is marked anomalous and earlier observations exist, that newest value is excluded from its comparison baseline. The returned sample size and raw baseline values make that choice inspectable; small historical samples remain weak evidence.

Admission categories are exact normalized values: `General`, `SC`, `ST`, `OBC`, `EWS`, `NRI`, `OCI`, `Foreign-National`, and `Supernumerary-TFW`. Regular categories are compared to approved intake; NRI and `Supernumerary-TFW` limits are compared independently when explicitly configured and are never summed. OCI/Foreign-National admissions return `NEEDS_REVIEW` because the current rule schema has no applicable limits for them. Duplicate student rows count once and trigger review; conflicting categories for one student also trigger review. `rule_configured=false`, missing/ambiguous active cycles, invalid dates, future effective dates, unsupported stored categories, or missing relevant category limits do not produce a compliance conclusion.

Approved-intake versions are appended in the existing table; prior seat/source/effective-date values remain queryable. The schema has no expiry date, so results explicitly return `rule_expiration_status=NOT_TRACKED_IN_CURRENT_SCHEMA`. An operator must deactivate a rule that is no longer applicable; the service does not infer regulatory expiry. No official quota values are supplied by the application.

## Tests and Test Database Isolation (Phase 2)

Automated tests run strictly against isolated, temporary SQLite databases. Access to the persistent demo database (`apaar_sentinel.db`) is blocked at the SQLAlchemy engine level via an event listener that aborts any automated test attempting to execute SQL against the demo database.

To run the complete automated test suite (120 tests across 23 test modules):

```powershell
$env:PYTHONPATH = "backend"
python -m pytest backend/tests -v
```

All tests create fresh schemas from SQLAlchemy models in an isolated temporary database, seed the demo fixtures required for baseline testing, and clean up automatically. The persistent demo database remains 100% untouched.

## CSV Import Pipeline (Phase 2 Enhancements)

The CSV ingestion pipeline supports:
1. **File Validation**: Enforces a 10 MB limit, 10,000-row limit, UTF-8 and UTF-8 BOM parsing, and structural checks. Missing mandatory columns (`student_ref`, `institution_id`, `programme_id`, `academic_year`, `enrolment_start`, `enrolment_status`) are rejected immediately with HTTP 400.
2. **Row Validation**: Evaluates required fields, date formats (ISO 8601), chronological sanity (end >= start), valid enrolment statuses (`Active`, `Completed`, `Withdrawn`, `Suspended`), academic-year span syntax, and 12-digit APAAR format rules (`VAL-APAAR-FMT-001`).
3. **Duplicate & Collision Detection**:
   - In-batch duplicate tuples (`student_ref`, `institution_id`, `programme_id`, `start_date`) are rejected under `VAL-DUP-001`.
   - In-batch APAAR collisions (different student references sharing the same APAAR ID) are rejected under `VAL-APAAR-COLLISION`.
   - Database identity conflicts (an existing student reference registered with a differing APAAR ID) are rejected under `VAL-ID-CONFLICT`.
   - Registered APAAR collisions against other students in the database are rejected under `VAL-APAAR-COLLISION`.
   - Student name discrepancies between uploaded records and existing database records generate `VAL-ID-NAME-MISMATCH` warnings without silent merges.
4. **Preview / Dry-Run Mode**: Passing `preview=true` or `dry_run=true` to `POST /api/v1/students/upload-csv` validates all rows, creates an `ImportJob` with status `PREVIEW` and individual `ImportRowResult` entries for review, while committing zero changes to `students` or `enrolments`.
5. **Transactional Integrity & Rollback**: All inserts are committed transactionally. An unexpected failure rolls back all entity writes, marks the `ImportJob` as `FAILED`, and records safe error logs without exposing sensitive student identifiers.
6. **Repeat Upload Safety**: Submitting identical records or resubmitting previously accepted enrolments prevents duplicate records and tracks linkages via `previous_job_id`.

Database migration workflow: after installing requirements, run `alembic upgrade head`. The initial migration only adds `alert_review_events`; it preserves existing alert rows. Application startup also uses `create_all` for missing tables for backward-compatible local development, but Alembic should be used to record schema version for deployments.

## Known Limitations

- Bearer-token authentication, role checks, purpose-scoped verifier identity, and institution scoping are available when `AUTH_REQUIRED=true` and hashed principal claims are configured. There is no user login/session system, token issuance/expiry/rotation service, or rate limiting. With `AUTH_REQUIRED=false`, the compatibility principal is privileged and the API must remain on a trusted local development network. Production mode remains blocked; the API is not production-ready for real student data.
- Student, enrolment, certificate, verifier, and consent routes can expose full identity fields. Protect the API and database; response masking remains required.
- There is no Alembic migration history. `create_all` creates missing tables but does not apply schema changes to existing tables.
- The alert row retains the latest decision for backward compatibility; prior actions are preserved in the append-only review-event table. Evidence-file contents are not stored.
- Alert assignment, clarification requests, notes, evidence references, resolution reasons, and explicit reopening are stored in append-only review events. Evidence files themselves are not uploaded or stored; references are metadata only. Actor and assignee values are not verified identities until authentication is implemented.
- CSV import is student-level, partial-success, and not tracked through persistent import jobs. Institution-level intake CSV import is not implemented.
- Intake category totals and rules require official source verification; this prototype must not be used to infer regulations.
- Certificate HMAC uses one shared secret and does not provide public-key verification or APAAR identity verification. Configure a non-default secret outside source control; an asymmetric signing migration is still required before production use.
- CORS is restricted to localhost Vite origins by default; set the exact allowed origins for the deployment.
- No CatBoost or other trained ML model is present. Anomaly rules are deterministic statistical/demo rules only.
- No official APAAR, ABC, UDISE+, DigiLocker, or AICTE system integration is configured.

## Database migrations

Before starting the updated application, run `python -m alembic upgrade head` from the backend directory. This records migration history and creates the composite index used for efficient duplicate-enrolment lookups. The migration is safe to run on an existing database and does not delete existing rows.
