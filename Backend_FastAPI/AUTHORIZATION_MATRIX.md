# MA TRẬN PHÂN QUYỀN ENDPOINT - FINAL FORM

> **Version:** 1.0.0
> **Generated:** 2026-01-05
> **Based on:** Code analysis + AUTHORIZATION_DECISIONS.md + State Machine

---

## LEGEND (Chú giải)

| Symbol | Ý nghĩa |
|--------|---------|
| ✅ | Casbin ALLOW - Được phép gọi API |
| ❌ | Casbin DENY - Không được phép |
| ⚠️ | Casbin ALLOW + bắt buộc kiểm tra thêm (IDOR/State/Business) |
| 🔒 | Break-glass - Cần audit bắt buộc |
| 📝 | Rate limited |
| 🔐 | Requires password confirmation |

**Check types:**
- `IDOR` = Ownership check (return 404 if not owner)
- `STATE` = State machine check (admission lifecycle)
- `UNIT` = Unit-based filtering (manager sees only their unit)
- `SELF` = Current user only

---

## 1️⃣ AUTHENTICATION & SESSION

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/auth/register` | POST | ✅ | ✅ | ✅ | ✅ | 📝 3/min | Public |
| `/api/auth/login` | POST | ✅ | ✅ | ✅ | ✅ | 📝 5/min | Public |
| `/api/auth/logout` | POST | ✅ | ✅ | ✅ | ✅ | | Authenticated |
| `/api/auth/check-status` | GET | ✅ | ✅ | ✅ | ✅ | | Session check |
| `/api/auth/forgot-password` | POST | ✅ | ✅ | ✅ | ✅ | 📝 3/hour | Public |
| `/api/auth/reset-password` | POST | ✅ | ✅ | ✅ | ✅ | | Token-based |
| `/api/auth/change-password` | POST | ✅ | ✅ | ✅ | ✅ | 🔐 SELF | Requires current pwd |
| `/api/auth/refresh` | POST | ✅ | ✅ | ✅ | ✅ | | Cookie-based |

---

## 2️⃣ PROFILE & USER

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/profile` | GET | ✅ | ✅ | ✅ | ✅ | SELF | Decision 8 |
| `/api/profile` | PUT | ✅ | ✅ | ✅ | ✅ | SELF | Decision 8 |
| `/api/users/me` | GET | ✅ | ✅ | ✅ | ✅ | SELF | Alias for profile |

---

## 3️⃣ NOTIFICATIONS

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/notifications` | GET | ✅ | ✅ | ✅ | ✅ | SELF | List own only |
| `/api/notifications/mark-as-read` | POST | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/notifications/mark-all-as-read` | POST | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/notifications/{id}` | DELETE | ⚠️ | ⚠️ | ⚠️ | ✅ | IDOR→404 | Decision 2,5 |

---

## 4️⃣ SESSIONS & SECURITY

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/sessions` | GET | ✅ | ✅ | ✅ | ✅ | SELF | List own sessions |
| `/api/sessions/{id}` | DELETE | ⚠️ | ⚠️ | ⚠️ | ✅ | IDOR | Revoke session |
| `/api/sessions/revoke-all` | POST | ✅ | ✅ | ✅ | ✅ | SELF | Revoke all other |
| `/api/security/login-history` | GET | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/security/suspicious-logins` | GET | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/security/confirm-login` | POST | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/security/secure-account` | POST | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/security/trusted-devices` | GET | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/security/trusted-devices/{id}` | DELETE | ⚠️ | ⚠️ | ⚠️ | ✅ | IDOR | |
| `/api/security/trusted-devices` | DELETE | ✅ | ✅ | ✅ | ✅ | SELF | Remove all |

---

## 5️⃣ LEADS

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/leads` | GET | ❌ | ⚠️ | ⚠️ | ✅ | UNIT | Officer: assigned only, Manager: unit only |
| `/api/leads` | POST | ❌ | ✅ | ✅ | ✅ | | Create with auto-assign |
| `/api/leads/{id}` | GET | ❌ | ⚠️ | ⚠️ | ✅ | IDOR→404 | Decision 6 |
| `/api/leads/{id}` | PUT | ❌ | ❌ | ⚠️ | ✅ | IDOR | Manager: unit only |
| `/api/leads/{id}` | DELETE | ❌ | ❌ | ❌ | 🔒 | AUDIT | **Decision 7** - Admin only |
| `/api/leads/{id}/consultations` | POST | ❌ | ⚠️ | ⚠️ | ✅ | IDOR | |
| `/api/leads/{id}/consultations/{cid}` | PUT | ❌ | ⚠️ | ⚠️ | ✅ | IDOR | Officer: latest only |
| `/api/leads/{id}/consultations/{cid}` | DELETE | ❌ | ⚠️ | ⚠️ | ✅ | IDOR | Officer: latest only |
| `/api/leads/{id}/assign` | POST | ❌ | ❌ | ⚠️ | ✅ | IDOR+UNIT | Manager: within unit |
| `/api/leads/{id}/action` | POST | ❌ | ⚠️ | ⚠️ | ✅ | IDOR | Reject/Reassign |
| `/api/leads/{id}/timeline` | GET | ❌ | ⚠️ | ⚠️ | ✅ | IDOR | |
| `/api/leads/{id}/insights` | GET | ❌ | ⚠️ | ⚠️ | ✅ | IDOR | |
| `/api/leads/my/reassign-quota` | GET | ❌ | ✅ | ✅ | ✅ | | Check quota |
| `/api/leads/distribution-preview` | GET | ❌ | ❌ | ✅ | ✅ | | |
| `/api/leads/export` | GET | ❌ | ❌ | ✅ | ✅ | | CSV/XLSX |
| `/api/leads/import/template` | GET | ❌ | ✅ | ✅ | ✅ | | |
| `/api/leads/import` | POST | ❌ | ✅ | ✅ | ✅ | 📝 | Officer import |
| `/api/leads/bulk-assign` | POST | ❌ | ❌ | ✅ | ✅ | UNIT | |
| `/api/leads/bulk-update-stage` | POST | ❌ | ❌ | ❌ | 🔒 | AUDIT | |
| `/api/leads/bulk-delete` | POST | ❌ | ❌ | ❌ | 🔒 | AUDIT | |

---

## 6️⃣ APPLICATIONS

> **REMOVED** — Legacy Application stack retired. See `APPLICATION_LEGACY_CLEANUP.md`.
> All admission workflows now use Section 7 (ADMISSIONS).

---

## 7️⃣ ADMISSIONS (State Machine: Decision 10)

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admissions` | GET | ❌ | ⚠️ | ⚠️ | ✅ | UNIT | Role-filtered list |
| `/api/admissions` | POST | ❌ | ✅ | ✅ | ✅ | | Create profile |
| `/api/admissions/{id}` | GET | ❌ | ⚠️ | ⚠️ | ✅ | IDOR | |
| `/api/admissions/{id}` | PUT | ❌ | ⚠️ | ⚠️ | ✅ | IDOR+STATE | DRAFT only |
| `/api/admissions/{id}` | DELETE | ❌ | ⚠️ | ⚠️ | ✅ | IDOR+STATE | DRAFT only |
| `/api/admissions/{id}/submit` | POST | ❌ | ⚠️ | ⚠️ | ✅ | IDOR+STATE | DRAFT→SUBMITTED |
| `/api/admissions/{id}/documents/{code}/upload` | POST | ❌ | ⚠️ | ⚠️ | ✅ | IDOR+STATE | |
| `/api/admissions/{id}/enroll` | POST | ❌ | ❌ | ❌ | 🔒 | STATE+AUDIT 📝 10/min | EVALUATED→ENROLLED |
| `/api/admissions/{id}/override` | POST | ❌ | ❌ | ❌ | 🔒 | AUDIT | **Decision 11** |

---

## 8️⃣ ADMISSION CONFIG (Read-only for most)

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admission-config/subjects` | GET | ✅ | ✅ | ✅ | ✅ | | |
| `/api/admission-config/subjects/{code}` | GET | ✅ | ✅ | ✅ | ✅ | | |
| `/api/admission-config/subject-groups` | GET | ✅ | ✅ | ✅ | ✅ | | |
| `/api/admission-config/subject-groups/{code}` | GET | ✅ | ✅ | ✅ | ✅ | | |
| `/api/admission-config/methods` | GET | ✅ | ✅ | ✅ | ✅ | | |
| `/api/admission-config/criteria` | GET | ❌ | ⚠️ | ⚠️ | ✅ | VISIBILITY | |
| `/api/admission-config/scoring-preview` | POST | ❌ | ⚠️ | ⚠️ | ✅ | VISIBILITY | |

---

## 9️⃣ PIPELINE CONFIG

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/pipeline/stages` | GET | ❌ | ✅ | ✅ | ✅ | | |
| `/api/pipeline/all` | GET | ❌ | ✅ | ✅ | ✅ | | Full pipeline |
| `/api/pipeline/allowed-next-statuses` | GET | ❌ | ✅ | ✅ | ✅ | | Transition rules |

---

## 🔟 NOTIFICATION CONFIG (Admin Only)

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/notification-rules` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/notification-rules` | POST | ❌ | ❌ | ❌ | ✅ | | |
| `/api/notification-rules/{id}` | GET | ❌ | ❌ | ❌ | ⚠️ | IDOR | |
| `/api/notification-rules/{id}` | PUT | ❌ | ❌ | ❌ | ⚠️ | IDOR | |
| `/api/notification-rules/{id}` | DELETE | ❌ | ❌ | ❌ | ⚠️ | IDOR | |
| `/api/notification-rules/{id}/toggle` | PATCH | ❌ | ❌ | ❌ | ⚠️ | IDOR | |
| `/api/notification-rules/metadata` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/notification-templates` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/notification-templates` | POST | ❌ | ❌ | ❌ | ✅ | | |
| `/api/notification-templates/{id}` | * | ❌ | ❌ | ❌ | ⚠️ | IDOR | |

---

## 1️⃣1️⃣ NOTIFICATION PREFERENCES

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/notification-preferences` | GET | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/notification-preferences` | PUT | ✅ | ✅ | ✅ | ✅ | SELF | |
| `/api/notification-preferences/event-groups` | GET | ✅ | ✅ | ✅ | ✅ | | |
| `/api/notification-preferences/event-groups/{g}` | GET | ✅ | ✅ | ✅ | ✅ | | |
| `/api/notification-preferences/event-groups/{g}` | PUT | ✅ | ✅ | ✅ | ✅ | SELF | |

---

## 1️⃣2️⃣ KPI CONFIG (Decision 4)

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admin/kpi-config/configs` | GET | ❌ | ❌ | ✅ | ✅ | | require_admin_or_manager |
| `/api/admin/kpi-config/configs` | POST | ❌ | ❌ | ❌ | ✅ | | require_admin |
| `/api/admin/kpi-config/configs/{id}` | PUT | ❌ | ❌ | ❌ | ✅ | | require_admin |
| `/api/admin/kpi-config/configs/{id}` | DELETE | ❌ | ❌ | ❌ | ✅ | | require_admin |
| `/api/admin/kpi-config/targets` | GET | ❌ | ❌ | ✅ | ✅ | | |
| `/api/admin/kpi-config/targets` | POST | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/kpi-config/targets/{id}` | PUT | ❌ | ❌ | ❌ | ⚠️ | IDOR | |
| `/api/admin/kpi-config/targets/{id}` | DELETE | ❌ | ❌ | ❌ | ⚠️ | IDOR | |
| `/api/admin/kpi-config/targets/{id}/sync` | POST | ❌ | ❌ | ❌ | ⚠️ | IDOR | Sync YTD |

---

## 1️⃣3️⃣ ADMIN - USER MANAGEMENT

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admin/users` | GET | ❌ | ❌ | ⚠️ | ✅ | UNIT | Manager: unit only |
| `/api/admin/users` | POST | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/users/{id}` | GET | ❌ | ❌ | ⚠️ | ✅ | IDOR+UNIT | |
| `/api/admin/users/{id}` | PUT | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/users/{id}` | DELETE | ❌ | ❌ | ❌ | 🔒 | AUDIT | Soft delete |
| `/api/admin/users/export` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/users/sync` | POST | ❌ | ❌ | ❌ | ✅ | | Casbin sync |
| `/api/admin/users/sync/status` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/users/activity-logs` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/users/statistics` | GET | ❌ | ❌ | ❌ | ✅ | | |

---

## 1️⃣4️⃣ ADMIN - ASSIGNMENT CONFIG

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admin/assignment-config/{unit_id}` | GET | ❌ | ❌ | ⚠️ | ✅ | IDOR+UNIT | Manager: own unit |
| `/api/admin/assignment-config/{unit_id}` | PUT | ❌ | ❌ | ⚠️ | ✅ | IDOR+UNIT | Manager: own unit |

---

## 1️⃣5️⃣ ADMIN - PIPELINE (Decision 3)

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admin/pipeline/stages` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/pipeline/stages` | POST | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/pipeline/stages/{id}` | PUT | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/pipeline/stages/{id}` | DELETE | ❌ | ❌ | ❌ | 🔒 | AUDIT | |
| `/api/admin/pipeline/consultation-statuses` | * | ❌ | ❌ | ❌ | ✅ | | |

---

## 1️⃣6️⃣ ADMIN - ROLES & POLICIES

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admin/roles` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/roles` | POST | ❌ | ❌ | ❌ | 🔒 | AUDIT | Create role |
| `/api/admin/roles/{id}` | DELETE | ❌ | ❌ | ❌ | 🔒 | AUDIT | |
| `/api/admin/policies` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/admin/policies` | POST | ❌ | ❌ | ❌ | 🔒 | AUDIT | Decision 12 |
| `/api/admin/policies` | DELETE | ❌ | ❌ | ❌ | 🔒 | AUDIT | Check CRITICAL |

---

## 1️⃣7️⃣ MONITORING (Decision 3)

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/monitoring/celery/workers` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/monitoring/celery/tasks` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/monitoring/celery/stats` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/monitoring/redis/info` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/monitoring/socket/connections` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/monitoring/notifications/metrics` | GET | ❌ | ❌ | ❌ | ✅ | | |
| `/api/monitoring/system/overview` | GET | ❌ | ❌ | ❌ | ✅ | | |

---

## 1️⃣8️⃣ SYSTEM (Decision 3)

| Endpoint | Method | User | Officer | Manager | Admin | Checks | Ghi chú |
|----------|--------|------|---------|---------|-------|--------|---------|
| `/api/admin/system/alert` | POST | ❌ | ❌ | ❌ | ✅ | | System alert |
| `/health` | GET | ✅ | ✅ | ✅ | ✅ | | Public health check |
| `/api/system/cache-stats` | GET | ❌ | ❌ | ❌ | ✅ | | require_admin |
| `/api/system/health-detailed` | GET | ❌ | ❌ | ❌ | ✅ | | require_admin |

---

## 📊 THỐNG KÊ TỔNG HỢP

### Tổng số endpoints: ~100

| Role | ✅ ALLOW | ❌ DENY | ⚠️ CONDITIONAL | 🔒 BREAK-GLASS |
|------|---------|--------|----------------|----------------|
| **User** | 32 | 68 | 0 | 0 |
| **Officer** | 32 | 40 | 28 | 0 |
| **Manager** | 45 | 30 | 25 | 0 |
| **Admin** | 85 | 0 | 15 | 15 |

### Breakdown by Check Type:

| Check Type | Count | Description |
|------------|-------|-------------|
| **IDOR** | 25 | Ownership verification (returns 404) |
| **STATE** | 8 | Admission state machine check |
| **UNIT** | 12 | Unit-based filtering |
| **SELF** | 18 | Current user only |
| **AUDIT** | 15 | Break-glass with mandatory logging |
| **RATE** | 6 | Rate limited endpoints |

---

## 🔗 REFERENCE TO DECISIONS

| Decision | Endpoints Affected |
|----------|-------------------|
| Decision 1 (Admin Wildcard) | All `/api/admin/*` |
| Decision 2 (404 for IDOR) | All IDOR-protected endpoints |
| Decision 3 (require_admin) | `/api/system/*`, `/api/monitoring/*` |
| Decision 4 (KPI Config) | `/api/admin/kpi-config/*` |
| Decision 5 (Notification Ownership) | `/api/notifications/{id}` |
| Decision 6 (Lead Ownership) | `/api/leads/*` |
| Decision 7 (Manager No DELETE) | `DELETE /api/leads/{id}` |
| Decision 8 (CasbinAuth Default) | 85% of endpoints |
| Decision 9 (Role Inheritance) | Implicit in all Casbin checks |
| Decision 10 (State ≠ Auth) | `/api/admissions/*` actions |
| Decision 11 (Override Audit) | `/api/admissions/{id}/override` |
| Decision 12 (No Retroactive) | Policy change procedures |
| Decision 13 (Audit Retention) | All logged actions |

---

## ⚠️ CRITICAL PATHS (Cần review kỹ)

### 1. Destructive Operations
```
DELETE /api/leads/{id}        → Admin only, soft delete, audit
DELETE /api/admin/users/{id}  → Admin only, soft delete, audit
```

### 2. State Transitions
```
POST /api/admissions/{id}/submit  → STATE: DRAFT → SUBMITTED
POST /api/admissions/{id}/enroll  → STATE: EVALUATED → ENROLLED, Admin only
POST /api/admissions/{id}/override → AUDIT REQUIRED
```

### 3. Policy Changes
```
POST /api/admin/policies   → Creates new permission
DELETE /api/admin/policies → Check CRITICAL_POLICIES before delete
```

---

**END OF AUTHORIZATION MATRIX**

> *"Ma trận này không chỉ là tài liệu.*
> *Nó là hợp đồng giữa code và business."*
