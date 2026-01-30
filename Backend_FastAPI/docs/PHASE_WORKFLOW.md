# Phase Workflow - Luồng Xử Lý Trạng Thái Lead

## Tổng Quan

Hệ thống QLTS sử dụng **Phase-Based FSM Engine** để quản lý trạng thái Lead qua các giai đoạn tuyển sinh. Mỗi Lead đi qua 4 phase chính theo thứ tự:

```
CONSULTATION → ADMISSION → FEE → ENROLLED
```

---

## 1. CONSULTATION PHASE (Tư vấn)

### Mục đích
Giai đoạn tư vấn ban đầu, từ khi Lead được tạo đến khi đồng ý nộp hồ sơ.

### Stages
| Stage ID | Tên | Mô tả |
|----------|-----|-------|
| stg01 | Tiếp cận | Lead mới, chưa liên hệ được |
| stg02 | Tư vấn | Đã liên hệ, đang tư vấn |

### Statuses

```
┌─────────────────────────────────────────────────────────────────┐
│                      CONSULTATION PHASE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│   sts00 (Chưa tiếp cận)                                          │
│      │                                                            │
│      ├──→ sts02 (Đã kết nối) ──→ sts03 (Có nhu cầu)             │
│      │         │                      │                          │
│      │         ├──→ sts05 (Hẹn lại) ←─┤                          │
│      │         │         │            │                          │
│      │         ↓         ↓            ↓                          │
│      │      sts04 ←── sts04 ←──── sts04 (Từ chối)               │
│      │         │                                                  │
│      │         └──→ sts03/sts05/sts06 (Đổi ý - tư vấn lại)      │
│      │                                                            │
│      └──→ sts03 ──→ sts06 (Đồng ý tư vấn)                       │
│      └──→ sts05                  │                               │
│      └──→ sts06 ─────────────────┘                               │
│                                  │                               │
│                                  ↓ [SYSTEM - Tạo AdmissionProfile]│
│                            ═══════════                            │
│                            ADMISSION PHASE                        │
└─────────────────────────────────────────────────────────────────┘
```

### Status Details

| ID | Code | Tên | Trigger | is_final | Ghi chú |
|----|------|-----|---------|----------|---------|
| sts00 | NOT_CONTACTED | Chưa tiếp cận | user | No | Default khi tạo Lead |
| sts01 | NO_ANSWER | Không nghe máy | user | No | Universal - không update pipeline |
| sts02 | CONTACTED | Đã kết nối | user | No | |
| sts03 | INTERESTED | Có nhu cầu | user | No | |
| sts04 | CONSULT_REJECTED | Từ chối tư vấn | user | **No*** | Có thể đổi ý sau tư vấn lại |
| sts05 | CALLBACK_LATER | Hẹn liên hệ lại | user | No | |
| sts06 | CONSULT_ACCEPTED | Đồng ý tư vấn | user | No | Cửa ngõ sang Admission |

> **Lưu ý:** sts04 có `is_final=false` vì Lead từ chối vẫn có thể được tư vấn lại và đổi ý.

### Universal Statuses (Áp dụng mọi phase)

| ID | Code | Tên | Mô tả |
|----|------|-----|-------|
| sts01 | NO_ANSWER | Không nghe máy | Gọi điện không bắt máy |
| sts15 | NO_REPLY_MESSAGE | Nhắn tin không phản hồi | Gửi tin không reply |
| sts19 | CANCELLED | Đã hủy lịch hẹn | Hủy appointment |

---

## 2. ADMISSION PHASE (Xét tuyển)

### Mục đích
Giai đoạn nộp và xét duyệt hồ sơ tuyển sinh.

### Stages
| Stage ID | Tên | Mô tả |
|----------|-----|-------|
| stg03 | Tiếp nhận hồ sơ | Hồ sơ đang được xử lý |
| stg04 | Kết quả xét tuyển | Hồ sơ đã có kết quả |

### Luồng xử lý

```
┌─────────────────────────────────────────────────────────────────┐
│                      ADMISSION PHASE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│   sts07 (Tiếp nhận hồ sơ)                                        │
│      │                                                            │
│      ├──→ sts17 (Yêu cầu bổ sung) ──→ sts07 (Bổ sung xong)      │
│      │                                                            │
│      ├──→ sts08 (Rút hồ sơ) ✗ FINAL                              │
│      │                                                            │
│      ├──→ sts16 (Không đạt) ✗ FINAL [role only]                  │
│      │                                                            │
│      │    ┌─────────────────────────────────────────┐            │
│      │    │     APPLICATION FEE CHECK               │            │
│      │    ├─────────────────────────────────────────┤            │
│      │    │                                         │            │
│      ├────┤  admission_path.requires_application_fee?│            │
│      │    │                                         │            │
│      │    │   YES ──→ sts13 (Đã hoàn lệ phí)       │            │
│      │    │              │                          │            │
│      │    │              ↓                          │            │
│      │    │           sts09 (Đủ điều kiện)         │            │
│      │    │                                         │            │
│      │    │   NO  ──→ sts09 (Đủ điều kiện)         │            │
│      │    │              │                          │            │
│      │    └──────────────┼──────────────────────────┘            │
│                          │                                        │
│                          ↓ [SYSTEM]                              │
│                    ═══════════                                    │
│                    FEE PHASE                                      │
└─────────────────────────────────────────────────────────────────┘
```

### Status Details

| ID | Code | Tên | Trigger | is_final | Ghi chú |
|----|------|-----|---------|----------|---------|
| sts07 | APPLICATION_RECEIVED | Tiếp nhận hồ sơ | user | No | Tạo khi có AdmissionProfile |
| sts08 | APPLICATION_WITHDRAWN | Rút hồ sơ | user | Yes | Lead tự dừng |
| sts09 | ELIGIBLE_FOR_ENROLLMENT | Đủ điều kiện | system | No | Hồ sơ được duyệt |
| sts13 | APPLICATION_FEE_PAID | Đã hoàn lệ phí | system | No | Payment callback |
| sts16 | APPLICATION_REJECTED | Không đạt | role | Yes | Manager/Admin từ chối |
| sts17 | APPLICATION_REVISION | Yêu cầu bổ sung | user | No | Thiếu giấy tờ |

### Application Fee Logic

```python
# Khi AdmissionProfile được submit:
if admission_path.requires_application_fee:
    # Chờ thanh toán lệ phí
    # Payment Gateway callback → sts13 → sts09
else:
    # Bypass lệ phí
    # System → sts09 trực tiếp
```

---

## 3. FEE PHASE (Học phí)

### Mục đích
Giai đoạn thu học phí sau khi hồ sơ được duyệt.

### Stage
| Stage ID | Tên | Mô tả |
|----------|-----|-------|
| stg05 | Thu học phí | Đang chờ thanh toán học phí |

### Luồng xử lý

```
┌─────────────────────────────────────────────────────────────────┐
│                         FEE PHASE                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│   sts14 (Chưa hoàn tất học phí)                                  │
│      │                                                            │
│      ├──→ sts10 (Đã hoàn tất học phí) [SYSTEM - Payment]        │
│      │         │                                                  │
│      │         ↓ [SYSTEM]                                        │
│      │   ═══════════                                              │
│      │   ENROLLED PHASE                                           │
│      │                                                            │
│      └──→ sts18 (Hoàn học phí) ✗ FINAL [SYSTEM - Refund]        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Status Details

| ID | Code | Tên | Trigger | is_final | Ghi chú |
|----|------|-----|---------|----------|---------|
| sts14 | TUITION_PENDING | Chưa hoàn học phí | user | No | Chờ thanh toán |
| sts10 | TUITION_PAID | Đã hoàn học phí | system | No | Payment success |
| sts18 | TUITION_REFUNDED | Hoàn học phí | system | Yes | Refund processed |

---

## 4. ENROLLED PHASE (Nhập học)

### Mục đích
Giai đoạn sau khi sinh viên chính thức nhập học.

### Stages
| Stage ID | Tên | Mô tả |
|----------|-----|-------|
| stg06 | Đã nhập học | Chính thức là sinh viên |
| stg07 | Ngừng học | Đã thôi học |

### Luồng xử lý

```
┌─────────────────────────────────────────────────────────────────┐
│                       ENROLLED PHASE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│   sts11 (Đã xác nhận nhập học) ✓ FINAL                           │
│      │                                                            │
│      └──→ sts12 (Ngừng theo học) ✗ FINAL [role only]            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Status Details

| ID | Code | Tên | Trigger | is_final | Ghi chú |
|----|------|-----|---------|----------|---------|
| sts11 | ENROLLED | Đã nhập học | system | Yes | Mục tiêu cuối cùng |
| sts12 | DROPPED_OUT | Ngừng học | role | Yes | Chỉ Manager/Admin |

---

## FSM Engine Rules

### Rule Summary

| # | Rule | Mô tả |
|---|------|-------|
| 1 | Transition-based | Status tiếp theo từ `allowed_transitions` table |
| 2 | Phase as Guard | Phase chỉ lọc, không sinh danh sách |
| 3 | required_phase | Là phase của TO_STATUS |
| 4 | Cross-phase forbidden | User/Role không được cross-phase |
| 5 | User/Role phase guard | `to_status.phase == lead.phase` |
| 6 | System cross-phase | System được phép cross-phase |
| 7 | Stage guard | Kiểm tra stage consistency |
| 8 | System status hidden | User không thấy system statuses |
| 9 | Universal = Activity | Universal status là activity |
| 10 | Activity independent | Activity không phụ thuộc transition |
| 11 | NULL → sts00 only | Lead mới chỉ có NOT_CONTACTED |

### Trigger Types

| Type | Ai thực hiện | Cross-phase | Ví dụ |
|------|--------------|-------------|-------|
| `user` | Officer | Không | Tư vấn, cập nhật trạng thái |
| `role` | Manager/Admin | Không | Từ chối hồ sơ, ngừng học |
| `system` | Hệ thống | Có | Payment callback, auto-approval |

---

## Allowed Transitions Table

### Consultation Phase Transitions

| From | To | Trigger | Description |
|------|----|---------|-------------|
| sts00 | sts02 | user | Kết nối được |
| sts00 | sts03 | user | Quan tâm ngay |
| sts00 | sts04 | user | Từ chối ngay |
| sts00 | sts05 | user | Hẹn gọi lại |
| sts00 | sts06 | user | Đồng ý tư vấn ngay |
| sts02 | sts03 | user | Quan tâm |
| sts02 | sts04 | user | Không quan tâm |
| sts02 | sts05 | user | Hẹn lại |
| sts02 | sts06 | user | Đồng ý tư vấn |
| sts03 | sts04 | user | Không tiếp tục |
| sts03 | sts05 | user | Hẹn gọi lại |
| sts03 | sts06 | user | Đồng ý tư vấn |
| sts04 | sts03 | user | Đổi ý - có nhu cầu |
| sts04 | sts05 | user | Đổi ý - hẹn lại |
| sts04 | sts06 | user | Đổi ý - đồng ý |
| sts05 | sts03 | user | Gọi lại có nhu cầu |
| sts05 | sts04 | user | Gọi lại từ chối |
| sts05 | sts06 | user | Đồng ý sau gọi lại |
| sts06 | sts03 | user | Quay lại quan tâm |
| sts06 | sts04 | user | Từ chối sau tư vấn |
| sts06 | sts05 | user | Hẹn lại |

### Cross-Phase Transitions (System Only)

| From | To | Trigger | Description |
|------|----|---------|-------------|
| sts06 | sts07 | system | Tạo AdmissionProfile |
| sts07 | sts13 | system | Thanh toán lệ phí |
| sts07 | sts09 | system | Miễn lệ phí |
| sts13 | sts09 | system | Lệ phí hợp lệ |
| sts09 | sts14 | system | Chuyển thu học phí |
| sts14 | sts10 | system | Thanh toán học phí |
| sts14 | sts18 | system | Hoàn tiền |
| sts10 | sts11 | system | Nhập học |

### Admission Phase Transitions

| From | To | Trigger | Description |
|------|----|---------|-------------|
| sts07 | sts17 | user | Yêu cầu bổ sung |
| sts17 | sts07 | user | Bổ sung xong |
| sts07 | sts08 | user | Rút hồ sơ |
| sts07 | sts16 | role | Không đạt |

### Enrolled Phase Transitions

| From | To | Trigger | Description |
|------|----|---------|-------------|
| sts11 | sts12 | role | Ngừng học |

---

## Database Configuration

### consultation_status Table

```sql
-- Các trường quan trọng
id              -- Primary key (sts00, sts01, ...)
code            -- Unique code (NOT_CONTACTED, CONTACTED, ...)
name            -- Tên hiển thị
phase           -- consultation/admission/fee/enrolled/universal
stage_id        -- Link to pipeline_stage
trigger_type    -- user/role/system
is_final        -- True = trạng thái kết thúc
is_universal    -- True = áp dụng mọi phase
updates_pipeline -- True = cập nhật lead.consultation_status_id
selectable_mode -- user/role/system (ai được chọn)
```

### allowed_transitions Table

```sql
-- Các trường quan trọng
from_status_id  -- Status nguồn
to_status_id    -- Status đích
trigger_type    -- user/role/system
required_phase  -- Phase của to_status
is_active       -- True = transition đang hoạt động
```

---

## Application Fee Configuration

### Model: AdmissionPath

```python
class AdmissionPath(Base):
    # ... other fields ...

    application_fee = Column(
        Numeric(precision=12, scale=2),
        nullable=True,
        default=0,
        comment="Lệ phí xét tuyển (VND). 0 hoặc NULL = miễn phí"
    )

    @property
    def requires_application_fee(self) -> bool:
        return self.application_fee is not None and float(self.application_fee) > 0
```

### Usage in Service

```python
async def process_admission_profile(profile: AdmissionProfile):
    admission_path = profile.admission_path

    if admission_path.requires_application_fee:
        # Lead stays at sts07, waiting for payment
        # Payment Gateway will callback and move to sts13 → sts09
        return "pending_fee"
    else:
        # Bypass fee, move directly to sts09
        await transition_lead(profile.lead_id, "sts09")
        return "fee_exempt"
```

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-30 | 1.0 | Initial document |
| 2026-01-30 | 1.1 | Add application_fee to AdmissionPath |
