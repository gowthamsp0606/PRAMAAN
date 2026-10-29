# PRAMAAN / APAAR Sentinel — Phase 5 Deliverable Report
**Role-Specific Dashboard Experiences & Front-to-Back RBAC Integration**

---

## 1. Executive Summary

Phase 5 has successfully built and deployed **dedicated role-specific dashboard experiences** in the React/Vite frontend, fully integrated with the server-side authentication and role-based access control (RBAC) engine established in Phase 4.

### Key Deliverables Delivered
1. **Public vs. Protected Route Architecture**: Implemented `ProtectedRoute` component and `RootRedirector` that redirect unauthenticated traffic to `/login` and route authenticated users directly to their designated sovereign dashboard.
2. **Elimination of Frontend-Only Role Switching**: Removed the insecure `<select>` role switcher from `Header.tsx`. Users can no longer modify frontend state, URL parameters, or localStorage tokens to access unauthorized consoles.
3. **Role-Specific Dashboards**:
   - **`AdminDashboard` (`/admin-dashboard`)**: System telemetry, registered user directory with live provisioning form (`/api/v1/auth/users`), security architecture status, and national KPI metrics.
   - **`AuditorDashboard` (`/auditor-dashboard`)**: Immutable read-only surveillance console, ledger audit trail, intake anomaly listings, and direct CSV regulatory report exports.
   - **`InstitutionDashboard` (`/institution-dashboard`)**: Scoped to the authenticated registrar's institution (`INST-DELHI-DTU`), with college switching disabled for non-administrators.
   - **`EmployerPortal` (`/employer-portal`)**: Scoped to the authenticated verifier organization (`ORG-TCS-BGV`), purpose-limited to `EMPLOYMENT_VERIFICATION`.
   - **`AicteDashboard` (`/aicte-dashboard`)**: Regional directorate oversight, duplicate enrolment adjudication, and intake compliance monitoring.
4. **Dynamic Context-Aware Layouts**:
   - `Header.tsx`: Displays live user avatar initials, full name, role category pill, bound organization/institution tag, and secure `Logout` button.
   - `Sidebar.tsx`: Filters navigation sections strictly according to the authenticated principal's role tier.
5. **Automated Verification**: Created `backend/tests/test_phase5_role_dashboards.py` (6/6 tests passing) and confirmed 100% pass rate across the full backend regression suite (227/227 passed).

---

## 2. Persona-to-Dashboard Mapping Matrix

| Operational Persona | System Role (`role`) | Role Category (`role_category`) | Assigned Scope | Dedicated Dashboard Route | Permitted Secondary Routes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Prototype Admin** | `administrator` | `PROTOTYPE_ADMIN` | National / All Institutions | `/admin-dashboard` | `/overview`, `/aicte-dashboard`, `/institution-dashboard`, `/employer-portal`, `/auditor-dashboard`, `/students`, `/integrity`, `/validation`, `/intake`, `/consent`, `/certificates`, `/analytics`, `/reports`, `/audit`, `/settings` |
| **AICTE Regional Reviewer** | `reviewer` | `AICTE_REGIONAL_REVIEWER` | Regional Directorate | `/aicte-dashboard` | `/overview`, `/integrity`, `/students`, `/validation`, `/analytics`, `/reports` |
| **Institution Registrar** | `institution_officer` | `INSTITUTION_REGISTRAR` | `INST-DELHI-DTU` | `/institution-dashboard` | `/students`, `/intake`, `/validation`, `/consent`, `/certificates` |
| **BGV Verifier** | `external_verifier` | `BGV_VERIFIER` | `ORG-TCS-BGV` | `/employer-portal` | `/certificates` (public test root verification) |
| **Compliance Auditor** | `read_only_auditor` | `COMPLIANCE_AUDITOR` | Independent Audit | `/auditor-dashboard` | `/audit`, `/reports`, `/analytics` |

---

## 3. UI/UX Architecture & Implementation Details

### 3.1 Authentication Context & Session Management
- **File**: `frontend/src/context/AuthContext.tsx`
- **Capabilities**:
  - Initializes state from stored JWT bearer token.
  - Fetches authenticated principal claims via `GET /api/v1/auth/me`.
  - Dispatches `sentinel-session-expired` event upon receiving HTTP 401 from backend, clearing client session and redirecting to login.
  - Exposes `login()`, `logout()`, `user`, `loading`, `isAuthenticated`, and `sessionExpired`.

### 3.2 Route Protection & Redirection
- **Files**: `frontend/src/components/ProtectedRoute.tsx`, `frontend/src/App.tsx`
- **Route Guard Logic**:
  - Checks if user is authenticated; if not, redirects to `/login` preserving target location in router state.
  - Evaluates `allowedRoles` array against `user.role` and `user.role_category`.
  - If a user attempts to access an unauthorized route (e.g., an auditor visiting `/integrity` or registrar visiting `/admin-dashboard`), they are automatically redirected to their allowed `dashboard_route`.
  - Root route (`/`) mounts `RootRedirector`, dynamically steering each authenticated persona directly to their home dashboard.

### 3.3 Top Header Layout Refactoring
- **File**: `frontend/src/components/Layout/Header.tsx`
- **Modifications**:
  - Removed client-side `<select>` role switcher.
  - Added user initials avatar badge.
  - Added role category badge styled with distinct role colors (Purple for Admin, Blue for AICTE, Teal for Registrar, Amber for BGV Verifier, Slate for Auditor).
  - Added organizational scope badges (`INST-DELHI-DTU`, `ORG-TCS-BGV`).
  - Added `Logout` button invoking `api.logout()`, blacklisting token on server, clearing client state, and redirecting to `/login`.

### 3.4 Dynamic Sidebar Navigation
- **File**: `frontend/src/components/Layout/Sidebar.tsx`
- **Modifications**:
  - Navigation sections filtered dynamically using the authenticated user's role.
  - External verifiers only see verifier and public certificate tools.
  - Compliance auditors only see audit trail, executive reports, and historical analytics.
  - Institution registrars only see institutional operations, student records, intake compliance, and student consent.
  - Updated sidebar footer identity pill to reflect live user claims rather than hardcoded mock strings.

### 3.5 New & Updated Dashboard Pages
1. **`AdminDashboard.tsx` (`/admin-dashboard`)**:
   - System administration overview showing total students, conflicts, certificates, and registered accounts.
   - User table populated dynamically from `GET /api/v1/auth/users`.
   - Built-in user provisioning modal calling `POST /api/v1/auth/users`.
   - Security parameter display (PBKDF2-HMAC-SHA256, 60m JWT window, revocation blacklist).
   - "Trigger Engine Sync" button to evaluate temporal rules.
2. **`AuditorDashboard.tsx` (`/auditor-dashboard`)**:
   - Read-only surveillance dashboard.
   - Notice banner confirming read-only mode and DPDP privacy protections.
   - Executive regulatory summary and active anomaly detection stream.
   - Ledger audit trail explorer with entity and action filters.
   - One-click CSV export link for executive compliance reporting.
3. **`InstitutionDashboard.tsx` (`/institution-dashboard`)**:
   - Bound to `user.institution_id`.
   - For `institution_officer`, college selector is replaced with an immutable "Assigned Scope" badge (`INST-DELHI-DTU`), preventing cross-institution inspection.
4. **`EmployerPortal.tsx` (`/employer-portal`)**:
   - Bound to `user.verifier_org_id`.
   - For `external_verifier`, organization selector is replaced with an immutable locked badge (`ORG-TCS-BGV`) with Purpose Scope (`EMPLOYMENT_VERIFICATION`).

---

## 4. Test Suite Execution & Verification

### 4.1 Phase 5 Role Dashboard Test Suite (`test_phase5_role_dashboards.py`)
```text
============================= test session starts =============================
platform win32 -- Python 3.13.15, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava
collecting ... collected 6 items

backend/tests/test_phase5_role_dashboards.py::test_role_specific_dashboard_routes_returned_on_login PASSED [ 16%]
backend/tests/test_phase5_role_dashboards.py::test_auth_me_reflects_dashboard_route_and_scopes PASSED [ 33%]
backend/tests/test_phase5_role_dashboards.py::test_institution_scope_enforcement_for_registrar PASSED [ 50%]
backend/tests/test_phase5_role_dashboards.py::test_admin_dashboard_user_management_authorization PASSED [ 66%]
backend/tests/test_phase5_role_dashboards.py::test_auditor_prohibited_from_mutating_state PASSED [ 83%]
backend/tests/test_phase5_role_dashboards.py::test_external_verifier_scoped_access PASSED [100%]

======================= 6 passed, 61 warnings in 9.13s ========================
```

### 4.2 Full Backend Regression Test Suite
```text
============================= test session starts =============================
platform win32 -- Python 3.13.15, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\gowth\OneDrive\Documents\PROJECT\anvaya\anayava
collecting ... collected 227 items

227 passed, 2002 warnings in 54.31s (100% PASS RATE)
```

---

## 5. File Change Summary

| File | Change Nature | Purpose |
| :--- | :--- | :--- |
| `frontend/src/api/client.ts` | Modified | Added auth client methods (`login`, `logout`, `getCurrentUser`, `listUsers`, `createUser`), token storage, and session-expired dispatch. |
| `frontend/src/context/AuthContext.tsx` | Created | React Context providing user identity, login, logout, and token session monitoring. |
| `frontend/src/components/ProtectedRoute.tsx` | Created | Route guard enforcing authentication and role-based permissions. |
| `frontend/src/pages/Login.tsx` | Created | Sovereign login portal with credentials form, password visibility toggle, error banners, and demo fill chips. |
| `frontend/src/pages/AdminDashboard.tsx` | Created | Root administrator console with user provisioning, system metrics, and security status. |
| `frontend/src/pages/AuditorDashboard.tsx` | Created | Read-only compliance auditor console with audit trail explorer, anomaly feed, and export controls. |
| `frontend/src/pages/InstitutionDashboard.tsx` | Modified | Integrated `useAuth` to bind and lock view to registrar's assigned `institution_id`. |
| `frontend/src/pages/EmployerPortal.tsx` | Modified | Integrated `useAuth` to bind and lock view to verifier's assigned `verifier_org_id` and purpose scope. |
| `frontend/src/components/Layout/Header.tsx` | Modified | Removed insecure role dropdown; added user avatar, role category badge, org scope pill, and logout button. |
| `frontend/src/components/Layout/Sidebar.tsx` | Modified | Dynamically filtered navigation links by user role tier; updated footer profile card. |
| `frontend/src/App.tsx` | Modified | Mounted `AuthProvider`, public `/login` route, `RootRedirector`, and protected role dashboard routes. |
| `backend/app/security.py` | Modified | Restored token registry validation check for missing legacy tokens when `AUTH_REQUIRED=True`. |
| `backend/tests/test_phase5_role_dashboards.py` | Created | Automated test suite verifying role routing, scope enforcement, mutation blocking, and user management security. |

---

## 6. Conclusion & Status

Phase 5 is **complete and verified**. The application now features:
- End-to-end authentication with cryptographic password hashing (PBKDF2-HMAC-SHA256).
- 5 distinct, role-tailored dashboard experiences.
- Server-side RBAC and tenant scoping enforced on every API request.
- Client-side route protection preventing role elevation or horizontal privilege escalation.
- Zero test regressions across 227 automated tests.
