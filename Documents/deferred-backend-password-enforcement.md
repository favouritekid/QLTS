# Backend Enforcement: `password_reset_required` API Protection

> **Status**: 🔄 DEFERRED  
> **Created**: 2025-12-27  
> **Priority**: Medium  
> **Estimated Effort**: 2-4 hours

---

## Overview

Implementtion của `require_password_not_forced` dependency để block API access khi `password_reset_required=true`.

## Problem Statement

Khi user bị flag `password_reset_required=true` (sau khi click "Không phải tôi"):
- **Frontend**: Hiển thị banner yêu cầu đổi mật khẩu ✅
- **Backend**: **KHÔNG block** API calls ⚠️

**Risk**: Hacker có thể bypass frontend và gọi API trực tiếp.

---

## Proposed Solution

Áp dụng `require_password_not_forced` dependency (đã có trong `deps.py`) vào các business routers.

```python
# Example: leads.py
router = APIRouter(
    tags=["Leads"],
    dependencies=[Depends(require_password_not_forced)]
)
```

---

## Implementation Scope

### Routers to PROTECT:
- `leads.py` - All endpoints
- `applications.py` - All endpoints  
- `admissions.py` - All endpoints
- `admin/*.py` - All admin endpoints
- `officer.py`, `organization.py`, `pipeline.py`

### Routers to EXCLUDE:
- `auth.py`: `/change-password`, `/logout`, `/refresh`
- `security.py`: `/confirm-login`, `/secure-account`, `/suspicious-logins`
- `profile.py`, `notifications.py`, `notification_preferences.py`

---

## Prerequisites (MUST DO FIRST)

### 1. Frontend: Disable "Nhắc sau" button
```tsx
// SecurityBanner.tsx
// When password_reset_required=true, hide dismiss button
```

### 2. Frontend: Handle 403 PASSWORD_CHANGE_REQUIRED
```tsx
// API interceptor
if (error.response?.data?.detail?.code === "PASSWORD_CHANGE_REQUIRED") {
  router.push("/settings/security?forced=true");
}
```

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| User lock-out without knowing why | 🔴 Critical | Implement prerequisites first |
| Forgot to exclude essential endpoint | 🔴 Critical | Unit tests for excluded paths |
| Race condition with frontend state | 🟡 Medium | Update user state after password change |

---

## Testing Checklist

- [ ] Login with `password_reset_required=true`
- [ ] Verify business APIs return 403
- [ ] Verify excluded APIs work (change-password, confirm-login)
- [ ] Verify password change clears flag
- [ ] Verify frontend handles 403 correctly

---

## Related Files

- `app/core/deps.py` - `require_password_not_forced` function (line 258)
- `app/core/deps.py` - `PasswordSafeDep` alias (line 303)
- `frontend/src/components/layouts/SecurityBanner.tsx`

---

## References

- Session discussion: 2025-12-27
- Risk assessment artifact: Created during planning
