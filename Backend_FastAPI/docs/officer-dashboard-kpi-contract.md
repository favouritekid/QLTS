# Officer Dashboard — KPI Contract v1.0

> **Mục đích**: Chốt vocabulary, semantics, source of truth và render rules cho mọi metric hiển thị trên officer dashboard. Dùng làm tham chiếu khi thêm/sửa KPI, tránh drift giữa catalog, backend và frontend.

---

## A. Canonical KPI Table (8 metrics)

Source of truth: `Backend_FastAPI/app/services/kpi_catalog.py` → `METRIC_CATALOG`

| # | `code` | Display name | `unit` | `period_type` | Target source | Actual source | Comparison policy | Dashboard location |
|---|--------|-------------|--------|--------------|---------------|--------------|-------------------|-------------------|
| 1 | `consultations_daily` | Tư vấn/ngày | count | daily | KpiConfig (month) | Activity count in day | **Comparable** — always | Tier 1 card #1 |
| 2 | `conversion_rate` | Tỷ lệ chuyển đổi | % | monthly | KpiConfig (month) | Cohort rate (created→converted) | **Not comparable** — target is funnel-derived, actual is cohort-based | Tier 1 card #4 |
| 3 | `win_rate` | Tỷ lệ chốt đơn | % | monthly | KpiConfig (month) | Activity rate (won / (won+lost)) | **Comparable** — requires period = calendar month | Tier 1 card #3 |
| 4 | `response_time_hours` | Thời gian phản hồi | hours | daily | KpiConfig (plan-level) | Activity avg (assign→first consult) | **Comparable** — always | Tier 2 stat #3 |
| 5 | `enrollments_monthly` | Nhập học tháng | count | monthly | KpiConfig (month) | KpiPlanMonth.actual_enrollments snapshot | **Comparable** — requires period = calendar month | MonthlyBreakdown |
| 6 | `enrollments_annual` | Nhập học năm | count | annual | KpiTarget | Annual resolver: Celery snapshot or live YTD query | **Comparable** — always | AnnualProgressCard |
| 7 | `sla_compliance_rate` | SLA tuân thủ | % | monthly | KpiConfig (plan-level) | Activity rate (% responded ≤ SLA hours) | **Comparable** — always | Tier 2 stat #1 |
| 8 | `consultation_effectiveness` | Hiệu quả tư vấn | % | monthly | KpiConfig (month) | Activity rate (consulted-final→won) | **Not comparable** — target funnel-derived, actual activity-based | Tier 2 stat #2 |

### Notes

- **"KpiConfig (month)"** = target stored per month in `kpi_config` table, synced from `KpiPlanMonth` via planning sync job.
- **"KpiConfig (plan-level)"** = target stored at plan level (`KpiPlan.sla_target`, `KpiPlan.response_time_target`), same value all 12 months.
- **"KpiTarget"** = annual target in `kpi_target` table with YTD tracking.
- **"Not comparable"** = backend sends `null` for target field; frontend never shows "Mục tiêu: X".

---

## B. Dashboard Mapping Table

### B1. KPICardsGrid — Tier 1 (4 primary cards)

| Slot | Component | Field rendered | Canonical code | Target shown? | Render rule |
|------|-----------|---------------|----------------|---------------|-------------|
| #1 | `KPICard` | `consultations_today / consultations_target` (today in range) **or** `consultations_avg_per_day` (past range) | `consultations_daily` | Yes — always when `todayInRange` | Subtitle switches: "Mục tiêu hàng ngày" vs period label. Badge "Chỉ tiêu tập thể phòng" if `is_unit_target`. |
| #2 | `KPICard` | `active_leads` | — (operational) | No | **Not a canonical KPI.** Realtime snapshot of non-final leads. Trend compares `active_leads_in_period` between current/previous period. |
| #3 | `KPICard` | `win_rate` | `win_rate` | Yes — when `canShowTarget("win_rate", range)` (calendar month only) | Uses `KPICard.target` + `actualValue` for green/orange coloring. |
| #4 | `KPICard` | `new_lead_conversion_rate` | `conversion_rate` | **Never** (not comparable) | Backend sends `new_lead_conversion_rate_target: null`. |

### B2. KPICardsGrid — Tier 2 (3 secondary stats)

| Slot | Component | Field rendered | Canonical code | Target shown? | Render rule |
|------|-----------|---------------|----------------|---------------|-------------|
| #1 | `StatItem` | `sla_compliance_rate` | `sla_compliance_rate` | Yes — via `canShowTarget("sla_compliance_rate", range)` (always true) | Green/orange based on `isTargetMet`. |
| #2 | `StatItem` | `consultation_effectiveness` | `consultation_effectiveness` | **Never** (not comparable) | Backend sends `consultation_effectiveness_target: null`. |
| #3 | `StatItem` | `avg_response_time` | `response_time_hours` | **No** (intentionally omitted) | See Decision D1 below. |

### B3. KPICardsGrid — Tier 3 (Daily Quality KPIs)

| Slot | Label | Field | Canonical code | Is KPI? |
|------|-------|-------|----------------|---------|
| #1 | TV hợp lệ | `verified_consultations_daily` | — | Operational insight |
| #2 | Tỷ lệ chất lượng | `quality_rate_daily` | — | Operational insight |
| #3 | Cam kết follow-up | `followup_commitment_rate` | — | Operational insight |
| #4 | Tiến triển D+7 | `progress_rate_d7` | — | Operational insight |
| #5 | Tụt hạng D+3 | `rollback_rate_d3` | — | Operational insight |

> Tier 3 metrics are all **operational insights** — no target, no comparison, no catalog entry. They reflect daily quality signals, not performance KPIs.

### B4. AnnualProgressCard

| Field | Canonical code | Target source | Actual source | Notes |
|-------|----------------|---------------|---------------|-------|
| `annual_target` | `enrollments_annual` | `kpi_resolver.resolve_annual_progress()` | `achieved_ytd` (Celery-synced or live query) | Shows progress bar, rolling monthly target, expected progress marker. |
| `resolution_kind` | — | — | — | If `inherited_estimate` → shows "(ước tính)" badge + muted styling. |
| `expected_progress_pct` | — | Backend seasonal-aware calculation | — | Vertical marker on progress bar. Frontend fallback to `DEFAULT_SEASONAL_WEIGHTS` if backend null. |

### B5. MonthlyBreakdownCard

| Column | Source field on `KpiPlanMonth` | Canonical code | Actual field | Comparison? |
|--------|------------------------------|----------------|-------------|-------------|
| CT Tuyển sinh | `enrollment_target` | `enrollments_monthly` | `actual_enrollments` → `enrollment_actual` | Yes — green/orange coloring |
| TV/ngày | `consultations_daily` | `consultations_daily` | `actual_consultations_avg` → `consultations_actual_avg` | Yes — met/near/behind status |
| Tổng TV tháng | `consultations_daily × working_days` | — (derived) | `consultations_monthly_total` (computed at API layer) | No |
| Conv% | `conversion_rate` | `conversion_rate` | — (target only, no actual in plan) | No |
| Win% | `win_rate` | `win_rate` | — (target only, no actual in plan) | No |

> MonthlyBreakdownCard data comes entirely from `KpiPlanMonth` records, NOT from live dashboard queries. Actuals are populated by a background sync job.

---

## C. Documented Decisions

### D1. `response_time_hours` target not shown on dashboard card

**Status**: Intentional.

The `response_time_hours` target (e.g. 2h) is the SLA threshold — it defines the window for `sla_compliance_rate`. Showing "Mục tiêu: 2.0h" on the response time card AND "Mục tiêu: 80%" on the SLA card would create confusion about which is the "real" target. The SLA compliance card already expresses the aggregate outcome of the response time target.

The catalog marks `response_time_hours` as `comparable=true` because the _data_ supports comparison. The frontend opts not to display the target visually — this is a UX decision, not a data constraint.

### D2. `conversion_rate` and `consultation_effectiveness` targets permanently null

**Status**: By design — different measurement grain.

Both metrics have targets derived from planning formulas (funnel math), but their dashboard actuals use different computation methods (cohort-based, activity-based). Showing a target would mislead officers into thinking the numbers are directly comparable.

### D3. `active_leads` is not a canonical KPI

**Status**: By design.

It's a real-time operational count with no target or comparison policy. The trend is period-scoped for relative context only.

### D4. MonthlyBreakdownCard uses planning snapshots, not live data

**Status**: By design.

`conversion_rate` and `win_rate` columns show planning targets only — no actual column. `enrollment_actual` and `consultations_actual_avg` are populated by a background sync job into `KpiPlanMonth`, not queried live. This means monthly actuals may lag until the sync job runs.

---

## D. Findings

### F1. No current mismatch between catalog and frontend rendering

All 8 canonical metrics are correctly:
- Registered in `METRIC_CATALOG` with accurate `ComparisonPolicy`
- Mirrored in `use-kpi-catalog.ts` `LOCAL_FALLBACK` (matches backend exactly)
- Backend correctly nullifies targets for non-comparable metrics (lines 898-899 in `officer_service.py`)
- Frontend `canShowTarget()` correctly gates on catalog comparison policy

### F2. P1 naming drift issues (from prior audit) are resolved

The old `project_kpi_naming_drift.md` findings are no longer active:
- Canonical catalog exists and is the single source of truth
- `kpi_resolver.py` consolidates target resolution (no duplicated logic)
- Frontend `use-kpi-catalog` fetches from `/api/meta/kpi-catalog` (with local fallback)

### F3. MonthlyBreakdown `conversion_rate` and `win_rate` show target-only columns (no actuals)

The `KpiPlanMonth` model has `actual_conversion_rate` and `actual_win_rate` fields, but `get_officer_kpi_plan()` does not include them in the response. The MonthlyBreakdownCard displays planning targets without corresponding actuals for these two metrics.

**Impact**: Low — officers see directional targets but cannot compare actual vs target for these rates on a monthly basis. This aligns with Decision D2 (different grain), but may confuse users who expect the table to be fully filled.

---

## E. Recommendations

1. **Populate `actual_win_rate` and `actual_conversion_rate` in MonthlyBreakdown** (Priority: Medium)
   Add these actuals from `KpiPlanMonth` to the `get_officer_kpi_plan()` response. Even if the grain differs from dashboard actuals, having _any_ actual alongside the target in the table gives officers monthly feedback. Currently these columns show "—" forever.

2. **Add `response_time_hours` target display as opt-in** (Priority: Low)
   Consider showing "SLA: 2.0h" as subtle context text on the response time StatItem. This would make the connection between response_time and SLA explicit without creating a separate "Mục tiêu" line.

3. **Document Tier 3 quality KPIs formally** (Priority: Low)
   The 5 daily quality metrics (`verified_consultations_daily`, `quality_rate_daily`, `followup_commitment_rate`, `progress_rate_d7`, `rollback_rate_d3`) have no catalog entries. If they graduate to full KPIs with targets, they should be added to `METRIC_CATALOG`.

4. **Keep `LOCAL_FALLBACK` in sync via CI** (Priority: Medium)
   The `use-kpi-catalog.ts` local fallback mirrors the backend catalog manually. A drift test (comparing `/api/meta/kpi-catalog` response to `LOCAL_FALLBACK`) would catch accidental divergence. The comment says "Exported for drift testing only" but no test exists yet.

---

## F. Quick Reference: Source Files

| Layer | File | Responsibility |
|-------|------|---------------|
| Catalog | `services/kpi_catalog.py` | 8 canonical metrics, defaults, comparison policies |
| Resolver | `services/kpi_resolver.py` | Target resolution (monthly + annual) with inheritance |
| Service | `services/kpi_service.py` | Target CRUD, YTD sync, progress calculation |
| Dashboard | `services/officer_service.py` | `get_enhanced_dashboard_stats()` — builds KPI response |
| Schema | `schemas/officer.py` | `KPIStats`, `AnnualProgressInfo`, `OfficerKpiPlanResponse` |
| FE Hook | `hooks/useDashboardStats.ts` | React Query fetch + types |
| FE Catalog | `lib/hooks/use-kpi-catalog.ts` | `canShowTarget()`, display name resolution |
| FE Cards | `components/officer/dashboard/KPICardsGrid.tsx` | Tier 1/2/3 rendering |
| FE Annual | `components/officer/dashboard/AnnualProgressCard.tsx` | Annual progress bar + status |
| FE Monthly | `components/officer/dashboard/MonthlyBreakdownCard.tsx` | 12-month plan table |
