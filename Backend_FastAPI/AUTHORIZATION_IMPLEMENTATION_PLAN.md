# KẾ HOẠCH THỰC HIỆN CẢI TIẾN HỆ THỐNG PHÂN QUYỀN

> **Phiên bản:** 2.0
> **Ngày tạo:** 2026-01-05
> **Cập nhật:** 2026-01-05 (thêm Guardrails, Policy Drift Detection)
> **Dựa trên:** Authorization Audit Report, AUTHORIZATION_GUIDELINES.md, MASTER_ARCHITECTURE.md

---

## TỔNG QUAN

### Mục tiêu
Cải thiện hệ thống phân quyền Casbin để:
1. Tuân thủ 100% AUTHORIZATION_GUIDELINES.md
2. Khắc phục các lỗ hổng bảo mật được phát hiện
3. Đơn giản hóa và thống nhất pattern authorization
4. **MỚI:** Chặn vi phạm ở CI/CD, không chỉ code review

### Nguyên tắc thực hiện
- **Không breaking change:** Các thay đổi phải backward compatible
- **Refactor on touch:** Khi sửa file, áp dụng chuẩn mới
- **Test first:** Viết test trước khi sửa code
- **Incremental:** Triển khai từng phase, kiểm tra sau mỗi phase
- **MỚI: Guardrails first:** CI chặn trước khi code vào repo

---

## PHASE -1: GUARDRAILS (Ưu tiên: CRITICAL - LÀM ĐẦU TIÊN)

> **Triết lý:** Test có mà không chặn PR thì coi như chưa có.

### -1.1. CI Pre-commit Rules

**Tạo file:** `.github/workflows/authorization-check.yml`

```yaml
name: Authorization Guardrails

on: [pull_request]

jobs:
  auth-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Check for inline role checks in routers
        run: |
          if grep -rn "user\.role ==" app/routers/; then
            echo "❌ FAIL: Inline role check detected in router"
            echo "   Move to deps.py dependency instead"
            exit 1
          fi

      - name: Check for db.get() in routers
        run: |
          if grep -rn "db\.get\|await db\.get" app/routers/; then
            echo "❌ FAIL: Direct db.get() in router (IDOR risk)"
            echo "   Use get_{resource}_for_user dependency"
            exit 1
          fi

      - name: Check router has authorization
        run: |
          # Find routers without CasbinAuth or require_*
          python scripts/check_router_auth.py
```

**Tạo file:** `scripts/check_router_auth.py`

```python
#!/usr/bin/env python3
"""
CI Script: Kiểm tra tất cả router endpoint có authorization.

Rules:
- Mỗi async def trong router PHẢI có:
  - CasbinAuth, hoặc
  - require_admin, hoặc
  - require_admin_or_manager, hoặc
  - require_any_staff, hoặc
  - require_roles
- Ngoại trừ: endpoints trong WHITELIST (auth, health)
"""
import re
import sys
from pathlib import Path

WHITELIST_FILES = {
    "auth.py",      # Login, register không cần auth
    "monitoring.py", # Health check
}

WHITELIST_FUNCTIONS = {
    "health",
    "health_detailed",
    "login",
    "register",
    "refresh_token",
    "forgot_password",
    "reset_password",
}

AUTH_PATTERNS = [
    r"CasbinAuth",
    r"require_admin",
    r"require_admin_or_manager",
    r"require_any_staff",
    r"require_roles",
    r"get_current_active_user",  # Cho các endpoint đặc biệt
]

def check_file(filepath: Path) -> list[str]:
    """Kiểm tra 1 file router."""
    errors = []
    content = filepath.read_text()

    # Tìm tất cả async def
    for match in re.finditer(r"async def (\w+)\([^)]*\):", content):
        func_name = match.group(1)
        start = match.start()

        # Skip whitelist
        if func_name in WHITELIST_FUNCTIONS:
            continue

        # Tìm decorator và signature (200 chars trước async def)
        context = content[max(0, start-500):start + 500]

        # Kiểm tra có auth pattern không
        has_auth = any(re.search(pattern, context) for pattern in AUTH_PATTERNS)

        if not has_auth:
            errors.append(f"{filepath}:{func_name} - Missing authorization dependency")

    return errors

def main():
    errors = []
    router_dir = Path("app/routers")

    for filepath in router_dir.rglob("*.py"):
        if filepath.name in WHITELIST_FILES:
            continue
        if filepath.name.startswith("_"):
            continue

        file_errors = check_file(filepath)
        errors.extend(file_errors)

    if errors:
        print("❌ Authorization check FAILED:")
        for err in errors:
            print(f"   {err}")
        sys.exit(1)
    else:
        print("✅ All router endpoints have authorization")
        sys.exit(0)

if __name__ == "__main__":
    main()
```

### -1.2. Policy Drift Detection (Deploy Guard)

**Thêm vào:** `scripts/pre_deploy_check.py`

```python
#!/usr/bin/env python3
"""
Pre-deploy check: Đảm bảo admin không bị lockout.

Chạy TRƯỚC MỌI DEPLOY.
"""
import asyncio
import sys
from sqlalchemy import text
from app.database import async_db_engine

CRITICAL_POLICIES = [
    # (v0, v1, v2) - Admin wildcard PHẢI tồn tại
    ("role:admin", "/*", ".*"),
]

async def check_critical_policies():
    async with async_db_engine.connect() as conn:
        for v0, v1, v2 in CRITICAL_POLICIES:
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM casbin_rule
                WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
            """), {"v0": v0, "v1": v1, "v2": v2})

            count = result.scalar()
            if count == 0:
                print(f"🚨 CRITICAL: Missing policy ({v0}, {v1}, {v2})")
                print("   Admin lockout risk! DEPLOY BLOCKED.")
                return False

    print("✅ All critical policies present")
    return True

if __name__ == "__main__":
    success = asyncio.run(check_critical_policies())
    sys.exit(0 if success else 1)
```

**Thêm vào CI/CD pipeline:**

```yaml
# .github/workflows/deploy.yml
- name: Pre-deploy policy check
  run: python scripts/pre_deploy_check.py
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

### -1.3. Checklist Phase -1

- [ ] File `authorization-check.yml` đã tạo
- [ ] File `check_router_auth.py` đã tạo và test local
- [ ] File `pre_deploy_check.py` đã tạo
- [ ] CI chạy pass trên branch hiện tại
- [ ] Team đã được thông báo về guardrails mới

**Effort:** 2-3h
**ROI:** Chặn 90% lỗi authorization trước khi vào main branch

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

**Đã hoàn thành:**
- [x] `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md`
- [x] `Backend_FastAPI/MASTER_ARCHITECTURE.md`

**Cần tạo thêm:**
- [ ] `Backend_FastAPI/AUTHORIZATION_DECISIONS.md` (xem Phase 0.3)

---

### 0.3. Tạo AUTHORIZATION_DECISIONS.md (MỚI)

> **Mục đích:** Ghi lại LÝ DO đằng sau các quyết định authorization.
> Sau 1 năm, file này cứu team khỏi audit drama.

**Nội dung cần có:**

```markdown
# Authorization Decisions Log

## Decision 1: Admin Wildcard Policy
- **Quyết định:** Admin có policy `(role:admin, /*, .*)`
- **Lý do:** Admin cần full access để recovery khi có sự cố
- **Rủi ro:** Nếu xóa nhầm → lockout toàn bộ system
- **Mitigation:** Pre-deploy check, CRITICAL_POLICIES protection
- **Ngày:** 2026-01-05
- **Người quyết định:** [Tên]

## Decision 2: IDOR trả 404 thay vì 403
- **Quyết định:** Khi user truy cập resource không sở hữu → trả 404
- **Lý do:** Tránh inference attack (user đoán ID tồn tại)
- **Reference:** OWASP IDOR Prevention
- **Ngày:** 2026-01-05

## Decision 3: /api/system/* dùng require_admin
- **Quyết định:** Các endpoint system dùng static role check
- **Lý do:** Internal-only, không cần dynamic policy
- **Constraint:** Chỉ áp dụng cho endpoint KHÔNG public-facing
- **Review trigger:** Nếu endpoint có thể gọi từ client → chuyển sang Casbin
- **Ngày:** 2026-01-05
```

---

## PHASE 1: THỐNG NHẤT AUTHORIZATION PATTERN (Ưu tiên: HIGH)

### 1.1. Quy tắc áp dụng (ĐÃ CHỈNH)

| Module | Pattern | Lý do | Constraint |
|--------|---------|-------|------------|
| `/api/admin/*` | `CasbinAuth` | Policy có thể thay đổi | - |
| `/api/leads/*` | `CasbinAuth` + IDOR | Dynamic + ownership | - |
| `/api/officer/*` | `CasbinAuth` | Officer-specific | - |
| `/api/system/*` | `require_admin` | Internal only | **Phải có comment lý do** |
| `/api/internal/*` | `require_admin` | Internal only | **Không expose ra client** |
| `/api/kpi-config/*` | `require_admin` | Static, internal | - |

### 1.2. Rule mới (QUAN TRỌNG)

```yaml
RULES:
  - CasbinAuth là DEFAULT cho mọi API
  - require_admin chỉ được dùng khi:
    - Endpoint là internal-only (không public-facing)
    - CÓ COMMENT giải thích lý do
    - Đã ghi vào AUTHORIZATION_DECISIONS.md

  - ❌ KHÔNG ĐƯỢC dùng require_admin cho:
    - API mà client (web/mobile) gọi trực tiếp
    - API có thể cần phân quyền chi tiết sau này
```

### 1.3. Template khi dùng require_admin

```python
@router.get("/system/cache-stats")
async def get_cache_stats(
    request: Request,
    # AUTH: require_admin vì:
    # - Internal monitoring only
    # - Không cần dynamic policy
    # - Đã ghi vào AUTHORIZATION_DECISIONS.md
    current_user: models.User = Depends(require_admin),
):
    ...
```

### 1.4. Danh sách endpoint cần review

```bash
# Tìm endpoint dùng require_* để review
grep -rn "require_admin\|require_roles" app/routers/ --include="*.py"
```

**Action:**
- [ ] Liệt kê tất cả endpoint dùng require_*
- [ ] Với mỗi endpoint: xác nhận đúng là internal-only
- [ ] Thêm comment giải thích
- [ ] Ghi vào AUTHORIZATION_DECISIONS.md

---

## PHASE 2: TĂNG CƯỜNG IDOR PROTECTION (Ưu tiên: HIGH)

### 2.1. Checklist tài nguyên cần IDOR (ĐÃ CẬP NHẬT)

| Resource | Dependency | Status | Priority |
|----------|-----------|--------|----------|
| Lead | `get_lead_for_user` | ✅ Có | - |
| Application | `get_application_for_user` | ✅ Có | - |
| **Notification** | `get_notification_for_user` | ❌ **THIẾU** | **CRITICAL** |
| Consultation | `get_consultation_for_user` | ❌ Thiếu | HIGH |
| Document | `get_document_for_user` | ❌ Thiếu | HIGH |
| KPI Target | `get_kpi_target_for_user` | ⚠️ Cần kiểm tra | MEDIUM |

### 2.2. Notification IDOR (CRITICAL - LÀM NGAY)

> **Cảnh báo:** Notification IDOR là lỗ hổng dễ bị bỏ sót nhất.
> User có thể delete notification của người khác nếu không có check.

**Tạo dependency:**

```python
# deps.py
async def get_notification_for_user(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> models.Notification:
    """
    IDOR Protection cho Notification.

    Rules:
    - Admin: Xem tất cả
    - User/Officer/Manager: Chỉ xem notification của mình
    """
    repo = NotificationRepository(db)
    notification = await repo.get(notification_id)

    if not notification:
        raise ResourceNotFoundError("Notification not found")

    # Admin có thể xem tất cả
    if current_user.role == UserRole.ADMIN:
        return notification

    # User chỉ xem notification của mình
    if notification.user_id != current_user.id:
        raise ResourceNotFoundError("Notification not found")  # 404, không 403

    return notification
```

**Update router:**

```python
# TRƯỚC (NGUY HIỂM)
@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = CasbinAuth,
):
    notification = await db.get(models.Notification, notification_id)  # ❌ IDOR!
    ...

# SAU (AN TOÀN)
@router.delete("/notifications/{notification_id}")
async def delete_notification(
    request: Request,
    notification: models.Notification = Depends(get_notification_for_user),  # ✅
    db: AsyncSession = Depends(get_db),
):
    await db.delete(notification)
    await db.commit()
    ...
```

### 2.3. Consultation IDOR

```python
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

---

## PHASE 3: KHẮC PHỤC VẤN ĐỀ POLICY (Ưu tiên: MEDIUM)

### 3.1. Manager Wildcard Lead Access

**Vấn đề:** Policy `(role:manager, /api/leads/*, .*)` cho phép ALL operations.

**Giải pháp:** Thay wildcard bằng explicit policies.

### 3.2. Safety Net cho Migration (QUAN TRỌNG)

> **Rule sống còn:** TRƯỚC và SAU mọi migration policy → assert admin wildcard tồn tại.

**Migration template:**

```python
# alembic/versions/xxx_refine_manager_lead_policies.py

def upgrade():
    # ========== SAFETY CHECK TRƯỚC ==========
    conn = op.get_bind()
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing BEFORE migration")

    # ========== MIGRATION ==========
    # Xóa wildcard cũ
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/leads/*'
    """)

    # Thêm explicit policies
    policies = [
        ('role:manager', '/api/leads', 'GET'),
        ('role:manager', '/api/leads', 'POST'),
        ('role:manager', '/api/leads/{lead_id}', 'GET'),
        ('role:manager', '/api/leads/{lead_id}', 'PUT'),
        ('role:manager', '/api/leads/{lead_id}/consultations', 'GET'),
        ('role:manager', '/api/leads/{lead_id}/consultations', 'POST'),
        # Manager KHÔNG được DELETE lead
    ]

    for v0, v1, v2 in policies:
        op.execute(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', '{v0}', '{v1}', '{v2}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'
            )
        """)

    # ========== SAFETY CHECK SAU ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER migration")


def downgrade():
    # Rollback: khôi phục wildcard
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/leads/*', '.*'
        WHERE NOT EXISTS (...)
    """)
    # Xóa explicit policies...
```

### 3.3. Sử dụng Role Inheritance (Giảm duplication)

**Hiện tại (duplicate):**
```
(role:user, /api/profile, GET)
(role:officer, /api/profile, GET)
(role:manager, /api/profile, GET)
```

**Cải tiến:**
```sql
-- Base permissions
INSERT INTO casbin_rule (ptype, v0, v1, v2) VALUES
('p', 'role:user', '/api/profile', 'GET'),
('p', 'role:user', '/api/profile', 'PUT'),
('p', 'role:user', '/api/notifications', 'GET');

-- Role inheritance
INSERT INTO casbin_rule (ptype, v0, v1) VALUES
('g', 'role:officer', 'role:user'),
('g', 'role:manager', 'role:officer'),
('g', 'role:admin', 'role:manager');
```

**Lợi ích:**
- Giảm policy từ ~50 xuống ~20
- Thêm permission cho role:user → tất cả role cao hơn tự có

---

## PHASE 4: BẢO MẬT BỔ SUNG (Ưu tiên: MEDIUM)

### 4.1. Enforce Password Reset Check

```python
# deps.py
async def get_secure_active_user(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Composite dependency cho sensitive operations.
    """
    if current_user.password_reset_required:
        raise PermissionDeniedError(
            "Password change required before accessing this resource"
        )
    return current_user

# Alias
SecureUser = Depends(get_secure_active_user)
```

### 4.2. Rate Limiting Audit

| Endpoint | Sensitive? | Rate Limit | Status |
|----------|------------|------------|--------|
| POST /auth/login | ✅ | 5/minute | ✅ OK |
| POST /auth/forgot-password | ✅ | 3/hour | ⚠️ Check |
| DELETE /admin/roles/* | ✅ | 50/hour | ✅ OK |
| POST /admin/policies/batch | ✅ | 10/hour | ✅ OK |

---

## PHASE 5: TESTING & DOCUMENTATION (Ưu tiên: HIGH)

### 5.1. Authorization Integration Tests

```python
# tests/security/test_authorization_matrix.py

@pytest.mark.parametrize("role,endpoint,method,expected", [
    # Admin - Full access
    (UserRole.ADMIN, "/api/admin/users", "GET", 200),
    (UserRole.ADMIN, "/api/leads", "DELETE", 200),

    # Manager - Limited
    (UserRole.MANAGER, "/api/admin/users", "GET", 200),
    (UserRole.MANAGER, "/api/admin/roles", "GET", 403),

    # Officer - Lead ops only
    (UserRole.OFFICER, "/api/admin/users", "GET", 403),
    (UserRole.OFFICER, "/api/leads", "GET", 200),

    # User - Profile only
    (UserRole.USER, "/api/profile", "GET", 200),
    (UserRole.USER, "/api/leads", "GET", 403),
])
async def test_role_permissions(role, endpoint, method, expected, test_client):
    ...
```

### 5.2. IDOR Tests (QUAN TRỌNG)

```python
# tests/security/test_idor_protection.py

async def test_notification_idor_returns_404(test_client, user_a, user_b):
    """User A không thể xem notification của User B."""
    # Tạo notification cho user_b
    notif = await create_notification(user_id=user_b.id)

    # User A cố truy cập
    response = await test_client.get(
        f"/api/notifications/{notif.id}",
        headers=auth_headers(user_a)
    )

    # PHẢI trả 404, KHÔNG PHẢI 403
    assert response.status_code == 404

async def test_notification_delete_idor(test_client, user_a, user_b):
    """User A không thể xóa notification của User B."""
    notif = await create_notification(user_id=user_b.id)

    response = await test_client.delete(
        f"/api/notifications/{notif.id}",
        headers=auth_headers(user_a)
    )

    assert response.status_code == 404
    # Verify notification vẫn tồn tại
    assert await notification_exists(notif.id)
```

### 5.3. CI Gate (BẮT BUỘC)

**Thêm vào `.github/workflows/test.yml`:**

```yaml
- name: Run authorization tests
  run: |
    pytest tests/security/test_authorization_matrix.py -v
    pytest tests/security/test_idor_protection.py -v

- name: Authorization tests must pass
  if: failure()
  run: |
    echo "❌ Authorization tests failed - PR blocked"
    exit 1
```

---

## TIMELINE CẬP NHẬT

### Sprint 0 (Tuần 0 - LÀM NGAY)
| Task | Priority | Effort |
|------|----------|--------|
| Phase -1: Tạo CI guardrails | **CRITICAL** | 3h |
| Phase -1: Test guardrails local | **CRITICAL** | 1h |

### Sprint 1 (Tuần 1-2)
| Task | Priority | Effort |
|------|----------|--------|
| Phase 0.1: Thêm USER enum | CRITICAL | 1h |
| Phase 0.3: Tạo AUTHORIZATION_DECISIONS.md | HIGH | 2h |
| Phase 2.2: Notification IDOR (CRITICAL) | **CRITICAL** | 2h |
| Phase 5.1-5.2: Viết tests | HIGH | 4h |

### Sprint 2 (Tuần 3-4)
| Task | Priority | Effort |
|------|----------|--------|
| Phase 1: Review + refactor endpoints | HIGH | 8h |
| Phase 2: Tạo các IDOR dependency còn lại | HIGH | 4h |

### Sprint 3 (Tuần 5-6)
| Task | Priority | Effort |
|------|----------|--------|
| Phase 3.1: Migration manager policies | MEDIUM | 4h |
| Phase 3.3: Implement role inheritance | MEDIUM | 6h |

### Sprint 4 (Tuần 7-8)
| Task | Priority | Effort |
|------|----------|--------|
| Phase 4: Security hardening | MEDIUM | 4h |
| Phase 5.3: Documentation update | MEDIUM | 4h |

---

## CHECKLIST HOÀN THÀNH

### Phase -1: Guardrails
- [x] CI authorization check workflow hoạt động (`.github/workflows/authorization-check.yml`)
- [x] Pre-deploy policy check hoạt động (`scripts/pre_deploy_check.py`)
- [ ] Team đã được training về guardrails

### Phase 0: Cơ sở hạ tầng
- [x] `UserRole.USER` đã được thêm (`app/core/constants.py`)
- [x] `AUTHORIZATION_DECISIONS.md` đã tạo
- [x] Tất cả decisions đã được ghi lại

### Phase 1: Authorization Pattern
- [x] Tất cả `require_admin` có comment lý do (`kpi_config.py` updated)
- [x] Không có inline role check trong router (verified by CI script)
- [x] AUTHORIZATION_DECISIONS.md đã cập nhật

### Phase 2: IDOR Protection
- [x] **Notification IDOR đã implement** (`get_notification_for_user` in `deps.py`)
- [x] Consultation IDOR đã phân tích - protected via Lead IDOR + service validation
- [x] Không còn `db.get()` trong router (verified by grep)
- [x] Tất cả trả 404 cho unauthorized (IDOR prevention pattern)

### Phase 3: Policy
- [x] Manager không còn wildcard (migration `p3a1b2c3d4e5`)
- [x] Migration có safety checks (admin wildcard verified before/after)
- [x] Role inheritance đã implement (`g` policies in migration)

### Phase 4: Security
- [ ] Sensitive endpoints có password check
- [ ] Rate limit đã audit

### Phase 5: Testing
- [ ] Auth matrix test đạt 100%
- [x] IDOR test đã viết (`tests/security/test_idor_protection.py`)
- [ ] **CI gate chặn PR khi test fail**

---

## APPENDIX: COMMANDS HỮU ÍCH

```bash
# Tìm endpoint thiếu authorization
grep -rn "async def " app/routers/ | grep -v "CasbinAuth\|require_\|Depends"

# Tìm inline role check (vi phạm)
grep -rn "user\.role ==" app/routers/

# Tìm direct DB access trong router (vi phạm IDOR)
grep -rn "db\.get\|await db\.get" app/routers/

# Tìm HTTPException trong service (vi phạm architecture)
grep -rn "HTTPException" app/services/

# Kiểm tra admin policy tồn tại
psql -c "SELECT * FROM casbin_rule WHERE v0 = 'role:admin' AND v1 = '/*'"

# Count policies per role
psql -c "SELECT v0, COUNT(*) FROM casbin_rule WHERE ptype = 'p' GROUP BY v0"
```

---

**KẾT THÚC KẾ HOẠCH V2.0**

> *"Test có mà không chặn PR thì coi như chưa có."*
>
> *"Authorization không phải là việc làm code chạy được.*
> *Đó là việc ngủ ngon, pass audit, và không cháy production."*
