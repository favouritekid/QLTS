# Admission Pipeline Synchronization - Implementation Summary

## Executive Summary

This document describes the complete solution to synchronize admission events with the consultation pipeline system, addressing the critical architectural gap identified in `report.txt`.

**Problem:** Admission events were updating only `lead.status` but ignoring `lead.pipeline_stage_id` and `lead.consultation_status_id`, causing:
- Officers seeing leads stuck in "Đang tư vấn" when students were enrolled
- Broken pipeline reports and dashboards
- Missing audit trail for admission milestones
- Stale KPI metrics

**Solution:** Configuration-driven system consultation records that automatically synchronize pipeline stages with admission events, following the Golden Rule:

> 🔒 **GOLDEN RULE**: No Admission Event may occur without:
> 1. Being tied to a Consultation Status
> 2. Being tied to a Pipeline Stage
> 3. Creating a Consultation record (even if SYSTEM-generated)

---

## Architecture

### 1. Single Source of Truth: Admission Event Projection Config

**File:** `Backend_FastAPI/app/core/admission_event_mapping.py`

Defines the **canonical mapping** between admission events and consultation pipeline states:

```python
ADMISSION_EVENT_PROJECTIONS = {
    "profile_submitted": AdmissionEventProjection(
        event="profile_submitted",
        admission_status="submitted",
        consultation_status_id="sts07",    # Chờ nhập học
        consultation_name="Chờ nhập học",
        pipeline_stage_id="stg03",         # Đã nộp hồ sơ
        stage_name="Đã nộp hồ sơ",
        system_note_template="[HỆ THỐNG] Hồ sơ xét tuyển đã được nộp - Profile #{profile_id}",
        skip_if_converted=True,
    ),
    # ... 12 other events ...
}
```

**Key Features:**
- ✅ No hardcoded stage/status IDs anywhere in services
- ✅ Changes here propagate system-wide
- ✅ Validates against consultation_status.csv and pipeline_stage.csv
- ✅ Terminal state guard (respects "converted" status)
- ✅ Configurable note templates with variable substitution

### 2. System Consultation Helper Function

**File:** `Backend_FastAPI/app/services/admission_service.py`
**Function:** `_create_admission_milestone_consultation()`

**Responsibilities:**
1. Looks up event projection from `ADMISSION_EVENT_PROJECTIONS`
2. Creates a `Consultation` record with `method="system"`
3. Updates `lead.pipeline_stage_id` and `lead.consultation_status_id`
4. Syncs `lead.status` via `sync_lead_status_from_consultation()`
5. Logs state change to `lead_status_history` table

**Example Usage:**
```python
await _create_admission_milestone_consultation(
    db=db,
    lead=profile.lead,
    event="profile_submitted",
    actor=current_user,
    profile_id=profile_id,
)
```

**Architecture Compliance:**
- ✅ Pure service layer (no HTTP dependencies)
- ✅ Does NOT commit (caller commits via Router)
- ✅ Respects terminal state guard
- ✅ Full audit trail with structured logging

### 3. Updated Admission Service Functions

**File:** `Backend_FastAPI/app/services/admission_service.py`

All 7 admission event locations now call the helper function:

| Function | Event | Stage Transition | Status Transition |
|----------|-------|------------------|-------------------|
| `submit_and_evaluate()` | `profile_submitted` | stg02 → stg03 | sts06 → sts07 |
| `approve_profile()` | `profile_approved` | stg03 → stg04 | sts07 → sts09 |
| `reject_profile()` | `profile_rejected` | any → stg02 | any → sts04 |
| `resubmit_profile()` | `profile_resubmitted` | stg02 → stg03 | sts04 → sts07 |
| `confirm_enrollment()` | `profile_confirmed` | stg04 (stays) | sts09 (stays) |
| `override_profile()` | `profile_overridden` | any → stg04 | any → sts09 |
| `enroll_student()` | `profile_enrolled` | stg04 → stg06 | sts09 → sts11 |

**Before (Broken):**
```python
# Old implementation - INCOMPLETE
if profile.lead:
    profile.lead.status = "qualified"  # ❌ Only updates lead.status
    profile.lead.updated_at = datetime.now(timezone.utc)
    # ❌ Missing: pipeline_stage_id
    # ❌ Missing: consultation_status_id
    # ❌ Missing: consultation record
```

**After (Fixed):**
```python
# New implementation - COMPLETE
if profile.lead:
    await _create_admission_milestone_consultation(
        db=db,
        lead=profile.lead,
        event="profile_submitted",
        actor=current_user,
        profile_id=profile_id,
    )
    # ✅ Updates pipeline_stage_id
    # ✅ Updates consultation_status_id
    # ✅ Syncs lead.status via sync_lead_status_from_consultation()
    # ✅ Creates system consultation record
    # ✅ Logs to lead_status_history
```

---

## Complete Event Mapping Table

| Admission Event | Admission Status | Consultation Status | Consultation Name | Pipeline Stage | Stage Name | Auto Consultation Content |
|-----------------|------------------|---------------------|-------------------|----------------|------------|---------------------------|
| Lead created | – | sts00 | Chưa liên hệ | stg01 | Chưa tư vấn | `[SYSTEM] Lead được tạo trên hệ thống` |
| Officer contacted | – | sts05 | Cân nhắc | stg02 | Đang tư vấn | `[SYSTEM] Bắt đầu quá trình tư vấn` |
| Lead agrees | – | sts06 | Đồng ý tư vấn | stg02 | Đang tư vấn | `Học viên đồng ý tìm hiểu chương trình` |
| **Profile CREATED** | draft | **sts06** | Đồng ý tư vấn | **stg02** | Đang tư vấn | `[SYSTEM] Hồ sơ xét tuyển được khởi tạo (Draft)` |
| **Profile SUBMITTED** | submitted | **sts07** | Chờ nhập học | **stg03** | Đã nộp hồ sơ | `[SYSTEM] Hồ sơ xét tuyển đã được nộp` |
| Profile APPROVED | approved | sts09 | Chờ đóng học phí | stg04 | Chờ nhập học | `[SYSTEM] Hồ sơ xét tuyển đã được duyệt` |
| Profile CONFIRMED | confirmed | sts09 | Chờ đóng học phí | stg04 | Chờ nhập học | `[SYSTEM] Học viên xác nhận ý định nhập học` |
| Fee recorded | confirmed | sts10 | Đã nộp học phí | stg05 | Đã nộp học phí | `[SYSTEM] Học viên đã hoàn tất học phí` |
| **Student ENROLLED** | enrolled | **sts11** | Đã nhập học | **stg06** | Đã nhập học | `[SYSTEM] Học viên đã nhập học chính thức` |
| Profile REJECTED | rejected | sts04 | Không đồng ý | stg02 | Đang tư vấn | `[SYSTEM] Hồ sơ xét tuyển bị từ chối. Lý do: {reason}` |
| Profile RESUBMITTED | submitted | sts07 | Chờ nhập học | stg03 | Đã nộp hồ sơ | `[SYSTEM] Hồ sơ xét tuyển được nộp lại` |
| Admin Override | approved | sts09 | Chờ đóng học phí | stg04 | Chờ nhập học | `[SYSTEM] Hồ sơ được duyệt đặc biệt. Lý do: {reason}` |
| Drop / Refund | enrolled | sts12 / sts14 | Bỏ học / Rút học phí | stg07 | Không đi học | `[SYSTEM] Học viên không tiếp tục theo học` |

---

## Officer User Experience

### Before Implementation

**Consultation History View:**
```
📞 2026-01-10 09:30  |  Đồng ý tư vấn
   Officer: Nguyễn Văn A
   Method: phone
   Notes: "Học viên đồng ý tìm hiểu thêm"

[NOTHING HERE - BLACK HOLE]

Lead status shows "qualified" but no visible progress
Pipeline stage stuck at "stg02" (Đang tư vấn)
```

**Issues:**
- ❌ No visibility into admission progress
- ❌ Officers confused why lead shows "Đang tư vấn" when student enrolled
- ❌ Pipeline reports show incorrect stage distribution
- ❌ KPI metrics outdated

### After Implementation

**Consultation History View:**
```
📞 2026-01-10 09:30  |  Đồng ý tư vấn
   Officer: Nguyễn Văn A
   Method: phone
   Notes: "Học viên đồng ý tìm hiểu thêm"

🤖 2026-01-12 14:22  |  Chờ nhập học  [SYSTEM]
   Auto-recorded: Admission profile submitted
   Profile ID: #789

🤖 2026-01-15 10:05  |  Chờ đóng học phí  [SYSTEM]
   Auto-recorded: Admission profile approved
   Approved by: Manager Trần B

📞 2026-01-16 11:00  |  Đã nhập học
   Officer: Nguyễn Văn A
   Method: in_person
   Notes: "Học viên đến nhập học, nhận thẻ SV"
```

**Benefits:**
- ✅ Complete timeline visibility
- ✅ Accurate pipeline stage (stg06 = Đã nhập học)
- ✅ System consultations clearly marked with 🤖
- ✅ Officers can filter regular vs system consultations
- ✅ Pipeline reports show correct stage distribution
- ✅ KPI metrics reflect actual admission progress

---

## Database Impact

### Tables Modified

1. **`lead` table:**
   - `pipeline_stage_id` - NOW synchronized with admission events
   - `consultation_status_id` - NOW synchronized with admission events
   - `status` - NOW derived via `sync_lead_status_from_consultation()`
   - `updated_at` - Timestamp updated on every event

2. **`consultation` table:**
   - New records created with `method="system"`
   - `duration_minutes=0` for system consultations
   - `notes` contain structured information from templates

3. **`lead_status_history` table:**
   - Full audit trail of all state transitions
   - Tracks changes to `pipeline_stage_id`, `consultation_status_id`, `status`
   - Links to `changed_by_user_id` and includes `reason`

### Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       ADMISSION EVENT OCCURS                             │
│                   (e.g., profile_submitted)                              │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│     _create_admission_milestone_consultation()                          │
│                                                                           │
│  1. Lookup projection from ADMISSION_EVENT_PROJECTIONS                   │
│  2. Terminal state guard check                                           │
│  3. Capture old_state from lead                                          │
│  4. Load consultation_status object from DB                              │
│  5. Build note from template                                             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      UPDATE LEAD PIPELINE                                │
│                                                                           │
│  lead.consultation_status_id = projection.consultation_status_id         │
│  lead.pipeline_stage_id = projection.pipeline_stage_id                   │
│  sync_lead_status_from_consultation(lead, consultation_status)           │
│  lead.updated_at = now()                                                 │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  CREATE SYSTEM CONSULTATION                              │
│                                                                           │
│  Consultation(                                                            │
│    lead_id=lead.id,                                                      │
│    officer_id=actor.id,                                                  │
│    consultation_status_id=projection.consultation_status_id,             │
│    method="system",  # ✅ Special marker                                 │
│    notes="[HỆ THỐNG] ...",                                               │
│    duration_minutes=0                                                    │
│  )                                                                       │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│               LOG TO LEAD_STATUS_HISTORY                                 │
│                                                                           │
│  _log_lead_state_change(                                                 │
│    db, lead, old_state, new_state,                                       │
│    changed_by=actor,                                                     │
│    reason="Admission event: profile_submitted"                           │
│  )                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Testing Strategy

### Unit Tests Required

1. **`test_admission_event_mapping.py`:**
   - Test all projection lookups
   - Validate stage/status IDs match CSV seed data
   - Test note template variable substitution
   - Verify terminal state guard logic

2. **`test_admission_milestone_consultation.py`:**
   - Test consultation creation for each event
   - Verify pipeline stage updates
   - Verify consultation status updates
   - Verify lead.status sync
   - Verify lead_status_history logging
   - Test terminal state guard behavior
   - Test missing consultation_status error handling

3. **`test_admission_service_integration.py`:**
   - Test each admission function calls helper correctly
   - Verify no duplicate consultation records
   - Test transaction rollback behavior
   - Verify post-commit callbacks still work

### Integration Test Scenarios

**Scenario 1: Complete Happy Path**
```
1. Create lead → stg01, sts00
2. Officer contacts → stg02, sts05
3. Lead agrees → stg02, sts06
4. Submit profile → stg03, sts07 ✅
5. Approve profile → stg04, sts09 ✅
6. Confirm enrollment → stg04, sts09
7. Enroll student → stg06, sts11 ✅
```

**Scenario 2: Rejection and Resubmission**
```
1. Submit profile → stg03, sts07 ✅
2. Reject profile → stg02, sts04 ✅
3. Resubmit profile → stg03, sts07 ✅
4. Approve profile → stg04, sts09 ✅
```

**Scenario 3: Terminal State Guard**
```
1. Enroll student → stg06, sts11, status="converted"
2. Try to approve again → SKIPPED (terminal state) ✅
3. Consultation history shows only enrollment
```

### Manual Testing Checklist

- [ ] Create new lead and submit profile
- [ ] Verify consultation history shows system record
- [ ] Verify pipeline stage moved to stg03
- [ ] Approve profile and verify stg04 transition
- [ ] Check lead_status_history table has entries
- [ ] Verify lead.status matches derived status from stage
- [ ] Test rejection flow and verify stage rollback
- [ ] Enroll student and verify stg06 final state
- [ ] Check KPI reports show correct stage distribution
- [ ] Verify officer dashboard reflects accurate pipeline

---

## Deployment Checklist

### Pre-Deployment

1. **Database Validation:**
   - [ ] Verify `consultation_status.csv` seeded correctly
   - [ ] Verify `pipeline_stage.csv` seeded correctly
   - [ ] Verify `allowed_transitions.csv` allows system transitions
   - [ ] Check no orphaned leads with NULL pipeline_stage_id

2. **Code Review:**
   - [ ] Review `admission_event_mapping.py` projections
   - [ ] Review `_create_admission_milestone_consultation()` logic
   - [ ] Verify all 7 admission functions updated
   - [ ] Check no remaining hardcoded stage/status IDs

3. **Testing:**
   - [ ] Run full unit test suite
   - [ ] Run integration tests
   - [ ] Perform manual smoke tests
   - [ ] Verify no regression in existing workflows

### Deployment Steps

1. **Deploy Backend:**
   ```bash
   cd Backend_FastAPI
   git pull origin main
   pip install -r requirements.txt  # If dependencies changed
   alembic upgrade head  # Apply any new migrations
   systemctl restart qlts-api
   ```

2. **Verify Deployment:**
   ```bash
   # Check API health
   curl http://localhost:8000/health

   # Check logs for errors
   tail -f /var/log/qlts/api.log | grep ERROR
   ```

3. **Post-Deployment Validation:**
   - [ ] Submit test admission profile
   - [ ] Verify system consultation created
   - [ ] Check pipeline stage updated correctly
   - [ ] Verify lead_status_history logged
   - [ ] Monitor structured logs for errors

### Rollback Plan

If issues detected:

1. **Immediate Rollback:**
   ```bash
   git revert <commit-hash>
   systemctl restart qlts-api
   ```

2. **Data Cleanup (if needed):**
   ```sql
   -- Remove system consultations created during deployment
   DELETE FROM consultation
   WHERE method = 'system'
   AND consultation_date > '2026-01-15 00:00:00';
   ```

3. **Investigation:**
   - Check structured logs for error messages
   - Review lead_status_history for anomalies
   - Verify consultation_status.csv data integrity

---

## Monitoring and Observability

### Key Metrics to Monitor

1. **System Consultation Creation Rate:**
   - Track consultations created with `method="system"`
   - Alert if rate drops to zero (indicates broken sync)

2. **Pipeline Stage Distribution:**
   - Monitor leads in each stage
   - Alert if stg03-stg06 counts seem incorrect

3. **Lead Status Consistency:**
   - Audit query: leads where status doesn't match derived status from consultation_status
   - Should be zero after deployment

4. **Consultation History Gaps:**
   - Monitor for leads with admission profiles but no system consultations
   - Alert if count exceeds threshold

### Structured Log Queries

```python
# Query logs for admission milestone consultations
structlog.get_logger().info(
    "Admission milestone consultation created",
    lead_id=lead.id,
    event=event,
    stage_id=projection.pipeline_stage_id,
    status_id=projection.consultation_status_id,
    profile_id=profile_id,
    actor_id=actor.id,
)

# Query for terminal state guard triggers
structlog.get_logger().warning(
    "Skipping admission milestone consultation: lead already converted",
    lead_id=lead.id,
    event=event,
    current_status="converted",
)
```

### Dashboard Queries

**Pipeline Health Check:**
```sql
SELECT
    ps.name AS stage_name,
    COUNT(l.id) AS lead_count,
    COUNT(ap.id) AS profiles_count
FROM lead l
LEFT JOIN pipeline_stage ps ON l.pipeline_stage_id = ps.id
LEFT JOIN admission_profile ap ON l.id = ap.lead_id
GROUP BY ps.id, ps.name
ORDER BY ps.order;
```

**System Consultation Audit:**
```sql
SELECT
    DATE_TRUNC('day', c.consultation_date) AS date,
    COUNT(*) AS system_consultations_created
FROM consultation c
WHERE c.method = 'system'
GROUP BY date
ORDER BY date DESC
LIMIT 30;
```

---

## Future Enhancements

### Phase 2: Frontend Visualization

1. **Timeline Component:**
   - Visual timeline showing admission + consultation milestones
   - Color-coded markers: 🤖 system, 📞 officer, 👤 applicant
   - Expandable cards with full details

2. **Pipeline Stage Badges:**
   - Real-time stage badges on lead cards
   - Color-coded by stage (green = stg06, blue = stg04, etc.)
   - Hover tooltip showing last transition timestamp

3. **Consultation Filtering:**
   - Filter toggle: Show all / Hide system / Only system
   - Search by consultation status
   - Export consultation history as PDF

### Phase 3: Advanced Features

1. **Predictive Analytics:**
   - ML model to predict enrollment probability based on stage transitions
   - Alert officers when lead stuck in stage too long
   - Recommend next actions based on historical patterns

2. **Automated Notifications:**
   - Email/SMS when lead reaches specific stages
   - Scheduled reminders for stale leads
   - Manager alerts for profiles pending approval

3. **Stage Transition Rules Engine:**
   - Define custom transition rules per organization
   - Block transitions that don't make sense
   - Require approval for certain stage jumps

---

## References

- **Original Issue:** `Documents/report.txt`
- **Architecture Docs:** `Backend_FastAPI/MASTER_ARCHITECTURE.md`
- **Status Mapping:** `Backend_FastAPI/app/core/status_mapping.py`
- **Lead Service:** `Backend_FastAPI/app/services/lead_service.py`
- **Consultation Status CSV:** `Documents/Seeding data/consultation_status.csv`
- **Pipeline Stage CSV:** `Documents/Seeding data/pipeline_stage.csv`
- **Allowed Transitions CSV:** `Documents/Seeding data/allowed_transitions.csv`

---

## Glossary

- **Pipeline Stage:** Physical location in consultation funnel (stg01-stg07)
- **Consultation Status:** Specific outcome/intent within a stage (sts00-sts15)
- **Lead Status:** Legacy enum field derived from consultation_status (new, qualified, converted, etc.)
- **System Consultation:** Auto-generated consultation record with method="system"
- **Terminal State:** Final lead status that should not be overwritten ("converted")
- **Projection:** Mapping from admission event to pipeline state
- **Golden Rule:** Principle that every admission event must create consultation record

---

**Implementation Date:** 2026-01-15
**Author:** Claude Sonnet 4.5
**Status:** ✅ Complete - Ready for Testing
