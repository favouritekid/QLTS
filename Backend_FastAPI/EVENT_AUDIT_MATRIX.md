# Event Audit Matrix

> **Ngày audit:** 2026-03-31
> **Updated:** 2026-04-03 — Cleanup PR #93 + migration PR #95 applied. A2/A13/Finding 5 resolved. Appendix counts updated.
> **Phạm vi:** Toàn bộ SystemEvents (51), AdmissionEventProjections (20), Finance DomainEvents (18)
> **Mục tiêu:** Xác định event nào khai báo nhưng không trigger, trigger nhưng không phù hợp nghiệp vụ, hoặc nghiệp vụ có nhưng thiếu event

---

## Mục lục

1. [Kiến trúc 3 hệ thống event](#1-kiến-trúc-3-hệ-thống-event)
2. [Legend](#2-legend)
3. [Phase 1: Lead](#3-phase-1-lead)
4. [Phase 2: Consultation](#4-phase-2-consultation)
5. [Phase 3: Admission](#5-phase-3-admission)
6. [Phase 4: Fee / Payment](#6-phase-4-fee--payment)
7. [Phase 5: Enrollment](#7-phase-5-enrollment)
8. [Cross-cutting: CTV / Collaborator](#8-cross-cutting-ctv--collaborator)
9. [Cross-cutting: System / Admin](#9-cross-cutting-system--admin)
10. [Cross-cutting: Security](#10-cross-cutting-security)
11. [Cross-cutting: Organization (broadcast-only)](#11-cross-cutting-organization-broadcast-only)
12. [Dead / Future modules](#12-dead--future-modules)
13. [Architectural Findings](#13-architectural-findings)
14. [Gap Summary & Priority](#14-gap-summary--priority)
15. [Recommended Actions](#15-recommended-actions)

---

## 1. Kiến trúc 3 hệ thống event

Hệ thống hiện tại có **3 event system chạy song song**:

| Hệ thống | File gốc | Cơ chế | Mục đích | Runtime status |
|---|---|---|---|---|
| **SystemEvents** | `core/events.py` | `dispatch()` / `safe_dispatch()` | User-facing notification (browser, email, Zalo) | **ACTIVE** — 44/51 events có dispatch |
| **DomainEvent** | `core/finance_events.py` | `emit_event()` + handler registry | Cross-module communication (Finance) | **DEAD CODE** — 0 emit calls, 0 handlers |
| **AdmissionEventProjection** | `core/admission_event_mapping.py` | `get_projection()` → `sync_lead_from_admission()` | Lead ↔ Pipeline stage/status sync | **ACTIVE** — inline calls từ services |

### Dispatch patterns

| Pattern | Dùng ở | Transaction | Error handling |
|---|---|---|---|
| `dispatch()` | Service layer | Caller owns — trả `(ids, callback)` | Raise lên caller |
| `safe_dispatch()` | Router layer (sau `db.commit()`) | Tự commit + tự rollback | Nuốt hết, chỉ log warning |
| `emit_event()` | (Không ai dùng) | N/A | N/A |
| Direct inline call | Service → `sync_lead_*()` | Trong transaction của service | Phụ thuộc caller |

---

## 2. Legend

### Cột Defined
- **Yes**: Có trong `SystemEvents` enum + `NOTIFICATION_REGISTRY`
- **Yes(enum)**: Có trong `SystemEvents` enum, KHÔNG có registry config
- **Yes(proj)**: Chỉ có `AdmissionEventProjection`, không có SystemEvent
- **No**: Không có event/config nào

### Cột Emitted
- **Yes**: Có `dispatch()` hoặc `safe_dispatch()` call trong code
- **Yes(beat)**: Emit từ Celery Beat scheduled task
- **No**: Không có dispatch call nào
- **Stub**: Có TODO comment nhưng chưa implement

### Cột Business-fit
- **Fit**: Đúng ý nghĩa nghiệp vụ, đúng thời điểm trigger
- **Partial**: Đúng một phần, còn thiếu cascade hoặc thiếu pair
- **Weak**: Có dấu hiệu lệch ownership hoặc flow
- **No**: Khai báo nhưng chưa có flow thật / business cần nhưng chưa có event

### Cột Recipient-fit
- **Fit**: Resolver trả đúng người cần nhận
- **Partial**: Resolver có nhưng cần rà lại scope
- **N/A**: Không có dispatch nên chưa evaluate được

### Cột Runtime
- **Yes**: Có Playwright/E2E runtime coverage
- **Backend-only**: Có emitter/unit test backend
- **No**: Chưa có coverage

---

## 3. Phase 1: Lead

> Pipeline: stg01 (Chưa tư vấn) → stg02 (Đang tư vấn)
> Statuses: sts00, sts01, sts02, sts03, sts04, sts05, sts06, sts15, sts19

| # | Event | Owner | Dispatch file:line | Method | Defined | Emitted | Business-fit | Recipient-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| L1 | `lead_created` | Lead | `services/lead_service.py:~1164` | `dispatch()` | Yes | Yes | Fit | Fit — `ActorExcluded(UnitManagers)` | Yes | Maintain |
| L2 | `lead_assigned` (auto-assign trong create) | Lead | `services/lead_service.py:~1178` | `dispatch()` | Yes | Yes | Fit | Fit — `LeadOwner` | Yes | Maintain |
| L3 | `lead_assigned` (gán thủ công) | Lead | `services/lead_service.py:~2138` | `dispatch()` | Yes | Yes | Fit | Fit — `LeadOwner` | Yes | Maintain |
| L4 | `lead_assigned` (auto-assign Celery) | Lead | `services/assignment_service.py:~436` | `dispatch()` | Yes | Yes | Fit | Fit — `LeadOwner` | No | Thêm runtime cho auto-assign flow |
| L5 | `lead_assignment_failed` | Lead | `services/assignment_service.py:~163,~258` | `dispatch()` | Yes | Yes | Fit | Fit — `ActorExcluded(UnitManagers)` | No | Thêm runtime/backend coverage |
| L6 | `lead_reassigned` | Lead | `services/lead_service.py:~1677` | `dispatch()` | Yes | Yes | Fit | Partial — `Composite([Specific, ActorExcluded(UnitManagers)])`. Cần verify old officer nhận không | No | Rà recipient cũ/mới + thêm coverage |
| L7 | `lead_status_changed` (direct update) | Lead | `routers/leads.py:~651` | `safe_dispatch()` | Yes | Yes | Fit | Fit — `LeadOwner` | Yes | Maintain |
| L8 | `lead_status_changed` (officer action) | Lead | `routers/leads.py:~1580` | `safe_dispatch()` | Yes | Yes | Fit | Fit — `LeadOwner` | No | Thêm runtime |
| L9 | `lead_updated` | Lead | `routers/leads.py:~675` | `safe_dispatch()` | Yes | Yes | Partial — chủ yếu cho UI real-time sync, không phải notification event thuần | Fit — `ActorExcluded(Composite([LeadOwner, UnitManagers]))` | No | Chốt: notification event hay chỉ real-time broadcast? |
| L10 | `lead_deleted` | Lead | `routers/leads.py:~733` | `safe_dispatch()` | Yes | Yes | Fit | Partial — `ActorExcluded(Composite([Specific, UnitManagers]))`. Specific lấy từ đâu? | No | Verify resolver + quyết định coverage level |
| L11 | `lead_restored` | Lead | `routers/leads.py:~779` | `safe_dispatch()` | Yes | Yes | Fit | Partial — `ActorExcluded(Composite([LeadOwner, UnitManagers]))` | No | Chốt recipient policy |
| L12 | `lead_imported` | Lead | `routers/leads.py:~1436` | `safe_dispatch()` | Yes | Yes | Fit | Partial — `ActorExcluded(UnitManagers)` | No | Backend-only coverage đủ |
| L13 | `officer_availability_changed` | Lead | `services/officer_service.py:~243` | `dispatch()` | Yes | Yes | Fit | Fit — `ActorExcluded(AllAdmins)` | No | Backend-only coverage đủ |

**Phase 1 summary:** 13 dispatch points, tất cả ACTIVE. Không có event nào khai báo thừa. Vùng cần rà: `lead_updated` có thật sự cần là notification hay chỉ real-time sync.

---

## 4. Phase 2: Consultation

> Pipeline: stg01–stg02 (trong context consultation)
> Statuses: sts00 → sts02 → sts03/sts04/sts05 → sts06

| # | Event | Owner | Dispatch file:line | Method | Defined | Emitted | Business-fit | Recipient-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | `consultation_created` | Consultation | `routers/leads.py:~811` | `safe_dispatch()` | Yes | Yes | Partial — event bản thân đúng, nhưng service cũng đổi `lead.consultation_status_id` + `lead.pipeline_stage_id` mà **không emit `lead_status_changed`** | Fit — `ActorExcluded(Composite([LeadOwner, UnitManagers]))` | No | **GAP-C1**: Thêm cascade `lead_status_changed` khi `status_updated=True` |
| C2 | `consultation_updated` | Consultation | `routers/leads.py:~997` | `safe_dispatch()` | Yes | Yes | Partial — chỉ emit khi `consultation_status_id` thay đổi (đúng). Nhưng lead state đã đổi mà chỉ có event consultation, không có event lead | Fit — `ActorExcluded(LeadOwner)` | No | **GAP-C2**: Thêm cascade `lead_status_changed` |
| C3 | `consultation_deleted` | Consultation | `routers/leads.py:~1042` | `safe_dispatch()` | Yes | Yes | Partial — delete cũng **revert** lead status về consultation trước đó nhưng không emit `lead_status_changed` | Partial — `ActorExcluded(LeadOwner)` | No | **GAP-C3**: Thêm cascade `lead_status_changed` khi revert |
| C4 | `consultation_reminder` | Consultation | `tasks/notification_tasks.py:~247` | `dispatch()` Beat | Yes | Yes(beat) | Fit — Celery Beat check lịch hẹn sắp tới mỗi phút | Fit — `LeadOwner` | Backend-only | Maintain |

### Chi tiết GAP-C1/C2/C3: Consultation → Lead status gap

**Vấn đề:** Service `lead_service.py` thực hiện:
```python
# add_consultation (line 1888-1910):
lead.consultation_status_id = new_status.id
lead.pipeline_stage_id = new_status.stage_id
sync_lead_status_from_consultation(lead, new_status)
```

Nhưng router chỉ emit `CONSULTATION_CREATED` — **không emit `LEAD_STATUS_CHANGED`**.

**Hệ quả:**
- Lead di chuyển trên pipeline (stg01 → stg02) khi tạo consultation
- Nhưng notification layer không biết lead đã đổi status
- Nếu có rule dựa trên `lead_status_changed` (vd: trigger CTV commission, trigger reporting) → sẽ bị miss

**Phase 2 summary:** 4 events, tất cả ACTIVE. Gap chính là **consultation CRUD đổi lead state nhưng event graph không phản ánh**.

---

## 5. Phase 3: Admission

> Pipeline: stg03 (Đã nộp hồ sơ) → stg04 (Kết quả hồ sơ)
> Statuses: sts07, sts08, sts09, sts13, sts16, sts17
> State machine: draft → submitted → approved/rejected/revision_requested → confirmed → enrolled

### 5a. Events có dispatch

| # | Event | Trigger / new_status | Dispatch file:line | Kèm LEAD_STATUS? | Defined | Emitted | Business-fit | Recipient-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| A1 | `application_created` | Tạo AdmissionProfile | `routers/admissions.py:~282` | Không | Yes | Yes | Fit | Fit — `ActorExcluded(Composite([LeadOwner, AllAdmins]))` | Yes | Maintain |
| ~~A2~~ | ~~`application_created` (legacy service)~~ | ~~`services/application_service.py`~~ | — | — | — | — | **RESOLVED** — `application_service.py` đã bị xóa trong cleanup PR #93. Chỉ còn 1 emit point tại `admissions.py:284`. Duplicate risk đã loại bỏ. | — | — | Không còn action |
| A3 | `application_status_changed` → submitted | Submit & evaluate | `routers/admissions.py:~767` | Không (draft→submitted) | Yes | Yes | Fit | Fit | Yes | Maintain |
| A4 | `application_status_changed` → approved | Single approve | `routers/admissions.py:~1504` | Yes → sts09 | Yes | Yes | Fit | Fit | Yes/Partial | Maintain |
| A5 | `application_status_changed` → approved | Bulk approve | `routers/admissions.py:~362` | Yes → sts09 | Yes | Yes | Fit | Fit | No | Thêm bulk runtime |
| A6 | `application_status_changed` → rejected | Single reject | `routers/admissions.py:~1606` | Yes → sts16 | Yes | Yes | Fit | Fit | No | Thêm runtime |
| A7 | `application_status_changed` → rejected | Bulk reject | `routers/admissions.py:~438` | Yes → sts16 | Yes | Yes | Fit | Fit | No | Thêm bulk runtime |
| A8 | `application_status_changed` → revision_requested | Yêu cầu bổ sung | `routers/admissions.py:~1696` | Yes → sts17 | Yes | Yes | Fit | Fit | No | Thêm runtime |
| A9 | `application_status_changed` → resubmitted | Nộp lại | `routers/admissions.py:~1796` | Yes → sts07 | Yes | Yes | Fit | Fit | No | Thêm runtime |
| A10 | `application_status_changed` → confirmed | Magic link xác nhận (public) | `routers/admissions.py:~2121` | Không (sts09→sts09, skip) | Yes | Yes | Fit | Fit | No | Thêm runtime |
| A11 | `application_status_changed` → enrolled | Enroll student | `routers/admissions.py:~1111` | Yes → sts11 | Yes | Yes | Fit | Fit | Partial | Maintain |
| A12 | `application_status_changed` → enrolled | Finalize enrollment | `routers/admissions.py:~1987` | Yes → sts11 | Yes | Yes | Partial — dedupe_key khác A11 (`finalized` vs `enrolled`), có thể duplicate nếu cả 2 gọi | Fit | No | **GAP-A12**: Chuẩn hóa dedupe_key |
| ~~A13~~ | ~~`application_documents_updated`~~ | ~~Update documents~~ | — | — | — | — | **RESOLVED** — Event retired trong cleanup PR #93. Enum, registry, metadata, frontend UI đã xóa. `application_service.py` đã xóa. | — | — | Không còn action |
| A14 | `application_deleted` | Xoá profile | `routers/admissions.py:~1217` | Không | Yes | Yes | Fit | Fit — `ActorExcluded(Composite([Specific, AllAdmins]))` | Yes | Maintain |

### 5b. Business transitions KHÔNG CÓ SystemEvent dispatch

| # | Business step | AdmissionEvent (pipeline sync) | SystemEvent | Hệ quả | Action |
|---|---|---|---|---|---|
| A15 | **Profile withdrawn** (rút hồ sơ) | `profile_withdrawn` → sts08/stg07 — sync qua `_create_admission_milestone_consultation()` | **KHÔNG CÓ** — `admission_service.py:4497` `withdraw_profile()` không dispatch | Officer gán cho lead không biết hồ sơ đã rút | **P1**: Thêm `APP_STATUS_CHANGED(withdrawn)` + `LEAD_STATUS_CHANGED(sts08)` |
| A16 | **Admin override** (duyệt đặc biệt) | `profile_overridden` → sts09/stg04 — sync qua milestone consultation | **KHÔNG CÓ** — `admissions.py:1857` `override_admission()` + `admission_service.py:4067` không dispatch | Officer/lead không biết hồ sơ được duyệt bởi admin | **P1**: Thêm `APP_STATUS_CHANGED(overridden)` + `LEAD_STATUS_CHANGED(sts09)` |

### 5c. Admission → Lead status mapping

```
Admission status    → Lead consultation_status  → Pipeline stage
─────────────────────────────────────────────────────────────────
draft               → sts06 (Đồng ý tư vấn)     → stg02
submitted           → sts07 (Đã tiếp nhận)       → stg03
resubmitted         → sts07 (Đã tiếp nhận)       → stg03
approved            → sts09 (Đủ ĐK nhập học)     → stg04
confirmed           → sts09 (Đủ ĐK nhập học)     → stg04  (same → skip lead sync)
overridden          → sts09 (Đủ ĐK nhập học)     → stg04
rejected            → sts16 (Không đạt)           → stg04
revision_requested  → sts17 (Yêu cầu bổ sung)    → stg03
withdrawn           → sts08 (Không tiếp tục)      → stg07
enrolled            → sts11 (Đã nhập học)          → stg06
```

**Phase 3 summary:** 14 active dispatch points + 2 missing transitions. Gap chính: `withdrawn` và `overridden` có pipeline sync nhưng không notify.

---

## 6. Phase 4: Fee / Payment

> Pipeline: stg05 (Xử lý học phí)
> Statuses: sts14 (Chưa hoàn tất), sts10 (Đã hoàn tất), sts18 (Đã hoàn phí)
> Finance status machines: Fee (pending→calculated→invoiced→partial→paid), Invoice (draft→issued→partial→paid→overdue), Payment (pending→verified→rejected→refunded)

### 6a. Events có dispatch

| # | Event | Trigger | Dispatch file:line | Method | Defined | Emitted | Business-fit | Recipient-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| F1 | `payment_received` | Ghi nhận thanh toán (maker) | `services/payment_service.py:~213` | `safe_dispatch()` trong post_commit | Yes | Yes | Fit | Fit — `SpecificUsers` (verifier) | Yes | Maintain — nhưng xem note kiến trúc ở [Section 13](#13-architectural-findings) |
| F2 | `payment_verified` | Xác nhận thanh toán (checker) | `services/payment_service.py:~385` | `safe_dispatch()` trong post_commit | Yes | Yes | Fit | Fit — `SpecificUsers` (officer + lead) | Yes | Maintain — nhưng xem note kiến trúc |

### 6b. Events khai báo nhưng KHÔNG dispatch

| # | Event | Registry config | Emitted | Business-fit | Lý do | Action |
|---|---|---|---|---|---|---|
| F3 | `payment_overdue` | Yes — resolver `SpecificUsers`, channels browser+email, priority 20 | **No** | **No** — có nhu cầu nghiệp vụ thực sự nhưng không có Celery Beat task check overdue | Chưa implement beat task quét `invoice.due_date < now()` | **P1**: Thêm Celery Beat task + dispatch |
| F4 | `dorm_fee_created` | Yes — resolver `DormResidents` | **No** | **Weak** — module Dorm chưa tích hợp, ownership nên thuộc Dorm không phải Finance | Module chưa build | P3: Chuyển ownership sang Dorm module |

### 6c. Business transitions KHÔNG CÓ SystemEvent

| # | Business step | Pipeline sync | SystemEvent | DomainEvent class | Hệ quả | Action |
|---|---|---|---|---|---|---|
| F5 | **Học phí được tính** (sts14/stg05) | `sync_lead_tuition_calculated()` — inline call từ `fee_calculation_service.py:182` | **KHÔNG CÓ** | `FeeCalculated` (defined, chưa emit) | Lead/officer không biết phải đóng bao nhiêu, lead di chuyển sang stg05 nhưng không notify | **P2**: Thêm SystemEvent |
| F6 | **Invoice phát hành** | Không có pipeline sync riêng | **KHÔNG CÓ** | `InvoiceIssued` (defined, chưa emit) | Lead không biết có invoice mới + deadline | **P2**: Thêm SystemEvent |
| F7 | **Payment bị reject** | Không có pipeline sync | **KHÔNG CÓ** | `PaymentRejected` (defined, chưa emit). `payment_service.py:442` có **TODO stub trống** | Officer ghi payment không biết bị reject | **P2**: Implement TODO stub |
| F8 | **Fee fully paid** (sts10/stg05) | `sync_lead_tuition_paid()` — inline call từ `payment_service.py:323` | **KHÔNG CÓ** | `FeeFullyPaid` (defined, chưa emit) | **Gate cuối trước enrollment** — milestone quan trọng nhất nhưng không notify | **P1**: Thêm SystemEvent |
| F9 | **Hoàn học phí** (sts18/stg05) | `sync_lead_tuition_refunded()` — inline call từ `payment_service.py:859` | **KHÔNG CÓ** | `RefundProcessed` (defined, chưa emit) | Lead/accountant không biết tiền đã hoàn | **P2**: Thêm SystemEvent |

### 6d. Lệ phí xét tuyển (Application Fee)

| # | Business step | Pipeline sync | SystemEvent | Hệ quả | Action |
|---|---|---|---|---|---|
| F10 | **Lệ phí xét tuyển confirmed** (sts13/stg03) | `sync_lead_fee_paid()` — gọi từ service khi `fee_type=application` fully paid | **KHÔNG CÓ** | Officer không biết lead đã nộp lệ phí | **P2**: Thêm SystemEvent |

**Phase 4 summary:** Chỉ 2/10+ business steps có SystemEvent. Finance là domain **thiếu notification coverage nhất**. DomainEvent system hoàn toàn dead code.

---

## 7. Phase 5: Enrollment

> Pipeline: stg06 (Đã nhập học) → stg07 (Không đi học)
> Statuses: sts11 (Enrolled), sts12 (Dropped)

| # | Event | Trigger | Dispatch file:line | Defined | Emitted | Business-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|---|
| E1 | `application_status_changed` → enrolled | Enroll student | `routers/admissions.py:~1111` | Yes | Yes | Fit | Partial | Maintain (xem A11) |
| E2 | `lead_status_changed` → sts11 | Enroll student | `routers/admissions.py:~1129` | Yes | Yes | Fit | Partial | Maintain |
| E3 | `application_status_changed` → enrolled | Finalize enrollment | `routers/admissions.py:~1987` | Yes | Yes | Partial — dedupe_key conflict với E1 | No | Chuẩn hóa dedupe (xem A12) |
| E4 | `lead_status_changed` → sts11 | Finalize enrollment | `routers/admissions.py:~2002` | Yes | Yes | Fit | No | Maintain |
| E5 | `lead_status_changed` → sts12 | Drop student | `routers/admissions.py:~2256` | Yes | Yes | **Partial** — chỉ emit `LEAD_STATUS_CHANGED`, **không emit `APPLICATION_STATUS_CHANGED`**. Inconsistent với mọi transition khác (A4-A12 đều emit cặp đôi) | No | **GAP-E5**: Thêm `APP_STATUS_CHANGED` cho consistency |

**Note:** Enrollment không có namespace riêng (`enrollment_*`), reuse `application_status_changed` + `lead_status_changed`. Chấp nhận được vì enrollment là terminal state của admission flow.

**Phase 5 summary:** Coverage tương đối tốt. Gap chính: drop student thiếu `APP_STATUS_CHANGED`.

---

## 8. Cross-cutting: CTV / Collaborator

| # | Event | Dispatch file:line | Method | Defined | Emitted | Business-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|---|
| CTV1 | `ctv_claim_submitted` | `routers/collaborators.py:~417` | `safe_dispatch()` | Yes | Yes | Fit | No | Thêm runtime |
| CTV2 | `ctv_claim_approved` | `routers/collaborators.py:~207` | `safe_dispatch()` | Yes | Yes | Fit | No | Thêm runtime |
| CTV3 | `ctv_claim_rejected` | `routers/collaborators.py:~220` | `safe_dispatch()` | Yes | Yes | Fit | No | Thêm runtime |
| CTV4 | `ctv_approved` | `routers/collaborators.py:~285` | `safe_dispatch()` | Yes | Yes | Fit | No | Thêm runtime |
| CTV5 | `ctv_suspended` | `routers/collaborators.py:~339` | `safe_dispatch()` | Yes | Yes | Fit | No | Thêm runtime |
| CTV6 | `ctv_commission_created` | `services/commission_service.py:~161` | `safe_dispatch()` | Yes | Yes | Fit | No | Thêm runtime |
| CTV7 | `ctv_attribution_expiring` | `tasks/collaborator_tasks.py:~130` | `safe_dispatch()` Beat | Yes | Yes(beat) | Fit | No | Backend-only đủ |
| CTV8 | `ctv_attribution_expired` | `tasks/collaborator_tasks.py:~112` | `safe_dispatch()` Beat | Yes | Yes(beat) | Fit | No | Backend-only đủ |
| CTV9 | `ctv_weekly_summary` | `tasks/collaborator_tasks.py:~238` | `safe_dispatch()` Beat | Yes | Yes(beat) | Fit | No | Backend-only đủ |
| CTV10 | `ctv_lead_converted` | — | — | Yes (registry có resolver + template đầy đủ) | **No** | **No** — CTV cần biết lead tiến triển nhưng không ai dispatch event này. Commission flow chỉ dispatch `ctv_commission_created` | N/A | **GAP-CTV10**: Thêm dispatch khi lead status đổi cho leads có `referrer_id` |

**CTV summary:** 9/10 ACTIVE. `ctv_lead_converted` là dead config — có registry config hoàn chỉnh nhưng không ai gọi.

---

## 9. Cross-cutting: System / Admin

| # | Event | Dispatch file(s) | Defined | Emitted | Business-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|
| S1 | `system_alert` | `routers/admin/system.py:~88`, `admin/users.py:~1029`, `tasks/delivery_tasks.py:~583` | Yes | Yes | Fit | No | Maintain |
| S2 | `system_announcement` | `routers/admin/system.py:~164` | Yes | Yes | Fit | No | Maintain |
| S3 | `user_role_changed` | `routers/admin/users.py:~985` | Yes | Yes | Fit | No | Maintain |
| S4 | `user_deactivated` | `routers/admin/users.py:~1003` | Yes | Yes | Fit | No | Maintain |
| S5 | `pipeline_config_updated` | `routers/admin/pipeline.py` (8 dispatch points) | Yes | Yes | Fit | No | Maintain |
| S6 | `holiday_calendar_incomplete` | `tasks/cache_tasks.py:~529` Beat | Yes | Yes(beat) | Fit | No | Maintain |

**System summary:** 6/6 ACTIVE. Không có gap.

---

## 10. Cross-cutting: Security

| # | Event | Dispatch file:line | Defined | Emitted | Business-fit | Runtime | Action |
|---|---|---|---|---|---|---|---|
| SEC1 | `suspicious_login` | `routers/auth.py:~191` (post-commit callback) | Yes | Yes | Fit | No | Maintain |

---

## 11. Cross-cutting: Organization (broadcast-only)

Các event này dùng cho **Socket.IO real-time UI refresh**, KHÔNG có registry config → không gửi notification cho user.

| Event | Dispatch file | Status |
|---|---|---|
| `unit_created/updated/deleted` | `routers/admin/organization.py` | ACTIVE (broadcast only) |
| `program_created/updated/deleted` | `routers/admin/organization.py` | ACTIVE (broadcast only) |
| `offering_created/updated/deleted` | `routers/admin/organization.py` | ACTIVE (broadcast only) |

9 events, tất cả ACTIVE. Không có gap — đây là design intent (broadcast only, no user notification).

---

## 12. Dead / Future modules

Events có đầy đủ registry config (resolver, template, channels) nhưng **module chưa build**:

| Event | Registry | Module status | Action |
|---|---|---|---|
| `dorm_room_assigned` | Yes — `SpecificUsers`, browser+email | Dorm module chưa build | Giữ, implement khi build module |
| `dorm_maintenance_request` | Yes — `DormStaff`, browser+email | Dorm module chưa build | Giữ, implement khi build module |
| `asset_maintenance_alert` | Yes — `ActorExcluded(UnitStaff)`, browser+email | Asset module chưa build | Giữ, implement khi build module |
| `asset_checked_out` | Yes — `AllAdmins`, browser | Asset module chưa build | Giữ, implement khi build module |

---

## 13. Architectural Findings

### Finding 1: `finance_events.py` DomainEvent system là dead code

| Component | Defined | Runtime | Evidence |
|---|---|---|---|
| 18 DomainEvent classes | Yes | **Dead** | 0 `emit_event()` calls trong service layer |
| `emit_event()` function | Yes | **Never called** | `fee_calculation_service.py:193` có `# TODO: Emit FeeCalculated domain event` |
| Handler registry | Yes | **Always empty** | 0 `register_handler()` hoặc `@event_handler` trong production code |
| `ProcessedEvent` table | Defined | **Never populated** | Idempotency tracking, chỉ dùng trong test |

**Impact:** 3 inline sync calls (`sync_lead_tuition_calculated`, `sync_lead_tuition_paid`, `sync_lead_tuition_refunded`) làm việc mà DomainEvent system lẽ ra phải làm. Nếu miss inline call ở flow nào → lead pipeline lệch, không có safety net.

**Decision needed:** Wire up DomainEvent properly, hoặc chấp nhận inline calls và remove dead code.

### Finding 2: `safe_dispatch()` trong service layer (architecture violation)

`payment_service.py` dùng `safe_dispatch()` trong `post_commit()` callback:
```python
# payment_service.py:207-213
async def post_commit():
    from app.services.notification_dispatcher import safe_dispatch  # ← Service import router-level function
    await safe_dispatch(db=_db, event=SystemEvents.PAYMENT_RECEIVED, ...)
```

**Đúng pattern V3:** Service dùng `dispatch()` + trả callback cho router.
**Ảnh hưởng:** `PAYMENT_RECEIVED` (F1) và `PAYMENT_VERIFIED` (F2). Hoạt động đúng vì nằm trong post_commit, nhưng vi phạm separation of concerns.

### Finding 3: Admission cặp đôi dispatch không atomic

Mỗi admission state change trong router gọi **2 `safe_dispatch()` tuần tự**:
```python
await db.commit()                              # 1 business commit
await safe_dispatch(APP_STATUS_CHANGED, ...)    # 2 notification commit
await safe_dispatch(LEAD_STATUS_CHANGED, ...)   # 3 notification commit
```

Nếu dispatch thứ 2 fail sau khi thứ 1 commit → `APP_STATUS_CHANGED` gửi rồi nhưng `LEAD_STATUS_CHANGED` mất.

**So sánh:** `lead_service.py` dùng `dispatch()` + `begin_nested()` — cả hai notification nằm chung savepoint.

### Finding 4: `LEAD_STATUS_CHANGED` mang 2 ngữ nghĩa

| Source | Payload `old_status` / `new_status` | Context |
|---|---|---|
| `routers/leads.py` | `consultation_status_id` (sts00, sts02, ...) | Officer đổi status trực tiếp trên lead |
| `routers/admissions.py` | Admission-mapped status codes (sts09, sts16, ...) | Admission approve/reject tự sync lead |

Cùng event, cùng registry config, **khác ngữ cảnh và payload format**. Resolver `LeadOwnerResolver()` hoạt động đúng cho cả hai, nhưng nếu thêm condition-based routing (Phase 2 rules) cần lưu ý.

### ~~Finding 5: `APPLICATION_CREATED` có 2 emit points~~ (RESOLVED)

> **Update 2026-04-03:** `application_service.py` đã bị xóa trong cleanup PR #93. `APPLICATION_CREATED` giờ chỉ có **1 emit point** duy nhất tại `routers/admissions.py:~284`. Duplicate risk đã loại bỏ hoàn toàn.

---

## 14. Gap Summary & Priority

### P0 — Blocking business logic

| ID | Gap | Impact | Effort |
|---|---|---|---|
| — | (Không có P0 hiện tại) | — | — |

### P1 — Quan trọng, ảnh hưởng trực tiếp đến user experience

| ID | Gap | Impact | Effort |
|---|---|---|---|
| F3 | `payment_overdue` registry-only, không có Celery Beat task | Không ai biết khi quá hạn thanh toán | Medium — cần beat task + overdue detection logic |
| F8 | Fee fully paid không có SystemEvent | Gate cuối trước enrollment không notify — milestone quan trọng nhất | Low — thêm `safe_dispatch()` sau `sync_lead_tuition_paid()` |
| A15 | `profile_withdrawn` không dispatch | Officer không biết hồ sơ đã rút | Low — thêm 2 `safe_dispatch()` trong router |
| A16 | `profile_overridden` không dispatch | Officer/lead không biết admin override | Low — thêm 2 `safe_dispatch()` trong router |
| GAP-C1/C2/C3 | Consultation CRUD đổi lead state nhưng không emit `lead_status_changed` | Event graph lệch, CTV commission triggers có thể miss | Medium — cần thêm conditional dispatch khi `status_updated=True` |

### P2 — Cải thiện coverage, không blocking

| ID | Gap | Impact | Effort |
|---|---|---|---|
| F5 | Fee calculated không notify | Lead/officer không biết học phí | Low |
| F6 | Invoice issued không notify | Lead không biết invoice mới | Low |
| F7 | Payment rejected có TODO stub trống | Officer không biết payment reject | Low — fill TODO |
| F9 | Refund processed không notify | Lead không biết tiền hoàn | Low |
| F10 | Application fee paid không notify | Officer không biết lead nộp lệ phí | Low |
| CTV10 | `ctv_lead_converted` dead config | CTV không biết lead tiến triển | Low |
| E5 | Drop student thiếu `APP_STATUS_CHANGED` | Inconsistent với pattern | Low |
| ~~A2~~ | ~~`APPLICATION_CREATED` duplicate risk~~ | **RESOLVED** — legacy service xóa (PR #93) | — |
| A12 | Enrollment 2 paths dedupe conflict | Có thể nhận 2 "enrolled" notifications | Low — chuẩn hóa dedupe_key |

### P3 — Kiến trúc / tech debt

| ID | Gap | Impact | Effort |
|---|---|---|---|
| Arch-1 | `finance_events.py` DomainEvent dead code | Kiến trúc mơ hồ, inline calls fragile | Decision: wire up hoặc remove |
| Arch-2 | `payment_service` dùng `safe_dispatch()` | Vi phạm V3 separation, hoạt động nhưng không clean | Low — refactor về `dispatch()` |
| Arch-3 | Admission cặp đôi dispatch không atomic | Rare failure case: partial notification | Medium — bundle vào savepoint |
| ~~A13~~ | ~~`application_documents_updated` legacy~~ | **RESOLVED** — event retired, file xóa (PR #93) | — |
| F4 | `dorm_fee_created` ownership sai domain | Finance registry chứa Dorm event | Low — move khi build Dorm module |

---

## 15. Recommended Actions

### Thứ tự thực hiện đề xuất

**Sprint 1: P1 — Hoàn thiện notification coverage cho business-critical flows**

1. **F3** — Thêm Celery Beat task `check_overdue_invoices_task`:
   - Quét `invoice` table: `status IN ('issued', 'partial') AND due_date < now()`
   - Dispatch `SystemEvents.PAYMENT_OVERDUE` cho mỗi invoice overdue
   - Dedupe: `payment_overdue:{invoice_id}:{days_overdue_bucket}`

2. **F8** — Thêm `safe_dispatch(PAYMENT_VERIFIED)` hoặc tạo event mới `FEE_FULLY_PAID` sau `sync_lead_tuition_paid()` trong `payment_service.py:~325`

3. **A15 + A16** — Thêm cặp dispatch trong router cho `withdrawn` và `overridden`:
   ```python
   await safe_dispatch(db, SystemEvents.APPLICATION_STATUS_CHANGED, payload={...})
   await safe_dispatch(db, SystemEvents.LEAD_STATUS_CHANGED, payload={...})
   ```

4. **GAP-C1/C2/C3** — Trong `routers/leads.py`, sau mỗi consultation CRUD, nếu service trả `status_updated=True`:
   ```python
   if status_updated:
       await safe_dispatch(db, SystemEvents.LEAD_STATUS_CHANGED, payload={...})
   ```

**Sprint 2: P2 — Mở rộng coverage**

5. **F5/F6/F7/F9/F10** — Thêm SystemEvent cho các finance milestones
6. **CTV10** — Thêm dispatch `CTV_LEAD_CONVERTED` trong `_check_commission_on_status_change()` khi lead có `referrer_id`
7. **E5** — Thêm `APP_STATUS_CHANGED` cho drop student
8. **A2/A12** — Verify và fix duplicate risks

**Sprint 3: P3 — Kiến trúc cleanup**

9. **Arch-1** — Quyết định số phận `finance_events.py`: wire up hoặc remove
10. **Arch-2** — Refactor `payment_service` về `dispatch()` pattern
11. **Arch-3** — Bundle admission cặp đôi dispatch vào savepoint

---

## Appendix: Thống kê tổng hợp

| Metric | Count | Note (updated 2026-04-03) |
|---|---|---|
| Tổng SystemEvents enum | 51 | +3 vs audit gốc (PAYMENT_VERIFIED, HOLIDAY_CALENDAR_INCOMPLETE, SUSPICIOUS_LOGIN added; APPLICATION_DOCUMENTS_UPDATED removed) |
| Events có registry config (user-facing) | 42 | +3 vs audit gốc |
| Events broadcast-only (Socket.IO, no registry) | 9 | Unchanged |
| Events ACTIVE (có dispatch trong code) | 44 | +12 vs audit gốc (org events gained dispatch, new events, CTV Celery tasks) |
| Events REGISTRY-ONLY (config đủ, không dispatch) | 7 | Unchanged |
| DomainEvent classes (finance_events.py) | 18 | Unchanged — still dead code |
| DomainEvents actually emitted | 0 | Unchanged |
| AdmissionEventProjections | 20 | -1 vs audit gốc |
| AdmissionEventProjections có SystemEvent tương ứng | 14 | Unchanged |
| AdmissionEventProjections KHÔNG CÓ SystemEvent | 6 | -1 vs audit gốc |
| Business transitions thiếu cả 2 (SystemEvent + projection) | 3 | invoice, payment_reject, app_fee |
| Tổng identified gaps | 19 | -3 vs audit gốc (A2, A13, Finding 5 resolved by cleanup PR #93) |
| P1 gaps | 5 | Unchanged |
| P2 gaps | 7 | -2 vs audit gốc (A2 resolved, A13 retired) |
| P3 gaps | 4 | -1 vs audit gốc (A13 P3 line resolved) |
| Future/acceptable gaps | 4 | Unchanged |
