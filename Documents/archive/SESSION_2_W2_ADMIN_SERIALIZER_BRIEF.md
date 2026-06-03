# Session 2 brief — W2: Admin user serializer leak fix

> **Đối tượng**: Claude session thứ hai chạy song song với session
> đang giải quyết W1 (finance fixture deadlocks).

> **Branch**: `fix/admin-users-password-hash-leak`
>
> **Worktree path**: `D:/QLTS-w2-admin-serializer`
>
> **Effort**: 1-2h. Không đụng admission domain.

---

## 0. Bối cảnh

Trong PR #165 (test-debt partial cleanup) phát hiện 4 test failure
trong `tests/api/test_admin_users.py` đều có symptom giống nhau:

```
AssertionError: Password hash leaked in response
assert 'password_hash' not in {'password_hash': '$2b$15$...', ...}
```

Test failures (verified pre-existing trên main, không phải regression
do PR #165):

```
tests/api/test_admin_users.py::test_admin_create_user_success
tests/api/test_admin_users.py::test_admin_create_user_weak_password
tests/api/test_admin_users.py::test_admin_get_user_detail_success
tests/api/test_admin_users.py::test_admin_update_user_success
```

Memory: `project_test_debt_admission_workflow_e2e.md` (mục "4 admin
serializer failures").

## 1. Goal

Fix endpoint `/api/admin/users` (create + detail + update) để response
KHÔNG còn `password_hash` (cùng các sensitive field như
`totp_secret_encrypted`, `backup_codes_hashed`, `active_jti`,
`mfa_enabled` nếu cần).

## 2. Acceptance criteria

- 4 test trên ĐỀU PASS sau fix
- Không break các test khác trong `tests/api/test_admin_users.py`
- Không break Casbin grouping policy / role assignment behavior
- Không lộ field nào trong list `SENSITIVE_FIELDS` (xác định trong
  schema)

## 3. Tiếp cận

Khả năng cao là `app/routers/admin_users.py` đang dùng
`response_model=models.User` hoặc Pydantic schema thiếu
`Config.exclude` cho `password_hash`. Hai cách fix khả dĩ:

**Cách A**: Schema dedicated `UserAdminResponse(BaseModel)` chỉ
expose các field public, không có `password_hash`. Router declare
`response_model=UserAdminResponse`.

**Cách B**: Pydantic `model_config = ConfigDict(json_schema_extra=...)
` + field-level `Field(exclude=True)` trên những sensitive field.

→ **Cách A là chuẩn của repo** (xem các response schema khác
trong `app/schemas/user.py`).

## 4. Setup worktree + Docker isolated

### 4a. Tạo worktree

```bash
# Từ D:/QLTS
git worktree add D:/QLTS-w2-admin-serializer -b fix/admin-users-password-hash-leak main
cd D:/QLTS-w2-admin-serializer
```

### 4b. Docker stack riêng (port-shifted)

⚠️ **CRITICAL**: session 1 đang chạy Docker stack ở `D:/QLTS` với
port 8000/3000/5433/6380. Session 2 phải dùng port khác để KHÔNG
crash session 1.

Tạo file `docker-compose.w2.yml` trong `D:/QLTS-w2-admin-serializer`:

```yaml
services:
  postgres:
    ports:
      - "5444:5432"
  redis:
    ports:
      - "6390:6379"
  backend:
    ports:
      - "8001:8000"
  frontend:
    ports:
      - "3001:3000"
```

> Note: `docker-compose.w2.yml` không add vào git, chỉ local override.
> Nếu thấy bị track: `echo "docker-compose.w2.yml" >> .gitignore`

Up stack với project name riêng:

```bash
cd D:/QLTS-w2-admin-serializer
docker compose --env-file .env -p qlts-w2 \
  -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.w2.yml \
  up -d
```

Project name `qlts-w2` đảm bảo:
- Container tên `qlts-w2-backend-1` không đụng `qlts-backend-1`
- Volume `qlts-w2_postgres_data` riêng — DB sạch, không share data
- Network isolated

### 4c. Cài test deps trong session 2

```bash
docker compose -p qlts-w2 exec backend pip install -q -r requirements-dev.txt
```

### 4d. Verify stack lên đủ

```bash
docker compose -p qlts-w2 ps --format "table {{.Service}}\t{{.Status}}"
```

Kỳ vọng 6/6 service `Up (healthy)`.

## 5. Workflow

### 5a. Reproduce failure

```bash
cd D:/QLTS-w2-admin-serializer
docker compose -p qlts-w2 exec -T backend python -m pytest \
  tests/api/test_admin_users.py::test_admin_create_user_success -v 2>&1 | tail -20
```

Kỳ vọng FAIL với `Password hash leaked`. Note exact response shape
trong assertion để biết cần exclude field nào.

### 5b. Find culprit

```bash
# Trong worktree
grep -n "response_model=" Backend_FastAPI/app/routers/admin_users.py | head
grep -n "class User" Backend_FastAPI/app/schemas/user.py | head
```

Tìm endpoint POST `/api/admin/users` + GET `/api/admin/users/{id}` +
PUT `/api/admin/users/{id}`. Xem `response_model` đang dùng gì.

### 5c. Fix

Khả năng cao cần:

```python
# app/schemas/user.py
class UserAdminResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: str
    status: str
    unit_id: Optional[int] = None
    # ... các field public khác
    # KHÔNG có password_hash, totp_secret_encrypted,
    # backup_codes_hashed, active_jti, search_vector

    model_config = ConfigDict(from_attributes=True)
```

Router:

```python
# app/routers/admin_users.py
@router.post("", response_model=UserAdminResponse)
@router.get("/{user_id}", response_model=UserAdminResponse)
@router.put("/{user_id}", response_model=UserAdminResponse)
```

### 5d. Verify

```bash
docker compose -p qlts-w2 exec -T backend python -m pytest \
  tests/api/test_admin_users.py -v 2>&1 | tail -30
```

Tất cả test trong file phải PASS (cả 4 test ban đầu fail + các test
đã pass trước).

### 5e. Regression smoke

```bash
docker compose -p qlts-w2 exec -T backend python -m pytest \
  tests/api/test_admin_users.py tests/api/test_user_audit.py \
  tests/security/ -q 2>&1 | tail -10
```

(Nếu test_user_audit.py không tồn tại, bỏ qua — chỉ chạy cái có.)

## 6. Commit + Push

```bash
git add Backend_FastAPI/app/schemas/user.py Backend_FastAPI/app/routers/admin_users.py
git commit -m "$(cat <<'EOF'
fix(admin): scope admin user response to public fields, drop password_hash leak

The 3 admin user endpoints (POST/GET/PUT /api/admin/users[/{id}]) were
serializing the SQLAlchemy ``User`` model directly via
``response_model=User`` (or equivalent), which leaked
``password_hash``, ``totp_secret_encrypted``, ``backup_codes_hashed``,
``active_jti``, ``search_vector`` and other internal fields onto the
admin UI surface.

Add a dedicated ``UserAdminResponse`` Pydantic schema with only the
fields the admin UI legitimately needs, and switch the 3 endpoints
to use it as ``response_model``.

Pre-existing failure flagged during PR #165 (partial test-debt
cleanup). Memory: ``project_test_debt_admission_workflow_e2e``.

Tests:
- ``test_admin_create_user_success`` ✓
- ``test_admin_create_user_weak_password`` ✓
- ``test_admin_get_user_detail_success`` ✓
- ``test_admin_update_user_success`` ✓
- Full ``tests/api/test_admin_users.py`` PASS, no regression on
  Casbin grouping or role assignment.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

⚠️ KHÔNG push tự động. **Báo cáo cho user duyệt** (per memory
`feedback_push_approval`):

```
G2 W2 sẵn sàng push:
- Branch: fix/admin-users-password-hash-leak (1 commit <SHA>)
- Files changed: <list>
- Tests: <X>/<Y> PASS
- Push approval cần: confirm để mình push?
```

Khi user duyệt:

```bash
git push -u origin fix/admin-users-password-hash-leak
gh pr create --base main --title "fix(admin): scope admin user response to public fields" --body "..."
```

## 7. Cleanup khi xong

### 7a. Sau khi PR merge + deploy success

```bash
# Trong session 2
cd D:/QLTS-w2-admin-serializer
docker compose -p qlts-w2 down -v   # Xóa container + volume riêng
cd D:/QLTS
git worktree remove D:/QLTS-w2-admin-serializer --force
git branch -D fix/admin-users-password-hash-leak
```

## 8. Coordination với Session 1

Session 1 đang làm W1 (finance deadlocks) ở `D:/QLTS` với Docker
stack chính (port 8000/3000/5433/6380). Session 2 KHÔNG được:

- Touch port 8000/3000/5433/6380
- Touch project name `qlts` (default cho `D:/QLTS`)
- Touch volume `qlts_postgres_data`
- Push branch trùng tên với W1
- Modify file ngoài `app/routers/admin_users.py`,
  `app/schemas/user.py`, `tests/api/test_admin_users.py` (nếu cần
  add test)

Nếu phát sinh chạm `tests/conftest.py` hay shared fixture, **STOP +
báo session 1** trước khi commit, tránh conflict khi rebase.

## 9. Risk awareness (per memory `feedback_pattern_change_impact_audit`)

Trước khi swap `response_model=User` → `response_model=UserAdminResponse`,
audit:

1. **Caller dependencies**: FE nào đang đọc field nào từ response?
   Grep `frontend/src` cho `password_hash`, `totp_secret`,
   `active_jti` để chắc FE không depend vào field bị remove.
2. **Other callers**: có service/router khác đang import `User`
   Pydantic schema để re-export không?
3. **Admin audit log**: sau fix có còn log đủ thông tin không (audit
   ghi user_id, không cần password_hash)?

Disclose side-effect trong PR body. Anchor test phải assert sensitive
field NOT IN response (chứ không chỉ assert response valid).

## 10. Memory feedback đã nắm

- `feedback_push_approval` — không push tự động, chờ duyệt mỗi push
- `feedback_pattern_change_impact_audit` — audit pattern cũ trước khi swap
- `feedback_test_before_push` — tsc + pytest trước khi push
- `feedback_audit_before_fix` — DB/code/seed audit trước khi sửa
- `project_test_debt_admission_workflow_e2e` — context 4 failure này

Nếu chưa đọc các memory trên, đọc trước khi bắt đầu.
