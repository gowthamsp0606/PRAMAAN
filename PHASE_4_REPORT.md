# PRAMAAN / APAAR SENTINEL — PHASE 4 AUDIT & IMPLEMENTATION REPORT
## Authentication and Role-Based Access Control (RBAC) System

**Date:** 2026-10-27  
**System:** PRAMAAN / APAAR Sentinel Authentication & Authorization Subsystem  
**Backend Architecture:** FastAPI / SQLAlchemy / PyJWT / Cryptographic PBKDF2  
**Security Standard:** OWASP Top 10 API Security / Server-Enforced RBAC  

---

## 1. Executive Summary & Audit of Previous State

Prior to Phase 4, the frontend role switcher in `Header.tsx` was purely client-side state:
- The `<select>` element navigated to different pages upon change without authenticating.
- The backend relied on static, hardcoded dictionary tokens in `settings.API_TOKEN_PRINCIPALS` or bypassed authentication completely when `AUTH_REQUIRED=False` (defaulting to `local-prototype` with `prototype_admin`).
- There was no database-backed `User` model, no secure password hashing, no login/logout API endpoints, no token revocation mechanism, and no protection against horizontal or vertical privilege escalation.

### Phase 4 Completed Upgrades:
1. **User Identity & Revocation Models:** Created `User` and `RevokedToken` ORM models in [`backend/app/models/user.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/models/user.py).
2. **Cryptographic Password Hashing:** Implemented [`PasswordHasher`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/services/auth_service.py) using PBKDF2-HMAC-SHA256 with 600,000 iterations (OWASP standard) and 16-byte random salts. Plaintext passwords are never stored.
3. **Server-Side Session & JWT Management:** Implemented [`TokenManager`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/services/auth_service.py) issuing signed HS256 JWTs with unique `jti` identifiers. Logout invalidates tokens immediately via database-backed blacklist checking.
4. **Authentication Endpoints:** Created [`backend/app/routers/auth.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/app/routers/auth.py) implementing `/login`, `/logout`, `/me`, and admin-only `/users`.
5. **Rate Limiting & Generic Failure Messages:** Applied sliding-window login rate limiting and generic error messages (`"Invalid username/email or password."`) to prevent account enumeration.
6. **Development Demo Seeding:** Implemented non-destructive demo account seeding for the 5 personas, strictly disabled when `ENVIRONMENT=production`.

---

## 2. Operational Persona & Role Architecture

| Operational Persona | Category Name | Backend Role (`Principal.role`) | Server-Enforced Scope | Permitted Operations |
|---|---|---|---|---|
| **Prototype Admin** | `PROTOTYPE_ADMIN` | `administrator` | Full Sovereign Scope (`None`) | User & role management, system health, credential issuance, full audits. |
| **AICTE Regional Directorate** | `AICTE_REGIONAL_REVIEWER` | `reviewer` | Regional Reviewer Scope | Alert reviews, case re-evaluation, anomaly dismissals, AICTE summaries. |
| **DTU Registrar** | `INSTITUTION_REGISTRAR` | `institution_officer` | `institution_id = "INST-DELHI-DTU"` | Institution student records, enrolment uploads, validation, intake quotas. |
| **TCS BGV Cell** | `BGV_VERIFIER` | `external_verifier` | `verifier_org_id = "ORG-TCS-BGV"` | Candidate credential verification with active DPDP consent, verifier logs. |
| **Compliance Auditor** | `COMPLIANCE_AUDITOR` | `read_only_auditor` | Read-Only Audit Scope | System-wide audit trails, executive reports, analytics. **All mutations denied.** |

---

## 3. Demo Credentials Configuration

Demo accounts are seeded automatically on application startup in non-production environments without overwriting existing accounts:

| Persona | Username | Email | Default Development Password | Environment Override Variable |
|---|---|---|---|---|
| **Admin** | `admin` | `admin@pramaan.gov.in` | `PramaanAdmin@2026!` | `DEMO_PASSWORD_ADMIN` |
| **AICTE Reviewer** | `aicte_reviewer` | `ro102@aicte.gov.in` | `AicteReviewer@2026!` | `DEMO_PASSWORD_REVIEWER` |
| **DTU Registrar** | `dtu_registrar` | `registrar@dtu.ac.in` | `DtuRegistrar@2026!` | `DEMO_PASSWORD_INSTITUTION` |
| **TCS Verifier** | `tcs_verifier` | `bgv.verify@tcs.com` | `TcsVerifier@2026!` | `DEMO_PASSWORD_VERIFIER` |
| **Auditor** | `compliance_auditor` | `auditor@cag.gov.in` | `ComplianceAuditor@2026!` | `DEMO_PASSWORD_AUDITOR` |

> **Production Safety Note:** If `ENVIRONMENT=production`, demo seeding is completely skipped, and `settings.AUTH_REQUIRED` is strictly required.

---

## 4. API Endpoints Reference

### 1. `POST /api/v1/auth/login`
- **Rate Limit:** 10 requests / 60 seconds
- **Request Body:** `{"username": "...", "password": "..."}`
- **Response:**
  ```json
  {
    "success": true,
    "access_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "expires_at": "2026-10-27T18:20:00Z",
    "user": {
      "id": 1,
      "username": "admin",
      "email": "admin@pramaan.gov.in",
      "full_name": "Sovereign Administrator (Demo)",
      "role": "administrator",
      "role_category": "PROTOTYPE_ADMIN",
      "institution_id": null,
      "dashboard_route": "/admin-dashboard"
    }
  }
  ```
- **Cookies:** Sets HttpOnly, SameSite=Lax `pramaan_token` cookie.

### 2. `POST /api/v1/auth/logout`
- **Requires Auth:** Yes (Bearer or Cookie)
- **Effect:** Stores token `jti` in `revoked_tokens` table; clears cookies.

### 3. `GET /api/v1/auth/me`
- **Requires Auth:** Yes
- **Returns:** Authenticated principal claims, verified role, and scoped institution/organization.

### 4. `GET /api/v1/auth/users` & `POST /api/v1/auth/users`
- **Requires Auth:** Administrator only (HTTP 403 for other roles).
- **Effect:** Manages system users and assigns validated roles.

---

## 5. Automated Test Evidence

A dedicated test suite in [`backend/tests/test_phase4_authentication.py`](file:///c:/Users/gowth/OneDrive/Documents/PROJECT/anvaya/anayava/backend/tests/test_phase4_authentication.py) validates all Phase 4 requirements:

```text
tests/test_phase4_authentication.py::test_valid_login_for_each_persona PASSED              [ 10%]
tests/test_phase4_authentication.py::test_invalid_credentials_generic_error PASSED        [ 20%]
tests/test_phase4_authentication.py::test_logout_and_token_invalidation PASSED           [ 30%]
tests/test_phase4_authentication.py::test_expired_or_invalid_session PASSED               [ 40%]
tests/test_phase4_authentication.py::test_every_roles_permitted_operations PASSED        [ 50%]
tests/test_phase4_authentication.py::test_every_roles_forbidden_operations PASSED        [ 60%]
tests/test_phase4_authentication.py::test_cross_institution_access_denial PASSED         [ 70%]
tests/test_phase4_authentication.py::test_unauthorized_role_assignment PASSED            [ 80%]
tests/test_phase4_authentication.py::test_direct_api_access_without_authentication PASSED [ 90%]
tests/test_phase4_authentication.py::test_production_configuration_with_demo_authentication_disabled PASSED [100%]
=================================== 10 passed in 15.79s ====================================
```

---

## 6. Files Changed in Phase 4

| File | Status | Description |
|---|---|---|
| `backend/app/models/user.py` | **Created** | `User` and `RevokedToken` SQLAlchemy ORM models. |
| `backend/app/models/__init__.py` | **Modified** | Exported `User` and `RevokedToken`. |
| `backend/app/services/auth_service.py` | **Created** | PBKDF2 password hasher, JWT token manager, authentication service, and demo seeder. |
| `backend/app/routers/auth.py` | **Created** | Endpoints for `/login`, `/logout`, `/me`, and admin `/users`. |
| `backend/app/security.py` | **Modified** | Enhanced `get_current_principal` to verify JWTs, check revocation, and enforce RBAC. |
| `backend/app/main.py` | **Modified** | Mounted `/auth` router and registered development demo account seeder. |
| `backend/app/seed_data.py` | **Modified** | Integrated `AuthService.seed_demo_users` into database seed process. |
| `backend/tests/test_phase4_authentication.py` | **Created** | 10 comprehensive tests covering login, lockout, expiry, scopes, and production guards. |
| `PHASE_4_REPORT.md` | **Created** | Comprehensive audit report. |
