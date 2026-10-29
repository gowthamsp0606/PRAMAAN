# Phase 5 Implementation Report: Digital Credentials, Verification & Review Workflows

**Project:** PRAMAAN / APAAR Sentinel (AICTE Hackathon SIH26263)  
**Date:** 2026-10-27  
**Status:** COMPLETE — 8/8 Tests Passing  
**Environment:** Python 3.13.15, SQLite Test Isolation, Cryptography 50.0.0  

---

## 1. Executive Summary

Phase 5 delivers verifiable, tamper-evident digital credential issuance, offline and online asymmetric verification via **Ed25519**, robust revocation management with audit trails, privacy-preserving employer verification gated by student DPDP consent, and hardened alert review workflows.

All cryptographic private signing keys are strictly retained on the backend; verifiers and external institutions verify authenticity using public keys fetched via the Sentinel public key registry. Full backward compatibility is preserved for existing prototype HMAC-SHA256 credentials without compromising security or treating legacy signatures as Ed25519 signatures.

---

## 2. Key Architecture & Implemented Capabilities

### A. Asymmetric Digital Credentials (Ed25519)
- **Primary Standard:** `Ed25519` elliptic curve asymmetric cryptography via the `cryptography` library (`cryptography.hazmat.primitives.asymmetric.ed25519`).
- **Key Derivation:** The private signing key is deterministically derived on the backend using SHA-256 HKDF-style domain separation (`PRAMAAN-ED25519-SIGNING-ROOT:` + `settings.SECRET_KEY`). Private keys are never serialized to disk, transmitted over network endpoints, or returned in API responses.
- **Key Registry & Rotation:**
  - `ACTIVE_KEY_ID`: `SENTINEL-ED25519-2026-V1` (Active Ed25519 root key)
  - `LEGACY_HMAC_KEY_ID`: `SENTINEL-TEST-ROOT-2026` (Deprecated legacy symmetric key)
  - Registry API endpoints: `GET /api/v1/certificates/public-keys` and `GET /api/v1/certificates/public-keys/{key_id}`.
- **Minimal Verifiable Claims:** Credential payloads avoid unnecessary personal data leakage, containing only essential student reference, student name, institution, programme, issue date, completion date, and credential type (`AICTE_VERIFIED_COMPLETION`).

### B. Backward Compatibility (HMAC-SHA256)
- Existing legacy certificates signed with HMAC-SHA256 remain verifiable by `CertificateService.verify_certificate`.
- The system checks `cert.signature_algorithm` and verifies against the corresponding cryptographic engine.
- Old signatures are never silently treated as equivalent to new asymmetric signatures.

### C. Revocation Lifecycle & Tamper Detection
- **Explicit Outcomes:**
  - `VALID`: Cryptographically authentic and active status.
  - `TAMPER_DETECTED`: Payload mutated post-issuance (student name, degree, completion date mismatch).
  - `REVOKED`: Signature is mathematically valid, but institutional status is revoked with recorded reason.
  - `NOT_FOUND`: Nonexistent certificate identifier.
  - `UNSUPPORTED_ALGORITHM`: Unknown signature algorithm identifier.
- **Mandatory Substantive Reason:** Revocation requires a justification of at least 5 characters; blank or frivolous reasons are rejected with HTTP 422.
- **Audit Logging:** Every issuance and revocation action creates an immutable event in `AuditLog` (`action="ISSUE_CREDENTIAL"`, `action="REVOKE_CREDENTIAL"`).

### D. Privacy & DPDP Consent Gate Integration
- **Employer/External Verifier Checks:**
  - `POST /api/v1/verifier/verify-credential` checks student consent in `StudentConsent`.
  - If student consent is `WITHDRAWN` or missing: returns `CONSENT_WITHHELD` or `CONSENT_REQUIRED`, halting verification.
  - If verified: returns minimal purpose-limited confirmation (`MATCH_VERIFIED`), completely omitting raw APAAR IDs or sensitive demographics.
- **Role Isolation:** `external_verifier` principals are strictly scoped to their assigned `verifier_org_id` and `purpose_scope="EMPLOYMENT_VERIFICATION"`.

### E. Alert Review & Human-in-the-Loop Workflow Hardening
- **RBAC Enforcement:** `read_only_auditor` and `external_verifier` cannot review, assign, clarify, note, or reopen alerts (HTTP 403).
- **Institution Scoping:** `institution_officer` can only access and modify alerts where all supporting records belong to their assigned institution.
- **Traceable History:** Decisions (`CONFIRMED_CONFLICT`, `NOT_A_CONFLICT`, `EXCEPTION_ACCEPTED`, `NEEDS_MORE_INFO`), assignments, notes, and reopenings are appended to `AlertReviewEvent` and logged in `AuditLog`.
- **Identity Spoofing Prevention:** Authenticated principals cannot override `reviewed_by` with arbitrary caller-supplied names in non-prototype roles.

---

## 3. Test Verification Suite (`backend/tests/test_phase5_credentials_and_workflows.py`)

| Test Function | Verification Scope | Status |
| :--- | :--- | :--- |
| `test_ed25519_credential_issuance_and_asymmetric_verification` | Issues Ed25519 credential, verifies online via endpoint and offline using public key hex with `Ed25519PublicKey.verify`. | **PASSED** |
| `test_ed25519_tamper_detection` | Simulates field forgery (`student_name`), confirms `TAMPER_DETECTED` and `signature_valid: False`. | **PASSED** |
| `test_backward_compatibility_hmac_sha256` | Verifies legacy HMAC-SHA256 credentials continue to verify correctly under legacy key identifier. | **PASSED** |
| `test_credential_revocation_workflow_and_audit` | Enforces substantive revocation reason, checks `REVOKED` outcome, and validates `AuditLog` entry. | **PASSED** |
| `test_public_key_registry_endpoints` | Tests registry enumeration, single key lookup, and 404 for unknown keys. | **PASSED** |
| `test_credentials_role_authorization_and_scoping` | Confirms auditor cannot issue/revoke (403), officer cannot issue/revoke cross-institution (403). | **PASSED** |
| `test_verifier_portal_consent_gating_and_privacy` | Tests DPDP consent enforcement (`CONSENT_WITHHELD`), privacy masking, and safe `NO_MATCH`. | **PASSED** |
| `test_alert_review_workflow_scoping_and_audit` | Verifies alert review transitions, note validation (422), reopenings, and audit event preservation. | **PASSED** |

**Total:** 8 passed in 0.38s.

---

## 4. Limitations & Safe Operation

1. **Standalone Prototype Key Management:** In production, backend private keys should be backed by a Hardware Security Module (HSM) or Cloud KMS (e.g. AWS KMS / Google Cloud KMS) rather than environment secrets.
2. **Offline Verifier App:** Offline verifiers need to cache the public key registry; key rotation notifications should be distributed via published DNS/DID or AICTE root registry.
