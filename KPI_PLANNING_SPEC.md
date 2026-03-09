# KPI Planning Engine — Reverse-Funnel Spec

> **Trạng thái**: Đã chốt — sẵn sàng implement
> **Input**: 1 con số (annual enrollment target) → Output: 7 KPI tháng (→ KpiConfig) + 1 KPI năm (→ KpiTarget)
> **Revision**: v4 — thêm 7 KPI ngày (ops + quality), chống gian lận, rolling metrics

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

| Lớp | KPI codes | Logic | Sync target | Auto-calibrate? |
|-----|-----------|-------|-------------|-----------------|
| **Anchor** | `enrollments_annual` | Input trực tiếp | → `KpiTarget` (annual) | ❌ Admin sửa plan |
| **Anchor** | `enrollments_monthly` | Phân bổ seasonal từ annual | → `KpiConfig` (monthly) | ❌ Theo weights |
| **Derived** | `consultations_daily`, `conversion_rate`, `win_rate`, `consultation_effectiveness` | Tính ngược từ M_t + k_t/L_t/C_t | → `KpiConfig` (daily/monthly) | ✅ EMA hàng tháng |
| **Guardrail** | `sla_compliance_rate`, `response_time_hours` | Admin set ở plan-level, giữ nguyên 12 tháng | → `KpiConfig` (monthly/daily) | ❌ Chỉ đổi khi admin sửa plan |

### Định nghĩa biến

| Biến | Ý nghĩa |
|------|---------|
| `M_t` | Chỉ tiêu nhập học tháng t |
| `k_t` | Hệ số tư vấn — số lượt tư vấn cần thiết để có 1 nhập học |
| `WD_t` | Số ngày làm việc (T2-T7, trừ lễ) trong tháng t |
| `L_t` | Dự báo số leads mới trong tháng t |
| `C_t` | Dự báo số leads đóng (won + lost) trong tháng t |
| `consulted_closed_t` | Số leads đã tư vấn ít nhất 1 lần VÀ đã đóng (won hoặc lost) trong tháng t. Dùng để đo hiệu quả tư vấn: bao nhiêu % leads được tư vấn cuối cùng chuyển đổi thành nhập học |

### Công thức quy đổi 7 KPI tháng + 1 KPI năm

```
enrollments_annual      = 300                           (input)
enrollments_monthly_t   = round(300 × weight_t)         (seasonal, có reconciliation)
consultations_daily_t   = ceil(M_t × k_t / WD_t)        (reverse-funnel, WD_t=0 → NULL)
conversion_rate_t       = (M_t / L_t) × 100             (reverse-funnel, guard: L_t > 0)
win_rate_t              = (M_t / C_t) × 100              (reverse-funnel, guard: C_t > 0)
consultation_effectiveness_t = max(floor, M_t / consulted_closed_t × 100)  (guard: consulted_closed_t > 0)
sla_compliance_rate_t   = guardrail (e.g. 85%)           (policy)
response_time_hours_t   = guardrail (e.g. 2h)            (policy)
```

### Reconciliation — đảm bảo sum(M_t) == annual_target (Largest Remainder Method)

```python
# Bước 1: Tính M_t thô (giữ phần thập phân)
exact = [annual_target * w for w in weights]
floored = [math.floor(x) for x in exact]

# Bước 2: Tính diff cần phân bổ (có thể dương HOẶC âm)
diff = annual_target - sum(floored)

# Bước 3: Sắp xếp tháng theo phần lẻ (remainder) giảm dần
remainders = [(i, exact[i] - floored[i]) for i in range(12)]
remainders.sort(key=lambda x: x[1], reverse=True)

if diff > 0:
    # Bước 4a: Thiếu → cộng 1 cho diff tháng có remainder lớn nhất
    for i in range(diff):
        floored[remainders[i][0]] += 1
elif diff < 0:
    # Bước 4b: Thừa (tổng weights > 1.0) → trừ 1 cho |diff| tháng có remainder nhỏ nhất
    for i in range(abs(diff)):
        floored[remainders[-(i+1)][0]] -= 1

# Kết quả: sum(floored) == annual_target, cả khi tổng weights > 1 hoặc < 1
# Ví dụ 1: annual=300, weights sum=0.998 → floor sum=293, diff=+7 → cộng 1 cho 7 tháng top remainder
# Ví dụ 2: annual=300, weights sum=1.002, diff=-1 → trừ 1 cho tháng bottom remainder
```

### Division-by-zero & NULL semantics (2 lớp)

**Lớp 1: Planning internal (`kpi_plan_month`)** — nullable, ghi nhận "không tính được"

```python
# Rule duy nhất: WD_t cho phép = 0 (tháng nghỉ toàn bộ)
# Khi WD_t = 0:
consultations_daily_t = NULL     # Không tính được
conversion_rate_t = NULL
win_rate_t = NULL
consultation_effectiveness_t = NULL

# Khi L_t = 0 hoặc C_t = 0:
conversion_rate_t = NULL
win_rate_t = NULL

# Khi consulted_closed_t = 0:
consultation_effectiveness_t = floor  # Fallback về floor (50%)

# Khi M_t = 0 (weight rất nhỏ + annual_target nhỏ):
consultations_daily = 0          # Hợp lệ: 0 tư vấn cần thiết
conversion_rate = NULL
win_rate = NULL
consultation_effectiveness = floor
```

**Lớp 2: Dashboard contract (`KPIStats`, `KpiConfig`)** — non-null, luôn trả số

```python
# Dashboard schemas hiện tại dùng non-null float (KPIStats.win_rate: float = 0.0)
# KHÔNG đổi contract này. Giữ backward compatible.

# Sync job xử lý NULL → 0:
# Khi kpi_plan_month field = NULL:
#   → Sync job upsert KpiConfig với target_value=0 (không skip)
#   → Tránh fallback về DEFAULT_KPIS tạo target "ảo"
#     (VD: WD_t=0 → skip → default consultations_daily=10 → vô nghĩa)
#   → Dashboard hiện target=0, actual=0 → "tháng này không có chỉ tiêu"

# Admin Planning UI (GET /plans/{id}) — dùng schema riêng:
#   → Response trả Optional[float] cho derived fields
#   → Admin UI hiện "N/A" khi NULL
#   → Không ảnh hưởng officer dashboard schema
```

> **Tóm tắt**: NULL chỉ tồn tại trong `kpi_plan_month` table và Admin Planning API.
> Officer dashboard contract (`KPIStats`, `get_kpi_target()`) **không thay đổi** — luôn non-null.
> Sync job ghi `target_value=0` khi planning NULL → dashboard hiện 0 thay vì default ảo.

---

## 2. Quyết định đã chốt

### 2.1 Scope & Inheritance

```
Officer KpiPlanMonth  →  Unit KpiPlanMonth  →  Global KpiConfig  →  DEFAULT_KPIS
   (nếu có)                (mặc định)           (fallback)          (hardcode)
```

- **Unit plan** = mặc định. Manager tạo plan cho unit, áp dụng tất cả officers.
- **Officer override** = tùy chọn per tháng. Khi officer cần target cá nhân hóa.
- **Officer plan** khi có: override **toàn bộ 7 KPI tháng** cho tháng đó (không partial merge với unit plan). Lý do: tránh logic kế thừa phức tạp, admin set rõ ràng.
- Sync job: lấy effective target theo inheritance chain trên.

#### Bảng precedence cho 1 KPI field cụ thể (VD: `consultations_daily` tháng T3)

| # | Source | Điều kiện | Ví dụ |
|---|--------|-----------|-------|
| 1 | **Officer plan month field override** | Officer plan tồn tại + field nằm trong `overridden_fields` | Admin override Officer A T3: `consultations_daily = 20` |
| 2 | **Officer plan month derived** | Officer plan tồn tại + field KHÔNG trong `overridden_fields` | Officer A plan tính ra `consultations_daily = 13` |
| 3 | **Unit plan month field override** | Không có officer plan + field nằm trong `overridden_fields` | Manager override unit T3: `consultations_daily = 15` |
| 4 | **Unit plan month derived** | Không có officer plan + field KHÔNG trong `overridden_fields` | Unit plan tính ra `consultations_daily = 12` |
| 5 | **Global KpiConfig** | Không có plan nào (hoặc plan inactive) | Admin set global `consultations_daily = 10` |
| 6 | **DEFAULT_KPIS (hardcode)** | Không có KpiConfig record | `DEFAULT_KPIS["consultations_daily"] = 10` |

> **Quy tắc**: Đi từ trên xuống, dừng ở level đầu tiên tìm thấy giá trị.
> Officer plan khi có sẽ bỏ qua toàn bộ unit plan (không partial merge).
> `overridden_fields` chỉ ảnh hưởng bên trong cùng 1 plan (sync job skip recalculate field đó).

### 2.2 Mặc định năm đầu (chưa có data lịch sử)

| Biến | Default | Ý nghĩa |
|------|---------|---------|
| `k_t` | 7 | 7 tư vấn để có 1 nhập học |
| `L_t` | `6 × M_t` | Conversion target mặc định ~16.7% |
| `C_t` | `3 × M_t` | Win rate target mặc định ~33.3% |
| `consultation_effectiveness` floor | 50% | Khi chưa đủ data |

> **Cần thêm** `win_rate` vào `DEFAULT_KPIS` trong `kpi_service.py` (hiện chỉ có 7 codes, thiếu `win_rate`):
> ```python
> DEFAULT_KPIS["win_rate"] = 33  # 33% — consistent với C_t = 3 × M_t
> ```

### 2.3 Auto-calibration (từ tháng thứ 4+)

- **Nguồn**: Rolling 3 tháng gần nhất (EMA — Exponential Moving Average)
- **Damping**: Giới hạn thay đổi ±15%/tháng so với tháng trước
- **Lần đầu từ default**: Cho phép ±30% (vì default có thể xa thực tế)
- **Không áp dụng cho**: Ô đã override thủ công (field nằm trong `overridden_fields`)

```python
# EMA calculation
k_new = 0.5 * k_actual_this_month + 0.3 * k_prev + 0.2 * k_prev_prev

# Damping
if is_first_calibration:  # Lần đầu chuyển từ default sang actual
    k_clamped = clamp(k_new, k_current * 0.70, k_current * 1.30)
else:
    k_clamped = clamp(k_new, k_current * 0.85, k_current * 1.15)
```

#### Fallback khi < 3 tháng data

```python
if months_with_data == 0:
    return default_value  # k=7, L=6×M, C=3×M

if months_with_data == 1:
    k_new = k_actual_month_1  # Dùng trực tiếp, không EMA

if months_with_data == 2:
    k_new = 0.6 * k_actual_month_2 + 0.4 * k_actual_month_1

if months_with_data >= 3:
    k_new = 0.5 * k_month_3 + 0.3 * k_month_2 + 0.2 * k_month_1  # Full EMA
```

### 2.4 Working days

- **Tự động**: Thứ 2-7 (T2-T7), loại trừ ngày lễ VN từ bảng `holiday_calendar`
- **Admin override**: Có thể sửa WD_t per tháng (bù ngày làm đặc biệt)
- **Audit**: Lưu `overridden_by`, `overridden_at` khi sửa
- **Cho phép WD_t = 0**: Tháng toàn nghỉ lễ → derived KPIs = NULL trong `kpi_plan_month`, sync upsert `target_value=0` vào KpiConfig (xem section 1 "Division-by-zero & NULL semantics")

### 2.5 Override KPI derived — Per-field granularity

- **Cho phép**: Admin/Manager override bất kỳ KPI derived nào per tháng
- **Granularity**: Override theo **từng field**, không phải cả row
- **Bắt buộc**: `override_reason`, `overridden_by`, `overridden_at`, `overridden_fields` (JSONB)
- **Sync protection**: Job monthly KHÔNG ghi đè field nằm trong `overridden_fields`
- **Reset**: Admin có thể "reset về auto" → xóa field khỏi `overridden_fields`, job tính lại field đó
- **IDOR**: Xem section 2.6 bên dưới

### 2.6 Security: IDOR Dependencies (MANDATORY)

> **Tuân thủ**: `Backend_FastAPI/AUTHORIZATION_GUIDELINES.md` — KHÔNG dùng `if` trong
> Router/Service để check quyền. LUÔN trả 404, KHÔNG BAO GIỜ trả 403.

```python
# app/core/deps.py — Dependency mới cho KPI Planning

async def get_kpi_plan_for_user(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> KpiPlan:
    """
    IDOR-safe: Admin thấy tất cả, Manager chỉ thấy plan thuộc unit mình.
    Trả 404 nếu không tìm thấy HOẶC không có quyền (chống inference).
    """
    plan = await kpi_planning_repo.get_by_id(db, plan_id)
    if not plan or not plan.is_active:
        raise ResourceNotFoundError("KpiPlan", plan_id)  # 404
    if current_user.role == "admin":
        return plan
    if current_user.role == "manager" and plan.unit_id == current_user.unit_id:
        return plan
    raise ResourceNotFoundError("KpiPlan", plan_id)  # 404, KHÔNG 403


async def get_kpi_plan_month_for_user(
    month_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> KpiPlanMonth:
    """
    IDOR-safe cho plan month. Join plan → check unit scope.
    """
    month = await kpi_planning_repo.get_month_with_plan(db, month_id)
    if not month or not month.plan.is_active:
        raise ResourceNotFoundError("KpiPlanMonth", month_id)
    if current_user.role == "admin":
        return month
    if current_user.role == "manager" and month.plan.unit_id == current_user.unit_id:
        return month
    raise ResourceNotFoundError("KpiPlanMonth", month_id)
```

```python
# Router sử dụng — KHÔNG có logic check quyền trong router body
@router.put("/months/{month_id}/override")
async def override_month(
    overrides: OverrideRequest,
    month: KpiPlanMonth = Depends(get_kpi_plan_month_for_user),  # IDOR ở đây
    db: AsyncSession = Depends(get_db),
):
    result, callback = await kpi_planning_service.override_month_kpi(...)
    await db.commit()
    if callback: await callback()
    return result
```

> **Checklist cho dev**:
> - Tất cả endpoint có `{plan_id}` → dùng `Depends(get_kpi_plan_for_user)`
> - Tất cả endpoint có `{month_id}` → dùng `Depends(get_kpi_plan_month_for_user)`
> - List endpoint: query filter `WHERE unit_id = user.unit_id` cho Manager (trong repository)
> - KHÔNG BAO GIỜ raise `HTTPException(403)` trong toàn bộ module KPI Planning
> - **Existing KPI endpoints** (`/api/admin/kpi-config`): cũng cần IDOR check. Hiện tại
>   `kpi_config.py` router chưa filter theo unit scope cho Manager. Phase A0 nên thêm
>   `get_kpi_config_for_user` dependency hoặc ít nhất filter query theo `user.unit_id`
>   cho GET/PUT/DELETE endpoints. Trả 404 khi Manager access KpiConfig ngoài unit mình.

---

## 3. Data Model

### 3.1 Prerequisite migration: `KpiConfig.target_value` Integer → NUMERIC

```sql
-- KpiConfig hiện tại lưu target_value dạng INTEGER.
-- Các KPI như conversion_rate (16.7%), win_rate (33.3%) cần thập phân.
-- Migration cần chạy TRƯỚC khi planning sync bắt đầu ghi dữ liệu.

-- CHỈ KpiConfig.target_value cần NUMERIC (vì chứa cả rates lẫn counts)
ALTER TABLE kpi_config
    ALTER COLUMN target_value TYPE NUMERIC(12,2) USING target_value::NUMERIC(12,2);

-- KpiTarget: GIỮ INTEGER — chỉ đếm enrollment (không có tỷ lệ)
-- annual_target = 300 (hồ sơ), achieved_ytd = 67 (hồ sơ) → luôn nguyên
-- Nếu sau này thêm kpi_code khác cần decimal, tạo bảng mới thay vì sửa

-- KpiMonthlySnapshot: GIỮ INTEGER — cùng semantics với KpiTarget
-- target_value/actual_value/gap đều là snapshot enrollment counts
```

> **Backward compatible**: Existing integer values trong KpiConfig (e.g. 10, 85) tự cast sang
> NUMERIC (10.00, 85.00). Code hiện tại so sánh `>`, `<` vẫn hoạt động.

```python
# Schema/API changes CHỈ cho KpiConfig:
#   KpiConfigCreate.target_value: int → float (Pydantic)
#   KpiConfigResponse.target_value: int → float
#   get_kpi_target() return type: int → float
#   get_all_kpi_targets() return type: Dict[str, int] → Dict[str, float]
#
# KpiTarget/KpiMonthlySnapshot schemas: KHÔNG ĐỔI (giữ int)
```

### 3.2 Bảng mới: `kpi_plan`

```sql
CREATE TABLE kpi_plan (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id         INTEGER NOT NULL REFERENCES organization_unit(id) ON DELETE CASCADE,  -- bắt buộc, không có global plan
    officer_id      INTEGER REFERENCES "user"(id) ON DELETE CASCADE,  -- NULL = unit plan
    fiscal_year     INTEGER NOT NULL,

    -- Anchor input
    annual_enrollment_target  INTEGER NOT NULL,  -- 300

    -- Guardrails
    sla_target              NUMERIC(5,2) NOT NULL DEFAULT 85.00,   -- %
    response_time_target    NUMERIC(5,2) NOT NULL DEFAULT 2.00,    -- hours

    -- Seasonal weights (JSON array of 12 floats, sum ≈ 1.0)
    -- NULL = dùng DEFAULT_ENROLLMENT_WEIGHTS
    seasonal_weights        JSONB,

    -- Meta
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      INTEGER REFERENCES "user"(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ⚠️ PostgreSQL: NULL != NULL trong unique index.
-- Nếu officer_id IS NULL (unit plan), 1 index gộp sẽ cho phép duplicate.
-- Giải pháp: 2 partial indexes tách biệt.

-- Unit plan: 1 plan active per unit per year
CREATE UNIQUE INDEX uix_kpi_plan_active_unit
ON kpi_plan (unit_id, fiscal_year)
WHERE is_active = TRUE AND officer_id IS NULL;

-- Officer plan: 1 plan active per officer per unit per year
CREATE UNIQUE INDEX uix_kpi_plan_active_officer
ON kpi_plan (unit_id, officer_id, fiscal_year)
WHERE is_active = TRUE AND officer_id IS NOT NULL;

COMMENT ON TABLE kpi_plan IS 'KPI planning — reverse-funnel từ annual target ra 7 KPI tháng + 1 KPI năm';
```

### 3.3 Bảng mới: `kpi_plan_month`

```sql
CREATE TABLE kpi_plan_month (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id         INTEGER NOT NULL REFERENCES kpi_plan(id) ON DELETE CASCADE,
    month           INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),

    -- Distributable inputs
    enrollment_target       INTEGER NOT NULL,            -- M_t: 46
    working_days            INTEGER NOT NULL DEFAULT 0,  -- WD_t: 26 (0 = tháng nghỉ toàn bộ)
    weight                  NUMERIC(6,4) NOT NULL,       -- 0.1530

    -- Historical factors (computed or manual)
    k_factor                NUMERIC(6,2) NOT NULL DEFAULT 7.00,  -- k_t
    lead_forecast           INTEGER,                     -- L_t (NULL = 6×M_t)
    close_forecast          INTEGER,                     -- C_t (NULL = 3×M_t)

    -- Derived KPI targets (auto-calculated, overridable per-field)
    -- NULL = không tính được (WD_t=0, M_t=0, etc.) → UI hiển thị "N/A"
    consultations_daily     INTEGER,                     -- NULL khi WD_t=0
    conversion_rate         NUMERIC(6,2),                -- % (NULL khi L_t=0)
    win_rate                NUMERIC(6,2),                -- % (NULL khi C_t=0)
    consultation_effectiveness NUMERIC(6,2),             -- %

    -- Per-field override tracking
    -- Ví dụ: {"consultations_daily": true, "win_rate": true}
    -- Sync job chỉ skip field nằm trong JSONB này, các field khác vẫn recalculate
    overridden_fields       JSONB NOT NULL DEFAULT '{}',
    override_reason         TEXT,           -- DB nullable, nhưng API enforce NOT NULL khi overridden_fields != '{}'
    overridden_by           INTEGER REFERENCES "user"(id),  -- idem
    overridden_at           TIMESTAMPTZ,    -- idem, service tự set = now()

    -- ⚠️ DB cho nullable vì record mới (chưa override) không cần giá trị.
    -- API validation: khi overridden_fields != '{}', bắt buộc:
    --   override_reason NOT NULL AND len >= 5
    --   overridden_by NOT NULL (service tự set từ current_user)
    --   overridden_at NOT NULL (service tự set = now())

    -- Actuals (filled by sync job at month end)
    actual_enrollments              INTEGER,
    actual_consultations_avg        NUMERIC(6,2),
    actual_conversion_rate          NUMERIC(6,2),
    actual_win_rate                 NUMERIC(6,2),
    actual_consultation_effectiveness NUMERIC(6,2),
    actual_sla_compliance_rate      NUMERIC(6,2),

    -- Audit
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (plan_id, month)
);

COMMENT ON TABLE kpi_plan_month IS 'Monthly breakdown of KPI plan with derived targets and actuals';
```

### 3.3 Bảng mới: `holiday_calendar`

```sql
CREATE TABLE holiday_calendar (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,
    name            VARCHAR(200) NOT NULL,       -- "Tết Nguyên Đán"
    year            INTEGER NOT NULL,
    is_recurring    BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE = lặp hàng năm (1/1, 30/4, ...)
    created_by      INTEGER REFERENCES "user"(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed VN holidays 2026
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

-- LƯU Ý: Giỗ Tổ Hùng Vương (10/3 âm lịch) và Tết Nguyên Đán theo âm lịch
-- → is_recurring = FALSE, admin cần seed ngày cụ thể cho mỗi năm mới
-- → Admin UI có nút "Tạo ngày lễ năm [X]" để nhập các ngày âm lịch
```

---

## 4. Validation Rules

### 4.1 `seasonal_weights`

```python
def validate_seasonal_weights(weights: list[float]) -> None:
    """Validate trước khi save vào kpi_plan.seasonal_weights."""
    assert len(weights) == 12, "Phải có đúng 12 phần tử"
    assert all(w > 0 for w in weights), "Mỗi weight phải > 0"
    total = sum(weights)
    assert 0.99 <= total <= 1.01, f"Tổng weights = {total}, phải ∈ [0.99, 1.01]"
```

### 4.2 `annual_enrollment_target`

- Tối thiểu: 1
- Tối đa: 10000 (configurable, phòng nhập nhầm)
- Phải là số nguyên dương

### 4.3 Guardrails

- `sla_target`: 0-100 (%)
- `response_time_target`: 1-48 (hours)

---

## 5. Service Layer

> **MANDATORY RULE**: Service KHÔNG BAO GIỜ gọi `await db.commit()`.
> Service chỉ `flush()` (hoặc không flush). Router gọi `commit()` sau khi service trả về.
> **Ngoại lệ duy nhất**: Celery tasks tự quản session → được phép `commit()`.
> Xem `Backend_FastAPI/CLAUDE.md` — "Router commits, Service flushes".

### 5.1 `kpi_planning_service.py` — Engine chính

```python
# Các hàm chính:
# ⚠️ Tất cả hàm dưới đây chỉ flush(), KHÔNG commit().
# Return type: Tuple[result, Optional[Callable]] — theo pattern (result, post_commit_callback).

async def create_plan(db, unit_id, fiscal_year, annual_target,
                      guardrails, seasonal_weights=None, created_by=None):
    """
    Tạo plan mới → auto-generate 12 KpiPlanMonth records.
    Nếu seasonal_weights = None → dùng DEFAULT_ENROLLMENT_WEIGHTS.
    Validate: seasonal_weights, annual_target range.
    Reconciliation: Largest Remainder đảm bảo sum(M_t) == annual_target.
    """

async def generate_monthly_kpis(db, plan_id):
    """
    Từ plan → tính 12 bộ KPI.
    Với mỗi tháng t:
      1. M_t = round(annual × weight_t) + Largest Remainder reconciliation
      2. WD_t = count_working_days(year, month) — từ holiday_calendar
      3. k_t = get_k_factor(officer_id, month) hoặc default 7
      4. L_t = lead_forecast hoặc 6 × M_t
      5. C_t = close_forecast hoặc 3 × M_t
      6. Tính 4 derived KPIs (với division-by-zero → NULL guards)
    Skip field nằm trong overridden_fields (per-field, không skip cả row).
    """

async def preview_plan(db, unit_id, fiscal_year, annual_target,
                       guardrails, seasonal_weights=None):
    """
    Dry-run: tính 12 bộ KPI KHÔNG persist.
    Trả về cấu trúc giống GET /plans/{id} nhưng không tạo record.
    Frontend gọi endpoint này (debounced) khi admin kéo thanh weights.
    ⚠️ KHÔNG có db.flush() — pure computation, read-only.
    """

async def recalibrate_factors(db, plan_id, up_to_month):
    """
    Auto-calibration: dùng actual data 3 tháng gần nhất → update k_t, L_t, C_t.
    Damping: ±15% max change (±30% cho lần đầu từ default).
    Fallback: < 3 tháng data → simple average thay vì EMA.
    Chỉ update tháng future, không sửa tháng đã qua.

    Phát hiện is_first_calibration:
      Truy vấn: có tồn tại kpi_plan_month nào thuộc plan scope (cùng unit/officer)
      có actual_enrollments IS NOT NULL không?
      - Nếu KHÔNG → is_first_calibration = True → damping ±30%
      - Nếu CÓ → is_first_calibration = False → damping ±15%
    """

async def update_plan(db, plan_id, annual_target=None, weights=None,
                      guardrails=None, user_id=None):
    """
    Sửa plan metadata.
    Nếu sửa annual_target giữa năm:
      - Redistribute cho tháng current + future (giữ nguyên actual tháng đã qua)
      - remaining = new_target - sum(actual_enrollments tháng đã qua)
      - Phân bổ remaining theo weights (re-normalize weights cho tháng còn lại)
    Nếu sửa weights hoặc guardrails:
      - Regenerate derived KPIs cho tháng future (skip overridden_fields)
    """

async def override_month_kpi(db, plan_month_id, overrides: dict, reason, user_id):
    """
    Admin override 1+ KPI cho tháng cụ thể.
    overrides = {"consultations_daily": 16, "win_rate": 40.0}
    Merge vào overridden_fields, lưu reason + who + when.
    """

async def reset_month_override(db, plan_month_id, fields: list[str] | None, user_id):
    """
    Reset override.
    fields = None → reset tất cả → clear overridden_fields → recalculate toàn bộ.
    fields = ["consultations_daily"] → chỉ xóa field đó, giữ các override khác.
    """

async def sync_plan_to_kpi_config(db, plan_id, month):
    """
    Với mỗi officer active trong unit:
      1. Tìm officer plan → nếu có, dùng officer plan targets
      2. Nếu không → dùng unit plan targets
      3. Upsert KpiConfig PER OFFICER (không giữ unit-level record)
         → 7 KPI tháng vào KpiConfig (per officer, per month)
         → 1 KPI năm vào KpiTarget (enrollments_annual)
    Ghi effective_month/year + source_plan_id.
    Khi derived KPI = NULL (WD_t=0, M_t=0): COALESCE(NULL, 0) → upsert target_value=0
    Dashboard đọc từ KpiConfig per officer như bình thường.
    """

async def deactivate_plan(db, plan_id, user_id):
    """
    Soft delete: set is_active = FALSE.
    Cleanup: xóa KpiConfig records được tạo bởi plan này cho tháng future.
    Tháng đã qua giữ nguyên (data lịch sử).
    """

async def fill_month_actuals(db, plan_id, month):
    """
    Cuối tháng: điền tất cả actual fields:
      - actual_enrollments
      - actual_consultations_avg
      - actual_conversion_rate
      - actual_win_rate
      - actual_consultation_effectiveness
      - actual_sla_compliance_rate
    Từ repository queries.
    """
```

### 5.2 `calendar_service.py` — Working days

```python
async def count_working_days(db, year: int, month: int) -> int:
    """
    Đếm ngày T2-T7 trong tháng, trừ ngày lễ từ holiday_calendar.
    Bao gồm cả ngày lễ is_recurring=TRUE (match theo tháng/ngày)
    và is_recurring=FALSE (match theo date chính xác).
    """

async def get_working_days_override(db, plan_month_id) -> int | None:
    """
    Nếu admin override WD → trả về override value.
    """
```

### 5.3 `historical_metrics_service.py` — Tính k_t/L_t/C_t từ data

```python
async def get_historical_k_factor(db, officer_id, unit_id, months_back=3):
    """
    k_t = total_consultations / total_enrollments trong N tháng gần nhất.
    ⚠️ PHẢI loại method='system' khi đếm consultations (dùng IS DISTINCT FROM).
    Admission flow tạo system consultations → nếu không loại, k_t bị phình.
    Guard: nếu total_enrollments = 0 → return default (7).
    Dùng EMA: 0.5 × month[-1] + 0.3 × month[-2] + 0.2 × month[-3]
    Fallback < 3 tháng: xem section 2.3.
    """

async def get_historical_lead_count(db, officer_id, unit_id, target_month):
    """
    L_t = avg leads mới/tháng trong 3 tháng cùng kỳ hoặc 3 tháng gần nhất.
    Guard: nếu không có data → return 6 × M_t (default).
    """

async def get_historical_close_count(db, officer_id, unit_id, target_month):
    """
    C_t = avg leads đóng/tháng (won + lost).
    Guard: nếu không có data → return 3 × M_t (default).
    """
```

---

## 6. Celery Jobs

### Job 1: `sync_kpi_plan_monthly` — Ngày 1 mỗi tháng, 02:00 AM

> **Lịch chạy**: 02:00 AM ngày 1 (KHÔNG 00:00/00:01). Lý do: đảm bảo mọi transaction
> của tháng trước đã kết thúc (CRM webhook, late-night operations, timezone offset).
> Celery Beat config: `crontab(hour=2, minute=0, day_of_month=1)`

```python
@celery_app.task
def sync_kpi_plan_monthly():
    """
    ⚠️ Celery task — tự quản session, ĐƯỢC PHÉP commit().

    1. Tìm tất cả KpiPlan WHERE is_active = TRUE AND fiscal_year = current year
    2. Với mỗi plan:
       a. fill_month_actuals(prev_month) — điền actual tháng trước
       b. recalibrate_factors(current_month) — hiệu chỉnh k/L/C nếu có data
       c. generate_monthly_kpis() — regenerate future months (skip overridden_fields)
       d. sync_plan_to_kpi_config(current_month) — push targets vào KpiConfig
    3. Lưu ý: plan có is_active = FALSE → skip hoàn toàn
    4. Commit sau mỗi plan (isolate failures — 1 plan lỗi không ảnh hưởng plan khác)
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

## 7. API Endpoints

> **Thin Client Doctrine**: Frontend KHÔNG BAO GIỜ tự tính KPI (Largest Remainder,
> `ceil(M_t × k_t / WD_t)`, conversion rates). Mọi tính toán 100% server-side.
> Khi admin kéo slider weights → frontend gọi `POST /plans/preview` (debounced 300ms)
> → backend trả về 12 bộ KPI → frontend chỉ render.

### Planning CRUD (`/api/admin/kpi-planning`)

| Method | Endpoint | Mô tả | Auth | IDOR |
|--------|----------|-------|------|------|
| `POST` | `/plans` | Tạo plan mới (annual target + weights + guardrails) | Admin | - |
| `GET` | `/plans` | List plans (filter by unit, year, pagination) | Admin/Manager | Manager: chỉ unit mình |
| `GET` | `/plans/{id}` | Chi tiết plan + 12 months | Admin/Manager | Manager: chỉ unit mình |
| `PUT` | `/plans/{id}` | Sửa annual target / weights / guardrails (xem section 5.1 `update_plan`) | Admin | - |
| `DELETE` | `/plans/{id}` | Soft delete + cleanup KpiConfig future (xem section 5.1 `deactivate_plan`) | Admin | - |
| `POST` | `/plans/{id}/regenerate` | Force recalculate derived KPIs KHÔNG thay đổi input (skip overridden_fields) | Admin | - |
| `POST` | `/plans/preview` | Preview KPIs dry-run (body = annual_target + weights + guardrails, không persist). Frontend gọi debounced khi admin kéo slider | Admin/Manager | - |
| `POST` | `/plans/{id}/clone` | Clone plan sang fiscal_year mới (copy weights + guardrails, reset actuals) | Admin | - |

### Monthly Override (`/api/admin/kpi-planning/months`)

| Method | Endpoint | Mô tả | Auth | IDOR |
|--------|----------|-------|------|------|
| `PUT` | `/months/{id}/override` | Override 1+ KPI fields cho 1 tháng (+ reason) | Admin/Manager | Manager: chỉ unit mình |
| `POST` | `/months/{id}/reset` | Reset override (all hoặc specific fields) → recalculate | Admin/Manager | Manager: chỉ unit mình |
| `PUT` | `/months/{id}/working-days` | Override working days | Admin | - |
| `PUT` | `/months/batch-override` | Override cùng fields cho nhiều tháng (VD: T6-T9) | Admin | - |

### Holiday Calendar (`/api/admin/calendar`)

| Method | Endpoint | Mô tả | Auth |
|--------|----------|-------|------|
| `GET` | `/holidays` | List holidays (filter by year, pagination) | Admin/Manager |
| `GET` | `/holidays/status/{year}` | Kiểm tra năm đã có đủ lịch lễ chưa (xem bên dưới) | Admin/Manager |
| `POST` | `/holidays` | Thêm ngày lễ | Admin |
| `PUT` | `/holidays/{id}` | Sửa ngày lễ | Admin |
| `DELETE` | `/holidays/{id}` | Xóa ngày lễ | Admin |
| `POST` | `/holidays/seed/{year}` | Seed ngày lễ recurring cho năm mới (copy từ is_recurring=TRUE) | Admin |

#### Holiday Calendar Warning (rủi ro vận hành)

> **Vấn đề**: Ngày lễ âm lịch (Tết Nguyên Đán, Giỗ Tổ Hùng Vương) thay đổi mỗi năm.
> Nếu admin quên seed ngày lễ cho năm mới, `count_working_days()` sẽ trả WD_t sai
> (thiếu trừ ngày lễ) → KPI targets sai.

**Giải pháp**: Endpoint `GET /holidays/status/{year}` + Celery warning.

```python
# GET /holidays/status/2027 → Response:
{
    "year": 2027,
    "total_holidays": 3,           # Chỉ có 3 ngày recurring (1/1, 30/4, 1/5)
    "has_lunar_holidays": false,    # Thiếu Tết, Giỗ Tổ
    "is_complete": false,
    "warning": "Chưa cấu hình ngày nghỉ Tết Nguyên Đán và Giỗ Tổ Hùng Vương cho năm 2027"
}

# Celery check (chạy 1/11 hàng năm — 2 tháng trước năm mới):
@celery_app.task
def check_next_year_holidays():
    """
    Kiểm tra holiday_calendar cho năm kế tiếp.
    Nếu < 8 ngày lễ (threshold) → tạo notification cho Admin.
    """
```

> **Admin Dashboard**: Hiển thị banner warning nếu `is_complete = false` cho năm hiện tại hoặc năm kế tiếp.

---

## 8. Integration với hệ thống hiện có

### 8.1 Canonical KPI code mapping

> **Vấn đề hiện tại**: Codebase dùng lẫn lộn nhiều mã KPI legacy.
> Cần chuẩn hóa toàn bộ trước khi planning sync bắt đầu ghi dữ liệu.

```python
# CANONICAL KPI CODES — single source of truth
KPI_CODES = {
    "consultations_daily":        {"period_type": "daily",   "table": "KpiConfig"},
    "conversion_rate":            {"period_type": "monthly", "table": "KpiConfig"},
    "win_rate":                   {"period_type": "monthly", "table": "KpiConfig"},
    "consultation_effectiveness": {"period_type": "monthly", "table": "KpiConfig"},
    "enrollments_monthly":        {"period_type": "monthly", "table": "KpiConfig"},
    "sla_compliance_rate":        {"period_type": "monthly", "table": "KpiConfig"},
    "response_time_hours":        {"period_type": "daily",   "table": "KpiConfig"},
    "enrollments_annual":         {"period_type": "annual",  "table": "KpiTarget"},
}
```

#### Legacy codes cần khử (Phase A0)

| Legacy code | Canonical code | File(s) cần sửa |
|-------------|---------------|-----------------|
| `"enrollments"` | `"enrollments_annual"` | `kpi_service.py:112,288`, `officer_service.py:823` |
| `"response_time"` | `"response_time_hours"` | `frontend/admin/kpi-config/page.tsx:121` |
| `"enrollments"` (KpiTarget DB) | `"enrollments_annual"` | Data migration SQL |
| `"enrollments"` (admin UI default) | `"enrollments_annual"` | `frontend/admin/kpi-config/page.tsx:118,223,309,392,640` |

```sql
-- Data migration (Phase A0)
UPDATE kpi_target SET kpi_code = 'enrollments_annual' WHERE kpi_code = 'enrollments';
UPDATE kpi_config SET kpi_code = 'response_time_hours' WHERE kpi_code = 'response_time';
```

#### Admin KPI Config UI — transition strategy (Phase A0 → Phase C)

> **Vấn đề**: `admin/kpi-config/page.tsx` hiện cho phép admin CRUD KPI targets thủ công.
> Sau khi Planning Engine (Phase A) đi vào hoạt động, UI này sẽ conflict với sync job
> (admin set thủ công → sync job ghi đè, hoặc ngược lại).

| Giai đoạn | `admin/kpi-config` | `admin/kpi-planning` (mới) |
|-----------|--------------------|-----------------------------|
| **A0** | Sửa legacy codes, thêm disclaimer "Sẽ được thay thế bởi KPI Planning" | Chưa có |
| **Phase A** | **Read-only** — chỉ xem KpiConfig hiện tại, không cho create/edit | Bắt đầu dùng — tạo plan, preview |
| **Phase C** | **Ẩn khỏi menu** (giữ code, không xóa) | UI chính cho quản lý KPI |

```typescript
// Phase A: admin/kpi-config/page.tsx
// Thêm banner + disable mutation buttons
const isLegacy = true; // Set true khi planning engine active
// <Alert>KPI targets hiện được quản lý tự động qua KPI Planning. Trang này chỉ hiển thị.</Alert>
```

### 8.2 Flow tổng thể

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
│  KpiConfig (existing) — target_value: NUMERIC(12,2)         │
│  Upsert: kpi_code + target_value + unit_id/officer_id       │
│  + source_plan_id (FK → kpi_plan, nullable)                 │
│  ← Dashboard reads from here via get_kpi_target()           │
│  ← Soft-delete cleanup dùng source_plan_id để xác định      │
└───────────────────┬─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────────┐
│  Officer Dashboard                                          │
│  - KPI cards dùng target từ KpiConfig                       │
│  - Recommendation engine dùng KpiConfig-driven thresholds   │
│  - Annual progress dùng KpiTarget (kpi_code=enrollments_annual) │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 Sync mapping chi tiết

| KPI code | Source field | Target table | period_type | NULL handling |
|----------|-------------|-------------|-------------|---------------|
| `consultations_daily` | `kpi_plan_month.consultations_daily` | `KpiConfig` | `daily` | NULL → upsert `target_value=0` |
| `conversion_rate` | `kpi_plan_month.conversion_rate` | `KpiConfig` | `monthly` | NULL → upsert `target_value=0` |
| `win_rate` | `kpi_plan_month.win_rate` | `KpiConfig` | `monthly` | NULL → upsert `target_value=0` |
| `consultation_effectiveness` | `kpi_plan_month.consultation_effectiveness` | `KpiConfig` | `monthly` | NULL → upsert `target_value=0` |
| `enrollments_monthly` | `kpi_plan_month.enrollment_target` | `KpiConfig` | `monthly` | Always present |
| `sla_compliance_rate` | `kpi_plan.sla_target` | `KpiConfig` | `monthly` | Always present |
| `response_time_hours` | `kpi_plan.response_time_target` | `KpiConfig` | `daily` | Always present |
| `enrollments_annual` | `kpi_plan.annual_enrollment_target` | `KpiTarget` | `annual` | Always present |

> **NULL → upsert 0** (thay vì skip): Khi planning engine tính ra NULL (WD_t=0, M_t=0),
> sync job vẫn ghi `target_value=0` vào KpiConfig. Điều này tránh fallback về DEFAULT_KPIS
> (VD: `consultations_daily=10`) — sẽ tạo target "ảo" cho tháng không khả thi.
> `target_value=0` nghĩa là "tháng này không có chỉ tiêu" — dashboard hiện 0/0 = done.

### 8.4 Historical target resolution

> **Vấn đề**: `get_kpi_target()` không có `effective_date`. Khi dashboard xem kỳ quá khứ
> (VD: xem performance tháng 3), nó lấy target tháng hiện tại (tháng 6) — sai.

**Giải pháp**: Thêm `effective_month` vào KpiConfig + resolver.

```sql
-- ⚠️ Tất cả nằm trong CÙNG 1 migration A0 (trước khi tạo bảng kpi_plan ở A1).
-- source_plan_id FK → kpi_plan sẽ thêm SAU ở A1 migration (ALTER TABLE ADD CONSTRAINT).
-- Hoặc tạo column nullable không có FK ở A0, thêm FK ở A1.

-- Bước 1: Thêm columns
ALTER TABLE kpi_config ADD COLUMN effective_month INTEGER;  -- NULL = evergreen (legacy)
ALTER TABLE kpi_config ADD COLUMN effective_year INTEGER;   -- NULL = evergreen (legacy)
ALTER TABLE kpi_config ADD COLUMN source_plan_id INTEGER;   -- FK thêm ở A1 sau khi tạo bảng kpi_plan

-- ⚠️ UNIQUE CONSTRAINT: Index cũ `uq_kpi_config_scope` trên
-- (unit_id, officer_id, kpi_code, period_type) KHÔNG cho phép nhiều record
-- cùng kpi_code cho các tháng khác nhau. PHẢI thay thế:

DROP INDEX IF EXISTS uq_kpi_config_scope;
DROP INDEX IF EXISTS ix_kpi_config_unique_combo;  -- từ perf migration, cũng chặn multi-month

-- Unique mới: cho phép 1 record per kpi_code per scope PER THÁNG
-- Evergreen (legacy, effective_month=NULL): tách index riêng
CREATE UNIQUE INDEX uq_kpi_config_scope_evergreen
ON kpi_config (unit_id, officer_id, kpi_code, period_type)
WHERE is_active = TRUE AND effective_month IS NULL;

-- Monthly (from planning sync): 1 record per month
CREATE UNIQUE INDEX uq_kpi_config_scope_monthly
ON kpi_config (unit_id, officer_id, kpi_code, period_type, effective_year, effective_month)
WHERE is_active = TRUE AND effective_month IS NOT NULL;

-- ⚠️ PERFORMANCE: KpiConfig sẽ phình to khi lưu per-month thay vì evergreen.
-- Mỗi plan sync tạo ~7 records/tháng/officer. 50 officers × 12 tháng = 4200 records/năm.
-- Composite index bắt buộc để get_kpi_target() không full-scan:
CREATE INDEX idx_kpi_config_effective_lookup
ON kpi_config (kpi_code, unit_id, officer_id, effective_year, effective_month)
WHERE is_active = TRUE;

-- Sync job ghi: effective_month=3, effective_year=2026, source_plan_id=42
-- Legacy records (admin tạo thủ công): effective_month=NULL → evergreen

-- get_kpi_target() resolution order:
-- 1. Monthly record (effective_month/year match) → ưu tiên cao nhất
-- 2. Evergreen record (effective_month IS NULL) → fallback
-- 3. DEFAULT_KPIS → hardcoded
```

```python
async def get_kpi_target(
    db: AsyncSession,
    kpi_code: str,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    period_type: str = "daily",
    effective_date: Optional[date] = None,  # NEW: default=today
) -> float:
    """
    Inheritance + temporal resolution:
    1. Tìm record có effective_month/year match → dùng target tháng đó
    2. Nếu không có → tìm evergreen record (effective_month=NULL)
    3. Nếu không có → fallback DEFAULT_KPIS

    Khi effective_date=None (mặc định): dùng tháng hiện tại.
    Khi xem dashboard kỳ quá khứ: truyền effective_date=date(2026, 3, 15).
    """
```

> **Backward compatible**: Gọi `get_kpi_target()` không truyền `effective_date` → hoạt động
> như cũ (dùng tháng hiện tại). Code hiện tại không cần sửa ngay.

### 8.5 Recommendation engine — config-driven thresholds

> **Vấn đề**: `recommendation_engine.py` hardcode `THRESHOLDS` dict (line 52).
> Khi planning engine thay đổi target theo mùa, threshold cố định sẽ không phù hợp.

**Giải pháp**: Phase P3 — chuyển threshold sang đọc từ KpiConfig scope.

```python
# HIỆN TẠI (hardcoded):
THRESHOLDS = {
    "consultations_gap_critical": 0.5,   # < 50% of target
    "conversion_rate_low": 10,           # < 10%
    ...
}

# SAU (config-driven, Phase P3):
async def get_recommendation_thresholds(
    db: AsyncSession,
    officer_id: int,
    unit_id: int,
) -> dict:
    """
    Đọc threshold từ KpiConfig hoặc system config.
    Fallback về THRESHOLDS hardcoded nếu chưa có config.
    """
    # Ưu tiên: officer config → unit config → global config → hardcoded
    thresholds = dict(DEFAULT_THRESHOLDS)  # copy hardcoded as base
    # Override với config nếu có...
    return thresholds
```

> **Lưu ý**: Phase A-B KHÔNG cần sửa recommendation. Vẫn hoạt động vì threshold hardcoded
> là tỷ lệ tương đối (50% of target), không phải absolute value.
> Chỉ sửa ở Phase P3 khi có đủ data để tune thresholds per scope.

### 8.6 Type safety: int → float migration

> **Rủi ro**: `KpiConfig.target_value` chuyển từ `INTEGER` → `NUMERIC(12,2)`.
> Backend Python tự xử lý (Decimal/float tương thích), nhưng Frontend TypeScript
> có thể bị ảnh hưởng nếu code cũ dùng integer arithmetic (VD: `Math.floor`, `%`).

**Checklist Phase A0 — kiểm tra trước khi deploy migration:**

```typescript
// Frontend: tìm tất cả code dùng target_value hoặc consultations_target
// grep -r "target_value\|consultations_target\|kpi.*target" src/

// TRƯỚC (có thể expect int):
const progress = (actual / target) * 100;  // OK — float chia float vẫn đúng

// CẦN KIỂM TRA (nếu có):
if (target % 10 === 0) { ... }  // ❌ Modulo trên float có thể sai
const remaining = target - actual;  // OK — float trừ vẫn đúng

// Pydantic serialization: NUMERIC(12,2) → Python Decimal → JSON float
// Response: {"target_value": 16.7} thay vì {"target_value": 16}
// TypeScript: number type xử lý cả int lẫn float → an toàn
```

> **Kết luận**: Rủi ro thấp vì TypeScript `number` = float64. Chỉ cần audit
> code frontend tìm integer-specific operations (`%`, `parseInt`, bitwise).
> Backend `KPIStats` schema giữ `float` type → không ảnh hưởng.

### 8.7 Backward compatible — tổng hợp

| Component | Thay đổi? | Phase | Chi tiết |
|-----------|-----------|-------|----------|
| `KpiConfig.target_value` | ✅ **Integer → NUMERIC(12,2)** | **A0** | Prerequisite migration |
| `KpiConfig` schema/API | ✅ `target_value: int → float` | **A0** | Pydantic + router |
| `KpiTarget.kpi_code` | ✅ `enrollments → enrollments_annual` | **A0** | Data migration + code refs |
| `KpiTarget` column types | ❌ **Giữ INTEGER** | - | Enrollment counts luôn nguyên |
| `KpiMonthlySnapshot` types | ❌ **Giữ INTEGER** | - | Snapshot enrollment counts |
| `KpiConfig` + columns | ✅ Thêm `effective_month/year`, `source_plan_id` (column) + indexes | **A0-3** | Column + indexes ở A0, FK constraint ở A1 |
| `get_kpi_target()` return | ✅ `int → float` | **A0** | Type hint change |
| `get_kpi_target()` + effective_date | ✅ Thêm param (optional) | **B8** | Historical resolution |
| `DEFAULT_KPIS` | ✅ Thêm `win_rate: 33` | **A0** | Thiếu trong codebase |
| `officer_service.py:823` | ✅ `kpi_code="enrollments"` → `"enrollments_annual"` | **A0** | Code ref update |
| `KPIStats` (officer schema) | ❌ **Không đổi** | - | Non-null float, dashboard contract giữ nguyên |
| `recommendation_engine.py` | ❌ Không đổi (Phase A-B) | **P3** | Config-driven sau |
| Dashboard frontend | ⚠️ **Audit int ops** | **A0** | Tìm `%`, `parseInt`, bitwise trên target values |
| Holiday calendar | ⚠️ **Warning mechanism** | **A1** | `GET /holidays/status/{year}` + Celery check |

---

## 9. Seasonal Weights mặc định

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
# Sum = 0.998 → Largest Remainder reconciliation phân bổ diff cho tháng có remainder cao nhất
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

## 10. Edge Cases & Business Rules

### 10.1 Sửa annual_target giữa năm

```
Ví dụ: T6, admin đổi target 300 → 350

Tháng 1-5: đã có actuals, KHÔNG đổi enrollment_target
  actual_sum = sum(actual_enrollments cho T1-T5) = 84

remaining = 350 - 84 = 266

Phân bổ remaining cho T6-T12:
  sub_weights = normalize(weights[6:12])  # Re-normalize cho 7 tháng còn lại
  M_t = round(266 × sub_weight_t) + reconciliation

Derived KPIs cho T6-T12 recalculate theo M_t mới.
```

### 10.2 Soft-delete plan giữa năm

```
1. Set kpi_plan.is_active = FALSE
2. Cleanup KpiConfig: soft-delete records cho tháng current + future
   (WHERE source_plan_id = plan_id
      AND effective_year = fiscal_year
      AND effective_month >= current_month)
   → SET is_active = FALSE
3. Tháng đã qua (effective_month < current_month): giữ nguyên (data lịch sử)
4. Officer dashboard: resolver tìm evergreen KpiConfig → nếu không có → DEFAULT_KPIS
   (Soft-delete chỉ ảnh hưởng monthly records có source_plan_id; evergreen vẫn còn nếu có)
```

### 10.3 Nhiều officer plans trong cùng unit — phân bổ linh hoạt

#### Mô hình: Unit plan = baseline, Officer plan = override cá nhân

```
Unit plan: annual_target = 1200 → baseline cho officers chưa có plan riêng
Officer A plan: annual_target = 300 → override cá nhân
Officer B plan: annual_target = 300 → override cá nhân
Officer C: không có plan riêng → dùng unit plan (baseline = 1200)
Officer D: không có plan riêng → dùng unit plan (baseline = 1200)
```

#### Quy tắc phân bổ

> **Thiết kế chốt**: Unit plan target KHÔNG tự động chia đều cho officers.
> Unit plan là **target chung** (baseline) — mỗi officer không có plan riêng sẽ dùng
> nguyên target unit plan. Officer plan là **target cá nhân** hoàn toàn độc lập.

| Scenario | Hành vi |
|----------|---------|
| Officer có plan riêng | Dùng officer plan, bỏ qua unit plan hoàn toàn |
| Officer KHÔNG có plan riêng | Dùng unit plan target nguyên (không chia) |
| Tổng officer plans > unit plan | **Cho phép** — admin chịu trách nhiệm. Không validate |
| Tổng officer plans < unit plan | **Cho phép** — phần còn lại chưa giao cho ai cụ thể |

#### Tại sao không auto-distribute?

1. **Complexity**: Chia 1200 cho 5 officers cần biết capacity/seniority mỗi người → quá phức tạp cho MVP
2. **Flexibility**: Admin muốn giao khác nhau (senior 300, junior 100)
3. **Hiện thực**: Các trường thường giao KPI cá nhân qua Excel, không chia đều

#### Validation/Warning (UI, không block)

```python
# Admin Planning UI hiện warning (không block save):
total_officer_targets = sum(officer_plan.annual_enrollment_target for active officer plans)
if total_officer_targets > unit_plan.annual_enrollment_target:
    warning = f"Tổng chỉ tiêu officer ({total_officer_targets}) vượt chỉ tiêu unit ({unit_plan.annual_enrollment_target})"
if total_officer_targets < unit_plan.annual_enrollment_target:
    remaining = unit_plan.annual_enrollment_target - total_officer_targets
    info = f"Còn {remaining} chỉ tiêu chưa giao cho officer cụ thể"
```

#### Sync job behavior

```
Sync job xử lý từng officer active trong unit:
  1. Tìm officer plan (WHERE officer_id = X AND is_active = TRUE)
  2. Nếu có → dùng officer plan targets
  3. Nếu không → dùng unit plan targets (nguyên, không chia)
  4. Upsert vào KpiConfig cho officer đó
```

### 10.4 Officer mới vào giữa năm (join-date skip)

> **Vấn đề**: Officer được thêm vào unit ở tháng 6. Unit plan có target 300/năm.
> Nếu sync dùng nguyên target unit plan → officer mới bị giao target cho cả T1-T5
> (trước khi có mặt).

**Quy tắc**: Không phải proration (không tự scale annual target). Chỉ skip tháng trước ngày vào.

```python
# Source date: UserUnitAssignment.assigned_at (không dùng User.created_at vì có thể
# user tồn tại nhưng chưa được giao unit)

# Skip logic trong sync_plan_to_kpi_config():
start_month = assignment.assigned_at.month  # VD: 6 (tháng 6)

# Tháng trước start_month: KHÔNG upsert KpiConfig cho officer
# → Officer chưa có mặt → không có target → dashboard hiện DEFAULT_KPIS (chấp nhận)

# Tháng từ start_month trở đi: dùng unit plan monthly target M_t bình thường
# → KHÔNG chia lại annual target — officer dùng M_t theo mùa nguyên bản
# → Annual progress (KpiTarget): tạo với achieved_ytd=0, tính từ start_month

# Ví dụ: Unit plan T6 có M_t = 38. Officer mới nhận target M_t = 38 cho T6.
# Officer không bị gánh target T1-T5 (đã không có mặt).
```

> **Nếu cần proration thật** (scale target theo thời gian còn lại): Admin tạo officer plan
> riêng với annual_target đã tính sẵn (VD: 150 thay vì 300). Planning engine phân bổ 150
> cho T6-T12 theo weights re-normalized. Hệ thống không auto-prorate — admin quyết định.

### 10.5 Division-by-zero / NULL KPIs

Xem section 1 "Division-by-zero & NULL semantics" cho quy tắc chi tiết.

Tóm tắt: `WD_t=0`, `M_t=0`, `L_t=0`, `C_t=0` → derived KPI = NULL trong `kpi_plan_month` → sync upsert `target_value=0` vào KpiConfig → dashboard hiện target=0 (không fallback default ảo).

---

## 11. Instrumentation: Assignment Decision Log (v2.1 prep)

> **Mục đích**: Chuẩn bị dữ liệu cho fairness allocation v2.1.
> Auto-assign hiện có eligible pool ở runtime nhưng không lưu lại.
> Thêm logging ngay Phase A (không đổi logic assign) để sau có data phân tích.

```sql
CREATE TABLE assignment_decision_log (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id             INTEGER NOT NULL REFERENCES lead(id) ON DELETE CASCADE,
    assigned_officer_id INTEGER REFERENCES "user"(id),       -- NULL nếu không assign được
    decision_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Context snapshot tại thời điểm quyết định
    eligible_officer_ids   INTEGER[] NOT NULL,    -- pool trước khi chọn
    channel                VARCHAR(50),           -- "auto", "manual", "round_robin"
    unit_id                INTEGER REFERENCES organization_unit(id),

    -- Scoring factors (snapshot, không FK)
    scores_snapshot        JSONB,                 -- {"officer_1": 85, "officer_2": 72, ...}
    capacity_snapshot      JSONB,                 -- {"officer_1": {"current": 12, "max": 20}, ...}

    -- Result
    reason                 VARCHAR(200)           -- "lowest_workload", "round_robin", "manual_override"
);

CREATE INDEX idx_assignment_log_lead ON assignment_decision_log(lead_id);
CREATE INDEX idx_assignment_log_officer ON assignment_decision_log(assigned_officer_id);
CREATE INDEX idx_assignment_log_time ON assignment_decision_log(decision_at);
```

> **Phase A**: Thêm bảng + ghi log trong `assignment_service.py` (1 dòng `await log_decision(...)` sau assign).
> **Phase P2** (sau 1-2 tháng data): Dùng log để tính fairness metrics, redistribute workload.

---

## 12. Implementation Phases

### Phase A0: Data Foundation (prerequisite — chạy trước mọi thứ khác)

| Task | Files | Effort |
|------|-------|--------|
| A0-1. Migration: `KpiConfig.target_value` Integer → NUMERIC(12,2) | `alembic/versions/` | S |
| A0-2. Migration: `KpiTarget.kpi_code` `enrollments` → `enrollments_annual`, `KpiConfig.kpi_code` `response_time` → `response_time_hours` | `alembic/versions/` (cùng file) | S |
| A0-3. Migration: Thêm columns `effective_month/effective_year/source_plan_id` vào `kpi_config` + drop 2 unique indexes cũ (`uq_kpi_config_scope`, `ix_kpi_config_unique_combo`) + tạo 3 indexes mới (evergreen, monthly, lookup) | `alembic/versions/` (cùng file) | M |
| A0-4. Schema: `KpiConfigCreate/Response.target_value: int → float` | `app/routers/kpi_config.py` | S |
| A0-5. `get_kpi_target()` return type `int → float` | `app/services/kpi_service.py` | S |
| A0-6. `get_annual_target_progress(kpi_code="enrollments_annual")` | `app/services/kpi_service.py`, `officer_service.py` | S |
| A0-7. Thêm `win_rate: 33` vào `DEFAULT_KPIS` | `app/services/kpi_service.py` | XS |
| A0-8. Frontend: sửa legacy codes trong `admin/kpi-config/page.tsx` (`"response_time"` → `"response_time_hours"`, `"enrollments"` → `"enrollments_annual"`) | `frontend/src/app/(dashboard)/admin/kpi-config/page.tsx` | S |
| A0-9. Frontend: audit int-specific operations trên target values (`%`, `parseInt`, bitwise) | `frontend/src/` | S |
| A0-10. IDOR: thêm unit scope filter cho existing KPI config endpoints (Manager) | `app/routers/kpi_config.py`, `app/core/deps.py` | S |

> **LƯU Ý**: `KpiTarget` và `KpiMonthlySnapshot` GIỮ INTEGER — chỉ đếm enrollment counts.
> Chỉ `KpiConfig.target_value` cần NUMERIC vì chứa cả tỷ lệ (%) lẫn đếm.

### Phase A: Core Engine (MVP)

| Task | Files | Effort |
|------|-------|--------|
| A1. Migration: tạo 4 bảng (kpi_plan, kpi_plan_month, holiday_calendar, assignment_decision_log) + seed holidays + `ALTER TABLE kpi_config ADD CONSTRAINT fk_kpi_config_source_plan FOREIGN KEY (source_plan_id) REFERENCES kpi_plan(id) ON DELETE SET NULL` | `alembic/versions/` | M |
| A2. Models: KpiPlan, KpiPlanMonth, HolidayCalendar, AssignmentDecisionLog | `app/models/config.py`, `app/models/lead.py` | S |
| A3. Calendar service: count_working_days | `app/services/calendar_service.py` | S |
| A4. Planning service: create_plan, generate_monthly_kpis (Largest Remainder + NULL guards) | `app/services/kpi_planning_service.py` | M |
| A5. Planning repository | `app/repositories/kpi_planning_repository.py` | M |
| A6. API endpoints: CRUD plans + preview + IDOR dependencies (section 2.6) | `app/routers/kpi_planning.py`, `app/core/deps.py` | M |
| A7. Sync job: sync_plan_to_kpi_config (với effective_month/year + source_plan_id) | `app/tasks/cache_tasks.py` | M |
| A8. Assignment decision logging: 1-line log trong assignment_service.py | `app/services/assignment_service.py` | XS |
| A9. Holiday status endpoint + Celery yearly check (1/11) | `app/routers/kpi_planning.py`, `app/tasks/cache_tasks.py` | S |

### Phase B: Override & Calibration

| Task | Files | Effort |
|------|-------|--------|
| B1. Override API: per-field override + batch override + reset | `app/routers/kpi_planning.py` | M |
| B2. Historical metrics service: k_t, L_t, C_t from actual data | `app/services/historical_metrics_service.py` | M |
| B3. Auto-calibration: recalibrate_factors with EMA + damping (30%/15%) + fallback | `app/services/kpi_planning_service.py` | M |
| B4. Month-end actuals: fill_month_actuals (6 actual fields) | `app/services/kpi_planning_service.py` | S |
| B5. Enhanced sync job: actuals + recalibrate + sync | `app/tasks/cache_tasks.py` | S |
| B6. Mid-year target change: update_plan with redistribute | `app/services/kpi_planning_service.py` | M |
| B7. Soft-delete cleanup: deactivate_plan (dùng source_plan_id xóa KpiConfig) | `app/services/kpi_planning_service.py` | S |
| B8. `get_kpi_target()` + effective_date param cho historical resolution | `app/services/kpi_service.py`, `app/repositories/kpi_repository.py` | M |

### Phase C: Admin UI

| Task | Files | Effort |
|------|-------|--------|
| C1. Plan creation form (annual target + weights slider + guardrails) | `frontend/src/app/(dashboard)/admin/kpi-planning/` | L |
| C2. Monthly grid view (12 months × 7 KPIs tháng, editable per-field overrides) | `frontend/src/components/admin/kpi-planning/` | L |
| C3. Preview mode: gọi `POST /plans/preview` debounced (300ms), render kết quả. **KHÔNG** tính toán Largest Remainder/KPI trên frontend | Frontend | M |
| C4. Holiday calendar management UI + seed year action | Frontend | M |
| C5. Plan vs Actual comparison report | Frontend | M |
| C6. Clone plan from previous year | Frontend | S |

### Phase P2: Fairness Allocation (sau 1-2 tháng có data)

| Task | Files | Effort |
|------|-------|--------|
| P2-1. Fairness dashboard: phân tích assignment_decision_log | `app/services/fairness_service.py` | M |
| P2-2. Weighted distribution dựa trên capacity + historical fairness | `app/services/assignment_service.py` | L |

### Phase P3: Config-driven Recommendations

| Task | Files | Effort |
|------|-------|--------|
| P3-1. Chuyển THRESHOLDS hardcoded → đọc từ KpiConfig/system config | `app/services/recommendation_engine.py` | M |
| P3-2. Per-scope threshold customization (unit/officer level) | `app/routers/kpi_config.py` | S |

---

## 13. Ví dụ End-to-End

```
0. [Phase A0] Admin chạy migration: KpiConfig.target_value → NUMERIC,
   KpiTarget.kpi_code "enrollments" → "enrollments_annual"
   → Hệ thống hiện tại vẫn hoạt động bình thường (backward compatible)

1. Admin vào "KPI Planning" → chọn Unit "Phòng Tuyển sinh HN"
2. Nhập: Năm 2026, Chỉ tiêu: 300 nhập học
3. Hệ thống auto-fill 12 tháng theo seasonal weights
   → Largest Remainder reconciliation đảm bảo sum(M_t) = 300
4. Admin xem preview → thấy T7: 46 nhập học, 13 tư vấn/ngày
5. Admin override T8: consultations_daily = 16 (lý do: "Chiến dịch tư vấn đặc biệt")
   → overridden_fields = {"consultations_daily": true}
   → win_rate, conversion_rate vẫn auto-recalculate
6. Admin lưu plan → hệ thống tạo KpiPlan + 12 KpiPlanMonth
7. Celery sync ngày 1/T1: push KPI T1 vào KpiConfig
   → KpiConfig.target_value = 16.70 (NUMERIC, conversion_rate)
   → KpiConfig.effective_month = 1, effective_year = 2026
   → KpiConfig.source_plan_id = 42
   → Officer dashboard tự động hiện target mới
8. Cuối T3: Celery fill actuals, recalibrate k_t/L_t/C_t cho T4+
   → Đủ 3 tháng data (T1, T2, T3) → full EMA (0.5/0.3/0.2)
   → Damping ±30% (lần đầu từ default)
   → T4 targets tự adjust theo performance thực tế
9. T6: Admin đổi target 300 → 350
   → remaining = 350 - actual_sum(T1-T5) = 266
   → T6-T12 redistribute 266 theo Largest Remainder
10. T8: sync job thấy overridden_fields có consultations_daily
    → Giữ nguyên 16, recalculate các field khác bình thường
11. T10: Manager xem dashboard tháng 3 (quá khứ)
    → get_kpi_target(effective_date=2026-03-15) → lấy target T3 chính xác
    → Không bị lấy nhầm target T10 hiện tại
12. T12: Admin clone plan sang 2027, điều chỉnh target mới
13. [Phase P2] Sau 2 tháng: phân tích assignment_decision_log
    → Phát hiện Officer A nhận 40% leads, Officer B chỉ 15%
    → Điều chỉnh weighted distribution cho fairness
```

---

## 14. Test Plan

### 14.1 Phase A0: Migration Compatibility

| # | Test case | Verify |
|---|-----------|--------|
| 1 | Migration up/down idempotent | `alembic upgrade head` → `downgrade -1` → `upgrade head` thành công |
| 2 | Existing KpiConfig integer values cast OK | `SELECT target_value FROM kpi_config` trả `10.00`, `85.00` (NUMERIC) |
| 3 | Legacy kpi_codes migrated | KpiTarget: không còn `kpi_code = 'enrollments'` (→ `enrollments_annual`). KpiConfig: không còn `kpi_code = 'response_time'` (→ `response_time_hours`) |
| 4 | Unique constraint evergreen vẫn hoạt động | INSERT 2 evergreen records cùng scope → conflict |
| 5 | Unique constraint monthly cho phép multi-month | INSERT (kpi_code=X, effective_month=1) + (kpi_code=X, effective_month=2) cùng scope → OK |
| 6 | `get_kpi_target()` trả float | Call với legacy data → trả `10.0` thay vì `10` |
| 7 | `get_annual_target_progress(kpi_code="enrollments_annual")` | Trả progress đúng với data migrated |
| 8 | Frontend admin/kpi-config loads OK | Không còn gửi `"response_time"` hoặc `"enrollments"` khi create/edit |

### 14.2 Phase A: Core Engine

| # | Test case | Verify |
|---|-----------|--------|
| 1 | `create_plan()` basic | 300 annual → 12 KpiPlanMonth records, sum(M_t) == 300 |
| 2 | Largest Remainder reconciliation | Weights sum=0.998, annual=300: floor values sum=293, diff=+7 → cộng 1 cho 7 tháng có remainder cao nhất. Weights sum=1.002 → diff<0 → trừ 1 cho tháng remainder thấp nhất |
| 3 | `unit_id` NOT NULL enforced | `create_plan(unit_id=None)` → validation error |
| 4 | Unique index unit plan | 2 active plans cùng unit+year → DB conflict |
| 5 | Unique index officer plan | 2 active officer plans cùng scope → DB conflict |
| 6 | Unit plan uniqueness (officer_id=NULL) | `uix_kpi_plan_active_unit` chặn 2 active unit plans (officer_id IS NULL) cùng unit+year |
| 7 | Working days T2-T7 | Tháng có 5 ngày CN → WD_t = 26 (31-5=26, trừ thêm lễ) |
| 8 | WD_t = 0 → derived NULL | `consultations_daily=NULL`, `conversion_rate=NULL` |
| 9 | Sync NULL → upsert 0 | Plan month derived=NULL → KpiConfig có record `target_value=0` (không skip, không fallback default) |
| 10 | `effective_month/year` ghi đúng | Sync T3 → KpiConfig record có `effective_month=3, effective_year=2026` |
| 11 | Preview endpoint stateless | `POST /plans/preview` → response 200, no DB records created |
| 12 | IDOR: Manager truy cập plan unit khác → 404 | `get_kpi_plan_for_user` raise `ResourceNotFoundError` |
| 13 | IDOR: Manager list plans → chỉ thấy unit mình | Response chỉ chứa plans của unit_id = user.unit_id |
| 14 | Router commits, service doesn't | Mock `db.commit` trong service → never called |

### 14.3 Phase B: Override & Calibration

| # | Test case | Verify |
|---|-----------|--------|
| 1 | Per-field override | Override `consultations_daily` → `overridden_fields = {"consultations_daily": true}` |
| 2 | Override validation | Override không có `reason` (< 5 chars) → 400 |
| 3 | Sync skip overridden field | Regenerate → `consultations_daily` giữ nguyên, `win_rate` recalculate |
| 4 | Reset specific field | Reset `consultations_daily` → removed from `overridden_fields`, recalculated |
| 5 | is_first_calibration detection | Officer chưa có actuals → damping ±30%, có actuals → ±15% |
| 6 | EMA fallback < 3 months | 1 month data → direct value, 2 months → 0.6/0.4 weighted |
| 7 | Mid-year target change | Change 300→350 ở T6, remaining redistribute cho T6-T12 |
| 8 | Celery job timing | `sync_kpi_plan_monthly` scheduled `crontab(hour=2, minute=0, day_of_month=1)` |
| 9 | Job commit-per-plan isolation | Plan A fails → Plan B still syncs OK |

### 14.4 Temporal & Historical Resolution

| # | Test case | Verify |
|---|-----------|--------|
| 1 | `get_kpi_target(effective_date=T3)` | Trả target T3, không phải T6 hiện tại |
| 2 | Evergreen fallback | Xóa monthly records → fallback về evergreen record |
| 3 | DEFAULT_KPIS fallback | Xóa tất cả KpiConfig → trả giá trị hardcoded |
| 4 | No effective_date → current month | Gọi không có param → trả target tháng hiện tại |

### 14.5 Holiday Calendar

| # | Test case | Verify |
|---|-----------|--------|
| 1 | `GET /holidays/status/2027` incomplete | `is_complete=false`, `has_lunar_holidays=false` |
| 2 | Seed recurring holidays | `POST /holidays/seed/2027` → copy 1/1, 30/4, 1/5, 2/9 |
| 3 | Celery yearly check | Chạy 1/11 → notification khi < 8 ngày lễ cho năm kế |

---

## 15. Daily KPIs — Ops + Quality

> **Scope**: 7 KPI ngày bổ sung cho officer dashboard.
> Không cần migration mới — tất cả data source đã tồn tại.
> Chỉ cần thêm repository methods, service logic, schema fields, frontend cards.

### 15.1 Tổng quan

| Nhóm | KPI code | Tên | Công thức |
|------|----------|-----|-----------|
| **Ops** | `consultations_today` | Số tư vấn trong ngày | `H_D = count(consultation)` ngày D |
| **Ops** | `consultations_target` | Chỉ tiêu tư vấn/ngày | Từ `get_kpi_target()` inheritance chain |
| **Quality** | `verified_consultations_daily` | Tư vấn hợp lệ/ngày | `V_D = count(DISTINCT lead_id)` ngày D, lọc chất lượng |
| **Quality** | `quality_rate_daily` | Tỷ lệ tư vấn chất lượng | `V_D / H_D × 100` |
| **Quality** | `followup_commitment_rate` | Tỷ lệ có cam kết follow-up | `F_D / V_D_non_final × 100` |
| **Quality-Rolling** | `progress_rate_d7` | Tỷ lệ tiến triển sau 7 ngày | `% leads trong V_D có progress trong D..D+7` |
| **Quality-Rolling** | `rollback_rate_d3` | Tỷ lệ tụt trạng thái sau 3 ngày | `% leads trong V_D bị rollback trong D..D+3` |

### 15.2 Quy tắc chống gian lận (chốt)

| # | Quy tắc | Lý do |
|---|---------|-------|
| 1 | Loại `method = 'system'` (NULL-safe) | Dùng `IS DISTINCT FROM 'system'` (không phải `!=`). `method` nullable trong model (`lead.py:280`). SQL `NULL != 'system'` = NULL → bị loại nhầm. `IS DISTINCT FROM` giữ NULL records |
| 2 | `verified_consultations_daily` đếm `DISTINCT lead_id` | Chống spam nhiều log cho cùng 1 lead trong ngày |
| 3 | Không dùng `duration_minutes` làm điều kiện bắt buộc | Dễ fake, khó validate. System consultations đã có `duration_minutes=0` |
| 4 | Rolling KPIs (`progress_rate_d7`, `rollback_rate_d3`) có độ trễ | Dữ liệu D+7/D+3 cần thời gian thu thập. UI hiển thị data từ 7/3 ngày trước |

### 15.3 Chi tiết từng KPI

#### Timezone convention (áp dụng tất cả query ngày)

> **Chốt**: Business day = `Asia/Ho_Chi_Minh` (UTC+7).
> Tất cả query ngày dùng **range [day_start, day_end)** thay vì `DATE(...)`.
> Lý do: `DATE(timestamptz)` phụ thuộc session timezone, kém index.

```python
# Python helper — dùng cho tất cả query bên dưới
from zoneinfo import ZoneInfo
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
day_start = datetime(year, month, day, tzinfo=VN_TZ)  # 00:00:00+07
day_end = day_start + timedelta(days=1)                # 00:00:00+07 ngày kế
# Query: WHERE c.consultation_date >= :day_start AND c.consultation_date < :day_end
```

#### `consultations_today` (H_D)

```sql
SELECT COUNT(*)
FROM consultation c
WHERE c.consultation_date >= :day_start AND c.consultation_date < :day_end  -- range, index-friendly
  AND c.officer_id = :officer_id
  AND c.deleted_at IS NULL
  AND c.method IS DISTINCT FROM 'system'  -- NULL-safe: method=NULL vẫn pass
```

> **Đã có sẵn** trong `officer_service.get_enhanced_dashboard_stats()`.
> ⚠️ **Code hiện tại CHƯA filter** `method != 'system'` — đang đếm tất cả consultations
> bao gồm cả system-generated từ admission flow (`admission_service.py:820`).
> Task D5 bắt buộc implement filter này trước khi ship Daily Quality KPIs.

#### `consultations_target`

```python
target = await kpi_service.get_kpi_target(
    db, kpi_code="consultations_daily",
    officer_id=officer_id, unit_id=unit_id,
    period_type="daily"
)
```

> **Đã có sẵn**. Không cần thay đổi.

#### `verified_consultations_daily` (V_D)

**Định nghĩa**: Số lead DISTINCT được tư vấn hợp lệ trong ngày D.

**Điều kiện "hợp lệ"**:
1. `method != 'system'` — loại consultation tự động
2. `deleted_at IS NULL` — loại soft-deleted
3. `consultation_status.counts_for_funnel = TRUE` — status có ý nghĩa phễu
4. `consultation_status.updates_pipeline = TRUE` — status thay đổi pipeline
5. Có `lead_status_history` entry cho cùng `lead_id` trong cùng ngày D **(Phương án A)**

```sql
SELECT COUNT(DISTINCT c.lead_id)
FROM consultation c
JOIN consultation_status cs ON c.consultation_status_id = cs.id
WHERE c.consultation_date >= :day_start AND c.consultation_date < :day_end
  AND c.officer_id = :officer_id
  AND c.deleted_at IS NULL
  AND c.method IS DISTINCT FROM 'system'  -- NULL-safe: method=NULL vẫn pass
  AND cs.counts_for_funnel = TRUE
  AND cs.updates_pipeline = TRUE
  AND EXISTS (
      SELECT 1 FROM lead_status_history lsh
      WHERE lsh.lead_id = c.lead_id
        AND lsh.changed_at >= :day_start AND lsh.changed_at < :day_end
  )
```

> **Lưu ý**: `DISTINCT lead_id` — officer tư vấn lead X 3 lần trong ngày → đếm 1.
> Lead X tư vấn lại vào ngày khác → đếm 1 lần cho ngày đó. Đây là hành vi mong muốn.

#### `quality_rate_daily`

```python
quality_rate = (V_D / H_D * 100) if H_D > 0 else None
# NULL khi không có tư vấn nào trong ngày → UI hiển thị "N/A"
```

#### `followup_commitment_rate`

**Định nghĩa**: Trong tập V_D non-final, bao nhiêu % có `scheduled_at` hợp lệ.

**"Hợp lệ"** = `scheduled_at IS NOT NULL AND scheduled_at > consultation_date`

```sql
-- Tử số: verified non-final consultations có follow-up hẹn lịch
SELECT COUNT(DISTINCT c.lead_id)
FROM consultation c
JOIN consultation_status cs ON c.consultation_status_id = cs.id
WHERE c.consultation_date >= :day_start AND c.consultation_date < :day_end
  AND c.officer_id = :officer_id
  AND c.deleted_at IS NULL
  AND c.method IS DISTINCT FROM 'system'  -- NULL-safe: method=NULL vẫn pass
  AND cs.counts_for_funnel = TRUE
  AND cs.updates_pipeline = TRUE
  AND cs.is_final = FALSE                          -- chỉ non-final
  AND c.scheduled_at IS NOT NULL                   -- có hẹn follow-up
  AND c.scheduled_at > c.consultation_date         -- hẹn sau thời điểm tư vấn
  AND EXISTS (
      SELECT 1 FROM lead_status_history lsh
      WHERE lsh.lead_id = c.lead_id
        AND lsh.changed_at >= :day_start AND lsh.changed_at < :day_end
  )

-- Mẫu số: V_D_non_final = verified consultations non-final (query tương tự, bỏ scheduled_at conditions)
```

#### `progress_rate_d7`

**Định nghĩa**: Trong tập lead_ids của V_D, bao nhiêu % có tiến triển trong 7 ngày.

**"Tiến triển"** = bất kỳ điều nào sau, VỚI điều kiện outcome không âm:
- `new_pipeline_stage.order > old_pipeline_stage.order` **VÀ** outcome không phải `'negative'` (loại case lên stage nhưng kết quả xấu, VD: chuyển sang stage "Lost" có order cao)
- `new_consultation_status.is_final = TRUE AND outcome_type = 'positive'` (vào final tích cực)

```sql
-- Bước 1: Lấy V_D lead_ids (từ query verified_consultations_daily)
-- Bước 2: Đếm leads có progress
SELECT COUNT(DISTINCT lsh.lead_id)
FROM lead_status_history lsh
JOIN pipeline_stage old_ps ON lsh.old_pipeline_stage_id = old_ps.id
JOIN pipeline_stage new_ps ON lsh.new_pipeline_stage_id = new_ps.id
WHERE lsh.lead_id IN (:verified_lead_ids_day_D)
  AND lsh.changed_at > :day_D_end                      -- sau ngày tư vấn
  AND lsh.changed_at <= :day_D_end + INTERVAL '7 days'  -- trong 7 ngày
  AND (
      (new_ps."order" > old_ps."order"                  -- stage tiến lên
       AND NOT EXISTS (                                 -- nhưng KHÔNG phải outcome âm
           SELECT 1 FROM consultation_status cs_neg
           WHERE cs_neg.id = lsh.new_consultation_status_id
             AND cs_neg.outcome_type = 'negative'
       ))
      OR (new_ps.is_final_stage = TRUE                  -- hoặc vào final positive
          AND EXISTS (
              SELECT 1 FROM consultation_status cs2
              WHERE cs2.id = lsh.new_consultation_status_id
                AND cs2.outcome_type = 'positive'
          ))
  )

-- progress_rate = progress_count / total_V_D × 100
```

> **UI notice**: "Tỷ lệ tiến triển — dữ liệu tính từ 7 ngày trước"
> Khi hiển thị hôm nay (D=today), thực tế hiện data cho D=today-7.

#### `rollback_rate_d3`

**Định nghĩa**: Trong tập lead_ids của V_D, bao nhiêu % bị tụt trạng thái trong 3 ngày.

**"Tụt"** = `new_pipeline_stage.order < old_pipeline_stage.order` (xuống stage thấp hơn)

```sql
SELECT COUNT(DISTINCT lsh.lead_id)
FROM lead_status_history lsh
JOIN pipeline_stage old_ps ON lsh.old_pipeline_stage_id = old_ps.id
JOIN pipeline_stage new_ps ON lsh.new_pipeline_stage_id = new_ps.id
WHERE lsh.lead_id IN (:verified_lead_ids_day_D)
  AND lsh.changed_at > :day_D_end
  AND lsh.changed_at <= :day_D_end + INTERVAL '3 days'
  AND new_ps."order" < old_ps."order"                   -- stage tụt xuống

-- rollback_rate = rollback_count / total_V_D × 100
```

> **KHÔNG dùng `changed_by_user_id IS NULL`** làm tiêu chí loại trừ.
> Nhiều system-like transitions vẫn có actor user (VD: admission flow projections
> ghi `actor.id` dù là system action). Bám theo stage order thuần túy.

> **Tính gross rollback**: Lead tụt rồi lên lại trong 3 ngày → vẫn đếm rollback.
> Net rollback quá phức tạp cho MVP.

### 15.4 Data Sources — xác nhận tồn tại

| Data | Model | Field | Indexed? | Ref |
|------|-------|-------|----------|-----|
| Consultation date | `Consultation` | `consultation_date` | ✅ | `lead.py:270` |
| Consultation method | `Consultation` | `method` (String, có `"system"`) | ❌ | `lead.py:280` |
| Scheduled follow-up | `Consultation` | `scheduled_at` | ✅ | `lead.py:277` |
| Soft delete | `Consultation` | `deleted_at` | ✅ | `lead.py:290` |
| Funnel counting | `ConsultationStatus` | `counts_for_funnel` (Boolean) | ❌ | `pipeline.py:188` |
| Pipeline update | `ConsultationStatus` | `updates_pipeline` (Boolean) | ❌ | `pipeline.py:179` |
| Final status | `ConsultationStatus` | `is_final` (Boolean) | ❌ | `pipeline.py:144` |
| Outcome type | `ConsultationStatus` | `outcome_type` (String) | ❌ | `pipeline.py:152` |
| Stage order | `PipelineStage` | `order` (Integer, unique) | ✅ (implicit) | `pipeline.py:79` |
| History timestamp | `LeadStatusHistory` | `changed_at` | ✅ | `lead_history.py:21` |
| History stages | `LeadStatusHistory` | `old/new_pipeline_stage_id` | ✅ | `lead_history.py:42-47` |
| System consultation | `admission_service` | `method="system"` | — | `admission_service.py:826` |

### 15.5 Performance indexes (khuyến nghị cho production)

```sql
-- Consultation: query theo ngày + officer thường xuyên
CREATE INDEX idx_consultation_daily_officer
ON consultation (officer_id, consultation_date)
WHERE deleted_at IS NULL;

-- Consultation: filter method != 'system' (nếu tỷ lệ system cao)
-- Không bắt buộc cho MVP, cân nhắc khi system consultations > 10% total

-- LeadStatusHistory: rolling window queries (D+3, D+7)
-- changed_at đã indexed. lead_id đã indexed. Đủ cho MVP.
-- Nếu chậm ở scale lớn → composite index:
CREATE INDEX idx_lsh_lead_changed
ON lead_status_history (lead_id, changed_at);
```

### 15.6 Implementation tasks

| Task | Files | Effort |
|------|-------|--------|
| D1. Repository: `count_human_consultations_daily()`, `count_verified_consultations_daily()` | `app/repositories/officer_repository.py` | S |
| D2. Repository: `get_followup_commitment_stats()` | `app/repositories/officer_repository.py` | S |
| D3. Repository: `get_progress_rate_d7()`, `get_rollback_rate_d3()` | `app/repositories/officer_repository.py` | M |
| D4. Service: thêm 5 quality KPIs vào `get_enhanced_dashboard_stats()` | `app/services/officer_service.py` | M |
| D5. Service: filter `method != 'system'` cho `consultations_today` hiện tại | `app/services/officer_service.py` | XS |
| D6. Schema: thêm 5 fields vào `KPIStats` | `app/schemas/officer.py` | S |
| D7. Frontend type: thêm 5 fields vào `KPIStats` interface | `frontend/src/hooks/useDashboardStats.ts` | S |
| D8. Frontend UI: Quality metrics section trong `KPICardsGrid` | `frontend/src/components/officer/dashboard/KPICardsGrid.tsx` | M |
| D9. Performance indexes (optional) | `alembic/versions/` | S |

> **Thứ tự khuyến nghị**: D5 → D1 → D6 → D7 (có thể ship riêng, dashboard hiện quality)
> → D2 → D3 → D4 → D8 (ship rolling metrics sau)

### 15.7 Schema changes

```python
# app/schemas/officer.py — thêm vào class KPIStats:

# Daily Quality KPIs
verified_consultations_daily: int = 0
quality_rate_daily: Optional[float] = None     # NULL khi H_D = 0
followup_commitment_rate: Optional[float] = None  # NULL khi V_D_non_final = 0

# Rolling Quality KPIs (data có độ trễ 7/3 ngày)
progress_rate_d7: Optional[float] = None       # NULL khi chưa đủ data
progress_rate_d7_date: Optional[date] = None   # Ngày D thực tế (today - 7)
rollback_rate_d3: Optional[float] = None       # NULL khi chưa đủ data
rollback_rate_d3_date: Optional[date] = None   # Ngày D thực tế (today - 3)
```

```typescript
// frontend/src/hooks/useDashboardStats.ts — thêm vào KPIStats interface:

verified_consultations_daily: number;
quality_rate_daily: number | null;
followup_commitment_rate: number | null;

progress_rate_d7: number | null;
progress_rate_d7_date: string | null;  // ISO date, hiển thị "Dữ liệu ngày DD/MM"
rollback_rate_d3: number | null;
rollback_rate_d3_date: string | null;
```
