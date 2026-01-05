# KẾ HOẠCH THỰC HIỆN CẢI TIẾN HỆ THỐNG PHÂN QUYỀN

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-01-05
> **Dựa trên:** Authorization Audit Report, AUTHORIZATION_GUIDELINES.md, MASTER_ARCHITECTURE.md

---

## TỔNG QUAN

### Mục tiêu
Cải thiện hệ thống phân quyền Casbin để:
1. Tuân thủ 100% AUTHORIZATION_GUIDELINES.md
2. Khắc phục các lỗ hổng bảo mật được phát hiện
3. Đơn giản hóa và thống nhất pattern authorization

### Nguyên tắc thực hiện
- **Không breaking change:** Các thay đổi phải backward compatible
- **Refactor on touch:** Khi sửa file, áp dụng chuẩn mới
- **Test first:** Viết test trước khi sửa code
- **Incremental:** Triển khai từng phase, kiểm tra sau mỗi phase

---

## PHASE 0: CƠ SỞ HẠ TẦNG (Ưu tiên: CRITICAL)

### 0.1. Thêm USER vào UserRole Enum

**Vấn đề:** `UserRole` enum thiếu `USER`, gây lỗi khi so sánh role.

**File:** `app/core/constants.py`

**Thay đổi:**
```python
class UserRole(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    OFFICER = "officer"
    USER = "user"  # ← THÊM MỚI
```

**Kiểm tra ảnh hưởng:**
- [ ] Grep tất cả nơi dùng `UserRole`
- [ ] Đảm bảo không có hardcode `"user"` string

**Test:**
```python
def test_user_role_has_user():
    assert UserRole.USER == "user"
    assert "user" in [r.value for r in UserRole]
```

---

### 0.2. Tạo file tài liệu chuẩn

**Tạo mới:**
- [ ] `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md` (copy từ nội dung đã cung cấp)
- [ ] `Backend_FastAPI/MASTER_ARCHITECTURE.md` (copy từ nội dung đã cung cấp)

**Lý do:** Code đã reference nhưng file chưa tồn tại.

---

## PHASE 1: THỐNG NHẤT AUTHORIZATION PATTERN (Ưu tiên: HIGH)

### 1.1. Phân tích hiện trạng

**Vấn đề:** Hệ thống dùng 2 pattern song song:

| Pattern | Cơ chế | Vấn đề |
|---------|--------|--------|
| `CasbinAuth` | Casbin enforce `(user, path, method)` | Dynamic, có thể thay đổi policy |
| `require_*` | So sánh `user.role` string | Static, bypass Casbin |

**Theo AUTHORIZATION_GUIDELINES.md Section 3:**
> "A. Casbin RBAC (Dynamic) - DEFAULT"
> "B. Role-Based (Static) - When Needed"

→ Cả 2 đều được phép, nhưng phải **nhất quán** trong cùng module.

### 1.2. Quy tắc áp dụng

| Module | Nên dùng | Lý do |
|--------|----------|-------|
| `/api/admin/*` | `CasbinAuth` | Policy có thể thay đổi |
| `/api/leads/*` | `CasbinAuth` + IDOR deps | Dynamic + ownership check |
| `/api/officer/*` | `CasbinAuth` | Officer-specific policies |
| `/api/kpi-config/*` | `require_admin` | Static, internal only |
| `/api/system/*` | `require_admin` | Static, internal only |

### 1.3. Danh sách endpoint cần review

**Tìm các endpoint dùng cả 2 pattern:**

```bash
# Tìm file dùng cả CasbinAuth và require_*
grep -l "CasbinAuth" app/routers/**/*.py | xargs grep -l "require_admin\|require_roles"
```

**Action:**
- [ ] Liệt kê tất cả endpoint có vấn đề
- [ ] Quyết định pattern cho từng module
- [ ] Refactor để nhất quán

### 1.4. Template chuẩn cho endpoint mới

```python
# ============ BUSINESS API (Casbin) ============
@router.get("/items")
async def get_items(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = CasbinAuth,  # Layer 2: Authorization
):
    ...

# ============ ADMIN INTERNAL API (Static) ============
@router.get("/config")
async def get_config(
    request: Request,
    current_user: models.User = Depends(require_admin),  # Layer 2: Authorization
):
    ...

# ============ API VỚI IDOR PROTECTION ============
@router.get("/leads/{lead_id}")
async def get_lead(
    request: Request,
    lead: models.Lead = Depends(get_lead_for_user),  # Layer 3: IDOR
    # current_user đã được inject trong get_lead_for_user
):
    return lead
```

---

## PHASE 2: TĂNG CƯỜNG IDOR PROTECTION (Ưu tiên: HIGH)

### 2.1. Kiểm tra độ bao phủ IDOR

**Theo MASTER_ARCHITECTURE.md Section D.1:**
> "Defense: Dependency Injection Resource Access"
> "Mechanism: `get_resource_access` dependency fetches AND checks ownership"

**Checklist tài nguyên cần IDOR:**

| Resource | Dependency hiện có | Status |
|----------|-------------------|--------|
| Lead | `get_lead_for_user` | ✅ |
| Application | `get_application_for_user` | ✅ |
| Notification | ❓ Cần kiểm tra | ⚠️ |
| Consultation | ❓ Cần kiểm tra | ⚠️ |
| Document | ❓ Cần kiểm tra | ⚠️ |

### 2.2. Tạo dependency IDOR còn thiếu

**Pattern theo AUTHORIZATION_GUIDELINES.md Section 4:**

```python
# deps.py
async def get_consultation_for_user(
    consultation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> models.Consultation:
    """
    IDOR Protection cho Consultation.

    - Admin: Xem tất cả
    - Manager: Xem trong unit
    - Officer: Chỉ xem của lead được gán
    """
    repo = ConsultationRepository(db)
    consultation = await repo.get_with_lead(consultation_id)

    if not consultation:
        raise ResourceNotFoundError("Consultation not found")

    # IDOR CHECK - Luôn trả 404, không 403
    if current_user.role == UserRole.ADMIN:
        return consultation

    if current_user.role == UserRole.MANAGER:
        if consultation.lead.unit_id != current_user.unit_id:
            raise ResourceNotFoundError("Consultation not found")
        return consultation

    # Officer chỉ xem consultation của lead được gán
    if consultation.lead.assigned_officer_id != current_user.id:
        raise ResourceNotFoundError("Consultation not found")

    return consultation
```

### 2.3. Migration các endpoint chưa có IDOR

**Tìm endpoint truy cập trực tiếp DB:**

```bash
grep -n "db.get\|db.execute" app/routers/**/*.py
```

**Action:**
- [ ] Liệt kê endpoint vi phạm
- [ ] Tạo dependency tương ứng
- [ ] Refactor endpoint

---

## PHASE 3: KHẮC PHỤC VẤN ĐỀ POLICY (Ưu tiên: MEDIUM)

### 3.1. Manager Wildcard Lead Access

**Vấn đề:** Policy `(role:manager, /api/leads/*, .*)` cho phép ALL operations.

**Giải pháp:** Thay wildcard bằng explicit policies:

```sql
-- HIỆN TẠI (Quá rộng)
DELETE FROM casbin_rule WHERE v0 = 'role:manager' AND v1 = '/api/leads/*';

-- THAY THẾ (Explicit)
INSERT INTO casbin_rule (ptype, v0, v1, v2) VALUES
('p', 'role:manager', '/api/leads', 'GET'),
('p', 'role:manager', '/api/leads', 'POST'),
('p', 'role:manager', '/api/leads/{lead_id}', 'GET'),
('p', 'role:manager', '/api/leads/{lead_id}', 'PUT'),
('p', 'role:manager', '/api/leads/{lead_id}/consultations', 'GET'),
('p', 'role:manager', '/api/leads/{lead_id}/consultations', 'POST'),
-- Manager KHÔNG được DELETE lead
-- Manager KHÔNG được bulk operations
;
```

**Tạo migration:**
- [ ] File: `alembic/versions/xxx_refine_manager_lead_policies.py`
- [ ] Test rollback

### 3.2. Sử dụng Role Inheritance

**Vấn đề:** Cùng policy khai báo cho nhiều role (duplication).

**Hiện tại:**
```
(role:user, /api/profile, GET)
(role:officer, /api/profile, GET)  # Duplicate
(role:manager, /api/profile, GET)  # Duplicate
```

**Cải tiến với grouping policy:**
```
-- Base permissions cho role:user
(role:user, /api/profile, GET)
(role:user, /api/profile, PUT)
(role:user, /api/notifications, GET)

-- Role inheritance
g, role:officer, role:user
g, role:manager, role:officer
g, role:admin, role:manager
```

**Lợi ích:**
- Giảm số policy từ ~50 xuống ~20
- Dễ maintain
- Tự động inherit khi thêm permission cho role thấp

**Action:**
- [ ] Vẽ sơ đồ role hierarchy
- [ ] Tạo migration để restructure policies
- [ ] Test implicit permissions

---

## PHASE 4: BẢO MẬT BỔ SUNG (Ưu tiên: MEDIUM)

### 4.1. Enforce Password Reset Check

**Vấn đề:** `require_password_not_forced` là optional dependency.

**Giải pháp:** Tạo composite dependency mặc định:

```python
# deps.py

async def get_secure_active_user(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Composite dependency cho sensitive operations.
    Kết hợp: active check + password reset check
    """
    if current_user.password_reset_required:
        raise PermissionDeniedError(
            "Password change required before accessing this resource"
        )
    return current_user

# Alias cho dễ dùng
SecureUser = Depends(get_secure_active_user)
```

**Áp dụng cho:**
- [ ] Change email endpoint
- [ ] Change phone endpoint
- [ ] Financial operations
- [ ] API key management

### 4.2. Rate Limiting cho Sensitive Endpoints

**Kiểm tra endpoint nhạy cảm có rate limit:**

| Endpoint | Rate Limit | Status |
|----------|------------|--------|
| POST /api/auth/login | ✅ | OK |
| POST /api/auth/forgot-password | ⚠️ | Cần kiểm tra |
| DELETE /api/admin/roles/* | ✅ | OK |
| POST /api/admin/roles/policies | ✅ | OK |

---

## PHASE 5: TESTING & DOCUMENTATION (Ưu tiên: HIGH)

### 5.1. Authorization Integration Tests

**Tạo test matrix:**

```python
# tests/security/test_authorization_matrix.py

@pytest.mark.parametrize("role,endpoint,method,expected", [
    # Admin - Full access
    (UserRole.ADMIN, "/api/admin/users", "GET", 200),
    (UserRole.ADMIN, "/api/admin/users", "POST", 200),
    (UserRole.ADMIN, "/api/leads", "DELETE", 200),

    # Manager - Limited admin
    (UserRole.MANAGER, "/api/admin/users", "GET", 200),
    (UserRole.MANAGER, "/api/admin/roles", "GET", 403),  # Cannot manage roles
    (UserRole.MANAGER, "/api/leads", "GET", 200),

    # Officer - Lead operations only
    (UserRole.OFFICER, "/api/admin/users", "GET", 403),
    (UserRole.OFFICER, "/api/leads", "GET", 200),
    (UserRole.OFFICER, "/api/leads", "POST", 200),

    # User - Profile only
    (UserRole.USER, "/api/profile", "GET", 200),
    (UserRole.USER, "/api/leads", "GET", 403),
])
async def test_role_permissions(role, endpoint, method, expected, test_client):
    ...
```

### 5.2. IDOR Tests

```python
# tests/security/test_idor_protection.py

async def test_officer_cannot_access_other_lead(test_client, officer_user, other_lead):
    """Officer không thể xem lead của người khác."""
    response = await test_client.get(
        f"/api/leads/{other_lead.id}",
        headers=auth_headers(officer_user)
    )
    assert response.status_code == 404  # NOT 403!

async def test_manager_cannot_access_other_unit_lead(test_client, manager_user, other_unit_lead):
    """Manager không thể xem lead của unit khác."""
    response = await test_client.get(
        f"/api/leads/{other_unit_lead.id}",
        headers=auth_headers(manager_user)
    )
    assert response.status_code == 404  # NOT 403!
```

### 5.3. Cập nhật Documentation

- [ ] Thêm section Authorization vào API docs
- [ ] Tạo diagram cho permission flow
- [ ] Document tất cả dependencies trong deps.py

---

## TIMELINE VÀ PHÂN CÔNG

### Sprint 1 (Tuần 1-2): Foundation
| Task | Priority | Effort |
|------|----------|--------|
| Phase 0.1: Thêm USER enum | CRITICAL | 1h |
| Phase 0.2: Tạo file docs | CRITICAL | 30m |
| Phase 5.1: Viết auth tests | HIGH | 4h |

### Sprint 2 (Tuần 3-4): Authorization Cleanup
| Task | Priority | Effort |
|------|----------|--------|
| Phase 1.3: Liệt kê endpoints | HIGH | 2h |
| Phase 1.4: Refactor endpoints | HIGH | 8h |
| Phase 2.1: Audit IDOR coverage | HIGH | 2h |

### Sprint 3 (Tuần 5-6): Policy Refinement
| Task | Priority | Effort |
|------|----------|--------|
| Phase 3.1: Refine manager policies | MEDIUM | 4h |
| Phase 3.2: Implement inheritance | MEDIUM | 6h |
| Phase 5.2: IDOR tests | HIGH | 4h |

### Sprint 4 (Tuần 7-8): Hardening
| Task | Priority | Effort |
|------|----------|--------|
| Phase 4.1: Secure user dep | MEDIUM | 2h |
| Phase 4.2: Rate limit audit | MEDIUM | 2h |
| Phase 5.3: Documentation | MEDIUM | 4h |

---

## CHECKLIST HOÀN THÀNH

### Phase 0: Cơ sở hạ tầng
- [ ] `UserRole.USER` đã được thêm
- [ ] `AUTHORIZATION_GUIDELINES.md` đã tạo
- [ ] `MASTER_ARCHITECTURE.md` đã tạo

### Phase 1: Authorization Pattern
- [ ] Tất cả endpoint đã review
- [ ] Pattern đã thống nhất theo module
- [ ] Không còn inline role check trong router

### Phase 2: IDOR Protection
- [ ] Tất cả resource có dependency
- [ ] Không còn `db.get()` trong router
- [ ] Trả 404 (không 403) cho unauthorized

### Phase 3: Policy
- [ ] Manager không còn wildcard
- [ ] Role inheritance đã implement
- [ ] Policy count giảm 30%+

### Phase 4: Security
- [ ] Sensitive endpoints có password check
- [ ] Rate limit đã audit

### Phase 5: Testing
- [ ] Auth matrix test đạt 100%
- [ ] IDOR test đạt 100%
- [ ] Docs đã cập nhật

---

## APPENDIX: COMMANDS HỮU ÍCH

```bash
# Tìm endpoint thiếu authorization
grep -rn "async def " app/routers/ | grep -v "CasbinAuth\|require_\|Depends"

# Tìm inline role check (vi phạm)
grep -rn "user.role ==" app/routers/

# Tìm direct DB access trong router (vi phạm)
grep -rn "db.get\|db.execute\|db.query" app/routers/

# Tìm HTTPException trong service (vi phạm)
grep -rn "HTTPException" app/services/

# Count policies per role
SELECT v0, COUNT(*) FROM casbin_rule WHERE ptype = 'p' GROUP BY v0;
```

---

**KẾT THÚC KẾ HOẠCH**

> *"Authorization không phải là việc làm code chạy được.*
> *Đó là việc ngủ ngon, pass audit, và không cháy production."*
>
> — AUTHORIZATION_GUIDELINES.md
