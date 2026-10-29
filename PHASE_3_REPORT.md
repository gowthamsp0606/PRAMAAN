# PRAMAAN / APAAR SENTINEL — PHASE 3 AUDIT & REPAIR REPORT
## Digital Credentials & Cryptographic Verification Workflow

**Date:** 2026-10-27  
**System Under Audit:** PRAMAAN / APAAR Sentinel Digital Credential Engine  
**Backend Framework:** FastAPI / SQLAlchemy (SQLite) / Cryptography (Hazmat)  
**Frontend Framework:** React 18 / Vite / Tailwind CSS  
**Target Architecture:** Dual-Signature Cryptographic Standard (Ed25519 Asymmetric & Legacy HMAC-SHA256 Symmetric)

---

## 1. Executive Summary

Phase 3 performed an end-to-end cryptographic and security audit of the Digital Credentials workflow in PRAMAAN / APAAR Sentinel. The audit inspected the data models, signing algorithms, verification logic, tamper simulation testbed, and revocation mechanics across both backend services and the frontend portal.

### Key Audit Findings & Remediations
1. **Non-Destructive Tamper Simulation Verified:**
   - **Pre-existing concern:** UI confirmation dialog warned that tamper testing would mutate stored credentials.
   - **Audit finding:** The backend endpoint `POST /api/v1/certificates/{certificate_id}/simulate-tamper` created a shallow in-memory clone of `payload_json`, but lacked explicit isolation metadata, authorization scoping, and tamper-to-original integrity guarantees.
   - **Remediation:** Hardened `simulate-tamper` to enforce `Principal` authentication and role scoping (`institution_officer` cannot tamper-test another institution's credentials; read-only roles are blocked). Added explicit response fields `"database_mutated": false` and `"isolation_mode": "IN_MEMORY_DISPOSABLE_CLONE"`. Added frontend reassurance pills and post-simulation "Re-verify Stored Record" verification action confirming zero database mutation.
2. **Key Trust Registry & Algorithm Enforcement (CWE-347 / CWE-327):**
   - **Audit defect:** `CertificateService.verify_certificate` verified Ed25519 or HMAC signatures without validating that the certificate's `public_key_id` existed in the trusted `KEY_REGISTRY`, nor that the key's designated algorithm matched the certificate.
   - **Remediation:** Integrated trusted key registry validation into `verify_certificate`. Untrusted key IDs immediately yield `UNTRUSTED_KEY` (`is_authentic: false`, `signature_valid: false`); algorithm mismatches yield `KEY_ALGORITHM_MISMATCH`.
3. **Cryptographic Honesty: HMAC vs. Public-Key Cryptography:**
   - **Audit defect:** Frontend `CertificateVerification.tsx` displayed hardcoded "HMAC-SHA256 Authenticated" and labeled symmetric key IDs as "Public Test Root Key". Symmetric HMAC keys have no public keys.
   - **Remediation:** Dynamically updated the UI to accurately distinguish symmetric vs. asymmetric credentials:
     - `Ed25519`: Displays "Ed25519 Asymmetric Signature" and "Public Key ID (Asymmetric Ed25519)".
     - `HMAC-SHA256`: Displays "HMAC-SHA256 Symmetric MAC" and "Key ID (Symmetric HMAC-SHA256)".
4. **Data Privacy & Identifier Masking:**
   - **Remediation:** Non-administrator roles (`institution_officer`, `read_only_auditor`, `external_verifier`) have APAAR IDs masked (e.g., `********1001`) and `signature_hex` suppressed in `/verify` and `/simulate-tamper` responses.

---

## 2. Cryptographic Architecture & Specifications

### A. Supported Cryptographic Standards
| Dimension | Primary Standard (Active) | Backward-Compatibility Standard (Legacy) |
|---|---|---|
| **Algorithm** | **Ed25519** (Edwards-curve Digital Signature Algorithm) | **HMAC-SHA256** (Keyed-Hash Message Authentication Code) |
| **Cryptography Type** | **Asymmetric Public-Key** | **Symmetric Keyed Hash** |
| **Key Identifier** | `SENTINEL-ED25519-2026-V1` | `SENTINEL-TEST-ROOT-2026` / `SENTINEL-TEST-KEY` |
| **Public Key Availability** | Public key published via `/api/v1/certificates/public-keys` | `None` (Symmetric server secret — never published) |
| **Third-Party Offline Verification** | Fully supported via public key without calling backend | Not supported without sharing server secret |
| **Signature Length** | 64 bytes (128 hex characters) | 32 bytes (64 hex characters) |
| **Canonical Payload** | RFC 8785 deterministic JSON (sorted keys, compact separators) | RFC 8785 deterministic JSON (sorted keys, compact separators) |

### B. Canonical Payload Construction
Payloads are deterministically serialized prior to hashing or signing:
```python
def canonical_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode("utf-8")
```
Example canonical payload:
```json
{"certificate_id":"CERT-APAAR-2026-001","completion_date":"2026-05-31","credential_type":"AICTE_VERIFIED_COMPLETION","institution_id":"INST-DELHI-DTU","institution_name":"Delhi Technological University (Demo)","issue_date":"2026-06-15","programme_id":"BTECH-CSE","programme_name":"B.Tech Computer Science & Engineering","student_name":"Aarav Sharma","student_ref":"STU-DEMO-001"}
```

---

## 3. Discovered Vulnerabilities & Fixes

### Defect 1: Unverified Signing Key Identifier in Verification Engine
- **Location:** `backend/app/services/certificate_service.py`
- **Vulnerability:** `verify_certificate` bypassed `KEY_REGISTRY` checking and verified directly against whatever algorithm string was stored on the certificate. An attacker could forge a record with an arbitrary `public_key_id` or mismatched algorithm.
- **Correction:** Implemented key trust validation:
  ```python
  key_entry = KEY_REGISTRY.get(cert.public_key_id)
  if not key_entry:
      return {
          "verification_status": "UNTRUSTED_KEY",
          "is_authentic": False,
          "signature_valid": False,
          "message": f"UNTRUSTED SIGNING KEY: Key ID '{cert.public_key_id}' is not in the Sentinel trusted key store."
      }
  if key_entry.get("status") == "REVOKED":
      return {"verification_status": "SIGNING_KEY_REVOKED", "is_authentic": False, "signature_valid": False}
  if key_entry.get("algorithm") != algorithm:
      return {"verification_status": "KEY_ALGORITHM_MISMATCH", "is_authentic": False, "signature_valid": False}
  ```

### Defect 2: Missing Authentication and Scope Guards on Tamper Simulation
- **Location:** `backend/app/routers/certificates.py` (`simulate_tampered_verification`)
- **Vulnerability:** The endpoint lacked `principal: Principal = Depends(get_current_principal)`. When `AUTH_REQUIRED=True`, unauthenticated users or cross-institution officers could tamper-test certificates. Furthermore, unmasked APAAR IDs and signature hex were leaked in responses.
- **Correction:**
  - Added `principal: Principal = Depends(get_current_principal)`.
  - Added institution-level authorization scoping (`enforce_institution_scope`).
  - Added role restrictions: `read_only_auditor` and `external_verifier` return HTTP 403.
  - Added sensitive data masking: `mask_identifier` applied to `apaar_id`; `signature_hex` suppressed for non-administrators.
  - Added structured audit event `TAMPER_SIMULATION_TEST` logging with `database_modified: False`.

### Defect 3: Misleading Public-Key Claims for Symmetric HMAC Credentials
- **Location:** `frontend/src/pages/CertificateVerification.tsx`
- **Vulnerability:** The UI labeled HMAC-SHA256 credentials with "Public Test Root Key: SENTINEL-TEST-ROOT-2026" and hardcoded "HMAC-SHA256 Authenticated".
- **Correction:** Dynamic algorithm badges and key descriptors:
  - Displays `"Ed25519 Asymmetric Signature"` and `"Public Key ID (Asymmetric):"` for Ed25519 credentials.
  - Displays `"HMAC-SHA256 Symmetric MAC"` and `"Key ID (Symmetric HMAC):"` for HMAC credentials.

### Defect 4: Operator Confusion Over Tamper Destruction
- **Location:** `frontend/src/pages/CertificateVerification.tsx`
- **Issue:** Operators were concerned that testing tamper detection would overwrite real or demo certificates in the database.
- **Correction:**
  - Added informational pill: `"Non-Destructive In-Memory Simulation: Modifying fields below evaluates an in-memory disposable clone. The original stored certificate in the database ledger is never altered."`
  - Added post-test confirmation badge: `"Database Record Intact (Not Mutated)"` with a one-click `"Re-verify Stored"` button.

---

## 4. Distinction Between Invalid and Revoked Credentials

A key regulatory requirement is ensuring revoked certificates are distinguishable from cryptographically invalid credentials:

| State | `verification_status` | `is_authentic` | `signature_valid` | Meaning |
|---|---|---|---|---|
| **Active Valid** | `VALID` | `true` | `true` | Cryptographic signature matches and certificate is active. |
| **Cryptographically Tampered** | `TAMPER_DETECTED` | `false` | `false` | Payload has been modified or corrupted post-issuance. |
| **Administratively Revoked** | `REVOKED` | `false` | `true` | **Mathematical signature is intact**, but institutional authority revoked the credential. |
| **Tampered Revoked** | `TAMPER_DETECTED` | `false` | `false` | Tampering takes precedence: an invalid payload fails cryptographic check before revocation evaluation. |
| **Untrusted Key** | `UNTRUSTED_KEY` | `false` | `false` | Key identifier is not in the Sentinel trusted key store. |
| **Non-Existent Certificate** | `NOT_FOUND` | `false` | `false` | Record does not exist in ledger. |

---

## 5. Automated Test Suite Results

A dedicated regression test suite was created in `backend/tests/test_phase3_digital_credentials.py` testing all required scenarios against isolated test data.

### Targeted Test Results (`test_phase3_digital_credentials.py`):
```text
tests/test_phase3_digital_credentials.py::test_valid_certificate_ed25519 PASSED            [ 11%]
tests/test_phase3_digital_credentials.py::test_valid_certificate_legacy_hmac PASSED        [ 22%]
tests/test_phase3_digital_credentials.py::test_modified_payload_fails_verification PASSED [ 33%]
tests/test_phase3_digital_credentials.py::test_invalid_signature_hex PASSED                [ 44%]
tests/test_phase3_digital_credentials.py::test_untrusted_key_id PASSED                      [ 55%]
tests/test_phase3_digital_credentials.py::test_revoked_certificate_distinguishable_from_tampered PASSED [ 66%]
tests/test_phase3_digital_credentials.py::test_unknown_certificate PASSED                  [ 77%]
tests/test_phase3_digital_credentials.py::test_unauthorized_verification_and_scoping PASSED [ 88%]
tests/test_phase3_digital_credentials.py::test_tamper_test_does_not_damage_original_record PASSED [100%]
=================================== 9 passed in 0.30s ====================================
```

### Full Backend Test Suite Verification:
```text
================================= 211 passed in 24.28s ===================================
```
- **Total Tests Passed:** 211 / 211 (100% passing)
- **Regressions:** 0
- **Database Safety Guard:** Verified; no writes executed on `apaar_sentinel.db` during test runs.

---

## 6. Files Changed in Phase 3

| File | Status | Description |
|---|---|---|
| `backend/app/services/certificate_service.py` | **Modified** | Added `TEST_HMAC_KEY_ID` to `KEY_REGISTRY`; added key trust validation, key status verification, and algorithm consistency checks in `verify_certificate`. |
| `backend/app/routers/certificates.py` | **Modified** | Hardened `simulate_tampered_verification` with `Principal` dependency, cross-institution scoping, role permission checks (403 for read-only/verifier), sensitive data masking, and audit logging. |
| `frontend/src/pages/CertificateVerification.tsx` | **Modified** | Replaced hardcoded "HMAC-SHA256 Authenticated" and "Public Test Root Key" labels with dynamic algorithm/key descriptors; added non-destructive in-memory simulation disclaimers and live re-verification controls. |
| `backend/tests/test_phase3_digital_credentials.py` | **Created** | Comprehensive test suite covering valid certificates, tampered payloads, corrupted signatures, untrusted keys, revocation distinctions, unauthorized access, and original record immutability. |
| `PHASE_3_REPORT.md` | **Created** | Audit documentation, architectural overview, defect analysis, and test evidence. |

---

## 7. Status & Next Steps

Phase 3 is complete. The digital credentials workflow correctly implements:
- Asymmetric Ed25519 signing with public key discovery.
- Backward-compatible symmetric HMAC-SHA256 verification.
- Non-destructive in-memory tamper simulation that guarantees the original ledger record is never mutated.
- Strict distinction between cryptographically invalid and administratively revoked credentials.
- Full role-based authorization and data privacy protection.

Per instruction, execution stops after Phase 3.
