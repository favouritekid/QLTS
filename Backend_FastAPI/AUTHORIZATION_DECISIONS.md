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
| **Ngày** | 2026-01-05 |
| **Status** | ✅ IMPLEMENTED - Migration `p3a1b2c3d4e5` |

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

## Decision 10: Admission State ≠ Authorization

| Field | Value |
|-------|-------|
| **Quyết định** | Casbin chỉ quyết định CÓ ĐƯỢC GỌI API không, KHÔNG quyết định state transition |
| **Lý do** | Admission state là business logic, phụ thuộc thời gian, dữ liệu, và nghiệp vụ |
| **Hệ quả** | State transition được enforce ở Service layer (AdmissionStateMachine) |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Architecture Team |

**Phân tách trách nhiệm:**
```
┌─────────────────────────────────────────────────────────────┐
│                      Request Flow                           │
├─────────────────────────────────────────────────────────────┤
│  1. Casbin: "User có quyền gọi POST /admissions/submit?"    │
│     → YES/NO (chỉ check role + endpoint)                    │
│                                                             │
│  2. Service: "Profile này CÓ THỂ submit không?"             │
│     → Check state machine (DRAFT → SUBMITTED)               │
│     → Check business rules (documents đủ? deadline?)        │
└─────────────────────────────────────────────────────────────┘
```

**Anti-pattern cần tránh:**
```python
# ❌ SAI - Nhét state vào Casbin
enforcer.add_policy("role:officer", "/admissions/*/submit", "POST", "state:draft")

# ✅ ĐÚNG - Casbin check role, Service check state
# Router: CasbinAuth (role check)
# Service: state_machine.can_transition(profile, "SUBMITTED")
```

---

## Decision 11: OVERRIDDEN Là Trạng Thái Ngoại Lệ Có Audit

| Field | Value |
|-------|-------|
| **Quyết định** | OVERRIDDEN chỉ dùng cho trường hợp phá rule có chủ đích |
| **Constraint** | Admin-only, bắt buộc reason, audit log |
| **Rủi ro** | Lạm dụng override → bypass toàn bộ business rule |
| **Mitigation** | 1. Log mọi override action<br>2. Review định kỳ override rate<br>3. Alert nếu override > 5% admissions |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Business + Security Team |
| **Review trigger** | Nếu override rate > 5% trong 1 tháng |

**Use cases hợp lệ:**
- Hồ sơ đặc biệt được ban giám đốc approve
- Trường hợp khẩn cấp cần xử lý ngoài quy trình
- Fix lỗi dữ liệu do bug hệ thống

**Use cases KHÔNG hợp lệ:**
- Bỏ qua bước kiểm tra vì "gấp"
- Tạo admission không qua flow chuẩn
- Bypass document requirements vì "khách VIP"

---

## Decision 12: Policy Change Không Áp Dụng Retroactively

| Field | Value |
|-------|-------|
| **Quyết định** | Policy change chỉ áp dụng cho request/data MỚI, không thay đổi kết quả đã xử lý |
| **Lý do** | 1. Tránh thay đổi kết quả đã hoàn thành<br>2. Đảm bảo audit trail chính xác<br>3. Tránh drama "sao hôm qua được mà hôm nay không?" |
| **Exception** | Admin override có audit trail rõ ràng |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Architecture Team |
| **Review trigger** | Khi có major policy change giữa mùa tuyển sinh |

**Ví dụ thực tế:**

| Scenario | Cách xử lý |
|----------|-----------|
| Thêm permission mới cho Manager | Manager có thể dùng ngay cho request mới |
| Bỏ permission của Officer | Officer không gọi được API đó nữa, nhưng data cũ giữ nguyên |
| Đổi admission rule giữa mùa | Profile cũ xử lý theo rule cũ, profile mới theo rule mới |

**Anti-pattern:**
```python
# ❌ SAI - Apply policy change cho dữ liệu cũ
async def apply_new_policy_retroactively():
    all_profiles = await get_all_profiles()
    for profile in all_profiles:
        profile.status = recalculate_with_new_rules(profile)  # Drama!

# ✅ ĐÚNG - Chỉ apply cho dữ liệu mới
# New policy effective from: 2026-01-05
# Profiles created before: use old rules
# Profiles created after: use new rules
```

---

## Decision 13: Audit Log Retention Policy

| Field | Value |
|-------|-------|
| **Quyết định** | Authorization audit logs giữ tối thiểu 2 năm |
| **Lý do** | 1. Compliance requirement<br>2. Security investigation<br>3. Legal disputes có thể kéo dài |
| **Scope** | Tất cả: login, permission change, override, sensitive actions |
| **Access** | Admin-only, với audit cho việc xem log |
| **Ngày** | 2026-01-05 |
| **Người quyết định** | Security + Legal Team |

**Logs cần giữ:**
- Login/logout events
- Permission denied events (potential attacks)
- Policy changes (who, when, what)
- Override actions (with reason)
- Sensitive data access (PII)

**Storage:**
- Hot storage (searchable): 90 days
- Cold storage (archive): 2 years
- Deletion: After 2 years, with deletion log

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
| 2026-01-05 | 7 | Implemented via migration - manager wildcard removed | Phase 3 |
| 2026-01-05 | 9 | Implemented via migration `p3a1b2c3d4e5` | Phase 3 |
| 2026-01-05 | 10-13 | Added state/auth separation, override, retroactive, audit retention | Senior Review |

---

**END OF DECISIONS LOG**

> *"The best time to document a decision was when you made it.*
> *The second best time is now."*
