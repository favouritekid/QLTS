# Q9 #07 PR5 Redesign — Temporal Multi-School KV Resolution

**Status**: DRAFT v1.3 2026-05-18 — 2-field parallel (cultural + vocational) correction per VN admission convention (supersedes v1.2 single `diploma_submitted` enum); supersedes PR5 candidate FE commit `a58d2eb2` (reset)
**Owner**: solo dev
**Replaces**: PR1 single `high_school_id` design + PR4 single-table import + PR5 single-field PriorityTab

---

## Why redesign

PR5 candidate FE (commit `a58d2eb2`) đã viết `PriorityTab.tsx` với **1 field `high_school_id` duy nhất**. Sau khi audit TT 05/2021/TT-BLĐTBXH Phụ lục 01 + user feedback, phát hiện 3 vấn đề:

### 1. TT 05/2021 yêu cầu rule "thời gian học dài nhất"

Verbatim TT Phụ lục 01:
> "Nếu chuyển trường, **thời gian học ở khu vực nào lâu hơn được hưởng ưu tiên theo khu vực đó**."
>
> "Khi mỗi năm học một trường thuộc các khu vực có mức ưu tiên khác nhau hoặc nửa thời gian học ở trường này, nửa thời gian học ở trường kia thì **tốt nghiệp ở khu vực nào, hưởng ưu tiên theo khu vực đó**."

→ Không thể derive KV từ 1 trường. Cần multi-school history với weighted resolution.

### 2. Pathway theo **2 field PARALLEL** — Trình độ văn hóa + Trình độ chuyên môn

**Correction 2026-05-18 v1.3**: Theo VN admission convention (Luật GDNN 2014/2025 + TT 05/2021 Điều 4), candidate khai 2 dimension **độc lập song song**, KHÔNG phải 1 enum diploma:

#### **Trình độ văn hóa** (`cultural_education_level`) — required
Cấp giáo dục PHỔ THÔNG candidate đã hoàn thành/tốt nghiệp:
- `completed_thcs` — Hoàn thành THCS (đã học lớp 9 nhưng CHƯA được cấp bằng — rare case: dropout giữa năm hoặc chuyển TC trước thi tốt nghiệp; N2 verified per VN reality hiếm gặp)
- `graduated_thcs` — **Tốt nghiệp THCS** (có bằng — common case)
- `completed_thpt` — Hoàn thành THPT (đủ kiến thức văn hóa, chưa thi tốt nghiệp — TT 05/2021 Điều 4 lối 2 cho CĐ liên thông yêu cầu giấy CN này)
- `graduated_thpt` — **Tốt nghiệp THPT** (có bằng — common)
- `graduated_gdtx` — Tốt nghiệp GDTX (tương đương Tốt nghiệp THPT theo Luật GDNN)

#### **Trình độ chuyên môn** (`vocational_qualification`) — optional, default `none`
Cấp NGHỀ NGHIỆP candidate đã tốt nghiệp (nếu có):
- `none` — Chưa có (default)
- `so_cap` — Tốt nghiệp Sơ cấp (3-12 tháng)
- `trung_cap` — Tốt nghiệp Trung cấp (1-2 năm)
- `cao_dang` — Tốt nghiệp Cao đẳng (2-3 năm)

#### Cấp mới future-proof: Trung học nghề
Dự thảo TT 2026 BGDĐT thêm cấp "Trung học nghề" (THPT + TC nghề combined). Schema `vn_school.level` enum + academic_history `level` field add value `'TRUNG_HOC_NGHE'`.

#### Multi-school rule (TT 05/2021 Phụ lục 01 verbatim)
> "Nếu trong **3 năm học trung học phổ thông (hoặc trong thời gian học trung cấp)** có chuyển trường thì thời gian học ở khu vực nào lâu hơn được hưởng ưu tiên"

→ Rule áp dụng cho **THPT** (3 năm) HOẶC **TC** (thời gian học), KHÔNG có rule THCS-multi-school.

#### KV resolution basis derivation matrix (COMPLETE — v1.3 C3 fix)

| # | Cultural | Vocational | Basis | Pathway | Eligibility |
|---|---|---|---|---|---|
| 1 | `graduated_thpt` / `graduated_gdtx` | any | **THPT** | `thpt_multi_school` | CĐ + TC both OK |
| 2 | `completed_thpt` | `trung_cap` / `cao_dang` | **THPT** (if history) ELSE **TC** | `thpt_multi_school` OR `tc_multi_school` | CĐ liên thông OK (TT path 2) |
| 3 | `completed_thpt` | `so_cap` / `none` | **COMMUNE_FALLBACK** | `commune_fallback` | TC eligible (THPT kiến thức = equiv); CĐ FAIL eligibility |
| 4 | `graduated_thcs` | `trung_cap` / `cao_dang` | **TC** | `tc_multi_school` | TC OK; CĐ FAIL (cần văn hóa THPT) |
| 5 | `graduated_thcs` | `so_cap` / `none` | **COMMUNE_FALLBACK** | `commune_fallback` | TC OK; CĐ FAIL |
| 6 | `completed_thcs` | any | **COMMUNE_FALLBACK** | `commune_fallback` | TC FAIL (cần Tốt nghiệp THCS); CĐ FAIL |
| 7 | `None` (chưa khai) | any | **NOT_RESOLVED** | `not_resolved` | N/A — draft state |
| 8 | (any) + `area_resolution_basis='permanent_address_special'` | bypass | **COMMUNE_SPECIAL** | `commune_special` | 4 cases TT 05/2021 |
| 9 | (any) + `area_resolution_basis='manual_override'` | bypass | **MANUAL** | `manual_override` | Admin/officer fill |

**Note**: Matrix rows 3, 4, 5, 6 có thể trigger KV resolve nhưng FAIL eligibility tại submit T1. KV resolution và eligibility là **2 concern độc lập** (xem decoupling note dưới).

#### Helper `_derive_kv_basis_level()` — C1 fix

```python
from typing import Optional

def _derive_kv_basis_level(
    cultural: Optional[str],
    vocational: str,
    area_resolution_basis: Optional[str] = None,
) -> str:
    """
    Map (cultural, vocational, area_basis) → KV resolution basis per
    TT 05/2021 Phụ lục 01 multi-school rules.

    Returns one of:
      'THPT'              — apply 3-year THPT multi-school rule (rows 1, 2)
      'TC'                — apply TC time multi-school rule (rows 2 fallthrough, 4)
      'COMMUNE_FALLBACK'  — THCS only / so_cap / completed_thpt+none (rows 3, 5, 6)
      'COMMUNE_SPECIAL'   — 4 special cases bypass (row 8)
      'MANUAL'            — admin override (row 9)
      'NOT_RESOLVED'      — cultural chưa khai (row 7, draft)
    """
    # Row 8/9: area_resolution_basis overrides matrix
    if area_resolution_basis == 'permanent_address_special':
        return 'COMMUNE_SPECIAL'
    if area_resolution_basis == 'manual_override':
        return 'MANUAL'

    # Row 7: cultural not set (draft state)
    if cultural is None:
        return 'NOT_RESOLVED'

    # Rows 1, 2 (partial): THPT pathway
    if cultural in ('graduated_thpt', 'graduated_gdtx', 'completed_thpt'):
        # Row 1 + Row 2 if THPT history sufficient → THPT
        # Row 2 fallthrough if no THPT history → TC handled by caller
        # Row 3 (completed_thpt + so_cap/none) → COMMUNE_FALLBACK
        if cultural == 'completed_thpt' and vocational in ('so_cap', 'none'):
            return 'COMMUNE_FALLBACK'  # Row 3
        return 'THPT'  # Rows 1, 2

    # Rows 4, 5: graduated_thcs + vocational branching
    if cultural == 'graduated_thcs':
        if vocational in ('trung_cap', 'cao_dang'):
            return 'TC'  # Row 4
        return 'COMMUNE_FALLBACK'  # Row 5

    # Row 6: completed_thcs (any vocational) → fallback
    if cultural == 'completed_thcs':
        return 'COMMUNE_FALLBACK'

    # Defensive: unknown cultural (shouldn't happen due to CHECK enum)
    return 'NOT_RESOLVED'
```

#### Decoupling note — C2 fix

**KV resolution và eligibility check là 2 concern độc lập**:

- `resolve_kv_for_profile(profile)`: tính KV theo combination hiện tại của profile (draft/submitted/T6)
- `validate_eligibility(profile, target_level)`: gate profile submit/approval based on target program

Flow:
1. **Draft state**: candidate edit form → KV resolve real-time hiển thị preview (ngay cả khi combo fail eligibility — show "Sẽ KHÔNG đủ điều kiện CĐ" warning)
2. **Submit T1**: eligibility check chạy TRƯỚC KV freeze. Nếu fail → reject submit (HTTP 422); KV snapshot KHÔNG fire.
3. **Engine T6**: chỉ chạy cho profile đã submit thành công → eligibility đã pass.

→ KV resolution KHÔNG cần guard `_passes_eligibility()` because flow guarantee: invalid combos KHÔNG bao giờ reach T6 freeze.

Tuy nhiên, FE PriorityTab nên show eligibility warning kết hợp KV preview để candidate sửa trước khi submit (UX defense).

**4 special cases bypass** (TT 05/2021): PT DTNT / lớp dự bị / quân nhân / xuất ngũ → `permanent_commune_code`.

#### Eligibility validation (NEW v1.3)

System validate target program against (cultural, vocational):

```python
def validate_eligibility(profile, target_level):
    """target_level: 'so_cap' | 'trung_cap' | 'cao_dang' | 'trung_hoc_nghe'"""
    cultural = profile.cultural_education_level
    vocational = profile.vocational_qualification

    if target_level == 'cao_dang':
        # Lối 1: Tốt nghiệp THPT
        if cultural in ('graduated_thpt', 'graduated_gdtx'):
            return None
        # Lối 2: TC + chứng nhận văn hóa THPT (per TT 05/2021)
        if vocational == 'trung_cap' and cultural in ('completed_thpt', 'graduated_thpt'):
            return None
        return "Cao đẳng yêu cầu Tốt nghiệp THPT HOẶC Tốt nghiệp TC + chứng nhận văn hóa THPT"

    if target_level == 'trung_cap':
        # Tốt nghiệp THCS và tương đương trở lên
        if cultural in ('graduated_thcs', 'completed_thpt', 'graduated_thpt', 'graduated_gdtx'):
            return None
        return "Trung cấp yêu cầu tối thiểu Tốt nghiệp THCS"

    # so_cap + trung_hoc_nghe: accept all (theo dự thảo TT 2026, chưa có quy định cụ thể)
    return None
```

#### THCS KV strategy (giữ nguyên v1.2)
- `vn_school` table chứa cả THCS + THPT + TRUNG_HOC_NGHE entries
- THCS school KV derive at import time từ school's `ward_code` → `vn_commune_area_map` → KV (QĐ 861 chain)
- Frozen snapshot pattern (xem Phase B.3)

### 3. Trường THPT có "slowly-changing dimensions"

- **Tên trường** có thể đổi (vd sát nhập 2 trường thành 1)
- **KV của trường** có thể đổi qua các năm (TT mới, thay đổi địa giới hành chính)
- **Trường có thể bị sát nhập / giải thể**

→ Schema phải lookup KV **theo thời điểm học** (academic_year), không phải theo state hiện tại.

---

## Schema design

### Table: `vn_school` (master directory)

Replace existing `vn_high_school` (empty, deployed nhưng chưa dùng).

```sql
CREATE TABLE vn_school (
    id BIGSERIAL PRIMARY KEY,

    -- MOET reference (Bộ GD-ĐT 21/4/2025)
    moet_school_code VARCHAR(10) NOT NULL,
    moet_province_code VARCHAR(3) NOT NULL,
    moet_district_code VARCHAR(5),

    -- Canonical / current info (slowly-changing → see vn_school_name_history)
    name VARCHAR(255) NOT NULL,
    address TEXT,
    province VARCHAR(100) NOT NULL,
    district VARCHAR(100),
    ward VARCHAR(100),

    -- Level support: cả THCS + THPT + Trung học nghề (dự thảo TT 2026)
    level VARCHAR(20) NOT NULL,  -- 'THCS' | 'THPT' | 'THCS_THPT' | 'TRUNG_HOC_NGHE' | 'OTHER'
    is_dtnt BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,

    -- Merger / dissolution tracking
    merged_into_id BIGINT REFERENCES vn_school(id),
    merge_effective_date DATE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (level IN ('THCS', 'THPT', 'THCS_THPT', 'TRUNG_HOC_NGHE', 'OTHER'))
);

-- Active records: unique per province + MOET code
CREATE UNIQUE INDEX uq_vn_school_moet_code_active
    ON vn_school(moet_province_code, moet_school_code)
    WHERE is_active = true;

-- Fuzzy name search (PR4 candidate FE dropdown)
CREATE INDEX ix_vn_school_name_trgm
    ON vn_school USING gin (name gin_trgm_ops);
```

### Table: `vn_school_name_history` (đổi tên)

```sql
CREATE TABLE vn_school_name_history (
    id BIGSERIAL PRIMARY KEY,
    school_id BIGINT NOT NULL REFERENCES vn_school(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    notes TEXT,

    UNIQUE(school_id, effective_from)
);

-- Lookup: tên trường tại 1 năm cụ thể
CREATE INDEX ix_vn_school_name_history_lookup
    ON vn_school_name_history(school_id, effective_from);
```

Query pattern:
```sql
SELECT name FROM vn_school_name_history
WHERE school_id = :sid
  AND effective_from <= :date
  AND (effective_to IS NULL OR effective_to >= :date)
ORDER BY effective_from DESC LIMIT 1;
```

### Table: `vn_school_kv_assignment` (KV theo năm)

Trọng tâm của redesign — temporal lookup table.

```sql
CREATE TABLE vn_school_kv_assignment (
    id BIGSERIAL PRIMARY KEY,
    school_id BIGINT NOT NULL REFERENCES vn_school(id) ON DELETE CASCADE,

    -- KV applicable trong khoảng năm này
    kv_code VARCHAR(20) NOT NULL,
    effective_from_year INTEGER NOT NULL,  -- vd 2023 = năm học 2023-2024
    effective_to_year INTEGER,              -- NULL = ongoing

    source VARCHAR(50) NOT NULL,  -- 'moet_2024' | 'moet_2025' | 'manual_admin'
    notes TEXT,
    created_by INTEGER REFERENCES "user"(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (kv_code ~ '^KV[1-9](-NT)?$'),
    CHECK (effective_to_year IS NULL OR effective_to_year >= effective_from_year),

    -- M3 simplification: drop EXCLUDE GiST constraint (btree_gist
    -- extension dependency + ORM mirror complexity + test DB
    -- create_all incompatibility). Replace với index + service-layer
    -- overlap check.
);

CREATE INDEX ix_vn_school_kv_lookup
    ON vn_school_kv_assignment(school_id, effective_from_year DESC);
```

**Service-layer overlap check** (replaces EXCLUDE constraint per M3 review fix):
```python
async def add_kv_assignment(db, school_id, kv_code, effective_from_year, effective_to_year=None):
    """Reject if overlaps existing assignment for same school."""
    overlapping = await db.execute(
        select(VnSchoolKvAssignment)
        .where(
            VnSchoolKvAssignment.school_id == school_id,
            VnSchoolKvAssignment.effective_from_year <= (effective_to_year or 9999),
            or_(
                VnSchoolKvAssignment.effective_to_year.is_(None),
                VnSchoolKvAssignment.effective_to_year >= effective_from_year,
            ),
        )
        .limit(1)
    )
    if overlapping.first():
        raise ValidationError(
            f"KV assignment overlap cho school_id={school_id} năm {effective_from_year}"
        )
    db.add(VnSchoolKvAssignment(...))
```

Trade-off accepted: lose DB-level guarantee, gain ORM compat + test DB compat + memory `migration-predicate-safety` alignment. Admin write path 100% via service → guarded.

Query pattern (canonical KV lookup):
```sql
SELECT kv_code
FROM vn_school_kv_assignment
WHERE school_id = :school_id
  AND :academic_year BETWEEN effective_from_year
      AND COALESCE(effective_to_year, 9999)
LIMIT 1;
```

### `admission_profile.academic_history` JSONB shape (mở rộng existing)

```typescript
{
  // Existing fields (giữ nguyên backward compat)
  school_name: string,        // Free-text snapshot at submit time
  year_from: number,          // Năm bắt đầu (vd 2022)
  year_to: number,            // Năm kết thúc (vd 2025)
  gpa: number | null,
  graduation_type: string | null,

  // NEW fields cho KV resolution (Q9 #07 PR5 redesign)
  school_id: number | null,           // FK to vn_school.id (null = manual entry chưa match)
  level: 'THCS' | 'THPT' | 'OTHER',   // Cấp học
  grade_from: number,                 // Lớp bắt đầu (6/7/8/9 hoặc 10/11/12)
  grade_to: number,                   // Lớp kết thúc

  // Snapshot at profile-submit time (audit-safe, frozen)
  kv_at_attendance_snapshot?: {
    by_year: Record<number, string>,  // { 2022: 'KV1', 2023: 'KV1', ... }
    school_name_at_time: string,      // Tên trường tại thời điểm học
    resolved_at: string,              // ISO datetime
  } | null
}
```

### Drop columns trên `admission_profile`

```sql
ALTER TABLE admission_profile
    DROP COLUMN high_school_id,            -- PR1 phase1_08b — empty, no candidate data
    DROP COLUMN high_school_kv_resolved,   -- PR1 phase1_08b — empty
    DROP COLUMN area_resolution_reason;    -- canonical moved to priority_resolution_snapshot.manual_override_reason
```

Lý do: KV không còn là 1 field flat. Đã thay bằng:
- `academic_history[].school_id` (multi-entry)
- Snapshot computed result vào `priority_resolution_snapshot` JSONB column (xem dưới)

### Note: `area_resolution_basis` column status (N4 fix)

**KEEP existing column** từ PR1 phase1_08b — KHÔNG drop. Vẫn dùng cho:
- Default value: `'high_school'` — KV auto-derive từ academic_history
- Value `'permanent_address_special'` — trigger 4 special cases bypass (row 8 matrix)
- Value `'manual_override'` — trigger admin/officer override (row 9 matrix)

Algorithm `resolve_kv_for_profile` reads `area_resolution_basis` ở step 1 (xem helper `_derive_kv_basis_level`).

Drop chỉ `area_resolution_reason` (text) — canonical moved vào `priority_resolution_snapshot.manual_override_reason`.

### Add columns trên `admission_profile` (v1.3 — 2-field parallel)

```sql
ALTER TABLE admission_profile
    ADD COLUMN cultural_education_level VARCHAR(30),
    ADD COLUMN vocational_qualification VARCHAR(30) NOT NULL DEFAULT 'none';

-- CHECK constraints (mirror phase1_09 migration)
ALTER TABLE admission_profile
    ADD CONSTRAINT ck_cultural_education_level CHECK (
        cultural_education_level IS NULL OR cultural_education_level IN (
            'completed_thcs', 'graduated_thcs',
            'completed_thpt', 'graduated_thpt', 'graduated_gdtx'
        )
    ),
    ADD CONSTRAINT ck_vocational_qualification CHECK (
        vocational_qualification IN ('none', 'so_cap', 'trung_cap', 'cao_dang')
    );
```

- `cultural_education_level` nullable — candidate có thể chưa chọn ở draft state
- `vocational_qualification` NOT NULL DEFAULT `'none'` — auto fill cho 315 legacy + new profiles
- Both fields read on submit → eligibility validation + KV basis derivation

### NEW column: `admission_profile.priority_resolution_snapshot`

Frozen kết quả compute KV tại submit time + breakdown for audit.

```sql
ALTER TABLE admission_profile
    ADD COLUMN priority_resolution_snapshot JSONB DEFAULT '{}'::jsonb;
```

Shape (N3 standardized 2026-05-18 — separate `rule_applied` HOW vs `pathway` WHICH branch):
```typescript
{
  kv_resolved: 'KV1' | 'KV2' | 'KV2-NT' | 'KV3' | null,
  // rule_applied = HOW final value was decided
  rule_applied:
    | 'longest_duration'           // single KV winner by max years
    | 'tiebreak_graduation_school' // tied → graduation school KV wins
    | 'commune_lookup'             // fallback to permanent_commune_code
    | 'manual_override'            // admin/officer fill
    | 'ambiguous_requires_manual', // M1 edge: 2 graduation schools tied
  // pathway = WHICH matrix branch fired (audit which row of matrix)
  pathway:
    | 'thpt_multi_school'    // Rows 1, 2 (full THPT history)
    | 'tc_multi_school'      // Rows 2-fallthrough, 4 (TC time)
    | 'commune_fallback'     // Rows 3, 5, 6 (THCS only / so_cap / completed_thpt+none)
    | 'commune_special'      // Row 8 (4 special cases)
    | 'manual'               // Row 9 (admin override)
    | 'not_resolved',        // Row 7 (cultural chưa khai - draft)
  breakdown: {
    target_level: 'THPT' | 'TC' | 'COMMUNE',
    entries: Array<{
      school_id: number,
      school_name_at_time: string,
      year_from: number,
      year_to: number,
      years_by_kv: Array<{ year: number, kv: string }>
    }>,
    kv_totals: Record<string, number>,  // { 'KV1': 2, 'KV3': 1 }
    winner_years: number,
    tied_kv?: string[],
    graduation_school_id?: number,
    graduation_year?: number,
    tied_entries?: number[],  // M1: 2 schools cùng year_to + grade_to → manual required
    commune_code_used?: string  // TC pathway B
  },
  // M2 snapshot timing: tracked per freeze event
  frozen_at: string,  // ISO datetime
  frozen_at_status: 'draft_preview' | 'submitted_T1' | 'engine_T6',
  resolved_by: 'system' | 'manual_admin',
  manual_override_reason?: string  // Canonical — drops admission_profile.area_resolution_reason column
}
```

### Snapshot timing spec (M2 review fix)

| Profile lifecycle | Snapshot behavior | Purpose |
|---|---|---|
| `draft` / `revision_requested` | Computed real-time mỗi GET (Redis cache 5p); KHÔNG persist | UI preview while editing academic_history |
| Submit T1 → `submitted` | **Freeze** at first submit; persisted vào JSONB column with `frozen_at_status='submitted_T1'` | Audit immutability post-submit |
| Engine `evaluate_cascade` T6 → publish | **Re-freeze** với rates tại T6 (match Q-P3-11 `bonus_rule_snapshot` pattern); `frozen_at_status='engine_T6'` | Quy chế compliance — rates apply theo thời điểm xét tuyển |
| Final states (`enrolled`/`rejected`/`withdrawn`) | Frozen, immutable | Audit history |

Implementation: service `freeze_priority_snapshot(profile, status_at_freeze)` called from `submit_admission_profile` (T1) + `evaluate_cascade` (T6).

---

## Resolution algorithm (BE service)

```python
def resolve_kv_for_profile(
    profile: AdmissionProfile,
    db: AsyncSession
) -> tuple[str | None, dict]:
    """
    TT 05/2021 Phụ lục 01 — KV resolution per academic history.

    Branched by (cultural_education_level, vocational_qualification) — v1.3 2-field:

    | Cultural | Vocational | Basis filter | Rule |
    |---|---|---|---|
    | graduated_thpt / graduated_gdtx | any | level='THPT' | thpt_multi_school |
    | completed_thpt | trung_cap / cao_dang | level='THPT' (3-yr if exist) | thpt_multi_school |
    | graduated_thcs | trung_cap / cao_dang | level='TC' | tc_multi_school |
    | graduated_thcs | none / so_cap | (none) | commune_fallback |
    | completed_thcs | any | (none) | commune_fallback |
    | (any) + special_case basis | bypass | (none) | commune_special |

    Steps:
    1. Check special case bypass → commune lookup
    2. Derive basis_level từ (cultural, vocational) per matrix
    3. Filter basis_entries: history entries với level == basis_level + school_id
    4. Per entry: lookup KV cho từng năm trong khoảng (year_from..year_to)
       - THPT entries: KV từ vn_school_kv_assignment direct (MOET pre-compute)
       - TC entries: KV derived từ school.ward → vn_commune_area_map (QĐ 861 chain)
    5. Sum thời gian theo KV
    6. Pick KV với max duration
    7. Tiebreak: KV của trường tốt nghiệp
    8. M1 edge: nếu tiebreak ambiguous (2 entries cùng year_to+grade_to) → require manual
    """
    cultural = getattr(profile, 'cultural_education_level', None)
    vocational = getattr(profile, 'vocational_qualification', 'none')

    # Special cases bypass (4 case TT 05/2021): PT DTNT / dự bị / quân nhân / xuất ngũ
    if profile.area_resolution_basis == 'permanent_address_special':
        if profile.permanent_commune_code:
            kv = await _lookup_commune_kv(db, profile.permanent_commune_code)
            return kv, {
                'rule': 'permanent_commune_special_case',
                'pathway': 'commune_special',
                'commune_code_used': profile.permanent_commune_code,
            }
        return None, {'reason': 'special_case_no_commune', 'requires_manual_override': True}

    # Derive basis_level from (cultural, vocational) matrix
    basis_level = _derive_kv_basis_level(cultural, vocational)
    # Returns: 'THPT' | 'TC' | 'COMMUNE_FALLBACK' | None

    if basis_level == 'COMMUNE_FALLBACK':
        if profile.permanent_commune_code:
            kv = await _lookup_commune_kv(db, profile.permanent_commune_code)
            return kv, {
                'rule': 'commune_fallback_thcs_or_so_cap',
                'pathway': 'commune_fallback',
                'commune_code_used': profile.permanent_commune_code,
            }
        return None, {'reason': 'thcs_no_commune', 'requires_manual_override': True}

    if basis_level is None:
        return None, {'reason': 'cultural_not_set', 'requires_manual_override': True}

    # Multi-school rule applies (THPT or TC)
    history = profile.academic_history or []
    basis_entries = [
        e for e in history
        if e.get('level') == basis_level and e.get('school_id')
    ]

    if not basis_entries:
        return None, {'reason': 'no_qualifying_entries', 'requires_manual_override': True}

    # Per-year KV duration map
    kv_years: dict[str, int] = {}
    breakdown_per_entry = []

    for entry in basis_entries:
        sid = entry['school_id']
        y_from = entry['year_from']
        y_to = entry['year_to']

        entry_years_by_kv = []
        for year in range(y_from, y_to + 1):
            kv = await lookup_kv_for_school_year(db, sid, year)
            if kv:
                kv_years[kv] = kv_years.get(kv, 0) + 1
                entry_years_by_kv.append({'year': year, 'kv': kv})

        breakdown_per_entry.append({
            'school_id': sid,
            'school_name_at_time': entry.get('school_name'),
            'year_from': y_from,
            'year_to': y_to,
            'years_by_kv': entry_years_by_kv,
        })

    if not kv_years:
        return None, {'reason': 'no_kv_lookup_succeeded'}

    max_yrs = max(kv_years.values())
    winners = [kv for kv, y in kv_years.items() if y == max_yrs]

    if len(winners) == 1:
        return winners[0], {
            'rule': 'longest_duration',
            'winner_years': max_yrs,
            'breakdown': breakdown_per_entry,
            'kv_totals': kv_years,
        }

    # Tiebreak: KV của trường tốt nghiệp
    # M1 review fix: stable sort + detect ambiguous (2 entries cùng year_to+grade_to)
    candidates = sorted(
        enumerate(basis_entries),
        key=lambda pair: (pair[1]['year_to'], pair[1].get('grade_to', 0), pair[0]),
        reverse=True,
    )
    if len(candidates) >= 2:
        top, second = candidates[0][1], candidates[1][1]
        if (top['year_to'] == second['year_to']
            and top.get('grade_to') == second.get('grade_to')):
            return None, {
                'rule': 'ambiguous_requires_manual',
                'reason': 'tied_graduation_year_and_grade',
                'tied_entries': [top['school_id'], second['school_id']],
                'requires_manual_override': True,
                'breakdown': breakdown_per_entry,
                'kv_totals': kv_years,
            }

    grad_entry = candidates[0][1]
    grad_kv = await lookup_kv_for_school_year(
        db, grad_entry['school_id'], grad_entry['year_to']
    )

    return grad_kv, {
        'rule': 'thpt_tiebreak_graduation_school',
        'tied_kv': winners,
        'graduation_school_id': grad_entry['school_id'],
        'graduation_year': grad_entry['year_to'],
        'breakdown': breakdown_per_entry,
        'kv_totals': kv_years,
    }
```

### Special cases bypass

4 trường hợp đặc biệt TT 05/2021 (PT DTNT/lớp dự bị/quân nhân/xuất ngũ) skip rule trên, dùng `permanent_commune_code` → `vn_commune_area_map`. Existing PR1 schema giữ nguyên.

---

## Migration strategy

### Phase A: Schema cutover (new migration `phase1_09`)

PR1 `phase1_08b` đã deployed nhưng các bảng `vn_high_school` + columns `high_school_id`/`high_school_kv_resolved` chưa có data thực (315 profiles existing có values NULL all).

```python
# phase1_09_priority_kv_temporal.py

def upgrade():
    # 1. Drop PR1 empty placeholder
    op.drop_table('vn_high_school')  # 0 rows
    op.drop_column('admission_profile', 'high_school_id')
    op.drop_column('admission_profile', 'high_school_kv_resolved')

    # 2. Create vn_school + history + kv_assignment
    op.create_table('vn_school', ...)
    op.create_table('vn_school_name_history', ...)
    op.create_table('vn_school_kv_assignment', ...)

    # 3. Add resolution snapshot column
    op.add_column('admission_profile',
        sa.Column('priority_resolution_snapshot', JSONB,
                  server_default=sa.text("'{}'::jsonb"), nullable=False))

def downgrade():
    op.drop_column('admission_profile', 'priority_resolution_snapshot')
    op.drop_table('vn_school_kv_assignment')
    op.drop_table('vn_school_name_history')
    op.drop_table('vn_school')
    # Restore PR1 columns (best effort)
    op.add_column('admission_profile',
        sa.Column('high_school_id', sa.BigInteger, nullable=True))
    op.add_column('admission_profile',
        sa.Column('high_school_kv_resolved', sa.String(20), nullable=True))
    op.create_table('vn_high_school', ...)  # original PR1 shape
```

### Phase B: MOET school + BNV commune data import

**B.1 — MOET THPT school import** (replaces original PR4):

Script `app/scripts/import_moet_schools_2025.py`:

1. Read MOET file `3. Danh sach trường THPT 21.4.2025.xls` (~6,822 rows)
2. Verify column structure trước implement (m3 review polish — open MOET file + audit format)
3. For each row → upsert `vn_school` với `level='THPT'` (matched by `moet_province_code` + `moet_school_code`)
4. For each row → insert `vn_school_kv_assignment` với `effective_from_year=2025`, `source='moet_2025'`
5. (Optional) read older MOET dumps for retro KV assignments

**B.2 — VN commune KV map import** (NEW — required cho 4 special cases + **THCS school KV derive** + TC ward fallback):

Script `app/scripts/import_commune_kv_map.py`:

Data source chain (no single canonical file — Stage 1 hybrid strategy):

1. **Stage 1 (ship NGAY)**: Parse QĐ 861/QĐ-TTg PDF (4/6/2021) extract ~3,434 xã KV I/II/III DTTS → map sang KV1 tuyển sinh. Reuse `administrative_nodes` existing (memory `admin-nodes-gso-alignment`) cho province/district/ward lookup. Default mapping cho commune NOT in DTTS list: KV3 if phường thành phố TƯ, KV2 if phường tỉnh hoặc xã thành phố TƯ, KV2-NT otherwise.

2. **Stage 2 (parallel)**: Scrape thuvienphapluat.vn / FPT / HNUE bảng tra cứu để reconcile + identify gaps.

3. **Stage 3 (long-term post mùa 2026)**: Track 63 QĐ UBND tỉnh ban hành giai đoạn 2026-2030 (theo memo Luật Việt Nam 01/07/2025 phân quyền).

**KV mapping rule** (Bộ GD-ĐT vs Ủy ban Dân tộc):

⚠️ **Critical correction 2026-05-17**: QĐ 861 KV I/II/III (vùng DTTS classification gradients) **ALL** map → TT KV1 tuyển sinh (0.75đ). KHÔNG phải 1→KV1, 2→KV2, 3→KV3. KV I/II/III của QĐ 861 chỉ là internal disadvantaged-level gradient trong DTTS context — TT 06/2026 + TT 05/2021 KV1 tuyển sinh là tập union rộng hơn.

- **KV1 tuyển sinh** = (xã KV I/II/III vùng DTTS theo QĐ 861) ∪ xã biên giới ∪ xã hải đảo ∪ xã đặc khu ∪ xã bãi ngang ven biển (QĐ 353/2022)
- **KV2-NT** = xã ngoài KV1 (rural default, fallback)
- **KV2** = phường tỉnh + xã thành phố TƯ ngoài KV1
- **KV3** = phường thành phố TƯ ngoài KV1

**Data source verified** (research 2026-05-17): repo đã có `Documents/Seeding data/data province/`:
- `wards.sql` — **3,321 commune** post-sáp nhập 1/7/2025 với BNV 5-digit codes
- `provinces.sql` — **34 provinces** mới
- `ward_mappings.sql` — **10,039 old→new code mappings** (resolve pre-2025 names trong QĐ 861)

**Primary external source**: [luatvietnam.vn QĐ 861 HTML tables](https://luatvietnam.vn/chinh-sach/quyet-dinh-861-qd-ttg-danh-sach-cac-xa-khu-vuc-iii-ii-i-2021-2025-203245-d1.html) — verified WebFetch-accessible (chinhphu.vn blocked).

**Realistic Stage 1 effort**: ~6-7h (WebFetch chunks 3h + fuzzy match legacy 2h + QA 30min + script 1h).

**B.3 — TC school KV (N1 revised 2026-05-18)** — manual admin entry preferred:

V1.2 đề xuất ward-derive THCS KV. V1.3 dropped THCS multi-school rule per TT (chỉ THPT + TC có multi-school rule). Refocus B.3 vào **TC school KV**:

Script `app/scripts/seed_tc_schools_initial.py`:

1. **TC schools nation-wide ~100-200 schools** (per Bộ LĐTBXH statistics) — feasible cho manual admin entry
2. **N1 revised**: KHÔNG ward-derive (risk mismatch — TC schools thường ở khu công nghiệp với KV khác địa chỉ trường). Admin explicit manual entry per TC school + `vn_school_kv_assignment` row với `source='manual_admin'`
3. Bootstrap data: top 50 TC schools by enrollment volume (admin pre-seed before mùa 2026-08-01)
4. Long-term: locate Bộ LĐTBXH TC school registry nếu publish (Stage 3)

**THCS schools**: schema support `level='THCS'` trong `vn_school` cho audit log purposes (candidate khai academic_history THCS entry → store free-text school name). KHÔNG cần KV assignment vì THCS không có multi-school rule.

Effort: ~0.3d (Stage 1 manual seed 50 TC schools + 0.2d hook admin form vn_school).

**Phase B total**: ~1.8d (1d MOET THPT B.1 + 0.5d commune KV map B.2 + 0.3d TC manual seed B.3).

### Phase C: BE engine (replaces PR2 KV portion)

- `priority_service.resolve_kv_for_profile()` per algorithm above
- Snapshot to `priority_resolution_snapshot` at submit time
- Engine bonus computation reads `priority_resolution_snapshot.kv_resolved`

### Phase D: FE candidate UI (replaces PR5 PriorityTab)

**AcademicHistoryTab** (upgrade existing): mỗi row có:
- Dropdown chọn trường (search `vn_school` API) → sets `school_id`
- Auto-detect level từ chosen school's `level` field, allow manual override
- Grade range input (lớp X → lớp Y) → BE computes year range based on entry year
- Display "KV năm Y: KV1" inline (lookup `vn_school_kv_assignment` qua API)

**PriorityTab** (rewrite từ đầu):
```
┌────────────────────────────────────────────────┐
│ 📊 Khu vực ưu tiên (tự động xác định)         │
├────────────────────────────────────────────────┤
│ Cơ sở: Lịch sử học tập (hệ Cao đẳng → THPT)   │
│                                                │
│ • THPT Lê Quý Đôn (KV1): 2 năm (2022-2024)    │
│ • THPT Trần Đại Nghĩa (KV3): 1 năm (2024-2025)│
│   ↳ Trường tốt nghiệp                          │
│                                                │
│ → KV1 (theo thời gian học lâu hơn)            │
│   Quy chế TT 05/2021 Phụ lục 01                │
│                                                │
│ [✏ Ghi đè thủ công]   [✓ Đồng ý]              │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│ 🏅 Đối tượng ưu tiên (UT)                     │
│ ... (same as PR5 original) ...                 │
└────────────────────────────────────────────────┘
```

### Phase E: Officer FE (PR6)

- Verify evidence cho UT codes (Q9 #07 PR6 scope)
- Review KV breakdown trong audit log

### Phase F: Admin backfill (PR7)

- Tool fill `school_id` cho 315 existing profiles từ `school_name` (fuzzy match)
- Manual `vn_school_kv_assignment` cho năm cũ nếu chưa import

---

## Edge cases handled

| Case | Handling |
|---|---|
| Trường sát nhập | `vn_school.merged_into_id` chain; KV lookup vẫn dùng `school_id` gốc + năm gốc (không follow merger) |
| Trường đổi tên | `vn_school_name_history` track; UI show tên hiện tại với note "(Tên cũ: X)" |
| KV của trường đổi giữa năm học | Granularity = năm học (academic_year), không tháng. Acceptable per TT |
| Học sinh học liên thông TC→CĐ | (cultural=completed/graduated_thpt, vocational=trung_cap) → THPT multi-school nếu có history, else TC rule |
| Học sinh chuyển hệ giữa chừng | `level` per-entry; basis_entries filter theo derived basis_level từ (cultural, vocational) |
| 4 case đặc biệt (PT DTNT/dự bị/quân nhân/xuất ngũ) | Bypass logic, dùng `permanent_commune_code` (existing PR1 logic) |
| Học sinh học ở nước ngoài | MOET file có sẵn entry mã `800` mỗi tỉnh = KV3 (cultural=graduated_thpt only) |
| Tốt nghiệp THCS đi làm 5 năm → thi TC | (cultural=graduated_thcs, vocational=none) → commune_fallback (TC chưa nhập học) |
| Đã có Sơ cấp, muốn lên TC | (cultural=graduated_thcs, vocational=so_cap) → commune_fallback (Sơ cấp không qualify cho TC multi-school) |
| TC tốt nghiệp + thi CĐ liên thông | (cultural=completed_thpt, vocational=trung_cap) → THPT rule (nếu có) hoặc TC rule fallback |
| Trung học nghề (dự thảo 2026) | Future: cấp mới `level='TRUNG_HOC_NGHE'` — schema ready, rule TBD khi TT ban hành chính thức |

---

## Open questions

1. ~~**Backfill 315 hồ sơ existing**~~: **RESOLVED 2026-05-17** — 315 KHÔNG phải prod data, chỉ là test fixtures. Backfill workflow chỉ cần cover real candidates post-deploy mùa 2026-08-01.

2. **Năm học cross-format**: TT 05/2021 không define rõ "năm" = năm dương lịch hay năm học. Implementation hiện đề xuất dùng năm dương lịch (vd 2024 = năm học 2024-2025 hoặc 2023-2024 depending on context). Cần confirm với admin nghiệp vụ.

3. **TT mới có thể đổi rule**: TT 2026 BGDĐT đang dự thảo. Có cần rule pluggable (config per academic_year) không? Hay vẫn hardcode TT 05/2021 và refactor khi TT mới ban hành?

4. **Hệ liên thông TC→CĐ**: KV xác định theo THPT hay theo cấp đã tốt nghiệp (TC)? TT 05/2021 không nói rõ. Default: theo cấp gần nhất đã tốt nghiệp.

5. **Trường THPT chuyên / trường quốc tế** (chưa có trong MOET list): manual_override basis với reason text.

6. ~~**THCS school dictionary cho hệ TC**~~: **REVISED 2026-05-18 v1.3** — Per Luật GDNN + TT 05/2021 verbatim, multi-school rule chỉ apply cho **THPT (3 năm)** HOẶC **TC (thời gian học)**, KHÔNG có rule THCS-multi-school. THCS-only candidates fall back to `permanent_commune_code`. Schema vẫn support `level='THCS'` entries trong `academic_history` cho audit log (candidate khai school name historical) nhưng KHÔNG dùng cho KV multi-school resolution. THCS school KV derive in `vn_school` table reserve cho future use case (vd: dự thảo TT 2026 Trung học nghề).

7. ~~**Diploma conflict handling**~~: **RESOLVED 2026-05-18 v1.3** — Split thành 2 field parallel (cultural + vocational). KHÔNG còn conflict vì candidate khai cả 2 dimension độc lập. Validation: eligibility check ở `validate_eligibility(profile, target_level)` đảm bảo combination hợp lệ theo TT 05/2021 Điều 4.

---

## Effort estimate (v1.3 — 2-field parallel 2026-05-18)

| Phase | Description | v1.2 | v1.3 | Δ |
|---|---|---|---|---|
| A | Migration phase1_09 (drop legacy + create vn_school + 2 cultural/vocational columns) | 1.75d | 2d | +0.25d (2 columns + CHECK + eligibility validator unit tests) |
| B | MOET THPT + commune KV map (+ THCS schema-only) | 2.5d | 2d | -0.5d (THCS no multi-school rule → defer B.3 scaffold) |
| C | BE resolve_kv (2-field matrix) + eligibility validator + tests | 2.5d | 3d | +0.5d (matrix derivation + eligibility validator + edge case tests) |
| D | FE AcademicHistoryTab + PriorityTab + 2 dropdown (cultural + vocational) | 3.5d | 3.5d | — |
| E | Officer FE verify (PR6 scope) | 2d | 2d | — |
| F | Admin backfill (PR7 scope) | 2d | 2d | — |
| **Total** | | **~14.25d** | **~14.5d** | +0.25d (net) |

vs original plan (PR1 schema + PR2 engine + PR4 import + PR5 single FE + PR6 + PR7): **~14d** equivalent. 2-field design more accurate per VN convention + Luật GDNN, KHÔNG cần derive logic phức tạp.

---

## Open follow-ups (track separately)

- TT 2026 BGDĐT công bố → adapter cho phép switch rule per academic_year
- ~~File 2 (districts) + File 3 (KK communes) import~~ → **Required NOW** cho 4 special cases + THCS school KV derive. Moved vào Phase B.2.
- ~~THCS school list (separate MOET file?)~~ → **REVISED 2026-05-17**: needed cho diploma=THCS candidates; resolution = manual scaffold + ward-derive KV (Phase B.3) — không cần canonical MOET file.
- 63 QĐ UBND tỉnh 2026-2030: track + automate update khi tỉnh ban hành (Stage 3 long-term)
- Verify MOET THPT file `(moet_province_code, moet_school_code)` composite unique assumption
- TC liên thông từ TC sang CĐ: diploma=TC pathway covered (sub-case A2); verify TC school KV derivation accuracy
- Diploma derivation logic: rule để derive `diploma_submitted` từ `academic_history` (highest `graduation_type`) — handle conflict cases (vd khai THPT + TC cùng lúc, candidate đã tốt nghiệp 2 cấp)
