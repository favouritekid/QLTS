# P0 — Tuân thủ Quy chế Tuyển sinh GDNN 2026 — Implementation Plan

**Document version:** 1.0
**Audience:** QLTS backend + frontend engineers
**Scope:** 8 pull requests (P0-1 → P0-8) delivered over ~18–22 person-days
**Target readiness:** đủ dữ liệu compliance để export báo cáo theo PL02/03/05 TT 05/2021 và cho phép thí sinh tự đăng ký trực tuyến.

---

## 0. Tổng quan kiến trúc P0

### 0.1 Mental model

```
                   ┌───────────────────────────────┐
                   │   ConfigDegreeLevel            │  P0-1: +education_track enum
                   │   (gdnn | gddh)                │        +4 GDNN degree codes
                   └───────────────────────────────┘
                                ▲
                                │ snapshot
                                │
┌─────────────────┐      ┌──────┴──────────┐    ┌─────────────────────┐
│ AdmissionCouncil│─1:N──│ CouncilMember   │    │ OfferingAcademicInfo│
│ (1 per academic │      │ (role + user)   │    │   (year-versioned)  │
│  year / unit)   │      └─────────────────┘    └──────────┬──────────┘
└────────┬────────┘                                         │
         │ 1:N                                              │ 1:N
         ▼                                                  ▼
┌───────────────────────┐    N:1 (academic_info_id)  ┌──────────────────┐
│ AdmissionWave         │◀───────────────────────────│ AdmissionPath    │
│   (P0-2b): opens_at,  │                            │ (GĐĐH + GDNN)    │
│   closes_at,          │                            └──────────────────┘
│   submission_deadline,│
│   council_id          │
└──────────┬────────────┘
           │ 1:N (nullable for legacy profiles)
           ▼
┌───────────────────────────────────────────────┐
│ AdmissionProfile                              │
│  + admission_wave_id (FK, nullable)           │
│  + education_track (gdnn|gddh) denormalized   │
│  UNIQUE (citizen_id, academic_year, wave_id)  │
└───────────────────────────────────────────────┘
           ▲                          ▲
           │ self-registration        │ documents
           │                          │
┌──────────┴───────────┐   ┌──────────┴─────────────┐
│ PublicRegSession     │   │ ProfileDocument        │
│ (OTP + rate limit)   │   │ (existing, reused)     │
└──────────────────────┘   └────────────────────────┘
```

### 0.2 Canonical list of PRs and sequencing

| PR | Title | Depends on | Est (days) | Merge order |
|---|---|---|---|---|
| P0-1 | Mở rộng trình độ đào tạo GDNN | — | 1 | 1 |
| P0-2 | Hội đồng tuyển sinh (Council + Member) | P0-1 (seed) | 1.5 | 2 |
| P0-2b | Admission Wave + wiring | P0-2 | 2 | 3 |
| P0-3 | Self-reg portal phần 1 (form + OTP) | P0-2b | 3 | 4 |
| P0-4 | Self-reg phần 2 (upload + sửa trước deadline) | P0-3 | 2.5 | 5 |
| P0-5 | Thanh toán lệ phí (reuse Finance) | P0-3 | 1.5 | 6 |
| P0-6 | PDF Phiếu đăng ký (PL02) | P0-2b | 2 | 7 |
| P0-7 | PDF bộ hồ sơ thí sinh (merge) | P0-4, P0-6 | 2 | 8 |
| P0-8 | ZIP bundle theo đợt (Celery) | P0-7 | 2 | 9 |

**Total: ~17.5 person-days** with buffer → allocate **20 person-days (4 weeks)**.

### 0.3 Cross-cutting concerns

**Migration ordering guarantees:**
- Each PR introduces exactly one Alembic revision. Name format: `p0_<N>_<slug>_<YYYYMMDDHHMM>` to sort lexicographically below existing `fin20260131*` series.
- `down_revision` explicitly set (not `None`) even for first file; refer to latest head at PR opening.
- PR author runs `alembic upgrade head` then `alembic downgrade -1` then `upgrade head` locally before opening PR.
- PR description states: `down_revision = <previous_revision_hash>`.

**Casbin sync:**
- All new policies added via new migration calling `casbin_service.add_policies_batch` AND added to `app/casbin_config/policy_templates.py` so `make reseed-policies` stays idempotent.
- After deploy, run `POST /api/admin/policies/reload` or restart workers (Casbin enforcer reloads on boot).

**Rate limiting (slowapi):**
- New public endpoints use `RateLimits.PUBLIC_CONTACT` (5/h) for OTP request; `RateLimits.AUTH_REGISTER` (3/min) for registration submit; `RateLimits.FILE_UPLOAD` (20/h) for document upload.
- OTP verify is hot path — introduce new tier `RateLimits.PUBLIC_OTP_VERIFY = "20/hour"` scoped per citizen_id (custom key function).

**Observability (structlog):**
- Every new service method logs with `log.bind(event="<verb>.<noun>", ...)` at entry and exit.
- OTP channel selection logged: `log.info("otp.dispatch", channel="zalo", fallback=False)`.
- Celery ZIP tasks log progress every 10 profiles.

**Notification system integration:**
- Only add entries to existing `SystemEvents` + `event_catalog.py` + seed row in `notification_rule`. Per CLAUDE.md: no new event systems.
- New events: `SELF_REG_OTP_REQUESTED`, `SELF_REG_PROFILE_SUBMITTED`, `ADMISSION_WAVE_DEADLINE_REMINDER`.

---

## PR P0-1 — Mở rộng trình độ đào tạo GDNN

### 1.1 Mục đích
Thêm 4 trình độ GDNN (Sơ cấp, Trung cấp, Cao đẳng nghề, Cao đẳng chất lượng cao) vào `ConfigDegreeLevel` và phân loại bằng `education_track` (gdnn / gddh). Đây là prerequisite để mọi báo cáo/phân loại GDNN vs GDĐH hoạt động đúng (PL02/03/05 có biểu GDNN riêng).

### 1.2 Schema changes

**Model edit — `D:/QLTS/Backend_FastAPI/app/models/config.py` (class `ConfigDegreeLevel`):**
```python
education_track = Column(
    String(10),
    nullable=False,
    server_default="gddh",
    index=True,
    comment="gdnn = Giáo dục nghề nghiệp | gddh = Giáo dục đại học",
)
__table_args__ = (
    CheckConstraint(
        "education_track IN ('gdnn','gddh')",
        name="ck_config_degree_level_education_track",
    ),
)
```

**Alembic migration — `p0_1_degree_level_education_track_<ts>.py`:**
- **upgrade:**
  1. `op.add_column('config_degree_level', sa.Column('education_track', sa.String(10), nullable=False, server_default='gddh'))`
  2. `op.create_index('ix_config_degree_level_education_track', 'config_degree_level', ['education_track'])`
  3. `op.create_check_constraint('ck_config_degree_level_education_track', 'config_degree_level', "education_track IN ('gdnn','gddh')")`
  4. Seed 4 GDNN rows via raw SQL (`INSERT ... ON CONFLICT (code) DO UPDATE SET education_track='gdnn'`):
     - `so_cap` / Sơ cấp / order 10
     - `trung_cap` / Trung cấp / order 20
     - `cao_dang_nghe` / Cao đẳng nghề / order 30
     - `cao_dang_cl_cao` / Cao đẳng chất lượng cao / order 40
  5. Backfill existing `dai_hoc`, `cao_dang`, `thac_si`, `tien_si` rows with `education_track='gddh'`.
- **downgrade:** drop constraint → drop index → drop column → delete seeded GDNN rows.

### 1.3 Backend work

| File | Change |
|---|---|
| `app/models/config.py` | Add `education_track` column + check constraint |
| `app/schemas/config.py` | Add `education_track: Literal['gdnn','gddh']` in `ConfigDegreeLevelBase/Create/Update/Response` |
| `app/repositories/config_repository.py` | New method `list_by_education_track(track: str) -> list[ConfigDegreeLevel]` |
| `app/services/config_service.py` | Update `create_degree_level` / `update_degree_level` to validate track |
| `app/routers/config_data.py` | Add optional query param `?education_track=gdnn` to existing `GET /api/config/degree-levels` |

**Endpoints:** no new endpoint; filter param added.

**RBAC:** no new policy needed — existing `admin` policies on `/api/config/*` cover the new field. Seed data is via migration, not API.

**Domain exceptions:** none new.

### 1.4 Frontend work

| File | Change |
|---|---|
| `frontend/src/lib/api/config.ts` | Add `educationTrack` to `DegreeLevel` type + `?education_track` query |
| `frontend/src/app/(dashboard)/admin/config/degree-levels/page.tsx` (existing config UI) | Add column "Loại giáo dục" (GDNN/GDĐH) in table + radio select in create/edit form |
| `frontend/src/lib/config/degree-track.ts` (new) | Constants `EDUCATION_TRACKS = [{code:'gdnn', label:'Giáo dục nghề nghiệp'}, ...]` |

**Zod schema:** `degreeLevelSchema.extend({ educationTrack: z.enum(['gdnn','gddh']) })`.

**React Query:** existing `useDegreeLevels()` hook accepts new filter; no new hook.

### 1.5 Test plan

- **Unit:** `tests/services/test_config_service.py::test_create_degree_level_requires_track`, `::test_filter_by_track`.
- **Integration:** `tests/api/test_config_degree_levels.py::test_list_gdnn_filtered`, `::test_seed_data_migrated`.
- **Migration test:** `tests/migrations/test_p0_1.py` — run upgrade → assert 4 gdnn rows with correct codes → downgrade → rows gone.
- **E2E:** admin settings screen: create GDNN degree → appears in filter.

### 1.6 Dependencies
None. First PR in the series.

### 1.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Existing production `ConfigDegreeLevel` rows might have custom codes not matching our seed `ON CONFLICT` — migration could fail | Use `ON CONFLICT (code) DO NOTHING` for new seeds and a separate `UPDATE` for backfill. Verify with `SELECT DISTINCT code FROM config_degree_level` on staging before deploy. |
| Front-end table breaks if `education_track` is null for legacy rows | Server-default `'gddh'` at DB level + Zod default to keep union closed. |

---

## PR P0-2 — Hội đồng tuyển sinh (AdmissionCouncil + CouncilMember)

### 2.1 Mục đích
Quy chế TT 05/2021 Đ4 yêu cầu Trường thành lập Hội đồng tuyển sinh hàng năm. P0 giữ "lite" — 1 hội đồng/năm/trường, lưu thành viên để phục vụ PL05 (Danh sách Hội đồng) và footer chữ ký PDF.

### 2.2 Schema changes

**Models (new file `app/models/admission_council.py`):**
```python
class AdmissionCouncil(Base):
    __tablename__ = "admission_council"
    id = Column(Integer, primary_key=True)
    unit_id = Column(Integer, ForeignKey("organization_unit.id", ondelete="RESTRICT"), nullable=False, index=True)
    academic_year = Column(Integer, nullable=False, index=True)
    decision_number = Column(String(100), nullable=True, comment="Số QĐ thành lập Hội đồng")
    decision_date = Column(Date, nullable=True)
    decision_file_path = Column(String(500), nullable=True)
    name = Column(String(255), nullable=False, comment="Tên HĐ: 'Hội đồng TS Trường X năm 2026'")
    education_track = Column(String(10), nullable=False, comment="gdnn | gddh | all")
    status = Column(String(20), nullable=False, server_default="active", comment="active | archived")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    members = relationship("CouncilMember", back_populates="council", cascade="all, delete-orphan", lazy="selectin")
    waves = relationship("AdmissionWave", back_populates="council")

    __table_args__ = (
        UniqueConstraint("unit_id", "academic_year", "education_track", name="uq_council_unit_year_track"),
        CheckConstraint("education_track IN ('gdnn','gddh','all')", name="ck_council_track"),
        CheckConstraint("status IN ('active','archived')", name="ck_council_status"),
    )

class CouncilMember(Base):
    __tablename__ = "council_member"
    id = Column(Integer, primary_key=True)
    council_id = Column(Integer, ForeignKey("admission_council.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
                     comment="Nullable — external member")
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False,
                  comment="chairman | vice_chairman | secretary | member")
    title_in_school = Column(String(255), nullable=True, comment="Chức vụ tại trường")
    signature_file_path = Column(String(500), nullable=True)
    display_order = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    council = relationship("AdmissionCouncil", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint("role IN ('chairman','vice_chairman','secretary','member')", name="ck_member_role"),
        # Chairman unique within council
        Index("uq_council_chairman", "council_id", unique=True,
              postgresql_where=text("role='chairman'")),
    )
```

**Alembic migration — `p0_2_admission_council_<ts>.py`:**
- upgrade: create `admission_council` → `council_member` → indexes → partial unique for chairman.
- downgrade: drop in reverse.
- No seed — Admin tạo qua UI.

### 2.3 Backend work

**Files new/modify:**
- `app/models/admission_council.py` (new)
- `app/models/__init__.py` — add imports + `__all__`
- `app/schemas/admission_council.py` (new): `AdmissionCouncilBase/Create/Update/Response`, `CouncilMemberBase/Create/Update/Response`, `CouncilMemberRole` enum
- `app/repositories/admission_council_repository.py` (new): CRUD + `get_active_for_year(unit_id, year, track)` with eager-loaded members
- `app/services/admission_council_service.py` (new): create/update/archive; validate chairman uniqueness; IDOR via `unit_id`
- `app/routers/admission_councils.py` (new)
- `app/main.py` — register router
- `app/utils/exceptions.py` — no new exceptions; reuse `DuplicateResourceError`, `ResourceNotFoundError`

**Endpoints (all admin-only):**

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/admission/councils` | query: `?academic_year=&unit_id=&education_track=` | `AdmissionCouncilListResponse` |
| POST | `/api/admission/councils` | `AdmissionCouncilCreate` (name, year, unit_id, track, decision_*) | `AdmissionCouncilResponse` |
| GET | `/api/admission/councils/{id}` | — | with members |
| PUT | `/api/admission/councils/{id}` | `AdmissionCouncilUpdate` | `AdmissionCouncilResponse` |
| POST | `/api/admission/councils/{id}/members` | `CouncilMemberCreate` | member |
| PUT | `/api/admission/councils/{id}/members/{member_id}` | `CouncilMemberUpdate` | member |
| DELETE | `/api/admission/councils/{id}/members/{member_id}` | — | 204 |
| POST | `/api/admission/councils/{id}/archive` | — | 204 |

**RBAC (Casbin — migration `p0_2_casbin_policies_<ts>.py` + `policy_templates.py`):**
- `p, role:admin, /api/admission/councils*, (GET|POST|PUT|DELETE)` — full
- `p, role:manager, /api/admission/councils*, GET` — read-only

**Service methods:**
- `create_council(data, current_user)` → enforces `UniqueConstraint(unit_id, year, track)` at DB level, catches `IntegrityError` → `DuplicateResourceError`
- `add_member(council_id, data, current_user)` → if `role=chairman`, pre-check via repo
- `archive_council(council_id, current_user)` → sets `status='archived'`

### 2.4 Frontend work

**Files new:**
- `frontend/src/lib/api/admission-councils.ts`
- `frontend/src/hooks/admissions/useCouncils.ts`
- `frontend/src/app/(dashboard)/admin/admission-config/councils/page.tsx` (list)
- `frontend/src/app/(dashboard)/admin/admission-config/councils/[id]/page.tsx` (detail + members tab)
- `frontend/src/components/admission/CouncilForm.tsx`
- `frontend/src/components/admission/CouncilMemberTable.tsx`

**Zod schemas (`frontend/src/lib/api/admission-councils.ts`):**
```typescript
const CouncilMemberRole = z.enum(['chairman','vice_chairman','secretary','member']);
const councilSchema = z.object({
  name: z.string().min(5).max(255),
  academicYear: z.number().int().min(2020).max(2050),
  unitId: z.number().int().positive(),
  educationTrack: z.enum(['gdnn','gddh','all']),
  decisionNumber: z.string().max(100).optional(),
  decisionDate: z.string().datetime().optional(),
});
```

**React Query:** `useCouncils(filters)`, `useCouncil(id)`, `useCreateCouncil`, `useUpdateCouncil`, `useArchiveCouncil`, `useAddMember`, `useUpdateMember`, `useDeleteMember`.

### 2.5 Test plan

- **Unit:** `test_council_service.py::test_chairman_unique`, `::test_duplicate_year_track_rejected`, `::test_idor_crossunit_404`.
- **Integration:** `tests/api/test_admission_councils.py` — CRUD matrix per role, chairman constraint, archive workflow.
- **E2E:** Playwright — admin creates council → adds chairman + 2 members → archives.

### 2.6 Dependencies
- P0-1 (for `education_track` concept, though the council has its own separate column).

### 2.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Multi-unit deployment: 1 user account has units across education tracks — which council is "the" one? | Scoping by `unit_id + year + track` already enforces isolation; FE selector requires user to pick unit. |
| Chairman partial unique index may conflict on PostgreSQL versions <11 | We target PG 14+ (docker-compose locked). Guard with `if dialect.name == 'postgresql'` in migration. |

---

## PR P0-2b — Admission Wave (đợt tuyển sinh)

### 3.1 Mục đích
Đưa vào mô hình "đợt tuyển sinh" — 1 khoảng thời gian có `opens_at / closes_at / submission_deadline`, thuộc 1 Hội đồng và 1 năm học. Liên kết `AdmissionProfile` và `AdmissionPath` vào đợt để phân loại cho báo cáo và kiểm soát deadline sửa hồ sơ. Đổi unique constraint trên `admission_profile` theo OTP.1.

### 3.2 Schema changes

**Model mới — `app/models/admission_wave.py`:**
```python
class AdmissionWave(Base):
    __tablename__ = "admission_wave"
    id = Column(Integer, primary_key=True)
    council_id = Column(Integer, ForeignKey("admission_council.id", ondelete="RESTRICT"),
                        nullable=False, index=True)
    academic_year = Column(Integer, nullable=False, index=True)
    wave_number = Column(Integer, nullable=False, comment="Đợt 1, 2, 3...")
    name = Column(String(255), nullable=False)
    education_track = Column(String(10), nullable=False)  # gdnn | gddh
    opens_at = Column(DateTime(timezone=True), nullable=False)
    closes_at = Column(DateTime(timezone=True), nullable=False,
                       comment="Thời điểm đóng đăng ký mới")
    submission_deadline = Column(DateTime(timezone=True), nullable=False,
                                 comment="Hạn cuối sửa hồ sơ đã nộp (OTP.1/D.2)")
    result_announcement_at = Column(DateTime(timezone=True), nullable=True)
    enrollment_deadline = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, server_default="draft",
                    comment="draft | open | closed | archived")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    council = relationship("AdmissionCouncil", back_populates="waves")
    profiles = relationship("AdmissionProfile", back_populates="wave")
    paths = relationship("AdmissionPath", secondary="admission_wave_path", back_populates="waves")

    __table_args__ = (
        UniqueConstraint("council_id", "wave_number", name="uq_wave_council_number"),
        CheckConstraint("closes_at >= opens_at", name="ck_wave_close_after_open"),
        CheckConstraint("submission_deadline >= closes_at", name="ck_wave_deadline_after_close"),
        CheckConstraint("education_track IN ('gdnn','gddh')", name="ck_wave_track"),
        CheckConstraint("status IN ('draft','open','closed','archived')", name="ck_wave_status"),
    )

# M2M join
class AdmissionWavePath(Base):
    __tablename__ = "admission_wave_path"
    wave_id = Column(Integer, ForeignKey("admission_wave.id", ondelete="CASCADE"), primary_key=True)
    path_id = Column(Integer, ForeignKey("admission_path.id", ondelete="CASCADE"), primary_key=True)
    quota = Column(Integer, nullable=True, comment="Phân bổ chỉ tiêu cho đợt (nullable = không giới hạn riêng)")
```

**Modify `AdmissionProfile`:**
- Add `admission_wave_id: Mapped[Optional[int]]` FK nullable (legacy profiles before P0-2b have NULL).
- Add `education_track: Mapped[str]` denormalized (copied from wave at creation) for report filtering speed.
- Add `submission_locked_at: Mapped[Optional[datetime]]` = computed cache; set when wave's `submission_deadline` passes.
- Drop old `UniqueConstraint('citizen_id','academic_year')`; add `UniqueConstraint('citizen_id','academic_year','admission_wave_id', name='uq_citizen_year_wave')` (PostgreSQL treats NULL as distinct → legacy NULL rows won't collide, but for wave-scoped profiles this enforces exactly-one-per-wave).

**Modify `AdmissionPath`:**
- Add `waves` relationship via `admission_wave_path`.
- (No column change — M2M via join table keeps path reusable across waves.)

**Alembic migration — `p0_2b_admission_wave_<ts>.py`:**
- upgrade:
  1. Create `admission_wave` table with all constraints.
  2. Create `admission_wave_path` join.
  3. Add 3 columns to `admission_profile`: `admission_wave_id` (FK SET NULL), `education_track` (nullable for backfill), `submission_locked_at`.
  4. Backfill `education_track` from `AdmissionPath → OfferingAcademicInfo → ProgramOffering → MajorProgram.degree_level_id → ConfigDegreeLevel.education_track`. Fallback `'gddh'`.
  5. Make `education_track` NOT NULL with server_default `'gddh'`.
  6. `op.drop_constraint('uq_citizen_academic_year', 'admission_profile')`.
  7. `op.create_unique_constraint('uq_citizen_year_wave', 'admission_profile', ['citizen_id','academic_year','admission_wave_id'])`.
- downgrade: reverse steps; restore old unique constraint after deduplicating if needed (document caveat: cannot restore if wave split produced duplicates).

### 3.3 Backend work

**Files new/modify:**
- `app/models/admission_wave.py` (new)
- `app/models/admission.py` — add 3 columns + relationship `wave`
- `app/models/admission_config/admission_path.py` — add `waves` relationship
- `app/models/__init__.py` — export `AdmissionWave`, `AdmissionWavePath`
- `app/schemas/admission_wave.py` (new)
- `app/repositories/admission_wave_repository.py` (new): `get_open_for_track(track, now)`, `get_with_paths(id)`, `is_profile_editable(profile_id, now)` (compute based on wave deadline)
- `app/services/admission_wave_service.py` (new): CRUD + `open_wave`, `close_wave`, `link_paths(wave_id, path_ids)` with validation `wave.education_track == path → degree.education_track`
- `app/services/admission_service.py` — helper `_resolve_wave_for_profile(profile, ...)`; in `update_profile` and `upload_document` check `wave.submission_deadline` vs `now()` → raise `BusinessRuleViolation("wave_submission_closed")` if locked
- `app/routers/admission_waves.py` (new)
- `app/main.py` — register router

**Endpoints:**

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/admission/waves` | `?academic_year=&track=&status=&council_id=` | list |
| POST | `/api/admission/waves` | `AdmissionWaveCreate` | response |
| GET | `/api/admission/waves/{id}` | — | full w/ paths |
| PUT | `/api/admission/waves/{id}` | — | response |
| POST | `/api/admission/waves/{id}/paths` | `{path_ids: int[]}` | update M2M |
| POST | `/api/admission/waves/{id}/open` | — | status → open |
| POST | `/api/admission/waves/{id}/close` | — | status → closed |
| GET | `/api/public/admissions/waves` | `?track=gdnn&unit_id=` (public, no auth) | list of open waves for self-reg |

**RBAC:** admin full; manager read; public endpoint no auth.

**Domain exceptions:**
- `WaveNotOpenError(BusinessRuleViolation)` — self-reg rejects.
- `WaveSubmissionDeadlinePassedError(BusinessRuleViolation)` — profile edit/upload rejected.

**Service methods (key):**
- `resolve_editability(profile) -> tuple[bool, Optional[datetime]]` returning `(is_editable, deadline)` for FE to show countdown.
- `link_paths(wave_id, path_ids)` — validate all paths share track with wave; validate quota sum ≤ path's annual_admission_quota.

### 3.4 Frontend work

**Files new/modify:**
- `frontend/src/lib/api/admission-waves.ts`
- `frontend/src/hooks/admissions/useWaves.ts`, `useWaveEditability.ts`
- `frontend/src/app/(dashboard)/admin/admission-config/waves/page.tsx` (list)
- `frontend/src/app/(dashboard)/admin/admission-config/waves/[id]/page.tsx` (detail: timing + path assignment + profile count)
- `frontend/src/components/admission/WaveForm.tsx`
- `frontend/src/components/admission/WavePathPicker.tsx` (checklist of AdmissionPath filtered by track)

**Zod:**
```typescript
const admissionWaveSchema = z.object({
  councilId: z.number().int().positive(),
  academicYear: z.number().int(),
  waveNumber: z.number().int().positive(),
  name: z.string().min(3).max(255),
  educationTrack: z.enum(['gdnn','gddh']),
  opensAt: z.string().datetime(),
  closesAt: z.string().datetime(),
  submissionDeadline: z.string().datetime(),
}).superRefine((data, ctx) => {
  if (new Date(data.closesAt) < new Date(data.opensAt)) ctx.addIssue({...});
  if (new Date(data.submissionDeadline) < new Date(data.closesAt)) ctx.addIssue({...});
});
```

**React Query:** standard CRUD + `useOpenWave`, `useCloseWave`, `useLinkPaths`.

### 3.5 Test plan

- **Unit:** `test_admission_wave_service.py::test_track_mismatch_rejected`, `::test_deadline_ordering_validated`, `::test_profile_edit_locks_after_deadline`.
- **Integration:** `tests/api/test_admission_waves.py` — CRUD + link_paths + public list only returns `status='open'`.
- **Migration test:** apply with pre-existing profiles → `education_track` correctly backfilled.
- **Edit-after-deadline:** integration test that PUT /api/admissions/{id} returns 400 with code `wave_submission_closed`.

### 3.6 Dependencies
- P0-1 (for `education_track` on degree)
- P0-2 (for `council_id` FK)

### 3.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Backfilling `education_track` on large profile tables takes too long | Use `UPDATE ... FROM` with JOIN-based query; test on 100k rows. Run `ANALYZE` after. Accept 2–5 min downtime. |
| Dropping `uq_citizen_academic_year` then adding new unique may race if prod has duplicates | Pre-migration check: `SELECT citizen_id, academic_year, COUNT(*) FROM admission_profile GROUP BY 1,2 HAVING COUNT(*)>1`. Fail loudly. |
| Existing profiles have NULL wave_id; PostgreSQL treats nulls as distinct → user could double-register if service doesn't enforce wave_id on new profiles | Add service-level guard: new profiles MUST have `admission_wave_id != NULL`. Only legacy reads are null-tolerant. Validation in `admission_service.create_profile`. |

---

## PR P0-3 — Self-registration portal phần 1 (form + OTP + submit)

### 4.1 Mục đích
Mở cổng tự đăng ký cho thí sinh (không auth). OTP qua Zalo (primary nếu có phone đã consent) hoặc Email (fallback). Thí sinh điền thông tin → xác thực OTP → hệ thống tự tạo `Lead` + `AdmissionProfile` status `draft`, gắn vào `admission_wave` đang `open`.

### 4.2 Schema changes

**Model mới — `app/models/public_reg_session.py`:**
```python
class PublicRegSession(Base):
    __tablename__ = "public_reg_session"
    id = Column(Integer, primary_key=True)
    session_token = Column(String(64), unique=True, nullable=False, index=True,
                           comment="URL-safe random, given to FE in cookie/header")
    citizen_id = Column(String(12), nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    admission_wave_id = Column(Integer, ForeignKey("admission_wave.id", ondelete="CASCADE"), nullable=False)
    otp_hash = Column(String(128), nullable=False, comment="argon2(otp)")
    otp_channel = Column(String(20), nullable=False, comment="zalo | email")
    otp_expires_at = Column(DateTime(timezone=True), nullable=False)
    otp_attempts = Column(Integer, nullable=False, server_default="0")
    otp_verified_at = Column(DateTime(timezone=True), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    form_snapshot = Column(JSONB, nullable=True, comment="Cached form data before submit")
    created_profile_id = Column(Integer, ForeignKey("admission_profile.id", ondelete="SET NULL"),
                                nullable=True, comment="Set after successful submit")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("otp_channel IN ('zalo','email')", name="ck_reg_session_channel"),
        Index("ix_reg_session_citizen_wave", "citizen_id", "admission_wave_id"),
        Index("ix_reg_session_expires", "otp_expires_at"),  # cleanup scan
    )
```

**Alembic migration — `p0_3_public_reg_session_<ts>.py`:** create table + indexes. Downgrade drops.

**Modifies `AdmissionProfile`:**
- Add `created_via: Mapped[str]` column (default `'officer'`, values: `officer | self_registration | import`).
- Migration simply adds column with default.

### 4.3 Backend work

**Files new:**
- `app/models/public_reg_session.py`
- `app/schemas/public_registration.py` — `SelfRegStartRequest`, `OtpVerifyRequest`, `SelfRegSubmitRequest`, `SelfRegStartResponse`, `SelfRegSubmitResponse`
- `app/repositories/public_reg_repository.py`
- `app/services/public_registration_service.py` — 3 main methods:
  - `start_registration(data: SelfRegStartRequest, request: Request) -> SelfRegStartResponse` — picks channel (Zalo if `phone` and consent, else email), generates 6-digit OTP, hashes via argon2, dispatches via `notification_dispatcher.dispatch(event=SELF_REG_OTP_REQUESTED, ...)`, returns `session_token + masked_channel`
  - `verify_otp(session_token, otp) -> SelfRegVerifyResponse` — increments attempts, locks after 5 fails, sets `otp_verified_at`
  - `submit_registration(session_token, data: SelfRegSubmitRequest) -> AdmissionProfileResponse` — requires verified OTP, creates `Lead` (default `unit_id` derived from wave's council.unit_id) + `AdmissionProfile(status='draft', admission_wave_id=..., created_via='self_registration')` in one transaction. Returns profile + a magic-link-like `applicant_token` (reuse `AdmissionConfirmationToken` pattern scoped for "applicant editing") so thí sinh có thể quay lại sửa trước deadline.
- `app/services/notification_channels/` — extend `zalo_channel.py` to accept `self_reg_otp` template; register ZBS template `self_reg_otp` with Zalo (ops step)
- `app/routers/public_registration.py` — `/api/public/registrations/*`
- `app/services/notification_registry.py` or `app/services/notification_payloads.py` — add `SELF_REG_OTP_REQUESTED` event with payload `{otp, citizen_id_last4, wave_name, ttl_minutes}`
- `app/tasks/public_reg_tasks.py` (new) — Celery task `cleanup_expired_sessions` (runs hourly, deletes unverified sessions with `otp_expires_at < now - 1h`)

**Endpoints (all no-auth, but rate-limited):**

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/public/registrations/start` | `{citizen_id, phone?, email?, wave_id}` | `{session_token, channel, masked_destination, ttl_seconds}` |
| POST | `/api/public/registrations/verify-otp` | `{session_token, otp}` | `{verified: bool, attempts_left: int}` |
| POST | `/api/public/registrations/resend-otp` | `{session_token}` | `{ttl_seconds}` (max 2 resends) |
| POST | `/api/public/registrations/submit` | `SelfRegSubmitRequest` (full AdmissionProfile-like payload) | `{profile_id, applicant_token, lead_id}` |
| GET | `/api/public/registrations/{applicant_token}` | — | profile snapshot (for edit flow in P0-4) |

**Rate limits:**
- `start`: `RateLimits.PUBLIC_CONTACT` (5/h per IP) + custom key `citizen_id` (`10/hour` per CCCD)
- `verify-otp`: `20/hour` per `session_token`
- `resend-otp`: `3/hour` per `session_token`
- `submit`: `RateLimits.AUTH_REGISTER` (3/min)

**RBAC:** no Casbin policies (public endpoints skip enforcer via router prefix check).

**Domain exceptions (new in `exceptions.py`):**
- `OtpInvalidError(BusinessRuleViolation)` → 400 `{code: "otp_invalid", attempts_left}`
- `OtpExpiredError(BusinessRuleViolation)` → 400 `{code: "otp_expired"}`
- `OtpChannelUnavailableError(BusinessRuleViolation)` → 400 when no phone/email or no Zalo consent
- `WaveNotOpenError` (reuse from P0-2b)

**OTP channel logic (service layer):**
```python
async def _select_channel(phone, email, db) -> str:
    if phone:
        from app.repositories.notification_consent_repository import NotificationConsentRepository
        consent_granted = await NotificationConsentRepository(db).is_consent_granted(
            channel="zalo", source_type="lead", source_id=None,  # pre-lead
        )  # use phone-level check OR skip consent for self-reg? → Quy chế cho phép dùng phone người dùng tự cung cấp cho mục đích xác thực
        # Decision: skip strict consent check for self-reg OTP (user-initiated flow = implicit consent)
        return "zalo"
    if email:
        return "email"
    raise OtpChannelUnavailableError()
```

### 4.4 Frontend work

**Files new:**
- `frontend/src/app/tuyen-sinh/dang-ky/page.tsx` — landing: chọn đợt
- `frontend/src/app/tuyen-sinh/dang-ky/[waveId]/page.tsx` — multi-step form
- `frontend/src/app/tuyen-sinh/dang-ky/xac-thuc/page.tsx` — OTP entry
- `frontend/src/app/tuyen-sinh/dang-ky/hoan-tat/page.tsx` — success + show `applicant_token` link
- `frontend/src/components/public/SelfRegistrationForm.tsx`
- `frontend/src/components/public/OtpInput.tsx` (6-digit input)
- `frontend/src/components/public/WaveSelector.tsx`
- `frontend/src/lib/api/public-registration.ts`
- `frontend/src/hooks/admissions/useSelfRegistration.ts`

**Zod (mirror backend):**
```typescript
export const selfRegStartSchema = z.object({
  citizenId: z.string().length(12).regex(/^\d{12}$/),
  phone: z.string().regex(/^(\+84|0)\d{9,10}$/).optional(),
  email: z.string().email().optional(),
  waveId: z.number().int().positive(),
}).refine(d => d.phone || d.email, { message: "Cần phone hoặc email để nhận OTP" });

export const otpVerifySchema = z.object({
  sessionToken: z.string(),
  otp: z.string().length(6).regex(/^\d{6}$/),
});

export const selfRegSubmitSchema = admissionProfileSchema.pick({
  fullName: true, dob: true, gender: true, ethnicity: true,
  permanentProvince: true, permanentDistrict: true, permanentWard: true,
  permanentStreetAddress: true, placeOfBirth: true, nativePlace: true,
  // + family_info array, academic_history array, admission_path_id
});
```

**React Query:**
- `useStartSelfRegistration` (mutation)
- `useVerifyOtp` (mutation)
- `useResendOtp` (mutation with cooldown state via Zustand)
- `useSubmitSelfRegistration` (mutation)
- Store session state in `sessionStorage` (not localStorage — cleared on tab close)

### 4.5 Test plan

- **Unit:**
  - `test_public_registration_service.py::test_zalo_preferred_when_phone_present`
  - `::test_email_fallback_when_no_phone`
  - `::test_otp_expire_10_minutes`
  - `::test_otp_lock_after_5_failed_attempts`
  - `::test_submit_requires_verified_otp`
- **Integration:**
  - `tests/api/test_public_registration.py::test_full_happy_path`
  - `::test_rate_limit_enforced`
  - `::test_wave_closed_rejects_start`
  - `::test_duplicate_submit_same_wave_returns_conflict` (existing CCCD+wave unique)
- **E2E (Playwright):**
  - `tests/e2e/self-registration.spec.ts` — start → verify OTP (intercept OTP via test-only endpoint / fixture) → submit → see success page.

### 4.6 Dependencies
- P0-2b (requires `admission_wave` and wave-scoped unique constraint).

### 4.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Zalo ZNS quota (500/day as noted) could be exhausted during peak enrollment window | Monitor via `notification_quota_service`; alert at 80%; fallback to email when quota < 10% remaining; operators pre-purchase quota. |
| Abuse: attacker iterates CCCD to pre-register and block real students | Per-CCCD + per-IP rate limit; `WaveNotOpenError` before OTP sent; unverified sessions auto-cleanup after 1h; admin dashboard to clear blocked CCCDs. |
| OTP in transit security: attacker sniffs email | OTP 6 digits → 10⁶ space × 5 attempt lockout = acceptable; 10-min TTL; argon2 hash in DB. Consider rotating to HMAC on future hardening. |

---

## PR P0-4 — Self-registration phần 2 (upload tài liệu + sửa hồ sơ trước deadline)

### 5.1 Mục đích
Cho thí sinh (đã submit ở P0-3 với `applicant_token`) quay lại: upload tài liệu, chỉnh sửa thông tin hồ sơ đã điền sai, miễn là chưa qua `wave.submission_deadline`. Upload lưu local trên VPS theo convention hiện tại.

### 5.2 Schema changes

Không có bảng mới. Tận dụng `ProfileDocument` hiện có.
**Modifies:**
- Extend `AdmissionConfirmationToken` semantics: add `token_type: Mapped[str]` with values `enroll_confirm` (existing behavior) vs `applicant_edit` (new). Default `'enroll_confirm'` for legacy rows. Adjust unique `UniqueConstraint('profile_id','token_type')` (a profile can have both).

**Alembic migration — `p0_4_applicant_edit_token_<ts>.py`:**
- Add column `token_type VARCHAR(20) NOT NULL DEFAULT 'enroll_confirm'`.
- Drop existing `UniqueConstraint(profile_id)` → `UniqueConstraint(profile_id, token_type)`.
- Add CHECK constraint.

### 5.3 Backend work

**Files new/modify:**
- `app/models/admission.py` — add `token_type` to `AdmissionConfirmationToken`
- `app/services/public_registration_service.py` — add:
  - `get_profile_by_applicant_token(token) -> AdmissionProfileResponse` (validates not expired, token_type='applicant_edit')
  - `update_profile_via_applicant_token(token, data)` — checks wave deadline, delegates to `admission_service.update_profile` with synthetic `current_user=None` and bypasses officer-only permission checks using a new `system_actor` pattern
  - `upload_document_via_applicant_token(token, doc_code, file)` — same pattern
- `app/services/admission_service.py` — support `current_user=None` for self-service paths; add `actor_kind='applicant'` in audit fields
- `app/routers/public_registration.py` — new endpoints below
- `app/utils/file_helpers.py` — harden `save_upload` for public context (stricter MIME sniffing via `python-magic`, reject PHP/HTML regardless of extension)
- Storage location reuse: `app/static/uploads/admissions/{profile_id}/{doc_code}_{uuid}.ext`

**Endpoints:**

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/public/registrations/{token}/profile` | — | profile snapshot (hides internal fields) |
| PUT | `/api/public/registrations/{token}/profile` | `PublicProfileUpdateRequest` | updated snapshot |
| POST | `/api/public/registrations/{token}/documents/{doc_code}` | `multipart/form-data: file` | profile with updated docs |
| DELETE | `/api/public/registrations/{token}/documents/{doc_code}` | — | profile |
| POST | `/api/public/registrations/{token}/submit-final` | — | transitions status `draft` → `submitted` |

**RBAC:** no Casbin; token IS the auth mechanism. Token validates: (1) exists, (2) not expired, (3) `token_type='applicant_edit'`, (4) wave deadline not passed.

**Service method key logic:**
```python
async def _assert_editable(profile: AdmissionProfile, db: AsyncSession) -> None:
    if profile.admission_wave_id is None:
        raise BusinessRuleViolation("wave_required_for_edit")
    wave = await db.get(AdmissionWave, profile.admission_wave_id)
    if datetime.now(timezone.utc) > wave.submission_deadline:
        raise WaveSubmissionDeadlinePassedError()
    if profile.status not in ("draft","submitted","revision_requested","resubmitted"):
        raise BusinessRuleViolation(f"status_{profile.status}_not_editable_by_applicant")
```

**Domain exceptions:** reuse `WaveSubmissionDeadlinePassedError` from P0-2b.

### 5.4 Frontend work

**Files new:**
- `frontend/src/app/tuyen-sinh/ho-so-cua-toi/[token]/page.tsx` — landing with countdown timer to deadline
- `frontend/src/app/tuyen-sinh/ho-so-cua-toi/[token]/thong-tin/page.tsx` — editable profile form
- `frontend/src/app/tuyen-sinh/ho-so-cua-toi/[token]/tai-lieu/page.tsx` — document upload grid
- `frontend/src/components/public/ApplicantDocumentUploader.tsx`
- `frontend/src/components/public/DeadlineCountdown.tsx`
- `frontend/src/lib/api/public-registration.ts` — extend with profile GET/PUT + document upload/delete + submit-final
- `frontend/src/hooks/admissions/useApplicantProfile.ts`

**Zod:**
```typescript
export const publicProfileUpdateSchema = selfRegSubmitSchema.deepPartial();
// document upload uses FormData — no Zod on body, but validate on client: file.size < 10MB, type in [pdf, jpg, png]
```

**React Query:**
- `useApplicantProfile(token)` with `staleTime: 30s`
- `useUpdateApplicantProfile`
- `useUploadApplicantDocument`
- `useSubmitFinal`

### 5.5 Test plan

- **Unit:**
  - `test_applicant_token_edit.py::test_edit_blocked_after_deadline`
  - `::test_edit_blocked_when_approved`
  - `::test_file_mime_sniff_rejects_php`
- **Integration:**
  - `tests/api/test_public_applicant_edit.py::test_upload_document_via_token`
  - `::test_submit_final_transitions_status`
- **E2E:** Playwright — open token URL → edit phone → upload CCCD scan → verify server response.

### 5.6 Dependencies
- P0-3 (requires `applicant_token` generated at submit time).
- P0-2b (requires `wave.submission_deadline`).

### 5.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Path traversal / arbitrary file upload via public endpoint | Reuse hardened `upload_document` logic (UUID filename, extension whitelist, MIME sniff). Add antivirus hook (stub for future ClamAV). Store outside web root — serve via authenticated `/api/admissions/{id}/documents/{doc_id}/download`. |
| Local VPS disk filled by abusive uploads | File size cap 10MB enforced at FastAPI + nginx level. Total per-profile cap 50MB. Celery job monitors disk usage + alerts at 80%. |
| Token leaked via email forward → stranger edits profile | Token TTL mirrors wave deadline, single-use regeneration on suspicious activity (admin can rotate via `/api/admin/profiles/{id}/rotate-applicant-token`). |

---

## PR P0-5 — Thanh toán lệ phí tuyển sinh

### 6.1 Mục đích
Khi thí sinh submit (P0-3) hoặc sửa (P0-4) với `admission_path.application_fee > 0`, tạo `Fee` tương ứng và render bước thanh toán trong portal. Reuse Finance module — không đẻ bảng mới.

### 6.2 Schema changes
Không có bảng mới. Finance đã có `Fee` với FK `admission_profile_id`.

**Modifies:**
- `Fee` table — ensure there's a `fee_type = 'application'` enum value (already exists — confirm by reading `FeeTypeEnum`).
- `AdmissionProfile.created_via` FK chain: if `'self_registration'`, the Fee's `payer_type='applicant'` (existing field).

### 6.3 Backend work

**Files new/modify:**
- `app/services/public_registration_service.py` — after submit:
  ```python
  if path.requires_application_fee:
      fee = await fee_calculation_service.create_application_fee(
          db, profile=profile, amount=path.application_fee, due_date=wave.closes_at
      )
  ```
- `app/services/fee_calculation_service.py` — expose `create_application_fee`
- `app/routers/public_registration.py` — new endpoints:
  - `GET /api/public/registrations/{token}/fees` → list Fee for profile
  - `POST /api/public/registrations/{token}/fees/{fee_id}/initiate-payment` → create `PaymentIntent` via existing `payment_intent_service`, return VNPay/MoMo redirect URL
- `app/routers/payments.py` — existing webhook handlers already process `PaymentIntent` callbacks; verify they work with `payer_type='applicant'`.
- No new Casbin policies.

**Domain exceptions:** reuse Finance exceptions.

### 6.4 Frontend work

**Files new/modify:**
- `frontend/src/app/tuyen-sinh/ho-so-cua-toi/[token]/thanh-toan/page.tsx` — fee list + "Thanh toán online" button
- `frontend/src/app/tuyen-sinh/thanh-toan/ket-qua/page.tsx` — callback landing
- `frontend/src/components/public/ApplicantFeeList.tsx`
- `frontend/src/lib/api/public-registration.ts` — add fee endpoints
- `frontend/src/hooks/finance/useApplicantFees.ts`

**Zod:** `applicantFeeSchema` mirrors `FeeResponse`.

### 6.5 Test plan

- **Unit:** `test_application_fee_created_on_submit`, `test_zero_fee_skipped`.
- **Integration:** simulate VNPay callback → `Fee.status` transitions to paid.
- **E2E:** end-to-end via VNPay sandbox.

### 6.6 Dependencies
P0-3 (submit creates fee), P0-4 (token-authed endpoints).

### 6.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Fee created but payment intent never initiated → stale Fees clutter | Celery cleanup: cancel unpaid fees when wave closes (status → `cancelled`). |
| Payment callback arrives AFTER wave closes; profile in "submitted" but un-editable | Decouple fee payment from wave deadline — fee can be paid even after submission_deadline as long as status is still "submitted". Explicit logic in service. |

---

## PR P0-6 — Export PDF Phiếu đăng ký xét tuyển (PL02)

### 7.1 Mục đích
Render 1 PDF / 1 thí sinh đúng mẫu PL02 của TT 05/2021 (Phiếu đăng ký xét tuyển) để in, ký, lưu hồ sơ giấy. Cần hỗ trợ font tiếng Việt và chữ ký số của chủ tịch Hội đồng (từ P0-2).

### 7.2 Schema changes
Không có.

### 7.3 Backend work

**Dependencies new (add to `requirements.txt`):**
- `reportlab==4.2.5` (pure Python, handles Vietnamese via TTF registration) — primary choice
- Alternative considered: `WeasyPrint` — rejected (requires GTK + Cairo, heavy Docker image)

**Files new:**
- `app/services/admission_pdf_service.py` — 3 methods:
  - `render_pl02_registration_form(profile_id: int, db: AsyncSession) -> bytes` — returns PDF bytes
  - `_register_fonts()` — loads `DejaVuSans.ttf` + `DejaVuSans-Bold.ttf` from `app/static/fonts/`
  - `_build_pl02_layout(canvas, profile, council)` — ReportLab canvas drawing commands
- `app/routers/admissions.py` — add endpoint:
  - `GET /api/admissions/{profile_id}/export/registration-form.pdf` (officer + admin + manager) — returns `StreamingResponse(media_type="application/pdf")` with `Content-Disposition: attachment; filename=phieu-dang-ky-{citizen_id}.pdf`
- `app/routers/public_registration.py`:
  - `GET /api/public/registrations/{token}/export/registration-form.pdf` (applicant can download own form)
- `app/static/fonts/` (new dir) — commit `DejaVuSans.ttf` (GPL-compatible) or use Google Noto Sans.

**Template layout (hardcoded mapping per PL02):**
- Header: tên trường + năm học + ĐỢT X
- Block 1: thông tin cá nhân (họ tên, CCCD, ngày sinh, giới tính, dân tộc, …)
- Block 2: hộ khẩu thường trú
- Block 3: thông tin gia đình (table)
- Block 4: quá trình học tập (table)
- Block 5: nguyện vọng đăng ký (1 ngành trong P0 scope)
- Block 6: cam kết + chữ ký thí sinh + chữ ký chủ tịch HĐ (rendered from `council.members[chairman].signature_file_path`)
- Footer: ngày xuất + hash ngắn để chống giả mạo

**RBAC (migration `p0_6_casbin_<ts>.py` + templates):**
- `p, role:officer, /api/admissions/*/export/*, GET`
- `p, role:manager, /api/admissions/*/export/*, GET`
- `p, role:admin, /api/admissions/*/export/*, GET`

### 7.4 Frontend work

**Files new/modify:**
- `frontend/src/app/(dashboard)/admissions/[id]/page.tsx` — add "Xuất PL02 (PDF)" button
- `frontend/src/app/tuyen-sinh/ho-so-cua-toi/[token]/page.tsx` — add download button
- `frontend/src/lib/api/admissions.ts` — `downloadRegistrationFormPdf(profileId)` returns Blob
- No Zod — binary response.
- React Query: `useDownloadRegistrationForm` with `fetch` + blob + `saveAs`.

### 7.5 Test plan

- **Unit:** `test_admission_pdf_service.py::test_vietnamese_diacritics_render`, `::test_pl02_sections_present` (parses PDF with `pypdf` → extracts text → asserts keywords).
- **Integration:** `tests/api/test_admission_pdf_endpoint.py::test_returns_pdf_content_type`, `::test_idor_crossunit_404`.
- **Visual regression:** snapshot PDF → compare with golden file in `tests/fixtures/pdf/pl02_expected.pdf` via `pypdf.extract_text` diff.

### 7.6 Dependencies
- P0-2 (needs council chairman for signature block).
- P0-2b (wave info in header).

### 7.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Vietnamese characters broken | Pre-register DejaVu/Noto fonts; unit test `test_vietnamese_diacritics_render` before merge. |
| Layout drifts from official PL02 template when Ministry publishes final TT 2026 | Isolate layout in single file `pl02_layout.py`; easy to swap. Document "TT 05/2021 compatible" in PDF footer. |
| PDF generation slow at scale (100+ req/s) | ReportLab is ~50ms/PDF; acceptable. For batch → delegate to Celery (P0-8). |

---

## PR P0-7 — Export bộ hồ sơ thí sinh (PDF tổng hợp merged)

### 8.1 Mục đích
1 thí sinh → 1 PDF duy nhất gồm: PL02 + tất cả ProfileDocument (scan: PDF merge; ảnh JPG/PNG: convert thành trang PDF). Phục vụ lưu trữ số + chia sẻ với cán bộ xét duyệt.

### 8.2 Schema changes
Không có.

### 8.3 Backend work

**Dependencies new:**
- `pypdf==5.1.0` (merge PDFs)
- `Pillow==11.0.0` (image → PDF conversion; already likely present — check)

**Files new/modify:**
- `app/services/admission_pdf_service.py` — add:
  - `render_full_profile_bundle(profile_id, db) -> bytes` — generates PL02 → for each `ProfileDocument` with `status in ('uploaded','verified')` → if PDF: append; if image: wrap in PDF page with cover page "Tài liệu: {doc_type.name}"
- `app/routers/admissions.py` — add:
  - `GET /api/admissions/{profile_id}/export/full-bundle.pdf`

**Logic:**
```python
writer = pypdf.PdfWriter()
# 1. Add PL02
pl02_bytes = render_pl02_registration_form(...)
writer.append(io.BytesIO(pl02_bytes))
# 2. For each document
for doc in sorted(profile.documents, key=lambda d: d.document_type.display_order):
    if not doc.file_path or doc.status == 'missing': continue
    # Cover page
    cover = _render_doc_cover_page(doc.document_type.name)
    writer.append(io.BytesIO(cover))
    if doc.file_path.endswith('.pdf'):
        writer.append(doc.file_path)
    else:
        img = Image.open(doc.file_path).convert('RGB')
        img_pdf = io.BytesIO()
        img.save(img_pdf, format='PDF')
        writer.append(img_pdf)
out = io.BytesIO()
writer.write(out)
return out.getvalue()
```

**RBAC:** same policy as P0-6 (already added).

### 8.4 Frontend work

- `frontend/src/app/(dashboard)/admissions/[id]/page.tsx` — "Xuất bộ hồ sơ (PDF tổng)" button next to PL02.
- `frontend/src/lib/api/admissions.ts` — `downloadFullBundlePdf(profileId)`.

### 8.5 Test plan

- **Unit:** `test_full_bundle.py::test_merges_pl02_and_documents_in_order`, `::test_skips_missing_documents`, `::test_converts_jpg_to_pdf_page`.
- **Integration:** upload 3 mixed documents → download bundle → assert page count.

### 8.6 Dependencies
- P0-4 (documents uploaded)
- P0-6 (PL02 rendering)

### 8.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Huge files (50 MB per profile) block request thread | Stream via `StreamingResponse`. If profile has >30 docs, reject synchronous — redirect to P0-8 ZIP flow. |
| Corrupted uploaded PDF crashes pypdf | Wrap each append in try/except → on failure insert a "page unreadable" stub with the original filename + link to standalone download. |

---

## PR P0-8 — ZIP bundle theo đợt (Celery task)

### 9.1 Mục đích
Admin xuất "toàn bộ hồ sơ đợt X" thành 1 file ZIP chứa: 1 thư mục per profile, mỗi thư mục có `full-bundle.pdf` + `manifest.json` metadata. Công việc async qua Celery + tải về qua pre-signed URL (hoặc static serving).

### 9.2 Schema changes

**Model mới — `app/models/admission_export_job.py`:**
```python
class AdmissionExportJob(Base):
    __tablename__ = "admission_export_job"
    id = Column(Integer, primary_key=True)
    wave_id = Column(Integer, ForeignKey("admission_wave.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, server_default="queued")  # queued | processing | ready | failed
    requested_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    total_profiles = Column(Integer, nullable=True)
    processed_profiles = Column(Integer, nullable=False, server_default="0")
    output_path = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, comment="File deleted after this")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('queued','processing','ready','failed')", name="ck_export_job_status"),
    )
```

**Alembic migration — `p0_8_admission_export_job_<ts>.py`:** create table.

### 9.3 Backend work

**Files new:**
- `app/models/admission_export_job.py`
- `app/schemas/admission_export_job.py`
- `app/repositories/admission_export_job_repository.py`
- `app/services/admission_export_service.py` — `queue_wave_export(wave_id, current_user)`, `get_status(job_id)`
- `app/tasks/admission_export_tasks.py` — Celery task:
  ```python
  @celery_app.task(bind=True, max_retries=1)
  def build_wave_zip(self, job_id: int):
      # Use sync DB session (Celery pattern in this codebase)
      # For each profile in wave: call admission_pdf_service.render_full_profile_bundle()
      # Write to tempdir, then zip, then move to app/static/exports/wave_{wave_id}_{ts}.zip
      # Update job status progressively
      # Emit SystemEvents.ADMISSION_EXPORT_READY notification to requester
  ```
- `app/routers/admission_exports.py` — endpoints:
  - `POST /api/admission/waves/{wave_id}/exports` → enqueue, return job
  - `GET /api/admission/export-jobs/{id}` → status + download URL when ready
  - `GET /api/admission/export-jobs/{id}/download` → file stream (IDOR: requested_by OR admin)

**Event:** `ADMISSION_EXPORT_READY` in `event_catalog.py` + seed `notification_rule` row.

**RBAC:** admin + manager (scoped to wave.council.unit_id).

**Cleanup:** Celery beat schedule `cleanup_expired_exports` runs daily; deletes files past `expires_at` (default 7 days).

### 9.4 Frontend work

**Files new:**
- `frontend/src/app/(dashboard)/admin/admission-config/waves/[id]/page.tsx` — add "Xuất ZIP đợt" button
- `frontend/src/app/(dashboard)/admin/admission-config/export-jobs/page.tsx` (list + progress bars)
- `frontend/src/hooks/admissions/useAdmissionExport.ts` — polls job status every 3s until `ready`
- `frontend/src/lib/api/admission-exports.ts`

**React Query:** `useEnqueueExport`, `useExportJobStatus(jobId)` with `refetchInterval: (q) => q.state.data?.status === 'ready' ? false : 3000`.

### 9.5 Test plan

- **Unit:** `test_admission_export_tasks.py::test_zip_structure`, `::test_partial_failure_marks_job_failed_but_keeps_files`.
- **Integration:** queue job → poll → download → inspect ZIP via `zipfile`.
- **Load:** seed 500 profiles → measure task time → ensure <5 min.

### 9.6 Dependencies
- P0-7 (uses `render_full_profile_bundle`)

### 9.7 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Long-running Celery task times out (default 600s) | Increase `task_time_limit=1800` for this task; stream progress updates every N profiles. |
| Two admins click "export" simultaneously → duplicate work | In `queue_wave_export`, check for existing `queued`/`processing` job for same wave < 1h old → return existing job. |
| Disk fill by un-downloaded ZIPs | `expires_at = created_at + 7d`; beat task deletes old files; alert at >10GB in `exports/`. |

---

## 10. Cross-cutting: Deployment checklist cho P0 hoàn chỉnh

### 10.1 Pre-deployment
- [ ] Staging DB backup taken (pg_dump).
- [ ] Staging data audited for duplicate `(citizen_id, academic_year)` pairs — deduplicate BEFORE P0-2b migration.
- [ ] Zalo ZBS template for `self_reg_otp` submitted and approved by Zalo (5-day lead time).
- [ ] Fonts `DejaVuSans.ttf` + `DejaVuSans-Bold.ttf` committed to `app/static/fonts/` — verified in Docker image build.
- [ ] pypdf + reportlab + Pillow in `requirements.txt` — image built and smoke-tested.

### 10.2 Environment variables (new in `.env`)
```bash
# OTP
SELF_REG_OTP_TTL_SECONDS=600
SELF_REG_OTP_MAX_ATTEMPTS=5
SELF_REG_OTP_RESEND_COOLDOWN_SECONDS=60

# Zalo templates
ZALO_TEMPLATE_SELF_REG_OTP=<template_id_from_zalo_portal>

# Exports
ADMISSION_EXPORT_STORAGE_DIR=/app/static/exports
ADMISSION_EXPORT_TTL_DAYS=7
ADMISSION_EXPORT_MAX_SIZE_GB=20

# Uploads (existing but verify)
ADMISSION_UPLOAD_DIR=/app/static/uploads/admissions
ADMISSION_UPLOAD_MAX_MB=10
```

### 10.3 Migration run order
```bash
docker compose exec backend alembic upgrade head
# Should apply in order (if all PRs merged):
# p0_1_degree_level_education_track
# p0_2_admission_council
# p0_2b_admission_wave
# p0_3_public_reg_session
# p0_4_applicant_edit_token
# p0_6_casbin_pdf_export
# p0_8_admission_export_job
```

### 10.4 Casbin policy reload
After migration `p0_2_casbin_policies` and `p0_6_casbin_pdf_export`:
```bash
docker compose exec backend python -c "from app.services.casbin_service import reload_policies; import asyncio; asyncio.run(reload_policies())"
# OR: docker compose restart backend
```

### 10.5 Celery beat schedules
Add to `app/celery_app.py` `beat_schedule`:
```python
'cleanup-reg-sessions': {'task': 'app.tasks.public_reg_tasks.cleanup_expired_sessions', 'schedule': crontab(minute=0)},
'cleanup-export-files':  {'task': 'app.tasks.admission_export_tasks.cleanup_expired_exports', 'schedule': crontab(hour=2, minute=0)},
'close-waves-auto':      {'task': 'app.tasks.admission_wave_tasks.auto_close_expired_waves', 'schedule': crontab(minute='*/15')},
```

### 10.6 Static assets
- `app/static/fonts/` — TTFs committed, not in `.dockerignore`
- `app/static/uploads/admissions/` — created at container start (volume mount)
- `app/static/exports/` — created at container start (volume mount, separate disk if possible)

### 10.7 Nginx config
Add in `nginx/conf.d/qlts.conf`:
```nginx
client_max_body_size 12M;          # 10MB file + overhead
location /api/public/registrations/ {
    limit_req zone=public_registration burst=10 nodelay;
    proxy_pass http://backend:8000;
}
```

### 10.8 Seed data (run ONCE post-deploy)
```bash
docker compose exec backend python -m app.scripts.seed_p0_data
# Seeds:
# - 4 GDNN degree levels (idempotent via migration)
# - Default notification templates for SELF_REG_OTP_REQUESTED (email + zalo)
# - NotificationRule rows for new events
```

### 10.9 Smoke test checklist (production)
- [ ] `GET /api/config/degree-levels?education_track=gdnn` returns 4 items
- [ ] Admin creates council → adds chairman → visible in list
- [ ] Admin creates wave → status=draft → open → shows in `/api/public/admissions/waves`
- [ ] Thí sinh test: `/tuyen-sinh/dang-ky` → submit → receives Zalo OTP → verifies → sees success
- [ ] PL02 PDF renders with Vietnamese diacritics intact
- [ ] Admin queues wave export → 1 profile → ZIP downloadable in <60s

---

## 11. Open questions / gaps in provided context

1. **Lead creation on self-registration:** The current `Lead` table requires `unit_id`. When a self-registered applicant has no pre-existing Lead, we need to decide *which* unit to assign. Proposed rule: derive from `wave.council.unit_id`. **Confirm this matches business intent** — or should there be a "public inbox" unit per track?

2. **Auto-assignment of reviewer:** P0 scope says "Hội đồng TS lite phục vụ lưu trữ audit" — but self-registered profiles still need an `assigned_reviewer_id`. Current implementation leaves it null. Is that acceptable, or do we need P0 to integrate with existing `assignment_service`?

3. **NotificationConsent for self-reg OTP:** Zalo channel strictly checks consent (`zalo_channel.py` line 76–96). For self-reg, the user provides their phone directly → arguably implicit consent for OTP. **Proposal:** bypass consent check for `event=SELF_REG_OTP_REQUESTED` via a whitelist in `zalo_channel.execute_delivery`. Need product decision.

4. **Storage backend for P0-5/6/7/8 files:** Context says "lưu trữ local trên VPS". All current `app/static/uploads/*` code writes to the container's local FS. In multi-replica Docker setup, this breaks. **Recommend** volume mount `./data:/app/static` in `docker-compose.yml` shared across replicas; or use a single-replica deployment for P0 and revisit in P1 with S3/MinIO.

5. **PL02 exact layout:** The spec says "sẽ fetch chi tiết khi code". Until the final TT 2026/TT-BGDĐT template is published, we implement TT 05/2021's PL02. **Expect 1–2 days additional work** to swap layout when final published.

6. **OTP reconciliation with existing `AdmissionConfirmationToken`:** The magic-link pattern is similar but semantically different (enroll confirm vs applicant edit vs OTP). P0-4 introduces `token_type`. **Consider** instead making `PublicRegSession` also handle the "applicant edit" flow (one unified session) to avoid two auth primitives — but that widens PR-4 scope. Current plan keeps them separate for clarity.

7. **RBAC for self-registration "officer view" post-submit:** Self-registered profiles show up in officer dashboard, but they have no `assigned_officer_id` initially. Existing IDOR rules (`get_admission_profile_for_user`) would return 404. **Proposal:** add dependency variant `get_admission_profile_for_reviewer` that allows managers + admins in the same unit to view unassigned self-reg profiles. Needs separate PR note.

8. **Rate-limit key for `start` endpoint:** Per-IP is weak (NAT). Per-CCCD is fragile (attacker guesses). Implementation: both, in AND (fail if either exceeded). Verify with QA.

### Critical Files for Implementation
- `D:/QLTS/Backend_FastAPI/app/models/admission.py`
- `D:/QLTS/Backend_FastAPI/app/models/admission_config/admission_path.py`
- `D:/QLTS/Backend_FastAPI/app/services/admission_service.py`
- `D:/QLTS/Backend_FastAPI/app/services/notification_channels/zalo_channel.py`
- `D:/QLTS/Backend_FastAPI/app/casbin_config/policy_templates.py`