# BÁO CÁO RÀ SOÁT TOÀN DIỆN: HỆ THỐNG LEAD & ADMISSION

> **Author**: Senior System Architect + Business Analyst
> **Date**: 2026-01-26
> **Version**: 1.0
> **Scope**: Lead → Consultation → Admission workflow
> **Focus**: Production Readiness Assessment

---

## MỤC LỤC

1. [Business Flow Validation](#1-business-flow-validation)
2. [Edge Case Analysis](#2-edge-case-analysis)
3. [Data Consistency & Source of Truth](#3-data-consistency--source-of-truth)
4. [State Machine & Transition Logic](#4-state-machine--transition-logic)
5. [Performance & Scalability Review](#5-performance--scalability-review)
6. [Security & Data Safety](#6-security--data-safety)
7. [UX Flow & User Behavior](#7-ux-flow--user-behavior)
8. [Kết Luận Kiến Trúc](#8-kết-luận-kiến-trúc)

---

## 1. BUSINESS FLOW VALIDATION

### 1.1 Luồng Nghiệp Vụ Hiện Tại

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        LEAD LIFECYCLE (QLTS v3.0)                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────────┐    ┌──────────────────────────────┐ │
│  │  LEAD       │    │  CONSULTATION   │    │     ADMISSION PROFILE        │ │
│  │  CREATION   │───▶│  ACTIVITIES     │───▶│     PROCESSING               │ │
│  └─────────────┘    └─────────────────┘    └──────────────────────────────┘ │
│        │                    │                          │                     │
│        ▼                    ▼                          ▼                     │
│  ┌─────────────┐    ┌─────────────────┐    ┌──────────────────────────────┐ │
│  │ Phase:      │    │ Multiple        │    │ Status Machine:              │ │
│  │ CONSULTATION│    │ Consultation    │    │ draft → submitted →          │ │
│  │             │    │ Records         │    │ approved/rejected → enrolled │ │
│  │ Statuses:   │    │                 │    │                              │ │
│  │ sts00-sts06 │    │ FSM-validated   │    │ + Validation + Documents     │ │
│  └─────────────┘    └─────────────────┘    └──────────────────────────────┘ │
│                                                         │                    │
│                                                         ▼                    │
│                                            ┌──────────────────────────────┐ │
│                                            │     STUDENT RECORD           │ │
│                                            │     (Terminal State)         │ │
│                                            └──────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Đánh Giá Theo Logic Nghiệp Vụ Thực Tế

| Bước | Hiện Trạng | Phản Ánh Thực Tế? | Đánh Giá |
|------|------------|-------------------|----------|
| Lead Creation | ✅ Có validation phone, email, source | ✅ Đúng | OK |
| Auto-Assignment | ✅ Distribution config với rotation | ✅ Đúng | OK |
| Consultation Tracking | ✅ Nhiều consultation per lead | ✅ Đúng | OK |
| FSM Status Control | ✅ Phase-based transitions | ✅ Đúng | OK |
| Admission Profile Creation | ⚠️ **Không yêu cầu consultation** | ❌ **Thiếu checkpoint** | **WARNING** |
| Document Upload | ✅ Mandatory docs validation | ✅ Đúng | OK |
| Submit & Evaluate | ✅ Snapshot rules, auto-approve/reject | ✅ Đúng | OK |
| Magic Link Confirm | ✅ CCCD verification | ✅ Đúng | OK |
| Enrollment | ✅ ACID transaction, Student creation | ✅ Đúng | OK |

### 1.3 Điểm Đang Đi Tắt (CRITICAL)

#### **GAP #1: Admission Profile có thể được tạo khi Lead chưa có Consultation nào**

**Hiện trạng code** (`admission_service.create_profile`):
```python
# Chỉ check:
# 1. Lead exists
# 2. Lead không có profile sẵn
# 3. Offering + AdmissionPath valid
# KHÔNG check: Lead đã có ít nhất 1 consultation completed
```

**Hậu quả nghiệp vụ**:
- Officer có thể tạo hồ sơ cho lead chưa tư vấn
- Bỏ qua bước qualification (đánh giá lead phù hợp không)
- Workflow "Lead → Consultation → Admission" bị phá vỡ

**Khuyến nghị**: Thêm guard `lead.consultation_count >= 1` hoặc `lead.consultation_status_id NOT NULL`

#### **GAP #2: Lead status không sync với Admission status**

**Hiện trạng**:
- `lead.status` = "qualified" có thể tồn tại khi `admission_profile.status` = "rejected"
- Không có event listener khi admission status thay đổi
- Lead phase phụ thuộc admission status nhưng lead.status không auto-update

**Khuyến nghị**:
- Emit domain event `ADMISSION_STATUS_CHANGED`
- Update `lead.consultation_status_id` theo admission status

### 1.4 Thiếu Checkpoint

| Checkpoint | Có trong System? | Priority |
|------------|------------------|----------|
| Lead phải có ≥1 consultation trước khi tạo admission | ❌ THIẾU | **HIGH** |
| Consultation cuối phải là "completed" hoặc "qualified" | ❌ THIẾU | MEDIUM |
| Lead score phải đạt ngưỡng trước khi qualified | ❌ THIẾU | LOW |
| Manager phải review trước khi enrolled (2-eye principle) | ✅ Có (approve step) | OK |
| CCCD verification trước enrolled | ✅ Có (magic link) | OK |

---

## 2. EDGE CASE ANALYSIS

### 2.1 Danh Sách Edge Case Đầy Đủ

| # | Edge Case | Hiện Trạng | Hậu Quả | Rủi Ro |
|---|-----------|------------|---------|--------|
| 1 | **Một lead có nhiều consultation song song** | ✅ Allowed (design) | Không vấn đề | LOW |
| 2 | **Consultation bị hủy giữa chừng** | ⚠️ Soft delete chưa hoàn thiện | Lead status có thể stale | **MEDIUM** |
| 3 | **Lead bị trùng phone/email** | ✅ Duplicate check global | Blocked | OK |
| 4 | **Admission tạo rồi nhưng lead chỉnh info** | ⚠️ **Admission không copy data từ lead** | Data drift | **MEDIUM** |
| 5 | **Admission tạo khi consultation chưa completed** | ❌ **Không có guard** | Bypass workflow | **HIGH** |
| 6 | **Re-open hồ sơ sau reject** | ✅ resubmit endpoint | Officer fix & resubmit | OK |
| 7 | **Thay đổi ngành/nguyện vọng giữa chừng** | ⚠️ Admission snapshot `applied_rules` | Phải tạo profile mới | MEDIUM |
| 8 | **Data lệch giữa lead và admission profile** | ⚠️ **2 nguồn personal info** | Inconsistency | **HIGH** |
| 9 | **Concurrent update trên cùng profile** | ✅ Optimistic locking (version) | 409 Conflict | OK |
| 10 | **Lead deleted khi đang có admission** | ✅ Business rule guard | Blocked (400) | OK |
| 11 | **Officer reassign quá quota** | ✅ 5/week limit check | Blocked | OK |
| 12 | **Magic link expired** | ✅ expires_at check | Error message | OK |
| 13 | **CCCD nhập sai ≥5 lần** | ✅ Lock token | Account locked | OK |
| 14 | **Cùng CCCD đăng ký 2 năm khác nhau** | ✅ Composite unique (citizen_id, academic_year) | Allowed | OK |
| 15 | **Cùng CCCD đăng ký 2 lần trong 1 năm** | ✅ Unique constraint violation | Blocked (409) | OK |

### 2.2 Chi Tiết Edge Case Nghiêm Trọng

#### **EDGE CASE #2: Consultation Soft Delete Chưa Hoàn Thiện**

**File**: `app/services/lead_service.py` - `delete_consultation()`

**Hiện trạng**:
```python
# Hiện tại dùng HARD DELETE:
await db.delete(consultation)

# Mặc dù đã có cột deleted_at và migration:
# - Model có: deleted_at = Column(DateTime(timezone=True), nullable=True)
# - Migration: fix20260125001_add_deleted_at_to_consultation.py
```

**Vấn đề**:
- Audit trail bị mất khi delete consultation
- Không thể restore nếu xóa nhầm
- Inconsistent với lead soft delete

**Khuyến nghị**:
```python
# Sửa thành soft delete:
consultation.deleted_at = datetime.now(timezone.utc)
await db.flush()
```

#### **EDGE CASE #8: Data Drift Giữa Lead và Admission Profile**

**Vấn đề kiến trúc**:

```
┌─────────────────────┐          ┌─────────────────────────┐
│       LEAD          │          │   ADMISSION PROFILE     │
├─────────────────────┤          ├─────────────────────────┤
│ full_name           │    ≠     │ full_name               │
│ email               │    ≠     │ email                   │
│ phone               │    ≠     │ phone                   │
│ (Có thể sửa sau)    │          │ (Tách biệt, snapshot?)  │
└─────────────────────┘          └─────────────────────────┘
```

**Scenario lỗi**:
1. Officer tạo lead với `phone = "0901234567"`
2. Officer tạo admission profile (nhập lại phone trong form)
3. Lead sau đó được update `phone = "0907654321"` (typo fix)
4. Admission profile vẫn giữ phone cũ → Data không nhất quán

**Hậu quả**:
- Liên hệ với học sinh dùng thông tin sai
- Report bị sai
- Magic link gửi đến email cũ

**Khuyến nghị kiến trúc**: Xem mục 3.4 về Source of Truth

---

## 3. DATA CONSISTENCY & SOURCE OF TRUTH

### 3.1 Phân Tích Nguồn Dữ Liệu

| Nhóm Dữ Liệu | Lead | Consultation | Admission Profile | Source of Truth Đề Xuất |
|--------------|------|--------------|-------------------|-------------------------|
| **Thông tin cá nhân** | `full_name`, `email`, `phone` | ❌ | `full_name`, `email`, `phone`, `dob`, `gender`, ... | **Admission Profile** (đầy đủ hơn) |
| **Thông tin liên hệ** | `phone`, `phone2`, `email` | ❌ | `phone`, `email`, `permanent_*` | **Admission Profile** |
| **Nguyện vọng** | `offering_id` | ❌ | `offering_admission_config_id` → `applied_rules.admission_method` | **Admission Profile** (immutable snapshot) |
| **Điểm số** | ❌ | ❌ | `ProfileSubjectScore` (relational) | **Admission Profile** |
| **Hồ sơ giấy tờ** | ❌ | ❌ | `ProfileDocument` (relational) | **Admission Profile** |
| **Lịch sử tư vấn** | `consultation_count`, `last_consultation_at` (cached) | ✅ Full records | ❌ | **Consultation** |
| **Trạng thái workflow** | `consultation_status_id`, `pipeline_stage_id` | ❌ | `status` | **Phụ thuộc phase** |
| **Đánh giá lead** | `lead_score`, `fit_score`, `officer_rating` | ❌ | ❌ | **Lead** |

### 3.2 Nguy Cơ Data Consistency

#### **Risk #1: Ghi Đè Dữ Liệu**

| Scenario | Có Xảy Ra? | Mitigation |
|----------|------------|------------|
| Lead update → Admission profile auto-update | ❌ Không (tách biệt) | N/A |
| Admission profile update → Lead auto-update | ❌ Không | N/A |
| Concurrent lead updates | ✅ Có (optimistic lock) | 409 Conflict |
| Concurrent admission updates | ✅ Có (optimistic lock) | 409 Conflict |

**Đánh giá**: Không có nguy cơ ghi đè vì 2 entity độc lập + optimistic locking

#### **Risk #2: Stale Data**

| Scenario | Có Xảy Ra? | Impact |
|----------|------------|--------|
| Lead `phone` thay đổi sau khi tạo admission | ✅ CÓ | **HIGH** - Admission profile giữ phone cũ |
| Lead `email` thay đổi sau khi tạo admission | ✅ CÓ | **HIGH** - Magic link gửi email sai |
| Lead `offering_id` thay đổi sau admission | ❌ Không thể | Admission bị khóa bởi `applied_rules` |

#### **Risk #3: Update Lệch Thời Điểm**

**Không có cơ chế sync real-time giữa Lead và Admission Profile**

```
Timeline:
T1: Lead created (phone=A)
T2: Admission created (phone=A)
T3: Lead updated (phone=B)
T4: Admission still has (phone=A) ← STALE
T5: Magic link sent to phone=A ← WRONG
```

#### **Risk #4: Conflict Khi Nhiều User Thao Tác**

| Scenario | Protection | Status |
|----------|------------|--------|
| 2 officers edit cùng lead | ✅ Optimistic lock + version | OK |
| 2 managers approve cùng profile | ✅ Optimistic lock + FOR UPDATE | OK |
| Officer edit lead + Manager approve profile | ⚠️ Không có cross-entity lock | **POTENTIAL ISSUE** |

### 3.3 Proposed Source of Truth Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PROPOSED DATA ARCHITECTURE                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐                  ┌──────────────────────────┐ │
│  │    LEAD      │                  │   ADMISSION PROFILE      │ │
│  │              │                  │                          │ │
│  │ • lead_score │                  │ • personal_info (MASTER) │ │
│  │ • fit_score  │     Reference    │ • contact_info (MASTER)  │ │
│  │ • source     │◄────────────────▶│ • documents              │ │
│  │ • workflow   │                  │ • scores                 │ │
│  │   status     │                  │ • applied_rules          │ │
│  │              │                  │                          │ │
│  └──────────────┘                  └──────────────────────────┘ │
│         │                                    │                   │
│         │                                    │                   │
│         ▼                                    ▼                   │
│  ┌──────────────┐                  ┌──────────────────────────┐ │
│  │ CONSULTATION │                  │       STUDENT            │ │
│  │              │                  │                          │ │
│  │ • activities │                  │ • personal_info (copied) │ │
│  │ • notes      │                  │ • student_code           │ │
│  │ • scheduled  │                  │ • enrollment_date        │ │
│  │              │                  │                          │ │
│  └──────────────┘                  └──────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

RULES:
1. Khi Lead chưa có Admission Profile → Lead là nguồn contact info
2. Khi Admission Profile tồn tại → Profile là nguồn contact info (authoritative)
3. Lead chỉ giữ thông tin cho lead scoring & workflow tracking
4. Student copy từ Admission Profile tại thời điểm enrollment (snapshot)
```

### 3.4 Khuyến Nghị Cải Tiến

**Option A: Sync-on-Update Pattern** (Recommended)
```python
# Khi update admission profile personal info:
async def update_profile(db, profile_id, data):
    profile = await get_profile(db, profile_id)

    # Update profile
    profile.full_name = data.full_name
    profile.phone = data.phone
    profile.email = data.email

    # Sync back to lead (nếu khác)
    lead = profile.lead
    if lead.full_name != data.full_name:
        lead.full_name = data.full_name
    if lead.phone != data.phone:
        lead.phone = data.phone
    if lead.email != data.email:
        lead.email = data.email

    await db.flush()
```

**Option B: Reference Pattern** (Cleaner, Breaking Change)
```python
# Admission Profile chỉ giữ citizen_id + extra fields
# Personal info query JOIN từ Lead

class AdmissionProfile:
    lead_id: FK  # Source of personal info
    citizen_id: str  # Not in Lead
    dob: date  # Not in Lead
    # Remove: full_name, phone, email (use lead.*)
```

---

## 4. STATE MACHINE & TRANSITION LOGIC

### 4.1 Tổng Quan State Machine Hiện Tại

#### **Lead Workflow (FSM v3.0)**

```
                              ┌─────────────────────────────────────────┐
                              │          LEAD STATUS MACHINE            │
                              └─────────────────────────────────────────┘
                                              │
        ┌───────────────────────────────────────────────────────────────────┐
        │                         PHASE: CONSULTATION                       │
        │                         Stages: stg01, stg02                      │
        │  ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐            │
        │  │ sts00  │───▶│ sts02  │───▶│ sts03  │───▶│ sts04  │            │
        │  │NOT_CON-│    │CONTACT-│    │NEED_   │    │INTER-  │            │
        │  │TACTED  │    │ED      │    │FOLLOWUP│    │ESTED   │            │
        │  └────────┘    └────────┘    └────────┘    └────────┘            │
        │                                    │             │                │
        │                                    │             │                │
        │                                    ▼             ▼                │
        │                              ┌────────┐    ┌────────┐            │
        │                              │ sts05  │    │ sts06  │            │
        │                              │NOT_    │    │QUALIFI-│────────────┼───▶
        │                              │INTER-  │    │ED      │            │
        │                              │ESTED   │    └────────┘            │
        │                              └────────┘                          │
        └───────────────────────────────────────────────────────────────────┘
                                              │
        ┌───────────────────────────────────────────────────────────────────┐
        │                         PHASE: ADMISSION                          │
        │                         Stages: stg03, stg04                      │
        │  ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐            │
        │  │ sts07  │───▶│ sts08  │───▶│ sts09  │───▶│ sts16  │            │
        │  │PROFILE_│    │DOCS_   │    │SUBMIT- │    │APPROV- │────────────┼───▶
        │  │CREATED │    │UPLOAD  │    │TED     │    │ED      │            │
        │  └────────┘    └────────┘    └────────┘    └────────┘            │
        │                                    │                              │
        │                                    ▼                              │
        │                              ┌────────┐                          │
        │                              │ sts17  │                          │
        │                              │REJECT- │◄──────── (resubmit) ─────│
        │                              │ED      │                          │
        │                              └────────┘                          │
        └───────────────────────────────────────────────────────────────────┘
                                              │
        ┌───────────────────────────────────────────────────────────────────┐
        │                         PHASE: FEE                                │
        │                         Stage: stg05                              │
        │  ┌────────┐    ┌────────┐    ┌────────┐                          │
        │  │ sts10  │───▶│ sts14  │───▶│ sts18  │──────────────────────────┼───▶
        │  │FEE_    │    │FEE_    │    │FEE_    │                          │
        │  │PENDING │    │PARTIAL │    │PAID    │                          │
        │  │(system)│    │(system)│    │(system)│                          │
        │  └────────┘    └────────┘    └────────┘                          │
        └───────────────────────────────────────────────────────────────────┘
                                              │
        ┌───────────────────────────────────────────────────────────────────┐
        │                         PHASE: ENROLLED (Terminal)                │
        │                         Stages: stg06, stg07                      │
        │  ┌────────┐                                    ┌────────┐        │
        │  │ sts11  │                                    │ sts12  │        │
        │  │CONFIRM-│                                    │ENROLLED│        │
        │  │ED      │───────────────────────────────────▶│(final) │        │
        │  └────────┘                                    └────────┘        │
        └───────────────────────────────────────────────────────────────────┘

UNIVERSAL ACTIVITIES (Always Available):
  ┌────────┐    ┌────────┐
  │ sts01  │    │ sts15  │
  │SCHEDUL-│    │NOTES   │
  │ED      │    │ADDED   │
  └────────┘    └────────┘
```

#### **Admission Profile State Machine**

```
┌─────────────────────────────────────────────────────────────────────┐
│                  ADMISSION PROFILE STATUS MACHINE                    │
└─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────┐
  │       DRAFT         │◄──────────────────────────────────────┐
  │                     │                                       │
  │  • Officer edits    │                                       │
  │  • Upload docs      │                                       │
  │  • Enter scores     │                                       │
  └──────────┬──────────┘                                       │
             │                                                  │
             │ submit_and_evaluate()                            │
             ▼                                                  │
  ┌─────────────────────┐         ┌─────────────────────┐       │
  │     SUBMITTED       │────────▶│      REJECTED       │───────┘
  │                     │ reject  │                     │ resubmit
  │  • Manager reviews  │         │  • Reason required  │
  │  • Validates rules  │         │  • Officer can fix  │
  └──────────┬──────────┘         └─────────────────────┘
             │
             │ approve (auto hoặc manual)
             ▼
  ┌─────────────────────┐
  │      APPROVED       │
  │                     │
  │  • Magic link sent  │
  │  • Awaiting confirm │
  └──────────┬──────────┘
             │
             │ verify_and_confirm (CCCD check)
             ▼
  ┌─────────────────────┐
  │     CONFIRMED       │
  │                     │
  │  • Lead confirms    │
  │  • Ready to enroll  │
  └──────────┬──────────┘
             │
             │ enroll_student (ACID transaction)
             ▼
  ┌─────────────────────┐
  │      ENROLLED       │  (Terminal - No further transitions)
  │                     │
  │  • Student created  │
  │  • Docs transferred │
  └─────────────────────┘
```

### 4.2 Đánh Giá Transition Logic

#### **Lead FSM Evaluation**

| Aspect | Status | Comments |
|--------|--------|----------|
| **Phase Guard** | ✅ GOOD | User/Role không thể cross-phase |
| **Transition Table** | ✅ GOOD | `AllowedTransition` model với `is_active` flag |
| **Universal Activities** | ✅ GOOD | sts01, sts15 bypass FSM |
| **System Transitions** | ✅ GOOD | Idempotent với history check |
| **NULL to Initial** | ✅ GOOD | NULL → sts00 only |
| **Terminal Guard** | ⚠️ SOFT | Log warning nhưng không block |

**Vấn đề**: Terminal status guard (sts11, sts12) hiện chỉ log warning, không hard block:
```python
# Current code:
if lead.status == "converted":
    log.warning("Lead already converted, cannot change status")
    # Nhưng vẫn tiếp tục → KHÔNG HARD BLOCK
```

#### **Admission FSM Evaluation**

| Aspect | Status | Comments |
|--------|--------|----------|
| **Status Transitions** | ✅ GOOD | Hard-coded trong service |
| **Version Locking** | ✅ GOOD | Optimistic lock cho concurrent |
| **Pessimistic Lock** | ✅ GOOD | FOR UPDATE khi submit |
| **Snapshot Immutability** | ✅ GOOD | `applied_rules` không đổi |
| **Terminal Guard** | ✅ GOOD | Enrolled không thể revert |

### 4.3 Transition Lỏng Lẻo (WARNINGS)

#### **Issue #1: Lack of Cross-Entity State Consistency**

```
SCENARIO:
1. Lead status = "qualified" (sts06)
2. Admission profile created (status = "draft")
3. Admission rejected (status = "rejected")
4. Lead status vẫn = "qualified" ← INCONSISTENT
```

**Khuyến nghị**: Thêm event listener `ADMISSION_STATUS_CHANGED` → Update lead status

#### **Issue #2: Phase Transition Without Admission Profile Check**

Hiện tại FSM cho phép transition từ CONSULTATION → ADMISSION phase mà không kiểm tra admission profile đã tồn tại.

```python
# Current: Chỉ check phase guard
# Missing: Check admission_profile exists cho statuses sts07+
```

**Khuyến nghị**: Thêm `admission_profile_required` flag vào ConsultationStatus

### 4.4 Thiếu Trạng Thái Trung Gian

| Missing Status | Use Case | Priority |
|----------------|----------|----------|
| **PENDING_VERIFICATION** | Sau submit, trước khi hệ thống validate | LOW (hiện sync) |
| **MANAGER_ASSIGNED** | Manager nhận review nhưng chưa quyết định | ✅ Có (`assigned_reviewer_id`) |
| **PAYMENT_PENDING** | Chờ xác nhận thanh toán | ✅ Có (sts10, sts14) |
| **LOCKED** | Profile bị khóa tạm thời (dispute, audit) | ❌ THIẾU |
| **DEFERRED** | Hoãn xét tuyển sang kỳ sau | ❌ THIẾU |

---

## 5. PERFORMANCE & SCALABILITY REVIEW

### 5.1 Hiện Trạng Query Patterns

#### **Lead List Query** (`lead_repository.get_filtered`)

```python
# Current implementation analysis:

# GOOD: Eager loading
.options(
    selectinload(Lead.offering),
    selectinload(Lead.unit),
    selectinload(Lead.assigned_officer),
    selectinload(Lead.pipeline_stage),
    selectinload(Lead.consultation_status),
)

# GOOD: Proper pagination
.offset(skip).limit(limit)

# GOOD: Quick Disposition sorting
.order_by(
    case(
        (Lead.next_activity_at <= now, 0),  # Overdue
        (Lead.next_activity_at.between(today_start, today_end), 1),  # Today
        else_=2  # Future/NULL
    ),
    Lead.next_activity_at.asc().nullslast()
)

# GOOD: Filter by indexed columns
.where(Lead.unit_id.in_(unit_ids))
.where(Lead.status.in_(statuses))
.where(Lead.deleted_at.is_(None))
```

#### **Admission Profile Query** (`admission_repository.get_filtered`)

```python
# Similar pattern with eager loading
# + IDOR filter by lead.unit_id
```

### 5.2 Bottleneck Analysis

#### **Potential Bottleneck #1: Consultation Count Calculation**

**Hiện trạng**: `lead.consultation_count` là cached field, updated qua LeadCacheService

**Risk**: Nếu cache service fail, count có thể stale

**Mitigation**: ✅ Đã có fallback query trong repository

#### **Potential Bottleneck #2: Lead Score Calculation**

**Hiện trạng**: `calculate_lead_score()` là sync function, không cache

**Analysis**:
```python
# Factors:
# - Demographic: education, gpa, source, location
# - Behavioral: consultation_count, has_application, staleness

# Complexity: O(1) per lead
# Risk: Nếu gọi trong list endpoint → O(n)
```

**Actual**: Score được tính 1 lần khi create/update → ✅ OK

#### **Potential Bottleneck #3: N+1 Query Prevention**

| Query | N+1 Risk | Mitigation |
|-------|----------|------------|
| Lead list | ✅ Protected | `selectinload` all relationships |
| Lead detail | ✅ Protected | Full eager load |
| Admission list | ✅ Protected | `selectinload` + `joinedload(Lead)` |
| Consultation list | ✅ Protected | Part of lead detail load |

#### **Potential Bottleneck #4: Large Lead Volumes (10k-100k)**

| Scenario | Current | Optimized |
|----------|---------|-----------|
| 10k leads, page 1 | ~50ms | OK |
| 10k leads, page 500 | ~200ms (OFFSET) | ⚠️ Cursor pagination |
| 100k leads, full scan | ~5s | ❌ Avoid |
| 100k leads, filtered | ~100ms | OK (indexed) |

**Khuyến nghị**: Chuyển sang cursor-based pagination cho large datasets

### 5.3 Index Strategy

#### **Existing Indexes** (From model analysis)

```sql
-- Lead table
INDEX ix_lead_unit_id ON lead(unit_id)
INDEX ix_lead_status ON lead(status)
INDEX ix_lead_offering_id ON lead(offering_id)
INDEX ix_lead_assigned_officer_id ON lead(assigned_officer_id)
INDEX ix_lead_consultation_status_id ON lead(consultation_status_id)
INDEX ix_lead_deleted_at ON lead(deleted_at)
INDEX ix_lead_created_at ON lead(created_at)
INDEX ix_lead_next_activity_at ON lead(next_activity_at)

-- Consultation table
INDEX ix_consultation_lead_id ON consultation(lead_id)
INDEX ix_consultation_officer_id ON consultation(officer_id)
INDEX ix_consultation_status_id ON consultation(consultation_status_id)
INDEX ix_consultation_deleted_at ON consultation(deleted_at)

-- Admission Profile table
INDEX ix_admission_profile_lead_id ON admission_profile(lead_id)
UNIQUE ix_admission_profile_citizen_id_year ON admission_profile(citizen_id, academic_year)
```

#### **Missing Indexes (Recommended)**

```sql
-- Composite index cho common filter pattern
CREATE INDEX ix_lead_unit_status ON lead(unit_id, status) WHERE deleted_at IS NULL;

-- Composite cho Quick Disposition
CREATE INDEX ix_lead_unit_next_activity ON lead(unit_id, next_activity_at)
WHERE deleted_at IS NULL;

-- Admission filtered queries
CREATE INDEX ix_admission_profile_status ON admission_profile(status);
CREATE INDEX ix_admission_profile_unit ON admission_profile(lead_id, status);
```

### 5.4 Caching Strategy

#### **Current Cache Usage**

| Cache Key | TTL | Purpose |
|-----------|-----|---------|
| `lead:{id}:cache` | 5m | consultation_count, last_consultation_at |
| `user_blacklist:{id}` | Session | Auth invalidation |
| `blacklist:{jti}` | Token exp | JWT invalidation |

#### **Recommended Additional Caching**

| Cache Key | TTL | Purpose | Priority |
|-----------|-----|---------|----------|
| `lead:list:{unit_id}:{hash}` | 30s | Paginated lead list | MEDIUM |
| `pipeline:stages` | 1h | PipelineStage data | HIGH (static) |
| `consultation_status:all` | 1h | All statuses | HIGH (static) |
| `admission:config:{id}` | 10m | AdmissionPath rules | MEDIUM |

### 5.5 Scalability Recommendations

#### **Short Term (Current → 10k leads)**

1. ✅ Current pagination OK
2. Add composite indexes (above)
3. Enable Redis caching for static data

#### **Medium Term (10k → 100k leads)**

1. Switch to cursor-based pagination
2. Implement read replicas for list queries
3. Consider Elasticsearch for full-text search

#### **Long Term (100k+ leads)**

1. Partition tables by `academic_year` or `unit_id`
2. Implement CQRS pattern (separate read/write models)
3. Event sourcing for audit trail

---

## 6. SECURITY & DATA SAFETY

### 6.1 IDOR (Insecure Direct Object Reference) Analysis

#### **Current Protection Mechanism**

```python
# deps.py - IDOR Pattern

async def get_lead_for_user(
    lead_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Lead:
    # Admin bypass
    if current_user.role == UserRole.ADMIN:
        lead = await lead_repo.get_by_id(db, lead_id)
    else:
        # IDOR check: unit_id match
        lead = await lead_repo.get_by_id_and_unit(db, lead_id, current_user.unit_id)

    if not lead:
        raise ResourceNotFoundError("Lead not found")  # 404 not 403!
    return lead
```

#### **IDOR Coverage Matrix**

| Endpoint | Protected? | Method |
|----------|------------|--------|
| GET /leads/{id} | ✅ | `get_lead_for_user` |
| PUT /leads/{id} | ✅ | `get_lead_for_user` |
| DELETE /leads/{id} | ✅ | `get_lead_for_user` + Admin only |
| POST /leads/{id}/consultations | ✅ | `get_lead_for_user` |
| GET /admissions/{id} | ✅ | `get_admission_for_user` |
| PUT /admissions/{id} | ✅ | `get_admission_for_user` |
| POST /admissions/{id}/approve | ✅ | `get_admission_for_manager` |
| POST /admissions/{id}/confirm/{token} | ⚠️ | Token-based, no auth |

#### **Potential IDOR Gaps**

| Gap | Risk | Status |
|-----|------|--------|
| Officer xem lead của unit khác | ❌ Blocked | ✅ OK |
| Officer xem admission của unit khác | ❌ Blocked | ✅ OK |
| User xem consultation history lead khác | ❌ Blocked | ✅ OK |
| Magic link token guessing | LOW (256-bit token) | ✅ OK |
| Student code enumeration | ❌ Blocked (auth required) | ✅ OK |

### 6.2 Authorization Gaps

#### **Gap #1: Admission Update Ngược Dòng**

**Scenario**: Admission profile có thể update info mà không sync Lead

**Risk**: LOW - Không phải security issue, là data consistency issue

#### **Gap #2: Soft Delete Bypass**

**Scenario**: Trực tiếp query DB có thể thấy soft-deleted records

**Mitigation**: ✅ All repository queries có `deleted_at IS NULL` filter

#### **Gap #3: Rate Limiting Coverage**

| Endpoint | Rate Limit | Status |
|----------|------------|--------|
| POST /leads | ✅ 200/hour | OK |
| PUT /leads/{id} | ✅ 200/hour | OK |
| POST /admissions/{id}/confirm | ✅ 10/min | OK |
| POST /auth/login | ⚠️ Not specified | **CHECK** |

### 6.3 Audit Log Analysis

#### **Current Audit Trail**

| Entity | Audit Table | Coverage |
|--------|-------------|----------|
| Lead | `LeadStatusHistory` | ✅ Status changes |
| Lead | (missing) | ❌ Field changes |
| Consultation | (missing) | ❌ No audit |
| Admission | `approved_by`, `rejected_by`, `confirmed_at` | ✅ Partial |
| Admission | (missing) | ❌ Field changes |

#### **Audit Gap Assessment**

| What's Missing | Impact | Priority |
|----------------|--------|----------|
| Lead field changes (name, phone, email) | MEDIUM - Không trace được ai sửa | HIGH |
| Consultation CRUD audit | LOW - Less critical | MEDIUM |
| Admission field changes | MEDIUM - Không trace được ai sửa | HIGH |
| Document upload/delete audit | HIGH - Compliance requirement | **CRITICAL** |

**Khuyến nghị**: Implement generic audit log table

```python
class AuditLog(Base):
    id: int
    entity_type: str  # "lead", "admission_profile", "document"
    entity_id: int
    action: str  # "create", "update", "delete"
    changed_fields: JSONB  # {"phone": {"old": "...", "new": "..."}}
    changed_by_user_id: int
    changed_at: datetime
    ip_address: str
    user_agent: str
```

### 6.4 Data Safety Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Sensitive data encrypted at rest | ⚠️ DB-level | Recommend field-level for CCCD |
| CCCD displayed masked | ❌ Full display | Mask: ******1234 |
| Password hashing | ✅ bcrypt | OK |
| JWT secret rotation | ⚠️ Manual | Recommend auto-rotation |
| SQL injection protection | ✅ SQLAlchemy ORM | OK |
| XSS prevention | ✅ Pydantic validation | OK |
| CSRF protection | ⚠️ Cookie-based JWT | Recommend SameSite=Strict |

---

## 7. UX FLOW & USER BEHAVIOR

### 7.1 Phân Tích Luồng Nhân Viên Tư Vấn

#### **Happy Path: Lead → Admission**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    OFFICER HAPPY PATH                                │
└─────────────────────────────────────────────────────────────────────┘

Step 1: Tạo Lead
├── Form nhập: full_name, phone, email, source, offering_id
├── System auto-assign hoặc officer tự chọn
└── ✅ UX: Simple, clear form

Step 2: Tư Vấn (Consultations)
├── Thêm consultation với notes, method, scheduled_at
├── Chọn status từ dropdown (FSM-filtered)
├── Quick Disposition: Bubble-up overdue leads
└── ✅ UX: Status dropdown có thể gây confusion (many options)

Step 3: Qualify Lead
├── Chuyển status = "qualified" (sts06)
├── Có thể update lead_score, officer_rating
└── ⚠️ UX: Không rõ khi nào nên qualify

Step 4: Tạo Admission Profile
├── Click "Tạo hồ sơ" từ lead detail
├── Chọn admission_method
├── System snapshot applied_rules
└── ✅ UX: One-click creation

Step 5: Upload Documents
├── Upload từng document theo mandatory list
├── Có thể mark "paper_submitted" cho bản cứng
└── ⚠️ UX: Nhiều document types có thể overwhelming

Step 6: Submit for Evaluation
├── Click "Nộp hồ sơ"
├── System validate và auto-approve/reject
├── Nếu fail → hiển thị validation errors
└── ✅ UX: Clear feedback

Step 7: Manager Approval (nếu cần)
├── Manager review và approve/reject
├── Rejection cần reason
└── ✅ UX: Standard workflow

Step 8: Send Magic Link
├── Click "Gửi link xác nhận"
├── Email/SMS với token link
└── ✅ UX: One-click

Step 9: Enroll Student
├── Sau confirm, click "Hoàn tất nhập học"
├── System tạo Student + chuyển documents
└── ✅ UX: Clear final step
```

### 7.2 Điểm Gây Nhầm Lẫn

| Pain Point | Description | Recommendation |
|------------|-------------|----------------|
| **Status Dropdown quá nhiều options** | 15+ statuses, user không biết chọn gì | Group by phase, show descriptions |
| **Không rõ workflow progress** | User không biết đang ở step nào | Add progress indicator |
| **Admission creation hidden** | Button "Tạo hồ sơ" không nổi bật | Highlight khi lead qualified |
| **Document requirements unclear** | User không biết document nào mandatory | Add mandatory badge + checklist |
| **Validation errors scattered** | Errors hiển thị riêng lẻ | Group by section |

### 7.3 Hành Vi Chưa Được Mô Hình Hóa

| Real-world Behavior | Currently Supported? | Priority |
|---------------------|----------------------|----------|
| **Lead gọi lại nhiều lần trong ngày** | ✅ Multiple consultations | OK |
| **Chuyển lead cho đồng nghiệp (ngang cấp)** | ⚠️ Chỉ có reassign by manager | MEDIUM |
| **Lead xin hoãn xét tuyển** | ❌ Không có status DEFERRED | MEDIUM |
| **Lead đổi ngành nguyện vọng** | ⚠️ Phải tạo profile mới | LOW |
| **Lead từ chối sau approval** | ❌ Không có status DECLINED | MEDIUM |
| **Walk-in lead (không hẹn trước)** | ✅ source="walk_in" | OK |
| **Lead là người thân của sinh viên hiện tại** | ❌ Không track referral relationship | LOW |
| **Hồ sơ bị treo (chờ bổ sung giấy tờ)** | ⚠️ Dùng status "rejected" | MEDIUM |
| **Batch import leads từ event** | ✅ bulk-import endpoint | OK |

### 7.4 Đề Xuất UX Flow Cải Tiến

#### **Proposed: Guided Workflow UI**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    LEAD DETAIL PAGE (Improved)                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ WORKFLOW PROGRESS                                             │   │
│  │                                                               │   │
│  │  [✓] Contact  →  [✓] Qualify  →  [●] Profile  →  [ ] Enroll  │   │
│  │                                                               │   │
│  │  Current Step: Tạo hồ sơ tuyển sinh                          │   │
│  │  Next Action: [Button: Tạo hồ sơ mới]                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ QUICK ACTIONS                                                 │   │
│  │                                                               │   │
│  │  [Add Consultation]  [Change Status ▾]  [Create Profile]     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ STATUS DROPDOWN (Improved)                                    │   │
│  │                                                               │   │
│  │  --- Tư vấn ---                                              │   │
│  │  ○ Đã liên hệ - Cuộc gọi đầu tiên thành công                │   │
│  │  ○ Quan tâm - Lead có ý định đăng ký                        │   │
│  │  ○ Đủ điều kiện - Sẵn sàng tạo hồ sơ                        │   │
│  │                                                               │   │
│  │  --- Hoạt động ---                                           │   │
│  │  ○ Lên lịch - Đặt lịch tư vấn tiếp                          │   │
│  │  ○ Ghi chú - Thêm ghi chú không đổi trạng thái              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. KẾT LUẬN KIẾN TRÚC

### 8.1 Danh Sách Vấn Đề CRITICAL (Phải Fix Trước Production)

| # | Issue | Impact | File/Location | Effort |
|---|-------|--------|---------------|--------|
| 1 | **Admission Profile tạo được khi chưa có Consultation** | Bypass workflow, data không đầy đủ | `admission_service.create_profile()` | 2h | Đã Fixed, cần kiểm tra lại
| 2 | **Data không sync giữa Lead và Admission Profile** | Email/phone sai, magic link gửi sai | Architecture decision | 4h | Đã Fixed, cần kiểm tra lại
| 3 | **Consultation delete dùng hard delete** | Mất audit trail, không restore được | `lead_service.delete_consultation()` | 1h | Đã Fixed, cần kiểm tra lại
| 4 | **Document upload/delete không có audit log** | Compliance risk | Toàn bộ document workflow | 4h | Đã Fixed, cần kiểm tra lại
| 5 | **CCCD hiển thị đầy đủ, không mask** | Privacy/security risk | Frontend display | 1h | Đã Fixed, cần kiểm tra lại

### 8.2 Danh Sách Vấn Đề WARNING (Nên Fix Sớm)

| # | Issue | Impact | Priority |
|---|-------|--------|----------|
| 1 | Lead status không auto-sync với Admission status | Inconsistent reporting | HIGH | Đã Fixed, cần kiểm tra lại
| 2 | Không có status DEFERRED, DECLINED, LOCKED | Không cover real-world scenarios | MEDIUM |
| 3 | Terminal status guard chỉ log warning, không hard block | Potential state corruption | MEDIUM | Đã Fixed, cần kiểm tra lại
| 4 | Missing composite indexes cho common queries | Performance degradation at scale | MEDIUM | Đã Fixed, cần kiểm tra lại
| 5 | Lack of generic audit log | Khó trace field changes | MEDIUM | Đã Fixed, cần kiểm tra lại
| 6 | Rate limiting cho /auth/login không rõ | Brute force risk | HIGH | ĐÃ IMPLEMENT - Không cần thêm code mới.
| 7 | CSRF protection chưa optimal | Cookie-based JWT vulnerable | MEDIUM | Đã Fixed, cần kiểm tra lại

### 8.3 Điểm Thiết Kế RẤT TỐT

| # | Design Decision | Why It's Good |
|---|-----------------|---------------|
| 1 | **FSM Phase-Based Workflow** | Prevents invalid state transitions, enforces business rules |
| 2 | **Snapshot Pattern (applied_rules)** | Immutable audit trail, no rule drift |
| 3 | **Optimistic Locking (version field)** | Prevents race conditions, no database deadlocks |
| 4 | **IDOR via 404 (not 403)** | No information leakage about resource existence |
| 5 | **Repository Pattern** | Clean separation, testable, swappable |
| 6 | **Smart Dependencies** | Security checks centralized, not scattered in routers |
| 7 | **Quick Disposition (next_activity_at)** | Excellent UX for officers, no missed follow-ups |
| 8 | **LeadCacheService** | Denormalized metrics without N+1 queries |
| 9 | **Magic Link Confirmation** | Self-service enrollment confirmation, reduces staff workload |
| 10 | **Soft Delete Pattern** | Data recovery, audit trail preservation |

### 8.4 Đề Xuất Cải Tiến Kiến Trúc

#### **Short-Term (Trước Production - 1-2 tuần)**

1. **Fix Critical Issues** (items 8.1)
2. **Add missing indexes** (section 5.3)
3. **Implement generic audit log** (section 6.3)
4. **Add workflow checkpoint**: Require ≥1 consultation before admission

#### **Medium-Term (1-2 tháng)**

1. **Data Sync Strategy**: Implement event-based sync Lead ↔ Admission
2. **Add missing statuses**: DEFERRED, DECLINED, LOCKED
3. **Cursor-based pagination**: For 10k+ leads scalability
4. **Enhanced rate limiting**: Cover all sensitive endpoints
5. **Field-level encryption**: CCCD, email, phone

#### **Long-Term (3-6 tháng)**

1. **Event Sourcing**: Full audit trail via events
2. **CQRS Pattern**: Separate read/write models for scale
3. **Elasticsearch Integration**: Full-text search, analytics
4. **Multi-tenancy**: If expanding to multiple institutions
5. **Finance Module**: Fee verification before enrollment (as designed in v1.1)

---

## APPENDIX: Checklist Production Readiness

### A. Functional Completeness

- [x] Lead CRUD operations
- [x] Consultation CRUD operations
- [x] Admission Profile lifecycle
- [x] Document management
- [x] Magic link confirmation
- [x] Student enrollment
- [ ] Consultation soft delete implementation
- [ ] Lead-Admission data sync
- [ ] Workflow checkpoint enforcement

### B. Security

- [x] JWT authentication
- [x] RBAC authorization (Casbin)
- [x] IDOR protection
- [x] Input validation (Pydantic)
- [ ] CCCD masking
- [ ] Complete audit logging
- [ ] Rate limiting coverage
- [ ] CSRF protection enhancement

### C. Performance

- [x] Eager loading (N+1 prevention)
- [x] Pagination
- [x] Quick Disposition sorting
- [ ] Composite indexes
- [ ] Redis caching for static data
- [ ] Cursor-based pagination

### D. Operations

- [x] Structured logging (structlog)
- [x] Error handling
- [ ] Health check endpoints
- [ ] Metrics export (Prometheus)
- [ ] Alerting configuration
- [ ] Backup strategy verification

---

**Document Version**: 1.0
**Last Updated**: 2026-01-26
**Next Review**: Before Production Release
