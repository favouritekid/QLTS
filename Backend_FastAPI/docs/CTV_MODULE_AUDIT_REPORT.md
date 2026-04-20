# BÁO CÁO AUDIT TOÀN DIỆN: MODULE CTV (CỘNG TÁC VIÊN)

> **⚠️ Deprecated historical audit note**: references below mention the retired `Application` model (e.g. `Application.status = "passed"`) and are kept only as legacy analysis context, not current architecture. The active admission entity is `AdmissionProfile` — see `MASTER_ARCHITECTURE.md` and `CLAUDE.md` for current system docs. Retained for traceability of 2026-02 audit findings, not as design reference.

> **Ngày thực hiện**: 2026-02-24
> **Phạm vi**: Backend, Frontend, Database, Business Logic
> **Phiên bản module**: Phase 1 (CTV Registration + Lead Claim)
> **Đánh giá tổng thể**: **7/10** — Foundation vững chắc, cần security hardening + Phase 2
> **Cập nhật xác minh**: 2026-02-25 — S-1 hạ Critical → Low, F-5 loại (not a bug), thêm 8 issues mới (NEW-B1→B4, NEW-F1→F5)
> **Tài liệu thiết kế gốc**: `docs/CTV_ORIGINAL_DESIGN_V1.md` + `docs/CTV_ORIGINAL_README_V1.md` (đã khôi phục từ commit `0166c2d`, Nov 2025)
> **Kế hoạch triển khai**: `docs/CTV_COMMISSION_PLAN.md`
>
> **Quyết định nghiệp vụ (đã xác nhận 2026-02-24)**:
> 1. Scope chính sách: **Global** (không phân theo đơn vị)
> 2. Base tính hoa hồng: **Chỉ học phí** (tuition fee)
> 3. Approval workflow: **1 bước** (Admin duyệt)
> 4. Hoàn hoa hồng: **Không hoàn** (quyết định của sinh viên)
> 5. CTV categories/tiers: **Chưa cần** (deferred)

---

## MỤC LỤC

0. [Đối Chiếu Với Kế Hoạch Gốc](#0-đối-chiếu-với-kế-hoạch-gốc)
1. [Tổng Quan](#1-tổng-quan)
2. [Kiến Trúc & Thiết Kế](#2-kiến-trúc--thiết-kế)
3. [Nghiệp Vụ CTV](#3-nghiệp-vụ-ctv)
4. [Quản Lý Dữ Liệu](#4-quản-lý-dữ-liệu)
5. [Bảo Mật & Phân Quyền](#5-bảo-mật--phân-quyền)
6. [Tính Toán Hoa Hồng & Thanh Toán](#6-tính-toán-hoa-hồng--thanh-toán)
7. [API & Backend](#7-api--backend)
8. [Frontend / UX](#8-frontend--ux)
9. [Hiệu Năng & Khả Năng Mở Rộng](#9-hiệu-năng--khả-năng-mở-rộng)
10. [Rủi Ro Production](#10-rủi-ro-production)
10A. [Xác Minh Bổ Sung (2026-02-25)](#10a-xác-minh-bổ-sung-2026-02-25)
11. [Tổng Hợp Vấn Đề Theo Mức Độ](#11-tổng-hợp-vấn-đề-theo-mức-độ)
12. [Checklist Production](#12-checklist-production)
13. [Kế Hoạch Khắc Phục](#13-kế-hoạch-khắc-phục)

---

## 0. ĐỐI CHIẾU VỚI KẾ HOẠCH GỐC

### Nguồn tài liệu thiết kế

Hai tài liệu thiết kế gốc đã được tạo trong commit `0166c2d` (28/11/2025), đã bị xóa khỏi repo trong quá trình refactor Phase 1 và **đã được khôi phục** vào `docs/`:

- `docs/CTV_ORIGINAL_DESIGN_V1.md` — Hướng dẫn triển khai chi tiết (1,160 dòng)
- `docs/CTV_ORIGINAL_README_V1.md` — Quick reference (275 dòng)

### Kế hoạch gốc (V1 — Nov 2025)

Thiết kế gốc định nghĩa hệ thống CTV với **3 yêu cầu nghiệp vụ chính**:
1. Cộng tác viên nhập lead vào hệ thống
2. Theo dõi quá trình tư vấn lead
3. Tự động tính và trả hoa hồng khi lead nhập học thành công

**Database thiết kế gốc**: 3 bảng mới + 2 cột mới trong Lead

| Bảng | Mục đích | Cột chính |
|------|----------|-----------|
| `collaborators` | Thông tin CTV | code, full_name, email, phone, category, total_leads, successful_leads, total_commission_earned, pending_commission |
| `commission_policies` | Chính sách hoa hồng | calculation_type (percentage/fixed), percentage_value, fixed_amount, applicable_scope (JSON), collaborator_categories, priority, effective_date |
| `commissions` | Ghi nhận hoa hồng | collaborator_id, lead_id, application_id, policy_id, base_amount, commission_rate, commission_amount, status (pending/approved/paid/rejected) |
| `leads` (cập nhật) | Liên kết CTV | +referrer_id, +referrer_code |

**Business Flow thiết kế gốc** (6 bước):

```
1. Admin tạo CTV → nhận mã CTV001
2. Admin tạo CommissionPolicy → thiết lập chính sách HH (5%, 10%, cố định 2tr, ...)
3. CTV tạo Lead với referrer_code="CTV001" → hệ thống gán referrer_id + tăng total_leads
4. Officer tư vấn Lead → CTV theo dõi (read-only)
5. Application.status = "passed" → HỆ THỐNG TỰ ĐỘNG tạo Commission (pending)
6. Admin phê duyệt → thanh toán hoa hồng
```

### Hiện trạng Phase 1 (Feb 2026) — So sánh

| Hạng mục | Kế hoạch gốc (V1) | Hiện trạng Phase 1 | Trạng thái |
|----------|-------------------|---------------------|------------|
| **CTV Registration** | Tạo trực tiếp, không có phê duyệt | Quy trình pending → active → suspended | REDESIGNED (tốt hơn) |
| **Lead Submission** | CTV gửi `referrer_code` khi tạo lead | CTV submit lead qua claim workflow (3-layer lock) | REDESIGNED (tốt hơn) |
| **CTV Types** | Categories (VIP, Standard, Gold) | Independent vs Attached-to-Officer | REDESIGNED (khác cách tiếp cận) |
| **Lead Attribution** | `referrer_code` + `referrer_id` | `referrer_id` + `validity_status` + `created_via` | REDESIGNED (tốt hơn) |
| **Phone Masking** | Không có | CTV chỉ thấy `0912***456` | NEW (cải thiện bảo mật) |
| **First-Touch Lock** | Không có (ai tạo trước được) | 3-layer FOR UPDATE lock | NEW (ngăn race condition) |
| **Self-Claim Prevention** | Không có | Block CTV claim phone của chính mình | NEW (anti-fraud) |
| **Officer Routing** | Không có | Smart auto-assign tới officer quản lý CTV | NEW (UX tốt hơn) |
| **CTV Approval Workflow** | Không có (active ngay) | pending → approve → suspend | NEW (kiểm soát tốt hơn) |
| **Commission Model** | `commissions` table + workflow | **CHƯA TRIỂN KHAI** | MISSING |
| **CommissionPolicy** | `commission_policies` table + rules engine | **CHƯA TRIỂN KHAI** | MISSING |
| **Auto Commission** | Trigger khi Application.status="passed" | **CHƯA TRIỂN KHAI** | MISSING |
| **Commission Approval** | pending → approved → paid/rejected | **CHƯA TRIỂN KHAI** | MISSING |
| **CTV Statistics** | total_leads, successful_leads, commission amounts | total_leads, valid_leads, qualified_leads (không có commission) | PARTIAL |
| **CTV Categories** | VIP, Standard, Gold | Không có | DEFERRED (theo quyết định nghiệp vụ) |
| **CTV Dashboard** | Không thiết kế frontend | Đầy đủ: stats + leads + claims | NEW (vượt kế hoạch) |
| **Admin Management UI** | Không thiết kế frontend | Đầy đủ: table + filters + CRUD + claim review | NEW (vượt kế hoạch) |
| **IDOR Protection** | Không đề cập | 3-tier: Admin > Manager+unit > 404 | NEW (bảo mật tốt hơn) |
| **Casbin RBAC** | Không đề cập | role:collaborator riêng biệt | NEW (phân quyền tốt hơn) |
| **Test Coverage** | Không đề cập | 4 test files, ~60 test cases | NEW |

### Đánh giá tổng hợp

**Những gì Phase 1 làm TỐT HƠN kế hoạch gốc:**
- Claim workflow với 3-layer first-touch lock (thay vì referrer_code đơn giản)
- CTV approval workflow (kiểm soát ai được hoạt động)
- Phone masking + self-claim prevention (bảo mật tốt hơn)
- IDOR protection + Casbin RBAC (phân quyền bài bản)
- Frontend đầy đủ (kế hoạch gốc không thiết kế UI)
- Smart auto-assign officer routing
- Comprehensive test coverage

**Những gì Phase 1 THIẾU so với kế hoạch gốc (GAP ANALYSIS):**

| Gap ID | Tính năng thiếu | Mức độ | Ghi chú |
|--------|----------------|--------|---------|
| GAP-1 | **Commission table + workflow** | **Critical** | Core business value — CTV không có động lực nếu không có hoa hồng |
| GAP-2 | **CommissionPolicy rules engine** | **Critical** | Không thể cấu hình % hoa hồng, điều kiện |
| GAP-3 | **Auto commission trigger** | **High** | Khi lead đạt sts11 (ENROLLED) → tự động tạo commission |
| GAP-4 | **Commission approval + payment** | **High** | Workflow: pending → approved → paid/rejected |
| GAP-5 | **CTV categories/tiers** | Deferred | **Quyết định nghiệp vụ**: chưa cần triển khai |
| GAP-6 | **Attribution expiry** | Medium | 90-day window (constant tồn tại nhưng chưa active) |
| GAP-7 | **CTV self-service commission view** | Medium | CTV xem lịch sử hoa hồng, số tiền pending |
| GAP-8 | **Commission statistics** | Low | total_commission_earned, pending_commission trên CTV profile |
| GAP-9 | **Notification khi commission created/paid** | Low | Thông báo cho CTV |

### Khuyến nghị

1. **Tài liệu thiết kế gốc** đã được khôi phục vào `docs/` để làm reference cho Phase 2

2. **Phase 2 kế thừa** commission schema từ thiết kế gốc (commission_policy + commission tables), nhưng **KHÔNG kế thừa** phần logic cũ (V1 không có IDOR, không có domain exceptions, vi phạm architecture rules)

3. **Tích hợp commission trigger** qua Celery task khi lead đạt sts11 (ENROLLED) — phù hợp architecture V3.0 event-driven, không inline trong router

4. **Xem kế hoạch triển khai chi tiết** tại `docs/CTV_COMMISSION_PLAN.md`

---

## 1. TỔNG QUAN

### Mục đích module

Module CTV (Cộng tác viên) quản lý đối tác bên ngoài giới thiệu lead (thí sinh tiềm năng) vào hệ thống tuyển sinh. Hiện tại là **Phase 1** bao gồm:

- Đăng ký / phê duyệt / quản lý CTV
- Quy trình claim lead (3-layer first-touch lock)
- Theo dõi tính hợp lệ lead (validity_status)
- Dashboard tự phục vụ cho CTV (xem leads, claims, stats)
- Smart auto-assign (route referral leads tới officer quản lý CTV)

**Phase 2 (Commission & Payout)**: Chưa triển khai — chỉ có foundation (bank_account columns, 90-day constant).

### Phạm vi code

| Thành phần | Files | Lines (ước lượng) |
|------------|-------|-------------------|
| Backend Core | 7 files | ~2,000 |
| Backend Tests | 4 files | ~1,800 |
| Frontend | 9 files | ~2,500 |
| Migration | 1 file | ~150 |
| **Tổng** | **21 files** | **~6,450** |

### Inventory đầy đủ

**Backend:**

| Layer | File | Mô tả |
|-------|------|-------|
| Model | `app/models/collaborator.py` | Collaborator + LeadClaim models |
| Model (ext) | `app/models/lead.py` | referrer_id, validity_status, created_via columns |
| Schema | `app/schemas/collaborator.py` | 15+ Pydantic schemas |
| Router | `app/routers/collaborators.py` | admin_router + ctv_router (15 endpoints) |
| Service | `app/services/collaborator_service.py` | 511 lines business logic |
| Service (ext) | `app/services/lead_service.py` | CTV integration trong lead creation |
| Repository | `app/repositories/collaborator_repository.py` | CollaboratorRepository |
| Repository | `app/repositories/lead_claim_repository.py` | LeadClaimRepository |
| Repository (ext) | `app/repositories/lead_repository.py` | 4 new methods cho CTV |
| Deps | `app/core/deps.py` | 4 CTV dependencies |
| Constants | `app/core/constants.py` | UserRole.COLLABORATOR |
| Casbin | `app/casbin_config/policy_templates.py` | COLLABORATOR_TEMPLATE |
| Migration | `alembic/versions/ctv20260212001_*.py` | Phase 1 schema |
| Main | `app/main.py` | Router registration |

**Frontend:**

| Layer | File | Mô tả |
|-------|------|-------|
| Types | `src/types/collaborator.types.ts` | TypeScript interfaces |
| Zod | `src/lib/zod/collaborator.ts` | Validation schemas |
| API Client | `src/lib/api/collaborators.ts` | Axios-based API calls |
| Hooks | `src/hooks/useCollaborators.ts` | React Query hooks |
| Page (Admin) | `src/app/(dashboard)/admin/collaborators/` | Server + Client components |
| Page (CTV) | `src/app/(dashboard)/ctv/` | CTV dashboard |
| Component | `src/components/admin/CollaboratorDialog.tsx` | Create/Edit CTV |
| Component | `src/components/admin/ClaimReviewDialog.tsx` | Review claims |
| Component | `src/components/ctv/SubmitLeadDialog.tsx` | Submit lead |
| Navigation | `src/lib/config/navigation.ts` | Menu entries |
| Constants | `src/constants/lead.constants.ts` | Validity labels/colors |

**Tests:**

| File | Scope |
|------|-------|
| `tests/api/test_collaborator_api.py` | API integration + IDOR |
| `tests/services/test_collaborator.py` | Service CRUD |
| `tests/services/test_collaborator_claim.py` | Claim workflow |
| `tests/services/test_create_lead_referral.py` | Lead creation with referrer |

---

## 2. KIẾN TRÚC & THIẾT KẾ

### Điểm mạnh

- **Tuân thủ kiến trúc V3.0**: Smart deps (auth/IDOR) → Dumb router (I/O only) → Pure service (no FastAPI imports) → Repository (data access)
- **Tách biệt router rõ ràng**: `admin_router` cho Admin/Manager, `ctv_router` cho CTV self-service — phân quyền ngay từ routing level
- **Service isolation**: Không import FastAPI, chỉ raise domain exceptions (`BusinessRuleViolation`, `DuplicateResourceError`, etc.)
- **Coupling hợp lý với Lead module**: Tích hợp qua FK `referrer_id` và method extensions trong `LeadRepository`, không xâm phạm lead business logic
- **Pattern (result, callback)**: Service trả tuple để router quyết định commit timing — đúng pattern dự án

### Vấn đề

| ID | Mức độ | Vấn đề | Chi tiết |
|----|--------|--------|----------|
| A-1 | Medium | Service file quá lớn | `collaborator_service.py` (511 dòng) chứa cả CTV CRUD + Claim workflow + Stats + Phone check. Khi Phase 2 thêm commission logic, file này sẽ > 800 dòng. Nên tách `lead_claim_service.py` |
| A-2 | Low | Thiếu event/signal pattern | Khi claim được approve, không có mechanism để trigger side effects (Phase 2: commission calculation). Cần chuẩn bị hook point hoặc event bus |

---

## 3. NGHIỆP VỤ CTV

### Quy trình hiện tại

```
┌──────────────────────────────────────────────────────────────┐
│                   CTV LIFECYCLE                               │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│   Tạo CTV ──► pending ──► active ──► suspended               │
│    (Admin        │          │   (approve)  (suspend)          │
│     auto-       (Manager                                      │
│     approve)     waits)     ↓                                 │
│                           Hoạt động                           │
│                           - Submit leads                      │
│                           - View stats                        │
│                           - View own claims                   │
│                                                               │
│   ⚠ THIẾU: suspended → active (reactivate)                  │
│   ⚠ THIẾU: inactive status endpoint                          │
└──────────────────────────────────────────────────────────────┘
```

### Lead Claim Workflow

```
┌──────────────────────────────────────────────────────────────┐
│                   LEAD CLAIM WORKFLOW                          │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│   CTV check-phone ──► CTV submit claim ──► Admin review      │
│                                              │        │       │
│   3-layer first-touch lock:                  │        │       │
│   1. Lead has referrer? → BLOCK              ▼        ▼       │
│   2. Officer working? → BLOCK              Approve  Reject    │
│   3. Lead new? → ALLOW                      │        │        │
│                                              │        │        │
│   New lead created if not exists             │        ▼        │
│   Officer routing:                           │   referrer_id   │
│   - Attached CTV → CTV's officer            │   = NULL        │
│   - Independent CTV → auto-assign           │   source =      │
│                                              │   "other"       │
│                                              ▼                 │
│                                         validity_status       │
│                                         = "valid"             │
└──────────────────────────────────────────────────────────────┘
```

### Anti-Fraud Mechanisms (Hiện có)

| Mechanism | Mô tả | Đánh giá |
|-----------|-------|----------|
| Self-claim phone check (M2) | `collaborator.phone == claim_data.phone` → BLOCK | OK nhưng thiếu email check |
| First-touch lock | FOR UPDATE trên lead row | Tốt — ngăn race condition |
| Unique claim constraint | `(collaborator_id, lead_id)` unique | Tốt — 1 CTV / 1 lead |
| Active status check | CTV must be "active" to submit | Tốt |
| Claim review workflow | Manual approve/reject by Admin/Manager | Tốt nhưng bottleneck tiềm năng |

### Vấn đề

| ID | Mức độ | Vấn đề | File:Line |
|----|--------|--------|-----------|
| B-1 | **High** | **Thiếu reactivate flow**: CTV bị suspended không thể kích hoạt lại. `approve_collaborator()` kiểm tra `if collaborator.status == "suspended": raise BusinessRuleViolation`. Không có endpoint reactivate riêng | `collaborator_service.py:223-224` |
| B-2 | **High** | **`CollaboratorUpdate` cho phép thay đổi `status` trực tiếp**: Schema có field `status: Optional[str] = None`. Admin/Manager có thể gửi PUT với `status: "active"` hoặc bất kỳ string nào, bypass hoàn toàn approve/suspend workflow | `schemas/collaborator.py:90` |
| B-3 | Medium | **Thiếu rate limiting cho lead submission**: CTV có thể spam submit hàng trăm lead/phút qua `/api/ctv/leads/submit`. Không có throttle | `routers/collaborators.py:280` |
| B-4 | Medium | **Self-claim chỉ check phone**: CTV có thể tạo lead với email của chính mình. Chỉ phone được kiểm tra, không email | `collaborator_service.py:303` |
| B-5 | Low | Thiếu batch claim: Mỗi lead phải submit riêng lẻ — không hiệu quả cho CTV quy mô lớn | — |

---

## 4. QUẢN LÝ DỮ LIỆU

### Schema Summary

```sql
-- collaborator table (9 indexes)
CREATE TABLE collaborator (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(20) UNIQUE NOT NULL,       -- CTV-YYYY-XXXX
    full_name       VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    phone           VARCHAR(20) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    user_id         INTEGER UNIQUE REFERENCES user(id) ON DELETE SET NULL,
    unit_id         INTEGER NOT NULL REFERENCES organization_unit(id),
    managed_by_officer_id INTEGER REFERENCES user(id) ON DELETE SET NULL,
    id_card_number  VARCHAR(20),
    bank_account    VARCHAR(50),
    bank_name       VARCHAR(100),
    address         VARCHAR(500),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    deleted_at      TIMESTAMPTZ,                       -- soft delete
    approved_at     TIMESTAMPTZ,
    approved_by_id  INTEGER REFERENCES user(id) ON DELETE SET NULL
);

-- lead_claim table (4 indexes)
CREATE TABLE lead_claim (
    id              SERIAL PRIMARY KEY,
    collaborator_id INTEGER NOT NULL REFERENCES collaborator(id),
    lead_id         INTEGER NOT NULL REFERENCES lead(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    claim_data      JSON,                              -- {full_name, phone, email, notes}
    reviewed_by_id  INTEGER REFERENCES user(id) ON DELETE SET NULL,
    reviewed_at     TIMESTAMPTZ,
    rejection_reason VARCHAR(500),
    created_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (collaborator_id, lead_id)
);

-- lead table additions
ALTER TABLE lead ADD COLUMN referrer_id INTEGER REFERENCES collaborator(id) ON DELETE SET NULL;
ALTER TABLE lead ADD COLUMN validity_status VARCHAR(20) DEFAULT 'raw';
ALTER TABLE lead ADD COLUMN created_via VARCHAR(20) DEFAULT 'manual';
```

### Data Integrity Analysis

| Aspect | Status | Ghi chú |
|--------|--------|---------|
| Soft delete | ✅ OK | `deleted_at` column, queries filter `IS NULL` |
| FK integrity | ✅ OK | Proper `ondelete=SET NULL` cho optional FKs |
| Unique constraints | ✅ OK | `code`, `user_id`, `(collaborator_id, lead_id)` |
| Indexes | ✅ OK | 9 indexes trên collaborator, 4 trên lead_claim |
| Enum validation | ⚠ Partial | Enums defined in Python, NOT in DB. DB accepts any string |

### Vấn đề

| ID | Mức độ | Vấn đề | File:Line |
|----|--------|--------|-----------|
| D-1 | **High** | **Race condition trong `generate_next_code`**: Dùng `SELECT MAX(code)` không có `FOR UPDATE` (vì PG không cho phép `FOR UPDATE` với aggregates). Hai concurrent requests có thể get cùng MAX → generate cùng code. Retry loop (3 lần) + unique constraint giảm thiểu nhưng vẫn có thể fail dưới high concurrency | `collaborator_repository.py:160-187` |
| D-2 | Medium | **Phone uniqueness chỉ trong bảng collaborator**: Không cross-check với bảng `user` hoặc `lead`. CTV phone có thể trùng với thí sinh đã tồn tại | `collaborator_repository.py:77-89` |
| D-3 | Medium | **Cần verify index trên `lead.referrer_id`**: FK tồn tại nhưng cần confirm index cho `get_leads_by_referrer` performance | Migration file |
| D-4 | Medium | **Stats query không tối ưu**: 4 separate COUNT queries thay vì single GROUP BY. Với CTV có hàng ngàn leads → chậm | `lead_repository.py:1278+` |
| D-5 | Low | **`claim_data` JSON column**: Không thể query/filter trực tiếp trên tên/SĐT trong claim_data | `models/collaborator.py:138-139` |

---

## 5. BẢO MẬT & PHÂN QUYỀN

### Security Model

```
┌─────────────────────────────────────────────────────┐
│                 ACCESS CONTROL MATRIX                 │
├──────────────────┬──────┬─────────┬─────────┬───────┤
│ Resource         │Admin │Manager  │Officer  │CTV    │
├──────────────────┼──────┼─────────┼─────────┼───────┤
│ List CTVs        │ ALL  │ OWN_UNIT│ MANAGED │  —    │
│ Create CTV       │ YES  │ YES     │  —      │  —    │
│ Update CTV       │ ALL  │ OWN_UNIT│  —      │  —    │
│ Approve CTV      │ ALL  │ OWN_UNIT│  —      │  —    │
│ Suspend CTV      │ ALL  │ OWN_UNIT│  —      │  —    │
│ List Claims      │ ALL  │ OWN_UNIT│  —¹    │  —    │
│ Review Claim     │ ALL  │ OWN_UNIT│  —      │  —    │
│ Own Profile      │  —   │  —      │  —      │ OWN   │
│ Own Leads        │  —   │  —      │  —      │ OWN   │
│ Submit Lead      │  —   │  —      │  —      │ OWN   │
│ Own Claims       │  —   │  —      │  —      │ OWN   │
│ Own Stats        │  —   │  —      │  —      │ OWN   │
│ Phone Check      │  —   │  —      │  —      │ YES   │
└──────────────────┴──────┴─────────┴─────────┴───────┘

> ¹ **Xác minh 2026-02-25**: Officer **KHÔNG có** Casbin access tới `/api/collaborators/claims`. Route này chỉ nằm trong MANAGER_TEMPLATE (`policy_templates.py:307`), không phải OFFICER_TEMPLATE (L85-165). Diamond inheritance: `admin > manager > officer` — Manager kế thừa Officer, không phải ngược lại.
```

### Security Mechanisms (Hiện có)

| Mechanism | Status | Ghi chú |
|-----------|--------|---------|
| IDOR protection | ✅ | 3-tier: Admin (all) > Manager (unit) > 404 |
| Phone masking | ✅ | CTV thấy `0912***456`, không thấy full phone |
| FOR UPDATE locks | ✅ | Claim review + first-touch lock |
| Self-claim prevention | ✅ | Phone check (nhưng thiếu email) |
| Role separation | ✅ | `UserRole.COLLABORATOR` riêng, không kế thừa officer |
| Return 404 not 403 | ✅ | Đúng pattern ngăn resource enumeration |

### Vấn đề

| ID | Mức độ | Vấn đề | File:Line | Chi tiết |
|----|--------|--------|-----------|----------|
| S-1 | **Low** *(hạ từ Critical — xác minh 2026-02-25)* | **`list_claims` thiếu Officer scope filter (phòng ngừa)** | `routers/collaborators.py:118-142` | `list_claims` chỉ filter `unit_id` cho Manager, không có filter cho Officer. **Tuy nhiên**, OFFICER_TEMPLATE (`policy_templates.py:85-165`) **KHÔNG chứa** route `/api/collaborators/claims` — route này nằm trong MANAGER_TEMPLATE (L307). Do Casbin chặn Officer trước khi vào function, issue **không exploitable hiện tại**. Khuyến nghị: thêm defensive filter `if current_user.role == UserRole.OFFICER: raise ResourceNotFoundError(...)` để phòng trường hợp Casbin policy thay đổi trong tương lai |
| S-2 | **High** | **Financial data exposed** | `schemas/collaborator.py:124-148` | `CollaboratorResponse` chứa `id_card_number`, `bank_account`, `bank_name` gửi cho mọi GET request. Sensitive info không nên exposed mặc định |
| S-3 | **High** | **`sort_by` column enumeration** | `collaborator_repository.py:140` | `getattr(models.Collaborator, sort_by, ...)` cho phép thử arbitrary attribute names. Attacker có thể discover internal columns (bank_account, id_card_number, etc.) dù không thấy values |
| S-4 | Medium | **Phone check information disclosure** | `collaborator_service.py:504-511` | `/api/ctv/leads/check-phone` trả "Lead đang được tư vấn" — tiết lộ trạng thái internal. CTV có thể enumerate phones để khám phá lead states |
| S-5 | Medium | **PII không mã hóa trong claim_data JSON** | `models/collaborator.py:138-139` | `lead_claim.claim_data` chứa `full_name`, `phone`, `email` dạng plaintext. Nếu DB bị compromise → PII lộ |

---

## 6. TÍNH TOÁN HOA HỒNG & THANH TOÁN

### Status: CHƯA TRIỂN KHAI → ĐÃ CÓ KẾ HOẠCH

> **Kế hoạch triển khai**: `docs/CTV_COMMISSION_PLAN.md` (Phase 1-4)
>
> **Quyết định nghiệp vụ đã xác nhận**:
> - Scope: Global (không phân theo đơn vị)
> - Base: Chỉ học phí (tuition fee)
> - Approval: 1 bước (Admin duyệt)
> - Hoàn hoa hồng: Không hoàn (quyết định sinh viên)
> - CTV categories: Chưa cần (deferred)

**Hiện có (foundation):**
- `CONFIG_ATTRIBUTION_EXPIRE_DAYS = 90` — constant chuẩn bị cho zombie lock window
- `bank_account`, `bank_name` columns trên Collaborator model
- `CollaboratorStats` schema skeleton (total_leads, valid_leads, qualified_leads, converted_leads)

**Chưa có (sẽ triển khai theo CTV_COMMISSION_PLAN.md):**
- Bảng `commission_policy` + `commission` (2 bảng — đơn giản hóa theo quyết định nghiệp vụ)
- Commission calculation logic (percentage-based, global scope)
- Commission approval workflow (pending → approved → paid | rejected)
- Enrollment trigger (Celery task khi lead đạt sts11)
- Attribution expiry cron job

### Rủi ro nếu thiếu Commission

| ID | Mức độ | Rủi ro | Ghi chú |
|----|--------|--------|---------|
| C-1 | **Critical** | **Không có commission tracking**: CTV không có động lực vì không thể theo dõi hoặc nhận hoa hồng | Sẽ giải quyết trong Phase 2-3 |
| C-2 | Medium | **Không có attribution expiry**: CTV claim lead rồi bỏ → lead bị "khóa" referrer_id vĩnh viễn. 90-day window constant tồn tại nhưng KHÔNG active | Backlog — cần cron job |
| C-3 | Medium | Không có commission rules engine (% hoa hồng, điều kiện) — hiện chỉ plan percentage-based global | Sẽ giải quyết trong Phase 2 |

---

## 7. API & BACKEND

### Endpoint Inventory

**Admin/Manager Router** (`/api/collaborators/`):

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| GET | `/collaborators` | check_permission | List CTVs (filtered) |
| POST | `/collaborators` | require_admin_or_manager | Create CTV |
| GET | `/collaborators/claims` | check_permission | List all claims |
| GET | `/collaborators/claims/{id}` | get_lead_claim_for_review | Claim detail |
| POST | `/collaborators/claims/{id}/review` | require_admin_or_manager | Review claim |
| GET | `/collaborators/{id}` | get_collaborator_for_user | CTV detail |
| PUT | `/collaborators/{id}` | require_admin_or_manager | Update CTV |
| POST | `/collaborators/{id}/approve` | require_admin_or_manager | Approve CTV |
| POST | `/collaborators/{id}/suspend` | require_admin_or_manager | Suspend CTV |

**CTV Self-Service Router** (`/api/ctv/`):

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| GET | `/ctv/profile` | get_own_collaborator | Own profile |
| GET | `/ctv/leads` | get_own_collaborator | Own leads (masked) |
| POST | `/ctv/leads/submit` | get_own_collaborator | Submit lead claim |
| GET | `/ctv/leads/check-phone` | get_own_collaborator | Phone availability |
| GET | `/ctv/claims` | get_own_collaborator | Own claims |
| GET | `/ctv/stats` | get_own_collaborator | Own stats |

### Validation Analysis

| Input | Validation | Status |
|-------|-----------|--------|
| Phone (CTV) | Vietnam format normalization | ✅ OK |
| Phone (Lead claim) | Vietnam format normalization | ✅ OK |
| Email | Optional EmailStr (Pydantic) | ✅ OK |
| Pagination | `skip >= 0`, `limit 1-100` | ✅ OK |
| sort_by | ⚠ Not whitelisted | ❌ Cần fix |
| status filter | Not validated against enum | ⚠ Partial |
| CollaboratorUpdate.status | Not validated | ❌ Cần fix |

### Vấn đề

| ID | Mức độ | Vấn đề | File:Line |
|----|--------|--------|-----------|
| P-1 | **High** | **Status field trong update không validate enum**: `CollaboratorUpdate.status` chấp nhận bất kỳ string nào. Service `update_collaborator()` dùng `setattr(collaborator, field, value)` trực tiếp — DB accept any string vì column là VARCHAR, không có DB-level enum check | `collaborator_service.py:178-179`, `schemas/collaborator.py:90` |
| P-2 | Medium | **Thiếu endpoint `updateLeadValidity`**: Schema `LeadValidityUpdate` tồn tại, service function `update_lead_validity()` tồn tại, nhưng KHÔNG có router endpoint expose nó | Router file — missing |
| P-3 | Medium | **Officer list CTV nhưng không có claim context**: Officer thấy managed CTVs (forced `managed_by_officer_id` filter) nhưng không thể xem claims từ CTVs đó — UX thiếu hoàn chỉnh | `routers/collaborators.py:67-73` |
| P-4 | Low | **Thiếu persistent audit trail**: Chỉ có structlog (ephemeral logs). Không có bảng `audit_log` cho CTV lifecycle events (create, approve, suspend, claim review) | — |
| P-5 | Low | **TOCTOU gap giữa check-phone và submit**: Giữa 2 API calls, status có thể thay đổi. Tuy nhiên `submit_lead_claim` xử lý atomic → TOCTOU chỉ ảnh hưởng UX, không ảnh hưởng data integrity | — |

---

## 8. FRONTEND / UX

### Điểm mạnh

- **Responsive design**: Desktop table + Mobile cards cho cả admin và CTV dashboard
- **Vietnamese localization**: Toàn bộ labels, messages, date formatting (`vi-VN`)
- **AlertDialog**: Dùng cho destructive actions (approve, suspend) — đúng pattern
- **Real-time phone check**: Debounced 500ms trong SubmitLeadDialog
- **Skeleton loading**: Đầy đủ cho mọi loading state
- **Accessibility**: `aria-label` trên icon buttons, `aria-hidden` trên decorative icons
- **TanStack Table**: Proper column definitions, manual pagination, sorting

### Vấn đề

| ID | Mức độ | Vấn đề | File:Line | Chi tiết |
|----|--------|--------|-----------|----------|
| F-1 | Medium | **CTV Dashboard thiếu pagination** | `CTVDashboardClient.tsx:91-92` | `useCTVLeads()` và `useCTVClaims()` không truyền skip/limit params → chỉ load trang đầu (default limit=10). CTV có > 10 leads sẽ không thấy hết |
| F-2 | Medium | **Admin search không debounce** | `CollaboratorsClient.tsx:588-590` | `setSearch(e.target.value)` fire query mỗi keystroke. Gõ "Nguyễn Văn" = ~10 API calls |
| F-3 | Medium | **CTV Dashboard thiếu error handling** | `CTVDashboardClient.tsx` | Nếu API returns error, UI chỉ hiện skeleton vô hạn. Không có error state/retry |
| F-4 | Low | **Thiếu claim detail view cho CTV** | `CTVDashboardClient.tsx:249-254` | CTV chỉ thấy rejection_reason inline, không có dialog xem chi tiết claim |
| F-5 | ~~Low~~ **Not a bug** *(xác minh 2026-02-25)* | **HTML entity trong JSX** | `CTVDashboardClient.tsx:105` | `&agrave;` trong JSX **renders đúng** thành `à`. JSX hỗ trợ HTML entities natively. Output hiển thị "Xin chào, [name]" chính xác. Có thể thay bằng ký tự trực tiếp `à` cho consistency nhưng **không phải bug** |
| F-6 | Low | **Empty state thiếu CTA** | `CTVDashboardClient.tsx:225-226` | "Chưa có yêu cầu claim nào." — không có button hướng dẫn CTV submit lead đầu tiên |

---

## 9. HIỆU NĂNG & KHẢ NĂNG MỞ RỘNG

### Current Performance Profile

| Endpoint | DB Queries | Lock type | Bottleneck risk |
|----------|-----------|-----------|-----------------|
| GET /ctv/stats | 5 (4 COUNT + 1 claim count) | None | **High** — scales linearly with lead count |
| POST /ctv/leads/submit | 3-5 (phone check + lead upsert + claim insert) | FOR UPDATE (lead row) | Medium — serialization under concurrent claims |
| GET /collaborators | 2 (count + filtered list) | None | Low |
| POST /collaborators/{id}/approve | 1 (flush) | None | Low |
| POST /collaborators (create) | 3-5 (phone check + code gen + insert + maybe user update) | Savepoint | Medium — code generation collision |

### Vấn đề

| ID | Mức độ | Vấn đề | Impact | Fix |
|----|--------|--------|--------|-----|
| E-1 | **High** | Stats query 4 separate COUNT | 5 DB round-trips per dashboard load. 10K leads/CTV → noticeable latency | Single `GROUP BY validity_status` query |
| E-2 | Medium | `selectinload` luôn load 4 relationships | `get_by_id` load unit + officer + user + approved_by. Nhiều use cases chỉ cần basic info | Tạo `get_by_id_lite()` cho simple lookups |
| E-3 | Medium | `check_first_touch_for_update` row lock | FOR UPDATE lock toàn bộ lead row. Nhiều CTV claim cùng phone → serialization | Acceptable trade-off cho data integrity |
| E-4 | Low | Thiếu caching cho stats | Stats tính realtime mỗi request. Với large datasets → wasted DB cycles | Redis cache với 5-10 phút TTL |

---

## 10. RỦI RO PRODUCTION

### Abuse Scenarios

| Scenario | Mức độ | Mô tả | Mitigation hiện tại | Khuyến nghị |
|----------|--------|-------|---------------------|-------------|
| **CTV spam lead** | **Critical** | CTV tạo hàng trăm fake leads/ngày để inflate stats hoặc claim commissions (Phase 2) | Self-phone check (M2) only. Không rate limit | Rate limit 5-10 leads/phút/CTV |
| **Phone enumeration** | **High** | CTV dùng check-phone API để scan toàn bộ phone database, biết ai đang được tư vấn | Không mitigation | Rate limit + generic messages |
| **Status bypass** | **High** | Admin PUT với `status: "active"` bypass approve workflow | Không validation | Xóa status từ update schema |
| **Ghost attribution** | Medium | CTV inactive nhưng leads vĩnh viễn gắn referrer_id | `CONFIG_ATTRIBUTION_EXPIRE_DAYS=90` chưa active | Implement expiry cron |
| **Cross-CTV poaching** | Medium | CTV A check phone, biết available, gọi điện trước rồi claim | Inherent in first-touch model | Document policy, không technical fix |
| **Data harvesting** | Medium | Suspended CTV vẫn có user account. Nếu user role không bị reset → có thể access other endpoints | `get_own_collaborator` checks active status | OK nhưng nên audit user role cleanup |

### Single Points of Failure

1. **Code generation**: `SELECT MAX` → sequential bottleneck khi tạo nhiều CTV cùng lúc
2. **Claim submission**: FOR UPDATE lock → serialization khi nhiều CTV claim cùng phone
3. **Manual claim review**: Admin/Manager phải duyệt từng claim — bottleneck với lượng lớn CTV

---

## 10A. XÁC MINH BỔ SUNG (2026-02-25)

> **Phương pháp**: Line-by-line source code review đối chiếu với audit report. Đọc trực tiếp toàn bộ files: `policy_templates.py`, `deps.py`, `collaborators.py`, `collaborator_service.py`, `collaborator_repository.py`, `lead_claim_repository.py`, `lead_repository.py`, `CTVDashboardClient.tsx`, `SubmitLeadDialog.tsx`, `useCollaborators.ts`, `collaborator.types.ts`.

### Issues bổ sung đã xác minh

| ID | Severity | Mô tả | File:Line | Ghi chú |
|----|----------|-------|-----------|---------|
| NEW-B1 | Medium *(phòng ngừa)* | `get_collaborator_for_user` chỉ check Admin & Manager, Officer fall-through vào 404 "by accident" | `deps.py:2000-2005` | Officer hiện không có Casbin access tới `/{id}` endpoints. Behavior đúng nhưng không by design — nếu sau này thêm Officer vào Casbin policy sẽ vô tình mở full access. Khuyến nghị: thêm explicit Officer check |
| NEW-B2 | Low *(fragile coupling)* | `get_lead_claim_for_review` truy cập `claim.collaborator.unit_id` phụ thuộc eager loading | `deps.py:2023` | **Hiện KHÔNG phải bug**: `LeadClaimRepository.get_by_id()` (`lead_claim_repository.py:21-32`) **CÓ** `selectinload(models.LeadClaim.collaborator)`. Concern là fragile coupling — nếu ai đổi repo method sẽ gây `DetachedInstanceError` |
| NEW-B3 | Medium *(phòng ngừa)* | `update_collaborator` service dùng `setattr` loop không có field whitelist | `collaborator_service.py:178-180` | Hiện `CollaboratorUpdate` schema không có `unit_id`, nhưng nếu ai thêm vào schema → service cho phép thay đổi unit, phá vỡ scope isolation |
| NEW-B4 | Low | `count_leads_by_referrer_and_validity` mixing `validity_status` và `lead.status` | `lead_repository.py:1298-1314` | 3 counts đầu dùng `validity_status`, nhưng `converted_leads` dùng `lead.status == "converted"` — 2 classification systems khác nhau |
| NEW-F1 | Medium | CTV Dashboard không destructure `isError` — API error gây infinite loading | `CTVDashboardClient.tsx:89-92` | 4 hooks chỉ destructure `data` và `isLoading`, không có error state/retry UI |
| NEW-F3 | Low | Claims tab empty state thiếu CTA button | `CTVDashboardClient.tsx:225-227` | Leads tab có "Hãy gửi lead mới!" nhưng claims tab chỉ nói "Chưa có yêu cầu claim nào" — không có action button |
| NEW-F4 | Medium | Frontend `CollaboratorUpdate` type include `status` | `collaborator.types.ts:55` | Khi backend fix B-2/P-1 (xóa `status` khỏi schema), frontend type cũng cần sync |
| NEW-F5 | Medium | `SubmitLeadDialog.onSubmit` không try-catch `mutateAsync` | `SubmitLeadDialog.tsx:109-111` | Nếu `mutateAsync` throw (network error), unhandled rejection xảy ra. Dialog state có thể stale |
| **NEW-B6** | **Critical** | **`enroll_student` return type phá vỡ architecture pattern — Blocker cho Commission Plan Task 3.5** | `admission_service.py:2761`, `admissions.py:787-812` | Xem phân tích chi tiết bên dưới |

#### [NEW-B6] `enroll_student` return Dict thay vì Tuple — Blocker cho Commission Trigger
**Severity: CRITICAL** | `admission_service.py:2761` & `admissions.py:787-812`

`enroll_student()` là **hàm state-changing duy nhất** trong `admission_service.py` trả `Dict[str, Any]` trực tiếp thay vì `Tuple[result, callback]`:

| Function | Return Type | Theo pattern? |
|----------|------------|---------------|
| `approve_profile` | `tuple[result, callback]` | ✅ |
| `reject_profile` | `tuple[result, callback]` | ✅ |
| `confirm_profile` | `tuple[result, callback]` | ✅ |
| `override_status` | `tuple[result, callback]` | ✅ |
| **`enroll_student`** | **`Dict[str, Any]`** | ❌ |

Router (`admissions.py:787-812`) tiêu thụ result bằng dict access:
```python
result = await admission_service.enroll_student(db, profile_id, current_user)
await db.commit()
await safe_dispatch(..., payload={"student_id": result["student_id"], ...})
```

**Impact**: Commission Plan Task 3.5 đề xuất đổi return thành `return result, post_commit_callback`. Nếu apply mà không sửa router → `result["student_id"]` trở thành `tuple["student_id"]` → **TypeError crash** trên production.

**Giải pháp**: Refactor `enroll_student()` sang pattern `(result, callback)` trước, cập nhật router unpack tuple, rồi mới thêm commission trigger vào callback. Hoặc dùng `safe_dispatch` (đã có trong router) để trigger commission task mà không cần đổi return type.

### Điều chỉnh severity từ xác minh

| Issue gốc | Severity cũ | Severity mới | Lý do |
|-----------|-------------|--------------|-------|
| S-1 | Critical | **Low** | OFFICER_TEMPLATE (`L85-165`) **KHÔNG chứa** claims routes. Routes nằm trong MANAGER_TEMPLATE (`L307`). Officer bị Casbin chặn trước khi vào function |
| F-5 | Low | **Not a bug** | `&agrave;` trong JSX renders đúng thành `à`. JSX hỗ trợ HTML entities natively |

---

## 11. TỔNG HỢP VẤN ĐỀ THEO MỨC ĐỘ

### CRITICAL (2 vấn đề)

| ID | Vấn đề | Module | Trạng thái |
|----|--------|--------|------------|
| C-1 | Thiếu commission system (Phase 2 chưa triển khai) | Business | Có kế hoạch: `CTV_COMMISSION_PLAN.md` |
| NEW-B6 | `enroll_student` return Dict thay vì Tuple — Blocker cho Commission Task 3.5 | Architecture | **Phải fix trước Phase 3** |

> **S-1 đã hạ xuống LOW** (xác minh 2026-02-25): Officer không có Casbin access tới claims endpoint. Xem mục 5 để biết chi tiết.

### HIGH (7 vấn đề)

| ID | Vấn đề | Module | Trạng thái |
|----|--------|--------|------------|
| B-1 | Thiếu reactivate flow cho suspended CTV | Business | Cần fix |
| B-2 | `CollaboratorUpdate.status` cho phép bypass workflow | Business | Cần fix |
| P-1 | Status field trong update không validate enum | API | Cần fix |
| S-2 | Financial data (bank, CMND) exposed trong mọi response | Security | Cần fix |
| S-3 | `sort_by` cho phép SQL column enumeration | Security | Cần fix |
| D-1 | Race condition trong code generation (SELECT MAX) | Data | Cần fix |
| E-1 | Stats query 4 separate COUNT thay vì GROUP BY | Performance | Cần fix |

### MEDIUM (17 vấn đề — bao gồm 4 issues mới từ xác minh 2026-02-25)

| ID | Vấn đề | Module | Trạng thái |
|----|--------|--------|------------|
| C-2 | Thiếu attribution expiry (90-day zombie lock) | Business | Backlog |
| C-3 | Thiếu commission rules engine | Business | Có kế hoạch |
| B-3 | Thiếu rate limiting cho lead submission | Business | Cần fix |
| B-4 | Self-claim chỉ check phone, không email | Business | Cần fix |
| S-4 | Phone check information disclosure | Security | Backlog |
| S-5 | PII không mã hóa trong claim_data JSON | Security | Backlog |
| P-2 | Thiếu endpoint updateLeadValidity | API | Backlog |
| P-3 | Officer xem CTV nhưng không có claim context | API | Backlog |
| D-2 | Phone uniqueness chỉ check bảng collaborator | Data | Backlog |
| D-4 | Stats query không tối ưu (4 queries) | Data | Đã gộp vào E-1 |
| F-1 | CTV Dashboard thiếu pagination | Frontend | Cần fix |
| F-2 | Admin search không debounce | Frontend | Cần fix |
| F-3 | CTV Dashboard thiếu error handling | Frontend | Cần fix |
| NEW-B1 | `get_collaborator_for_user` thiếu explicit Officer check (phòng ngừa) | Security | Cần fix |
| NEW-B3 | `update_collaborator` setattr loop thiếu field whitelist (phòng ngừa) | Security | Cần fix |
| NEW-F1 | CTV Dashboard thiếu error state (`isError` không destructure) | Frontend | Cần fix |
| NEW-F4 | Frontend `CollaboratorUpdate` type include `status` — cần sync khi fix B-2 | Frontend | Fix cùng B-2 |
| NEW-F5 | `SubmitLeadDialog.onSubmit` thiếu try-catch cho `mutateAsync` | Frontend | Cần fix |

### LOW (9 vấn đề — bao gồm 3 issues mới, trừ F-5 đã loại)

| ID | Vấn đề | Module |
|----|--------|--------|
| A-1 | Service file quá lớn (511 lines) | Architecture |
| A-2 | Thiếu event/signal pattern cho Phase 2 | Architecture |
| B-5 | Thiếu batch claim submission | Business |
| D-5 | claim_data JSON không queryable | Data |
| P-4 | Thiếu persistent audit trail | API |
| S-1 | `list_claims` thiếu Officer filter (phòng ngừa — hạ từ Critical) | Security |
| NEW-B2 | `get_lead_claim_for_review` phụ thuộc eager loading (fragile coupling) | Security |
| NEW-B4 | `count_leads_by_referrer_and_validity` mixing `validity_status` và `lead.status` | Data |
| F-4 | CTV thiếu claim detail view | Frontend |
| F-6 | Empty state thiếu CTA button | Frontend |

---

## 12. CHECKLIST PRODUCTION

### Phase 1: Must-Have (Blockers) — Ước lượng 2-3 ngày

- [ ] **[B-2/P-1] Xóa `status` field khỏi `CollaboratorUpdate` schema** — ngăn bypass workflow
- [ ] **[S-1] Thêm defensive officer filter cho `list_claims`** — phòng ngừa (hạ từ Critical → Low, xem mục 5)
- [ ] **[S-3] Whitelist `sort_by` parameter** — chỉ cho phép: `created_at`, `full_name`, `code`, `phone`, `status`
- [ ] **[B-1] Thêm `reactivate` endpoint** cho suspended → active transition
- [ ] **[B-3] Thêm rate limit cho `/api/ctv/leads/submit`** (5-10 leads/phút)
- [ ] **[B-3] Thêm rate limit cho `/api/ctv/leads/check-phone`** (20 calls/phút)

### Phase 2: Should-Have (Production-Ready) — Ước lượng 3-5 ngày

- [ ] **[E-1/D-4] Optimize stats query** — single GROUP BY thay vì 4 COUNT
- [ ] **[D-1] Fix code generation** — dùng PostgreSQL sequence hoặc advisory lock
- [ ] **[S-2] Mask sensitive data** — tạo `CollaboratorSummaryResponse` (không có bank/CMND) cho list view
- [ ] **[F-1] Thêm pagination cho CTV dashboard** leads/claims tabs
- [ ] **[F-2] Debounce search** trên admin page (300ms)
- [ ] **[S-4] Generic hóa phone check messages** — không tiết lộ lead internal state
- [ ] **[F-3/NEW-F1] Thêm error handling** cho CTV dashboard (destructure `isError` + retry UI)
- [ ] **[P-2] Thêm endpoint `updateLeadValidity`** vào router (service đã sẵn sàng)
- [ ] **[NEW-B1] Thêm explicit Officer check** trong `get_collaborator_for_user` (phòng ngừa)
- [ ] **[NEW-B3] Thêm field whitelist** trong `update_collaborator` setattr loop
- [ ] **[NEW-F4] Sync frontend `CollaboratorUpdate` type** — xóa `status` khi fix B-2
- [ ] **[NEW-F5] Wrap `onSubmit` trong try-catch** — `SubmitLeadDialog.tsx`
- [ ] **[NEW-B6] Refactor `enroll_student` return type** — đổi từ `Dict` sang `Tuple[result, callback]` + cập nhật router unpack *(BLOCKER cho Commission Phase 3)*

### Phase 3: Nice-to-Have (Post-Launch) — Backlog

- [ ] **[P-4] Persistent audit trail** table cho CTV actions
- [ ] **[E-4] Redis caching** cho CTV stats (5 phút TTL)
- [ ] **[A-1] Tách `lead_claim_service.py`** khỏi collaborator_service
- [ ] **[B-4] Email cross-check** trong self-claim prevention
- [ ] Notification system khi claim được duyệt/từ chối
- [ ] Batch lead submission endpoint
- [ ] CTV self-service profile update endpoint
- [x] ~~**[F-5] Fix HTML entity**~~ — **Not a bug**: `&agrave;` renders đúng trong JSX (xác minh 2026-02-25)
- [ ] **[F-6] Add CTA** button trong empty states

---

## 13. KẾ HOẠCH KHẮC PHỤC

> **Kế hoạch chi tiết đầy đủ**: Xem `docs/CTV_COMMISSION_PLAN.md`
>
> Tài liệu này tổng hợp roadmap 4 phase kết hợp khắc phục audit + triển khai commission system.

### Tổng quan Roadmap

| Phase | Nội dung | Thời gian | Mục tiêu |
|-------|----------|-----------|----------|
| **Phase 1** | Security Hardening + Commission Foundation | 3 ngày | Fix Critical/High audit issues + tạo DB models/schemas cho commission |
| **Phase 2** | Commission Service Layer | 3-4 ngày | Business logic: calculate, approve, reject, pay + Celery task |
| **Phase 3** | Commission API + Enrollment Trigger | 3-4 ngày | Router endpoints, IDOR deps, Casbin, kết nối enrollment trigger |
| **Phase 4** | Frontend + Performance + Cleanup | 4-5 ngày | Commission UI cho CTV/Admin, fix Medium/Low audit issues |

### Nguyên tắc triển khai

1. **Foundation trước Services**: Phase 1 (models, schemas, migration) phải hoàn thành trước Phase 2 (business logic)
2. **Services trước API**: Phase 2 (service + repository) phải có unit tests pass trước Phase 3 (router endpoints)
3. **Backend trước Frontend**: Phase 3 (API) phải hoạt động + test trước Phase 4 (frontend)
4. **Test mỗi Phase**: Chạy toàn bộ test suite sau mỗi phase để đảm bảo không regression

### Audit Issues được giải quyết theo Phase

| Phase | Issues |
|-------|--------|
| Phase 1 | B-2/P-1, S-1 *(phòng ngừa)*, S-3, B-1, S-2, D-1, B-3, NEW-B1, NEW-B3 |
| Phase 2 | E-1/D-4, C-1 (partial), C-3, NEW-B4 |
| Phase 3 | C-1 (complete), **NEW-B6** *(blocker)*, GAP-1 đến GAP-4, GAP-7 |
| Phase 4 | F-1, F-2, F-3/NEW-F1, F-6, NEW-F4, NEW-F5, B-4, GAP-8 |
| Backlog | C-2, S-4, S-5, P-2, P-3, D-2, P-4, NEW-B2, GAP-5, GAP-6, GAP-9 |

---

## PHỤ LỤC: TEST COVERAGE HIỆN TẠI

| Test File | Test Cases | Coverage Area |
|-----------|-----------|---------------|
| `test_collaborator_api.py` | ~20 tests | IDOR, endpoint auth, CRUD |
| `test_collaborator.py` | ~15 tests | Service CRUD, phone uniqueness, approve/suspend |
| `test_collaborator_claim.py` | ~12 tests | Claim submit, 3-layer lock, review |
| `test_create_lead_referral.py` | ~15 tests | Lead creation with referrer, auto-assign |

### Thiếu test coverage

- [ ] Rate limiting tests (khi implement)
- [ ] Concurrent claim submission (race condition)
- [ ] Defensive officer filter cho claims (S-1 — phòng ngừa)
- [ ] Stats query accuracy
- [ ] CTV reactivate flow (khi implement)
- [ ] Edge case: CTV with suspended user account
- [ ] Edge case: Soft-deleted CTV's leads
- [ ] Frontend E2E: CTV dashboard flow
- [ ] Frontend E2E: Admin claim review flow
