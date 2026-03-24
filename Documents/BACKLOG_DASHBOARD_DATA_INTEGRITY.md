# Backlog: Dashboard Data Integrity — Phòng ngừa & Cải thiện

> Tạo: 2026-03-24
> Context: Audit toàn bộ dashboard KPI/funnel/drilldown/trends sau session fix mismatch
> Branch gốc: main (commit a0fcf4f6..408c2000)

---

## Đã hoàn thành trong session này

| # | Vấn đề | Commit | Ảnh hưởng |
|---|--------|--------|-----------|
| ✅ | Personal leads_snapshot dính `unit_ids` | b3133265 | Officer/admin personal leads list + export |
| ✅ | Aggregate KPI đếm system consultations + UTC timezone | b3133265 | Manager/admin dashboard consultation count |
| ✅ | Drilldown thiếu `human` default cho consultation metrics | b3133265 | Consultation drilldown pages |
| ✅ | E2E spec stale (URL pattern + pagination) | b3133265 | Test suite |
| ✅ | Drilldown `_date_bounds` dùng UTC thay vì VN | d4cf0e66 | Tất cả drilldown date boundaries |
| ✅ | Export endpoint thiếu `is_final`/`counts_for_funnel` | d4cf0e66 | Leads export |
| ✅ | `LeadListParams` TypeScript thiếu fields | d4cf0e66 | Type safety |
| ✅ | SSR/client query parity cho dashboard deep-links | 07c4051a | SSR first paint |
| ✅ | FunnelTable totalLeads dùng core-only (khác FunnelChart) | 07c4051a | Funnel % hiển thị |
| ✅ | `is_final`/`counts_for_funnel` stale sau exit context | a0fcf4f6 | URL cleanup khi thoát dashboard |
| ✅ | Performance trends đếm system consultations | 408c2000 | Trends chart |
| ✅ | 30 pre-existing frontend test failures | 9f95d400 | Test suite 617/617 |
| ✅ | `sts05` "Hẹn liên hệ lại" `counts_for_funnel=false` | SQL production | 6 leads thiếu khỏi funnel |
| ✅ | `sts00` thiếu `legacy_status='new'` | SQL production | 9 leads NULL status |
| ✅ | 9 leads `consultation_status_id=NULL` | SQL production | Leads không hiện trong funnel |

---

## Fix Next — Kỹ thuật, chưa ảnh hưởng production hiện tại

### 1. Response time / SLA thiếu system consultation filter
- **Priority:** Medium
- **Khi nào gây lệch:** Khi admission workflow bắt đầu tạo system consultations
- **Verify hiện tại:** 0 system consultations trong production → chưa lệch
- **Files:**
  - `officer_repository.py:1785-1788` — `get_avg_response_time_hours` first_consult_subq
  - `officer_repository.py:1841-1844` — `get_avg_response_time_hours_multi` first_consult_subq
  - `officer_repository.py:1909-1911` — `get_sla_compliance_stats` first_consult_subq
  - `officer_repository.py:1998-2001` — `get_aggregated_sla_compliance_stats` first_consult_subq
- **Fix:** Thêm `models.Consultation.method.is_distinct_from("system")` vào 4 subquery
- **Risk:** Thấp — chỉ thay đổi cách tìm "first consultation"

### 2. Shared date_bounds helper (drilldown vs KPI)
- **Priority:** Low
- **Hiện trạng:** `drilldown_service._date_bounds` đã dùng VN timezone (fix d4cf0e66). Nhưng `officer_repository.py` vẫn dùng `func.date(column) >= start_date` (DB timezone-dependent).
- **Files:**
  - `drilldown_service.py:26-43` — `_date_bounds()` dùng VN
  - `officer_repository.py:851,966,1021,1453` — dùng `func.date()` style
- **Fix đề xuất:** Tách `_date_bounds` thành `app/utils/date_bounds.py`, dùng chung cho cả drilldown và repository. Thay `func.date(col) >= date` bằng `col >= vn_midnight_dt`.
- **Risk:** Medium — thay đổi nhiều query paths, cần test kỹ

### 3. DB constraint phòng ngừa NULL pipeline_stage
- **Priority:** Low
- **Hiện trạng:** 3 universal statuses (sts01, sts15, sts19) có `updates_pipeline=false`, `stage_id=NULL`. An toàn hiện tại. Nhưng không có code/DB enforcement.
- **Fix:**
  ```sql
  ALTER TABLE consultation_status
  ADD CONSTRAINT ck_pipeline_update_requires_stage
  CHECK (updates_pipeline = false OR stage_id IS NOT NULL);
  ```
- **Risk:** Không có — chỉ validate data mới/update

---

## Deferred — Cần quyết định product

### 4. Leaderboard / team average: human-only hay all-consultations
- **Priority:** Deferred
- **Hiện trạng:** Leaderboard queries không filter system consultations. KPI cards đã filter. Hai nơi dùng semantic khác nhau.
- **Files:**
  - `officer_repository.py:1219` — `get_weekly_consultation_rankings`
  - `officer_repository.py:1244` — `get_officer_rank`
  - `officer_repository.py:1318` — `get_team_overview`
- **Quyết định cần:**
  - Option A: Thêm system filter → ranking thay đổi, cần thông báo nội bộ
  - Option B: Giữ nguyên, đổi label UI thành "TB team (mọi tư vấn)"
- **Lý do defer:** Fix có thể đổi thứ hạng, kéo theo truyền thông nội bộ

### 5. `consultations_avg_per_day` drilldown UX
- **Priority:** Deferred
- **Hiện trạng:** Card hiện average (20.1/ngày), drilldown hiện raw consultation records. User phải tự suy luận.
- **Fix đề xuất:** Thêm header trong drilldown page: "Hiển thị X tư vấn trong Y ngày (trung bình Z/ngày)"
- **Lý do defer:** UX improvement, không phải data bug

---

## Verify checklist cho lần deploy tiếp

Sau mỗi lần thay đổi consultation_status hoặc KPI logic:

```sql
-- 1. Funnel total = Active leads?
SELECT
  (SELECT COUNT(*) FROM lead l LEFT JOIN consultation_status cs ON l.consultation_status_id=cs.id WHERE l.deleted_at IS NULL AND (cs.is_final=false OR cs.is_final IS NULL)) AS active,
  (SELECT COUNT(*) FROM lead l JOIN consultation_status cs ON l.consultation_status_id=cs.id WHERE l.deleted_at IS NULL AND cs.counts_for_funnel=true) AS funnel;

-- 2. Leads NULL status?
SELECT COUNT(*) FROM lead WHERE deleted_at IS NULL AND consultation_status_id IS NULL;

-- 3. Statuses config consistency?
SELECT id, name, stage_id, counts_for_funnel, updates_pipeline, is_universal
FROM consultation_status WHERE stage_id IS NULL OR counts_for_funnel = false ORDER BY id;

-- 4. System consultations present?
SELECT method, COUNT(*) FROM consultation WHERE deleted_at IS NULL GROUP BY method;
```

---

## Data fixes đã chạy trên production (2026-03-24)

```sql
-- Fix root cause: sts00 thiếu legacy_status
UPDATE consultation_status SET legacy_status = 'new' WHERE id = 'sts00';

-- Fix config: sts05 thuộc funnel
UPDATE consultation_status SET counts_for_funnel = true WHERE id = 'sts05';

-- Fix data: 9 leads NULL status
UPDATE lead SET consultation_status_id = 'sts00', pipeline_stage_id = 'stg01'
WHERE deleted_at IS NULL AND consultation_status_id IS NULL;
-- Affected: 9 rows (IDs: 39, 64, 66, 68, 70, 74, 79, 84, 89)
```
