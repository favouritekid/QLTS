# KPI Coverage Audit & Implementation Plan — Officer Dashboard

> **Ngày audit**: 2026-03-08
> **Trạng thái**: Đã chốt giải pháp — sẵn sàng implement
> **Scope**: Toàn bộ metrics trên Officer Dashboard vs backend KPI config system

---

## Tổng quan hiện trạng

- **27 metrics** khảo sát trên dashboard
- **7 COVERED** — có target + đánh giá + trend + recommendation
- **10 PARTIAL** — có tracking nhưng thiếu target configurable hoặc thiếu recommendation
- **5 MISSING** — chỉ hiện số, không đánh giá
- **5 N/A** — metrics bản chất không cần target (rank change, new lead detection, v.v.)

---

## Quyết định đã chốt (9 điểm)

| # | Vấn đề | Giải pháp đã chốt |
|---|--------|-------------------|
| 1 | `win_rate` không có KPI target | Thêm vào DEFAULT_KPIS + recommendation rules theo tỉ lệ target |
| 2 | SLA/Effectiveness có target nhưng recommendation không dùng | Thêm rules đọc target động qua `get_kpi_target()` |
| 3 | Conversion/Response threshold hardcoded | Quy đổi theo target: `0.7×`, `1.0×`, `1.5×` |
| 4 | Funnel thresholds hardcoded | Đưa vào KPI config, dùng `config` param có sẵn |
| 5 | `active_leads` thiếu đánh giá | Đánh giá qua utilization (đã có), KHÔNG thêm KPI riêng |
| 6 | Chart thiếu reference lines | Rolling baseline cho leads, pace từ enrollments, tỉ lệ cho loss |
| 7 | Early Exit Count là số tuyệt đối | Dùng `early_exit_rate = count / leads_in_stage`, threshold vào config |
| 8 | Workload/Priority thresholds hardcoded | Cho phép config override |
| 9 | `response_time_critical` | Chốt `1.5 × target` (= 3h với default 2h) |

---

## Implementation Plan

### Phase 1: KPI Targets & Recommendations (P0)

#### Task 1.1: Thêm `win_rate` vào KPI system

**Files sửa:**
- `Backend_FastAPI/app/services/kpi_service.py` — thêm vào DEFAULT_KPIS
- `Backend_FastAPI/app/services/recommendation_engine.py` — thêm rules
- `Backend_FastAPI/app/services/officer_service.py` — truyền win_rate target vào KPIs response

**Chi tiết:**

```python
# kpi_service.py — DEFAULT_KPIS
"win_rate": 30,  # percentage, period_type="monthly"
```

```python
# recommendation_engine.py — Thêm Rule 8: Win Rate
# Lấy target động:
win_rate_target = await kpi_service.get_kpi_target(db, "win_rate", officer_id, user.unit_id, "monthly")
win_rate = kpis.get("win_rate", 0)

if win_rate_target > 0:
    if win_rate < win_rate_target * 0.5:       # < 15% (với target 30%)
        → CRITICAL: "Tỉ lệ chốt đơn rất thấp"
    elif win_rate < win_rate_target * 0.7:     # < 21%
        → HIGH: "Cần cải thiện tỉ lệ chốt đơn"
    elif win_rate >= win_rate_target * 1.2:    # ≥ 36%
        → LOW (celebrate): "Tỉ lệ chốt đơn xuất sắc"
```

**Migration:** Thêm seed record `kpi_code='win_rate', target_value=30, period_type='monthly'` vào bảng `kpi_config`.

---

#### Task 1.2: Thêm recommendation rules cho SLA + Effectiveness

**File sửa:** `Backend_FastAPI/app/services/recommendation_engine.py`

**Chi tiết:**

```python
# Rule 9: SLA Compliance
sla_target = await kpi_service.get_kpi_target(db, "sla_compliance_rate", officer_id, user.unit_id, "monthly")
sla_rate = kpis.get("sla_compliance_rate", 0)

if sla_target > 0:
    if sla_rate < sla_target * 0.5:            # < 40% (với target 80%)
        → CRITICAL: "Tuân thủ SLA rất thấp"
    elif sla_rate < sla_target * 0.7:          # < 56%
        → HIGH: "Cần cải thiện tuân thủ SLA"

# Rule 10: Consultation Effectiveness
eff_target = await kpi_service.get_kpi_target(db, "consultation_effectiveness", officer_id, user.unit_id, "monthly")
effectiveness = kpis.get("consultation_effectiveness", 0)

if eff_target > 0:
    if effectiveness < eff_target * 0.5:       # < 25% (với target 50%)
        → CRITICAL: "Hiệu quả tư vấn rất thấp"
    elif effectiveness < eff_target * 0.7:     # < 35%
        → HIGH: "Cần cải thiện hiệu quả tư vấn"
```

**Lưu ý:** `generate_recommendations()` hiện nhận `kpis: Dict` nhưng không nhận `db` session riêng cho KPI lookup. Cần truyền `db` + `officer_id` + `unit_id` vào hoặc pre-fetch tất cả targets trước khi gọi rules.

---

#### Task 1.3: Conversion/Response threshold quy đổi theo target

**File sửa:** `Backend_FastAPI/app/services/recommendation_engine.py`

**Hiện tại (hardcoded):**
```python
THRESHOLDS = {
    "conversion_rate_low": 10,       # Cứng
    "conversion_rate_good": 20,      # Cứng
    "response_time_critical": 4,     # Cứng
    "response_time_warning": 2,      # Cứng
}
```

**Đổi thành (dynamic):**
```python
# Trong generate_recommendations(), TRƯỚC khi check rules:
conversion_target = await kpi_service.get_kpi_target(db, "conversion_rate", officer_id, user.unit_id, "monthly")
response_target = await kpi_service.get_kpi_target(db, "response_time_hours", officer_id, user.unit_id, "daily")

# Rule 2: Conversion
conversion_low = conversion_target * 0.7      # 10.5% với target 15%
conversion_good = conversion_target * 1.2     # 18% với target 15%

# Rule 3: Response time
response_warning = response_target             # 2h
response_critical = response_target * 1.5      # 3h (đã chốt)
```

**Breaking change:** `THRESHOLDS` dict bỏ 4 keys hardcoded. Các rule dùng biến local tính từ target.

---

### Phase 2: Funnel Config (P1)

#### Task 2.1: Funnel thresholds vào KPI config

**Files sửa:**
- `Backend_FastAPI/app/services/kpi_service.py` — thêm DEFAULT_KPIS
- `Backend_FastAPI/app/services/officer_service.py` — đọc config trước khi gọi `generate_funnel_suggestions()`

**KPI codes mới:**

| kpi_code | period_type | Default | Mô tả |
|----------|------------|---------|--------|
| `funnel_bottleneck_threshold` | monthly | 50 | % conversion dưới ngưỡng này = bottleneck |
| `funnel_slow_stage_days` | monthly | 5 | Số ngày trung bình trên ngưỡng = slow stage |
| `funnel_high_loss_vnd` | monthly | 100000000 | Lost revenue trên ngưỡng = cảnh báo (VND) |
| `funnel_loss_reason_pct` | monthly | 20 | % loss reason trên ngưỡng = suggestion |
| `funnel_early_exit_rate` | monthly | 15 | % early exit rate trên ngưỡng = cảnh báo |

**Chi tiết wiring:**

```python
# officer_service.py — trước khi gọi generate_funnel_suggestions()
funnel_config = {
    "bottleneck_threshold": await kpi_service.get_kpi_target(db, "funnel_bottleneck_threshold", ...),
    "slow_stage_threshold_days": await kpi_service.get_kpi_target(db, "funnel_slow_stage_days", ...),
    "high_loss_threshold_vnd": await kpi_service.get_kpi_target(db, "funnel_high_loss_vnd", ...),
    "loss_reason_threshold_pct": await kpi_service.get_kpi_target(db, "funnel_loss_reason_pct", ...),
}
funnel_suggestions = generate_funnel_suggestions(sales_funnel, aggregated_loss, config=funnel_config)
```

`generate_funnel_suggestions()` đã có `config` param với `**(config or {})` merge — không cần đổi logic bên trong.

---

#### Task 2.2: Early Exit dùng rate thay vì absolute count

**File sửa:** `Backend_FastAPI/app/services/officer_service.py` — trong `generate_funnel_suggestions()`

**Thêm rule mới:**

```python
# Rule 5: High early exit rate
for stage in core_stages:
    if stage["lead_count"] > 0:
        exit_rate = (stage.get("early_exit_count", 0) / stage["lead_count"]) * 100
        if exit_rate > cfg.get("early_exit_rate_threshold", 15):
            suggestions.append({
                "type": "high_loss",
                "title": f"Tỉ lệ rời bỏ cao tại {stage['stage_name']}",
                "description": f"{exit_rate:.0f}% leads rời bỏ tại stage này...",
            })
```

---

### Phase 3: Chart Reference Lines & Workload Config (P2)

#### Task 3.1: Performance Chart — reference lines cho Enrolled và Leads Assigned

**File sửa:** `frontend/src/components/officer/PerformanceChart.tsx`

**Chi tiết:**

| Metric | Reference line | Nguồn data | Công thức |
|--------|---------------|------------|-----------|
| Nhập học | Monthly pace line | `enrollments_monthly` target / 30 | `enrollments_monthly_target / 30` = daily pace |
| Leads được giao | Rolling baseline | Tính từ data hiện có | `avg(leads_assigned)` trong kỳ (đã có `avgConsultations` pattern) |

**Backend:** Cần truyền `enrollments_monthly` target xuống frontend. Thêm vào KPIs response:
```python
"enrollments_monthly_target": await kpi_service.get_kpi_target(db, "enrollments_monthly", ...)
```

**Frontend:** Thêm 2 `<ReferenceLine>` mới trên chart.

---

#### Task 3.2: Workload/Priority thresholds configurable

**KPI codes mới:**

| kpi_code | period_type | Default | Dùng tại |
|----------|------------|---------|----------|
| `workload_warning_pct` | daily | 70 | `WorkloadCard.tsx` — ngưỡng amber |
| `workload_critical_pct` | daily | 90 | `WorkloadCard.tsx` — ngưỡng red |
| `hot_lead_score_threshold` | daily | 70 | `officer_service.py` — priority actions |
| `overdue_days_threshold` | daily | 3 | `officer_service.py` — priority actions |
| `urgency_score_threshold` | daily | 70 | `officer_service.py` — priority actions |

**Approach:** Backend pre-fetch tất cả thresholds, truyền qua API response hoặc riêng endpoint `/api/officer/config`.

---

## File Change Summary

| Phase | File | Thay đổi |
|-------|------|---------|
| **1** | `kpi_service.py` | Thêm `win_rate: 30` vào DEFAULT_KPIS |
| **1** | `recommendation_engine.py` | Thêm Rules 8-10 (win_rate, SLA, effectiveness). Đổi Rules 2-3 từ hardcode sang target-relative |
| **1** | `officer_service.py` | Truyền `win_rate_target` vào KPIs response |
| **1** | Alembic migration | Seed `win_rate` global config |
| **2** | `kpi_service.py` | Thêm 5 funnel KPI codes vào DEFAULT_KPIS |
| **2** | `officer_service.py` | Đọc funnel config trước khi gọi `generate_funnel_suggestions()`. Thêm early_exit_rate rule |
| **2** | Alembic migration | Seed funnel config records |
| **3** | `kpi_service.py` | Thêm workload/priority KPI codes |
| **3** | `officer_service.py` | `_calculate_priority_actions()` đọc thresholds từ config |
| **3** | `PerformanceChart.tsx` | Thêm 2 reference lines (enrolled pace, leads baseline) |
| **3** | `WorkloadCard.tsx` | Đọc warning/critical thresholds từ props |
| **3** | `useDashboardStats.ts` | Thêm `enrollments_monthly_target`, workload thresholds vào types |

---

## Không cần implement (đã fix hoặc quyết định không làm)

| Hạng mục | Lý do |
|----------|-------|
| `active_leads` thêm KPI riêng | Đánh giá qua utilization (WorkloadCard), không cần target tuyệt đối |
| `consultations_today` khi xem kỳ quá khứ | Đã fix: swap sang "TB tư vấn/ngày" (`KPICardsGrid.tsx`) |
| Chart tách enrolled/lost | Đã fix: 2 đường riêng (`PerformanceChart.tsx`) |
| `active_leads` realtime vs period | Đã fix: tách thành 2 fields (`officer_repository.py`) |
| Aggregated dashboard bugs (#12-#22) | Đã fix trong `officer_service.py` |
| Pydantic schema sync | Đã fix trong `schemas/officer.py` |

---

## Thứ tự implement khuyến nghị

```
Phase 1 (P0 — cốt lõi):
  Task 1.3  Conversion/Response target-relative     ← nhỏ nhất, refactor THRESHOLDS
  Task 1.2  SLA + Effectiveness rules               ← cùng file, cùng pattern
  Task 1.1  Win rate KPI + rules + migration         ← cần migration

Phase 2 (P1 — funnel):
  Task 2.1  Funnel config KPI codes + wiring         ← dùng existing config param
  Task 2.2  Early exit rate rule                     ← thêm 1 rule trong cùng function

Phase 3 (P2 — chart & workload):
  Task 3.1  Chart reference lines                    ← frontend only + 1 backend field
  Task 3.2  Workload/Priority config                 ← nhiều files, ít risk
```
