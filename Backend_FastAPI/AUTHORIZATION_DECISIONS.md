# Authorization Decisions Log

> **Mục đích:** Ghi lại LÝ DO đằng sau các quyết định authorization.
> Sau 1 năm, file này cứu team khỏi audit drama.
>
> **Quy tắc:** Mỗi quyết định authorization quan trọng PHẢI được ghi lại ở đây.

---

## Decision 1: Admin Wildcard Policy

| Field | Value |
|-------|-------|
| **Quyết định** | Admin có policy `(role:admin, /*, .*)` |
| **Lý do** | Admin cần full access để recovery khi có sự cố. Không thể liệt kê hết tất cả endpoint cho admin. |
| **Rủi ro** | Nếu xóa nhầm → lockout toàn bộ system, không ai có thể truy cập bất kỳ API nào |
| **Mitigation** | 1. `CRITICAL_POLICIES` trong `policy_templates.py` chặn xóa<br>2. Pre-deploy check script kiểm tra policy tồn tại<br>3. Migration có safety check trước và sau |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Security Team |
| **Review trigger** | Nếu cần giới hạn admin → tạo role "super_admin" mới |

---

## Decision 2: IDOR Trả 404 Thay Vì 403

| Field | Value |
|-------|-------|
| **Quyết định** | Khi user truy cập resource không sở hữu → trả 404 (Not Found) |
| **Lý do** | Tránh inference attack - user không thể biết ID nào tồn tại dựa vào response code |
| **Ví dụ** | User A gọi `/api/leads/999` (lead của User B) → nhận 404, không phải 403 |
| **Reference** | OWASP IDOR Prevention, CWE-639 |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Security Team |
| **Áp dụng cho** | Tất cả resource có ownership: Lead, Application, Notification, Consultation, Document |

**Anti-pattern cần tránh:**
```python
# ❌ SAI - Tiết lộ resource tồn tại
if lead.owner_id != user.id:
    raise PermissionDeniedError()  # 403

# ✅ ĐÚNG - Giấu sự tồn tại của resource
if lead.owner_id != user.id:
    raise ResourceNotFoundError()  # 404
```

---

## Decision 3: /api/system/* Dùng require_admin

| Field | Value |
|-------|-------|
| **Quyết định** | Các endpoint `/api/system/*` dùng static role check (`require_admin`) thay vì Casbin |
| **Lý do** | 1. Internal-only, không public-facing<br>2. Không cần dynamic policy<br>3. Performance tốt hơn (không query DB) |
| **Constraint** | CHỈ áp dụng cho endpoint KHÔNG expose ra client (web/mobile) |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Backend Team |
| **Review trigger** | Nếu endpoint cần gọi từ client → PHẢI chuyển sang Casbin |

**Endpoints áp dụng:**
- `/api/system/cache-stats` - Internal monitoring
- `/api/system/health-detailed` - DevOps only
- `/api/internal/*` - Service-to-service communication

---

## Decision 4: /api/kpi-config/* Dùng require_admin

| Field | Value |
|-------|-------|
| **Quyết định** | KPI config endpoints dùng `require_admin` |
| **Lý do** | 1. Chỉ admin cấu hình KPI<br>2. Không có nhu cầu phân quyền chi tiết<br>3. Internal tool |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Product Team |
| **Review trigger** | Nếu manager cần config KPI → chuyển sang Casbin |

---

## Decision 5: Notification Ownership Model

| Field | Value |
|-------|-------|
| **Quyết định** | Notification chỉ được xem/xóa bởi user nhận notification hoặc admin |
| **Lý do** | Privacy - notification có thể chứa thông tin nhạy cảm |
| **Model** | `notification.user_id` = owner |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Security Team |

**Rules:**
- Admin: Xem/xóa tất cả (debug, support)
- Manager: KHÔNG được xem notification của người khác
- Officer: KHÔNG được xem notification của người khác
- User: Chỉ xem/xóa của mình

---

## Decision 6: Lead Ownership Model

| Field | Value |
|-------|-------|
| **Quyết định** | Lead access theo role hierarchy |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Business Team |

**Rules:**
| Role | Access |
|------|--------|
| Admin | Tất cả leads |
| Manager | Leads trong unit của mình |
| Officer | Chỉ leads được gán (`assigned_officer_id`) |
| User | Không có quyền xem lead |

---

## Decision 7: Manager Không Được DELETE Lead

| Field | Value |
|-------|-------|
| **Quyết định** | Manager KHÔNG có quyền xóa lead, chỉ Admin |
| **Lý do** | 1. Tránh xóa nhầm dữ liệu quan trọng<br>2. Audit trail - cần admin approve<br>3. Business rule: lead là tài sản công ty |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Business Team |
| **Exception** | Không có |

---

## Decision 8: CasbinAuth là Default

| Field | Value |
|-------|-------|
| **Quyết định** | Mọi API endpoint PHẢI dùng `CasbinAuth` trừ khi có lý do documented |
| **Lý do** | 1. Dynamic policy - có thể thay đổi runtime<br>2. Audit trail - log trong casbin_rule<br>3. Consistency - một pattern cho tất cả |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Architecture Team |

**Exceptions được phép:**
1. `/api/system/*` - Internal only (Decision 3)
2. `/api/kpi-config/*` - Admin only (Decision 4)
3. `/api/auth/*` - Public endpoints (login, register)
4. `/health` - Health check

**Mỗi exception PHẢI có:**
- Comment trong code giải thích lý do
- Entry trong file này

---

## Decision 9: Role Inheritance Chain

| Field | Value |
|-------|-------|
| **Quyết định** | Role kế thừa theo chain: `user < officer < manager < admin` |
| **Lý do** | Giảm duplicate policies, dễ maintain |
| **Ngày** | 2026-01-05 (planned) |
| **Status** | PLANNED - Chưa implement |

**Inheritance:**
```
role:admin
    └── role:manager
            └── role:officer
                    └── role:user
```

**Ý nghĩa:**
- `role:user` permissions → tất cả role đều có
- `role:officer` permissions → manager và admin cũng có
- `role:manager` permissions → admin cũng có
- `role:admin` permissions → chỉ admin có

---

## Template Cho Decision Mới

```markdown
## Decision N: [Tên Decision]

| Field | Value |
|-------|-------|
| **Quyết định** | [Mô tả quyết định] |
| **Lý do** | [Tại sao chọn cách này] |
| **Rủi ro** | [Rủi ro nếu có] |
| **Mitigation** | [Cách giảm thiểu rủi ro] |
| **Ngày** | YYYY-MM-DD |
| **Người quyết định** | [Tên/Team] |
| **Review trigger** | [Khi nào cần xem xét lại] |
```

---

## Changelog

| Date | Decision | Change | By |
|------|----------|--------|-----|
| 2026-01-05 | 1-9 | Initial decisions documented | Security Audit |

---

**END OF DECISIONS LOG**

> *"The best time to document a decision was when you made it.*
> *The second best time is now."*
