# PRAMAAN / APAAR Sentinel — Phase 4 Implementation Report

**Project:** PRAMAAN / APAAR Sentinel (AICTE Hackathon SIH26263)  
**Phase:** Phase 4 — APAAR-FUSE & Explainable Anomaly Detection  
**Date:** 2026-10-27  
**Status:** COMPLETE  

---

## 1. Executive Summary

Phase 4 establishes an explainable statistical anomaly detection foundation and unified findings interface (APAAR-FUSE foundation) that separates statistical deviations from deterministic policy violations.
- **Historical Baselines:** Compares reported admissions against moving multi-year institutional baselines using both parametric (Z-score) and non-parametric robust statistics (median and IQR).
- **Insufficient History:** Explicitly flags cohorts with fewer than 3 historical years with `insufficient_history: True` and explanatory messaging, preventing invalid or misleading standard deviations on tiny samples.
- **Explainable Findings API:** Implemented `GET /api/v1/analytics/findings` unifying findings across statistical deviations (`HISTORICAL_DEVIATION`), deterministic conflicts (`TEMPORAL_CONFLICT`), and identity integrity issues (`IDENTITY_INCONSISTENCY`).
- **Authenticated Review & Scoping:** Hardened the dismissal workflow (`PATCH /api/v1/analytics/anomalies/{id}/dismiss`) to enforce authenticated principal identity, substantive justifications (>= 5 chars), role-based permissions (rejecting unauthorized verifiers and auditors), and strict institution-scoping.
- **Database Safety:** The demo database (`backend/apaar_sentinel.db`) remained completely untouched and isolated throughout all tests.
- **Test Results:** 5 new Phase 4 test cases added, bringing the total passing test suite to **182 tests** (0 failed, 0 skipped).

---

## 2. Files Changed & Added

| File | Status | Description |
| :--- | :--- | :--- |
| `backend/app/services/anomaly_service.py` | Modified | Added robust statistics (`baseline_median`, `baseline_iqr`), explicit `insufficient_history` tracking for samples < 3 years, query filtering in `get_all_anomalies`, substantive justification validation in `dismiss_anomaly`, and `get_explainable_findings` method. |
| `backend/app/routers/analytics.py` | Modified | Added authenticated `Principal` dependency, institution scoping for `institution_officer`, role restrictions, and the new `/findings` explainable API endpoint. |
| `backend/app/security.py` | Modified | Permitted `institution_officer` role to access `/analytics` and `/analytics/*` GET endpoints for their institution. |
| `backend/tests/test_phase4_anomalies_and_findings.py` | Created | Added 5 comprehensive test suites covering insufficient history, statistical vs deterministic finding separation, API filtering, dismissal validation, and role/scoping enforcement. |
| `backend/PHASE4_IMPLEMENTATION_REPORT.md` | Created | Implementation report documenting Phase 4 features, API contracts, and test verification. |

---

## 3. Implemented Capabilities

### A. Explainable Findings Contract (`GET /api/v1/analytics/findings`)
Each finding returned distinguishes statistical from deterministic logic:
- `finding_id`: Unique identifier (e.g. `FIND-ANOM-1`, `FIND-ALERT-ALT001`).
- `finding_type`: `HISTORICAL_DEVIATION` vs `TEMPORAL_CONFLICT` vs `IDENTITY_INCONSISTENCY`.
- `is_statistical_anomaly`: `True` for statistical outliers, `False` for deterministic rule violations.
- `rule_or_model_id`: `STAT-ZSCORE-V1`, `RULE-TEMP-OVERLAP-001`, `RULE-IDENTITY-COLLISION-001`.
- `observed_value`: Reported value (e.g., student count or reference).
- `comparison_baseline`: Moving mean, quota, or policy requirement.
- `sample_size`: Historical cohort count (or None for deterministic rules).
- `severity`: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`.
- `evidence`: Detailed dictionary with Z-score, percent change, IQR metrics, or supporting IDs.
- `explanation`: Contextual human-readable justification.
- `review_recommended`: Boolean indicating required human action.

### B. Statistical Reliability & Insufficient History Handling
- For institutions/programmes with fewer than 3 historical cohorts, `insufficient_history: True` is returned with a clear explanation: `"At least 3 historical cohort years are required for statistical significance"`.
- Prevents division-by-zero when standard deviation is zero.
- Calculates both mean/standard deviation and median/IQR for robust outlier assessment.

### C. Review & Dismissal Governance (`PATCH /api/v1/analytics/anomalies/{id}/dismiss`)
- **Justification Enforcement:** Requires a substantive string of at least 5 non-whitespace characters (returns HTTP 422 if empty or trivial).
- **Identity Spoofing Prevention:** Uses authenticated `principal.subject` rather than untrusted client payload values.
- **Role Enforcement:** Blocks `read_only_auditor` and `external_verifier` with HTTP 403.
- **Institution Scoping:** Enforces that `institution_officer` cannot dismiss findings belonging to other institutions.
- **Audit Logging:** Every dismissal records an audit event in `audit_logs` with actor attribution and rationale.

---

## 4. Test Verification

```bash
python -m pytest backend/tests/test_phase4_anomalies_and_findings.py -v
```
- **Passed:** 5 / 5 (0.27s)
- **Regressions:** None. Pre-existing tests (`test_anomaly_baseline.py`, `test_additional_features.py`) continue to pass 100%.
