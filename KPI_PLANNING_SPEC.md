# KPI Planning Engine — Reverse-Funnel Spec

> **Trạng thái**: Đã chốt — sẵn sàng implement
> **Input**: 1 con số (annual enrollment target) → Output: 8 KPI × 12 tháng

---

## 1. Tổng quan mô hình

```
Admin nhập: enrollments_annual = 300
                    ↓
         Seasonal Weights (12 tháng)
                    ↓
         M_t = enrollments_monthly per tháng
                    ↓
    ┌───────────────┼───────────────┐
    ↓               ↓               ↓
 DERIVED         DERIVED        GUARDRAIL
 (từ M_t +       (từ M_t +      (policy,
  historical)     forecast)      không đổi
                                 theo volume)
```

### 3 lớp KPI

| Lớp | KPI codes | Logic |
|-----|-----------|-------|
| **Anchor** | `enrollments_annual`, `enrollments_monthly` | Input + phân bổ seasonal |
| **Derived** | `consultations_daily`, `conversion_rate`, `win_rate`, `consultation_effectiveness` | Tính ngược từ M_t + k_t/L_t/C_t |
| **Guardrail** | `sla_compliance_rate`, `response_time_hours` | Chính sách, admin set trực tiếp |

### Công thức quy đổi 8 KPI cho tháng t

```
enrollments_annual      = 300                           (input)
enrollments_monthly_t   = round(300 × weight_t)         (seasonal)
consultations_daily_t   = ceil(M_t × k_t / WD_t)        (reverse-funnel)
conversion_rate_t       = (M_t / L_t) × 100             (reverse-funnel)
win_rate_t              = (M_t / C_t) × 100              (reverse-funnel)
consultation_effectiveness_t = max(floor, M_t / consulted_closed_t × 100)
sla_compliance_rate_t   = guardrail (e.g. 85%)           (policy)
response_time_hours_t   = guardrail (e.g. 2h)            (policy)
```

---

## 2. Quyết định đã chốt

### 2.1 Scope & Inheritance

```
Officer KpiPlanMonth  →  Unit KpiPlanMonth  →  Global KpiConfig  →  DEFAULT_KPIS
   (nếu có)                (mặc định)           (fallback)          (hardcode)
```

- **Unit plan** = mặc định. Manager tạo plan cho unit, áp dụng tất cả officers.
- **Officer override** = tùy chọn per tháng. Khi officer cần target cá nhân hóa.
- Sync job: lấy effective target theo inheritance chain trên.

### 2.2 Mặc định năm đầu (chưa có data lịch sử)

| Biến | Default | Ý nghĩa |
|------|---------|---------|
| `k_t` | 7 | 7 tư vấn để có 1 nhập học |
| `L_t` | `6 × M_t` | Conversion target mặc định ~16.7% |
| `C_t` | `3 × M_t` | Win rate target mặc định ~33.3% |
| `consultation_effectiveness` floor | 50% | Khi chưa đủ data |

### 2.3 Auto-calibration (từ tháng thứ 4+)

- **Nguồn**: Rolling 3 tháng gần nhất (EMA — Exponential Moving Average)
- **Damping**: Giới hạn thay đổi ±15%/tháng so với tháng trước
- **Không áp dụng cho**: Ô đã override thủ công

```python
# EMA calculation
k_new = 0.5 * k_actual_this_month + 0.3 * k_prev + 0.2 * k_prev_prev
# Damping
k_clamped = clamp(k_new, k_current * 0.85, k_current * 1.15)
```

### 2.4 Working days

- **Tự động**: Thứ 2-6, loại trừ ngày lễ VN từ bảng `holiday_calendar`
- **Admin override**: Có thể sửa WD_t per tháng (bù ngày làm đặc biệt)
- **Audit**: Lưu `overridden_by`, `overridden_at` khi sửa

### 2.5 Override KPI derived

- **Cho phép**: Admin/Manager override bất kỳ KPI derived nào per tháng
- **Bắt buộc**: `override_reason`, `overridden_by`, `overridden_at`, `is_manual_override`
- **Sync protection**: Job monthly KHÔNG ghi đè ô `is_manual_override = True`
- **Reset**: Admin có thể "reset về auto" → xóa flag override, job tính lại

---

## 3. Data Model

### 3.1 Bảng mới: `kpi_plan`

```sql
CREATE TABLE kpi_plan (
    id              SERIAL PRIMARY KEY,
    unit_id         INTEGER REFERENCES organization_unit(id) ON DELETE CASCADE,
    officer_id      INTEGER REFERENCES "user"(id) ON DELETE CASCADE,  -- NULL = unit plan
    fiscal_year     INTEGER NOT NULL,

    -- Anchor input
    annual_enrollment_target  INTEGER NOT NULL,  -- 300

    -- Guardrails
    sla_target              INTEGER NOT NULL DEFAULT 85,    -- %
    response_time_target    INTEGER NOT NULL DEFAULT 2,     -- hours

    -- Seasonal weights (JSON array of 12 floats, sum = 1.0)
    -- NULL = dùng DEFAULT_ENROLLMENT_WEIGHTS
    seasonal_weights        JSONB,

    -- Meta
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      INTEGER REFERENCES "user"(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Mỗi scope chỉ có 1 plan active per year
    UNIQUE (unit_id, officer_id, fiscal_year) WHERE is_active = TRUE
);

COMMENT ON TABLE kpi_plan IS 'KPI planning — reverse-funnel từ annual target ra 8 KPI × 12 tháng';
```

### 3.2 Bảng mới: `kpi_plan_month`

```sql
CREATE TABLE kpi_plan_month (
    id              SERIAL PRIMARY KEY,
    plan_id         INTEGER NOT NULL REFERENCES kpi_plan(id) ON DELETE CASCADE,
    month           INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),

    -- Distributable inputs
    enrollment_target       INTEGER NOT NULL,        -- M_t: 46
    working_days            INTEGER NOT NULL,        -- WD_t: 26
    weight                  FLOAT NOT NULL,          -- 0.153

    -- Historical factors (computed or manual)
    k_factor                FLOAT NOT NULL DEFAULT 7,    -- k_t
    lead_forecast           INTEGER,                     -- L_t (NULL = 6×M_t)
    close_forecast          INTEGER,                     -- C_t (NULL = 3×M_t)

    -- Derived KPI targets (auto-calculated, overridable)
    consultations_daily     INTEGER NOT NULL,
    conversion_rate         FLOAT NOT NULL,           -- %
    win_rate                FLOAT NOT NULL,            -- %
    consultation_effectiveness FLOAT NOT NULL,         -- %

    -- Override tracking
    is_manual_override      BOOLEAN NOT NULL DEFAULT FALSE,
    override_reason         TEXT,
    overridden_by           INTEGER REFERENCES "user"(id),
    overridden_at           TIMESTAMPTZ,

    -- Actuals (filled by sync job at month end)
    actual_enrollments      INTEGER,
    actual_consultations_avg FLOAT,
    actual_conversion_rate  FLOAT,
    actual_win_rate         FLOAT,

    UNIQUE (plan_id, month)
);

COMMENT ON TABLE kpi_plan_month IS 'Monthly breakdown of KPI plan with derived targets and actuals';
```

### 3.3 Bảng mới: `holiday_calendar`

```sql
CREATE TABLE holiday_calendar (
    id              SERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,
    name            VARCHAR(200) NOT NULL,       -- "Tết Nguyên Đán"
    year            INTEGER NOT NULL,
    is_recurring    BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE = lặp hàng năm (1/1, 30/4, ...)
    created_by      INTEGER REFERENCES "user"(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed VN holidays
INSERT INTO holiday_calendar (date, name, year, is_recurring) VALUES
('2026-01-01', 'Tết Dương lịch', 2026, TRUE),
('2026-01-28', 'Tết Nguyên Đán (28 Tết)', 2026, FALSE),
('2026-01-29', 'Tết Nguyên Đán (29 Tết)', 2026, FALSE),
('2026-01-30', 'Tết Nguyên Đán (30 Tết)', 2026, FALSE),
('2026-01-31', 'Tết Nguyên Đán (Mùng 1)', 2026, FALSE),
('2026-02-01', 'Tết Nguyên Đán (Mùng 2)', 2026, FALSE),
('2026-02-02', 'Tết Nguyên Đán (Mùng 3)', 2026, FALSE),
('2026-04-30', 'Ngày Giải phóng', 2026, TRUE),
('2026-05-01', 'Ngày Quốc tế Lao động', 2026, TRUE),
('2026-09-02', 'Ngày Quốc khánh', 2026, TRUE),
('2026-09-03', 'Nghỉ bù Quốc khánh', 2026, FALSE),
('2026-04-07', 'Giỗ Tổ Hùng Vương', 2026, FALSE);
```

---

## 4. Service Layer

### 4.1 `kpi_planning_service.py` — Engine chính

```python
# Các hàm chính:

async def create_plan(db, unit_id, fiscal_year, annual_target,
                      guardrails, seasonal_weights=None, created_by=None):
    """
    Tạo plan mới → auto-generate 12 KpiPlanMonth records.
    Nếu seasonal_weights = None → dùng DEFAULT_ENROLLMENT_WEIGHTS.
    """

async def generate_monthly_kpis(db, plan_id):
    """
    Từ plan → tính 12 bộ KPI.
    Với mỗi tháng t:
      1. M_t = round(annual × weight_t)
      2. WD_t = count_working_days(year, month) — từ holiday_calendar
      3. k_t = get_k_factor(officer_id, month) hoặc default 7
      4. L_t = lead_forecast hoặc 6 × M_t
      5. C_t = close_forecast hoặc 3 × M_t
      6. Tính 4 derived KPIs
    Skip ô is_manual_override = True.
    """

async def recalibrate_factors(db, plan_id, up_to_month):
    """
    Auto-calibration: dùng actual data 3 tháng gần nhất → update k_t, L_t, C_t.
    Damping: ±15% max change.
    Chỉ update tháng future, không sửa tháng đã qua.
    """

async def override_month_kpi(db, plan_month_id, overrides, reason, user_id):
    """
    Admin override 1+ KPI cho tháng cụ thể.
    Set is_manual_override = True, lưu reason + who + when.
    """

async def reset_month_override(db, plan_month_id, user_id):
    """
    Reset về auto → clear override flags → recalculate.
    """

async def sync_plan_to_kpi_config(db, plan_id, month):
    """
    Lấy effective target cho tháng (Officer plan > Unit plan > ...).
    Upsert vào KpiConfig records.
    Dashboard đọc từ KpiConfig như bình thường.
    """

async def fill_month_actuals(db, plan_id, month):
    """
    Cuối tháng: điền actual_enrollments, actual_conversion_rate, v.v.
    Từ repository queries.
    """
```

### 4.2 `calendar_service.py` — Working days

```python
async def count_working_days(db, year: int, month: int) -> int:
    """
    Đếm ngày T2-T6 trong tháng, trừ ngày lễ từ holiday_calendar.
    """

async def get_working_days_override(db, plan_month_id) -> int | None:
    """
    Nếu admin override WD → trả về override value.
    """
```

### 4.3 `historical_metrics_service.py` — Tính k_t/L_t/C_t từ data

```python
async def get_historical_k_factor(db, officer_id, unit_id, months_back=3):
    """
    k_t = total_consultations / total_enrollments trong N tháng gần nhất.
    Dùng EMA: 0.5 × month[-1] + 0.3 × month[-2] + 0.2 × month[-3]
    """

async def get_historical_lead_count(db, officer_id, unit_id, target_month):
    """
    L_t = avg leads mới/tháng trong 3 tháng cùng kỳ hoặc 3 tháng gần nhất.
    """

async def get_historical_close_count(db, officer_id, unit_id, target_month):
    """
    C_t = avg leads đóng/tháng (won + lost).
    """
```

---

## 5. Celery Jobs

### Job 1: `sync_kpi_plan_monthly` — Ngày 1 mỗi tháng

```python
@celery_app.task
def sync_kpi_plan_monthly():
    """
    1. Tìm tất cả KpiPlan active cho fiscal_year hiện tại
    2. Với mỗi plan:
       a. fill_month_actuals(prev_month) — điền actual tháng trước
       b. recalibrate_factors(current_month) — hiệu chỉnh k/L/C nếu có data
       c. generate_monthly_kpis() — regenerate future months (skip overrides)
       d. sync_plan_to_kpi_config(current_month) — push targets vào KpiConfig
    """
```

### Job 2: `sync_kpi_plan_actuals_daily` — Hàng ngày (bổ sung job YTD hiện có)

```python
@celery_app.task
def sync_kpi_plan_actuals_daily():
    """
    Update actual_enrollments MTD cho tháng hiện tại.
    Cho phép dashboard hiện progress vs monthly target real-time.
    """
```

---

## 6. API Endpoints

### Planning CRUD (`/api/admin/kpi-planning`)

| Method | Endpoint | Mô tả | Auth |
|--------|----------|-------|------|
| `POST` | `/plans` | Tạo plan mới (annual target + weights + guardrails) | Admin |
| `GET` | `/plans` | List plans (filter by unit, year) | Admin/Manager |
| `GET` | `/plans/{id}` | Chi tiết plan + 12 months | Admin/Manager |
| `PUT` | `/plans/{id}` | Sửa annual target / weights / guardrails → regenerate | Admin |
| `DELETE` | `/plans/{id}` | Soft delete plan | Admin |
| `POST` | `/plans/{id}/regenerate` | Force regenerate derived KPIs (skip overrides) | Admin |
| `GET` | `/plans/{id}/preview` | Preview KPIs trước khi save (dry-run) | Admin/Manager |

### Monthly Override (`/api/admin/kpi-planning/months`)

| Method | Endpoint | Mô tả | Auth |
|--------|----------|-------|------|
| `PUT` | `/months/{id}/override` | Override KPIs cho 1 tháng (+ reason) | Admin/Manager |
| `POST` | `/months/{id}/reset` | Reset override → recalculate | Admin/Manager |
| `PUT` | `/months/{id}/working-days` | Override working days | Admin |

### Holiday Calendar (`/api/admin/calendar`)

| Method | Endpoint | Mô tả | Auth |
|--------|----------|-------|------|
| `GET` | `/holidays` | List holidays (filter by year) | Admin/Manager |
| `POST` | `/holidays` | Thêm ngày lễ | Admin |
| `DELETE` | `/holidays/{id}` | Xóa ngày lễ | Admin |

---

## 7. Integration với hệ thống hiện có

### Flow tổng thể

```
┌─────────────────────────────────────────────────────────────┐
│  ADMIN UI: KPI Planning                                     │
│  Input: annual_target=300, weights, guardrails               │
└───────────────────┬─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│  KpiPlan + KpiPlanMonth (12 records)                        │
│  Derived: consultations_daily, conversion_rate, win_rate... │
└───────────────────┬─────────────────────────────────────────┘
                    ↓  Celery sync (ngày 1 mỗi tháng)
┌─────────────────────────────────────────────────────────────┐
│  KpiConfig (existing)                                       │
│  Upsert: kpi_code + target_value + unit_id/officer_id       │
│  ← Dashboard reads from here via get_kpi_target()           │
└───────────────────┬─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│  Officer Dashboard                                          │
│  - KPI cards dùng target từ KpiConfig                       │
│  - Recommendation engine dùng target từ KpiConfig           │
│  - Annual progress dùng KpiTarget (existing)                │
│  ← Không cần sửa logic dashboard                            │
└─────────────────────────────────────────────────────────────┘
```

### Backward compatible

| Component | Thay đổi? | Lý do |
|-----------|-----------|-------|
| `get_kpi_target()` | ❌ Không đổi | Vẫn đọc từ KpiConfig |
| `recommendation_engine.py` | ❌ Không đổi | Vẫn đọc KPIs từ dashboard stats |
| `officer_service.py` | ❌ Không đổi | Vẫn gọi `get_kpi_target()` |
| Dashboard frontend | ❌ Không đổi | Vẫn hiện target từ API |
| `KpiConfig` table | ✅ Có thêm records | Sync job upsert targets hàng tháng |
| `KpiTarget` table | ✅ Có thêm records | Plan tạo annual target tương ứng |

---

## 8. Seasonal Weights mặc định

```python
DEFAULT_ENROLLMENT_WEIGHTS = {
    1:  0.040,   # T1:  12/300 — sau Tết
    2:  0.033,   # T2:  10/300 — Tết
    3:  0.050,   # T3:  15/300 — bắt đầu tăng
    4:  0.060,   # T4:  18/300
    5:  0.073,   # T5:  22/300 — trước cao điểm
    6:  0.127,   # T6:  38/300 — CAO ĐIỂM
    7:  0.153,   # T7:  46/300 — CAO ĐIỂM ĐỈNH
    8:  0.160,   # T8:  48/300 — CAO ĐIỂM ĐỈNH
    9:  0.133,   # T9:  40/300 — CAO ĐIỂM
    10: 0.093,   # T10: 28/300 — cao điểm cuối
    11: 0.043,   # T11: 13/300 — giảm
    12: 0.033,   # T12: 10/300 — thấp nhất
}
# Sum = 0.998 → round adjustment ở tháng cuối
```

### Ví dụ output cho 300 nhập học/năm

| Tháng | M_t | WD_t | k_t | consultations_daily | conversion_rate | win_rate |
|-------|-----|------|-----|--------------------:|----------------:|---------:|
| T1 | 12 | 21 | 7 | 4 | 16.7% | 33.3% |
| T2 | 10 | 18 | 7 | 4 | 16.7% | 33.3% |
| T3 | 15 | 23 | 7 | 5 | 16.7% | 33.3% |
| T4 | 18 | 22 | 7 | 6 | 16.7% | 33.3% |
| T5 | 22 | 21 | 7 | 8 | 16.7% | 33.3% |
| T6 | 38 | 22 | 7 | 13 | 16.7% | 33.3% |
| **T7** | **46** | **26** | **7** | **13** | **16.7%** | **33.3%** |
| **T8** | **48** | **23** | **7** | **15** | **16.7%** | **33.3%** |
| T9 | 40 | 22 | 7 | 13 | 16.7% | 33.3% |
| T10 | 28 | 22 | 7 | 9 | 16.7% | 33.3% |
| T11 | 13 | 21 | 7 | 5 | 16.7% | 33.3% |
| T12 | 10 | 23 | 7 | 4 | 16.7% | 33.3% |

> Năm đầu conversion_rate/win_rate đồng nhất vì dùng default L_t/C_t. Từ tháng 4+ sẽ tự phân hóa theo data thực.

---

## 9. Implementation Phases

### Phase A: Core Engine (MVP)

| Task | Files | Effort |
|------|-------|--------|
| A1. Migration: tạo 3 bảng (kpi_plan, kpi_plan_month, holiday_calendar) + seed holidays | `alembic/versions/` | S |
| A2. Models: KpiPlan, KpiPlanMonth, HolidayCalendar | `app/models/config.py` | S |
| A3. Calendar service: count_working_days | `app/services/calendar_service.py` | S |
| A4. Planning service: create_plan, generate_monthly_kpis | `app/services/kpi_planning_service.py` | M |
| A5. Planning repository | `app/repositories/kpi_planning_repository.py` | M |
| A6. API endpoints: CRUD plans + preview | `app/routers/kpi_planning.py` | M |
| A7. Sync job: sync_plan_to_kpi_config | `app/tasks/cache_tasks.py` | S |

### Phase B: Override & Calibration

| Task | Files | Effort |
|------|-------|--------|
| B1. Override API: PUT /months/{id}/override, POST /months/{id}/reset | `app/routers/kpi_planning.py` | S |
| B2. Historical metrics service: k_t, L_t, C_t from actual data | `app/services/historical_metrics_service.py` | M |
| B3. Auto-calibration: recalibrate_factors with EMA + ±15% damping | `app/services/kpi_planning_service.py` | M |
| B4. Month-end actuals: fill_month_actuals | `app/services/kpi_planning_service.py` | S |
| B5. Enhanced sync job: actuals + recalibrate + sync | `app/tasks/cache_tasks.py` | S |

### Phase C: Admin UI

| Task | Files | Effort |
|------|-------|--------|
| C1. Plan creation form (annual target + weights slider + guardrails) | `frontend/src/app/(dashboard)/admin/kpi-planning/` | L |
| C2. Monthly grid view (12 months × 8 KPIs, editable overrides) | `frontend/src/components/admin/kpi-planning/` | L |
| C3. Preview mode (dry-run trước khi save) | Frontend | M |
| C4. Holiday calendar management UI | Frontend | M |
| C5. Plan vs Actual comparison report | Frontend | M |

---

## 10. Ví dụ End-to-End

```
1. Admin vào "KPI Planning" → chọn Unit "Phòng Tuyển sinh HN"
2. Nhập: Năm 2026, Chỉ tiêu: 300 nhập học
3. Hệ thống auto-fill 12 tháng theo seasonal weights
4. Admin xem preview → thấy T7: 46 nhập học, 13 tư vấn/ngày
5. Admin override T8: consultations_daily = 16 (lý do: "Chiến dịch tư vấn đặc biệt")
6. Admin lưu plan → hệ thống tạo KpiPlan + 12 KpiPlanMonth
7. Celery sync ngày 1/T1: push KPI T1 vào KpiConfig
   → Officer dashboard tự động hiện target mới
8. Cuối T3: Celery fill actuals, recalibrate k_t/L_t/C_t cho T4+
   → T4 targets tự adjust theo performance thực tế
9. T8: sync job thấy is_manual_override=True → giữ nguyên 16, không đè
```
