# Admission Event to Pipeline Projection Matrix

> **Generated from Codebase + Proposal**: Refined to separate "Request Changes" flow.
> **Last Updated**: 2026-01-15

## 🔒 The Golden Rule

> **No Admission Event may occur without:**
> 1. Being tied to a Consultation Status
> 2. Being tied to a Pipeline Stage
> 3. Creating a Consultation record (method="system")

---

## Mapping Matrix

| Admission Event Event Code | Admission Status `profile.status` | Target Pipeline Stage `lead.pipeline_stage_id` | Target Consultation Status `lead.consultation_status_id` | System Note Template |
| :--- | :--- | :--- | :--- | :--- |
| **LEAD CREATED**<br>`lead_created` | *None* | **stg01**<br>Chưa tư vấn | **sts00**<br>Chưa liên hệ | `[HỆ THỐNG] Lead được tạo trên hệ thống` |
| **OFFICER CONTACTED**<br>`officer_contacted` | *None* | **stg02**<br>Đang tư vấn | **sts05**<br>Cân nhắc | `[HỆ THỐNG] Bắt đầu quá trình tư vấn` |
| **LEAD AGREES**<br>`lead_agrees` | *None* | **stg02**<br>Đang tư vấn | **sts06**<br>Đồng ý tư vấn | `Học viên đồng ý tìm hiểu chương trình` |
| **PROFILE CREATED**<br>`profile_created` | `draft` | **stg02**<br>Đang tư vấn | **sts06**<br>Đồng ý tư vấn | `[HỆ THỐNG] Hồ sơ xét tuyển được khởi tạo (Draft) - Profile #{profile_id}` |
| **PROFILE SUBMITTED**<br>`profile_submitted` | `submitted` | **stg03**<br>Đã nộp hồ sơ | **sts07**<br>Chờ nhập học | `[HỆ THỐNG] Hồ sơ xét tuyển đã được nộp - Profile #{profile_id}` |
| **PROFILE APPROVED**<br>`profile_approved` | `approved` | **stg04**<br>Chờ nhập học | **sts09**<br>Chờ đóng học phí | `[HỆ THỐNG] Hồ sơ xét tuyển đã được duyệt - Profile #{profile_id}` |
| **PROFILE CONFIRMED**<br>`profile_confirmed` | `confirmed` | **stg04**<br>Chờ nhập học | **sts09**<br>Chờ đóng học phí | `[HỆ THỐNG] Học viên xác nhận ý định nhập học - Profile #{profile_id}` |
| **FEE RECORDED**<br>`fee_recorded` | `confirmed` | **stg05**<br>Đã nộp học phí | **sts10**<br>Đã nộp học phí | `[HỆ THỐNG] Học viên đã hoàn tất học phí - Profile #{profile_id}` |
| **STUDENT ENROLLED**<br>`profile_enrolled` | `enrolled` | **stg06**<br>Đã nhập học | **sts11**<br>Đã nhập học | `[HỆ THỐNG] Học viên đã nhập học chính thức - Profile #{profile_id}, Mã SV: {student_code}` |
| **PROFILE REJECTED**<br>`profile_rejected` | `rejected` | **stg03**<br>Đã nộp hồ sơ | **sts16** <br>*(NEW)* Yêu cầu bổ sung | `[HỆ THỐNG] Hồ sơ yêu cầu bổ sung/chỉnh sửa - Profile #{profile_id}. Lý do: {reason}` |
| **PROFILE RESUBMITTED**<br>`profile_resubmitted` | `submitted` | **stg03**<br>Đã nộp hồ sơ | **sts07**<br>Chờ nhập học | `[HỆ THỐNG] Hồ sơ xét tuyển được nộp lại sau khi chỉnh sửa - Profile #{profile_id}` |
| **ADMIN OVERRIDE**<br>`profile_overridden` | `approved` | **stg04**<br>Chờ nhập học | **sts09**<br>Chờ đóng học phí | `[HỆ THỐNG] Hồ sơ được duyệt đặc biệt bởi Admin - Profile #{profile_id}. Lý do: {reason}` |
| **STUDENT DROPPED**<br>`student_dropped` | `enrolled` | **stg07**<br>Không đi học | **sts12**<br>Bỏ học | `[HỆ THỐNG] Học viên không tiếp tục theo học - Profile #{profile_id}` |
| **STUDENT REFUNDED**<br>`student_refunded` | `confirmed` | **stg07**<br>Không đi học | **sts14**<br>Đã rút lại học phí | `[HỆ THỐNG] Học viên rút lại học phí - Profile #{profile_id}` |

---

## Important Implementation Notes

### ⚠️ Profile Confirmed (`profile_confirmed`)
*   **Behavior**: Events do NOT change the pipeline stage/status (remains `stg04`/`sts09`).
*   **Meaning**: This is a behavioral intent confirmation by the applicant ("I intend to enroll"), NOT a formal pipeline milestone.
*   **Pipeline Status**: The lead is already in `stg04` (Chờ nhập học) after approval; confirmation reinforces this state but doesn't advance it.

### ⚠️ Fee Recorded (`fee_recorded`)
*   **Role**: This is a **MANUAL financial confirmation event**.
*   **Source**: Only triggered by an Officer manually verifying payment.
*   **Constraint**: NOT emitted by the automated admission engine.

---

## Visualization of Submission Loop

```mermaid
graph TD
    %% Nodes
    draft[stg02: Draft]
    submitted[stg03: SUBMITTED (sts07)]
    supplement[stg03: REQUEST CHANGES (sts16)]
    approved[stg04: APPROVED (sts09)]
    
    %% Flows
    draft -->|Submit Profile| submitted
    submitted -->|Approve| approved
    submitted -->|Reject (Request Changes)| supplement
    supplement -->|Resubmit| submitted
```

## Transition Rules (Strict)

Based on the introduction of `sts16`, the following `allowed_transitions` are implicitly required:

1.  **Allowed Loop**:
    *   `sts07` (Chờ nhập học) → `sts16` (Yêu cầu bổ sung)
    *   `sts16` (Yêu cầu bổ sung) → `sts07` (Chờ nhập học)

2.  **Strict Prohibitions**:
    *   ⛔ `sts16` → `sts09` (Cannot approve directly from "Request Changes" - must resubmit to `sts07` first)
    *   ⛔ `sts16` → `stg02` (Cannot revert to "Consulting" stage - applicant is already committed to applying)

## Changes Checklist

1.  **Add `sts16` to `consultation_status.csv`**:
    *   ID: `sts16`
    *   Name: `Yêu cầu bổ sung`
    *   Stage: `stg03`
    *   Updates Pipeline: `True`

2.  **Add Transitions to `allowed_transitions.csv`**:
    *   `sts07` -> `sts16`
    *   `sts16` -> `sts07`

3.  **Update `admission_event_mapping.py`**:
    *   Update `profile_rejected` to use `sts16`.
    *   Add comments for `fee_recorded` and `profile_confirmed`.
