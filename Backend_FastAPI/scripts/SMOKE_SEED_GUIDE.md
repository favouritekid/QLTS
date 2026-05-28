# Smoke Seed Guide

Hướng dẫn sử dụng `scripts/seed_smoke_dev.py` để seed edge-state fixture cho
local pre-push Chrome MCP smoke verify.

## Mục đích

`seed_from_xlsx.py` + `seed_sample_data.py` lo phần **core data** (programs,
offerings, methods, users, casbin). Script này thêm layer **edge-state matrix**
cần cho 18 smoke scenarios cover PR-1+PR-2+PR-3+PR-4 — không trùng lặp với
seed gốc, không gọi từ CI fixture.

## Quick start

```bash
# Lần đầu (giả định core data đã loaded)
docker compose exec backend python -m scripts.seed_smoke_dev

# Verify
docker compose exec backend python -m scripts.seed_smoke_dev --verify

# Re-seed group cụ thể (idempotent)
docker compose exec backend python -m scripts.seed_smoke_dev --group 1 2

# Reset all smoke fixtures (cascade delete)
docker compose exec backend python -m scripts.seed_smoke_dev --reset
```

## Production guard

Hai-tầng abort:
1. `APP_ENV=production` → abort
2. `DATABASE_URL` chứa substring `qlts_prod` → abort

Cả hai layer nhằm tránh seed test data lên prod (sẽ làm SMK_* rounds visible
trên storefront + fake profile lẫn pipeline thật).

## Fixture matrix

### Group 1 — Round (6 rows)

| Round code | Window | multi_nv | Mục đích |
|------------|--------|----------|----------|
| `SMK_ACTIVE_MULTI` | today-10..today+30 | true | S3, S5, S10-14 |
| `SMK_ACTIVE_SINGLE` | today-10..today+30 | false | Audience filter |
| `SMK_EXPIRED` | today-30..today-1 | false | S7 cutoff create 410 |
| `SMK_ARCHIVED` | today-60..today-10, archived_at=NOW | false | S4 archived empty |
| `SMK_FUTURE` | today+30..today+60 | false | F43 future filter |
| `SMK_OPEN_ENDED` | NULL..NULL | false | F43 NULL window edge |

### Group 2 — Path (9 rows on Group 1 rounds)

| Label | Round | Quota | Audience | Visibility | Status |
|-------|-------|-------|----------|------------|--------|
| `full_quota_1` | ACTIVE_MULTI | 1 | — | public | active |
| `free_quota_5` | ACTIVE_MULTI | 5 | — | public | active |
| `unbounded_null` | ACTIVE_MULTI | NULL | — | public | active |
| `audience_thpt` | ACTIVE_SINGLE | 10 | `[POST_THPT]` | public | active |
| `audience_vlvh` | ACTIVE_SINGLE | 10 | `[VLVH]` | public | active |
| `audience_null` | ACTIVE_SINGLE | 10 | NULL (legacy all) | public | active |
| `internal_hidden` | OPEN_ENDED | 5 | — | **internal** | active |
| `archived_path` | OPEN_ENDED | 5 | — | public | **archived** |
| `on_expired_round` | EXPIRED | 5 | — | public | active |

### Group 3 — Annual quota Tier 1 (2 paths)

| Label | annual_admission_quota | admit_quota | Method | Mục đích |
|-------|------------------------|-------------|--------|----------|
| `capped_path_0` | 2 (set on academic_info) | 10 | hoc_ba | PR-1 Tier 1 cross-method anchor |
| `capped_path_1` | shares ai cap | 10 | thpt_qg | PR-1 Tier 1 cross-method anchor |

Group 4 seeded 2 profiles admitted via these paths → Tier 1 cap saturated.
Next admit attempt on either path returns `OFFERING_ANNUAL_QUOTA_EXHAUSTED`.

### Group 4 — Profile state (7 rows)

| Profile label | Citizen | Status | Choice decision | Mục đích |
|---------------|---------|--------|-----------------|----------|
| `DRAFT_active` | SMOKEDEV0001 | draft | (none) | S5 create + S8 PATCH cutoff |
| `DRAFT_expired` | SMOKEDEV0002 | draft | (none) | S9 DELETE allow after cutoff |
| `SUBMITTED_pending` | SMOKEDEV0003 | submitted | pending | PR-4 admin rollback realistic |
| `ADMITTED_consumer` | SMOKEDEV0004 | admitted | admitted | S10 quota anchor (consume full_quota_1) |
| `WAITLISTED_promotable` | SMOKEDEV0005 | waitlisted | waitlisted | S13, S14 promote |
| `REJECTED` | SMOKEDEV0006 | rejected | rejected | S11 FE label rendering |
| `ENROLLED` | SMOKEDEV0007 | enrolled | pending | KPI funnel smoke |

State transitions qua `admission_state_service.transition()` với `skip_dispatch=True`
— preserve audit chain + status_history, KHÔNG fire notification.

### Group 5 — Magic-link token (6 rows)

| Token label | Profile | action_type | State | Mục đích |
|-------------|---------|-------------|-------|----------|
| `SUBMIT_active` | DRAFT_active | submit | unused, 7d expiry | Magic-link submit happy path |
| `CONFIRM_active` | ADMITTED_consumer | confirm | unused | Confirm flow |
| `RESUBMIT_active` | REJECTED | resubmit | unused | Resubmit revision |
| `EXPIRED` | DRAFT_expired | submit | expires_at < now | Token expiry handling |
| `CONSUMED` | SUBMITTED_pending | confirm | confirmed_at NOT NULL | Replay prevention |
| `HARD_LOCKED` | WAITLISTED_promotable | submit | attempt=10, lock_until=+24h | Cooldown ladder cap |

Tokens deterministic: `smk_dev_<label>_<profile_id:06d>` (idempotent re-seed).

## Scenario coverage map

| Scenario | Fixture cần |
|----------|-------------|
| S1 storefront default | SMK_ACTIVE_MULTI + path (any) |
| S2 tuition default | (parity) |
| S3 explicit active round | SMK_ACTIVE_MULTI |
| S4 expired round explicit | SMK_EXPIRED + on_expired_round |
| S4a sentinel invalid | None (FE-level) |
| S4b audience filter | audience_thpt + audience_vlvh + audience_null |
| S5 create profile | SMK_ACTIVE_MULTI + free_quota_5 + officer auth + DRAFT_active reference |
| S6 submit profile | (same as S5) + SUBMITTED_pending sample |
| S7 cutoff create | SMK_EXPIRED |
| S8 choice PATCH cutoff | DRAFT_expired + on_expired_round |
| S9 choice DELETE allow | DRAFT_expired |
| S10 quota cascade | ADMITTED_consumer (đã chiếm seat) + full_quota_1 + free_quota_5 |
| S11 FE reason label | WAITLISTED_promotable view detail |
| S12 all-NV-full | new profile + full_quota_1 + full_quota_1' (manual seed?) |
| S13 promote blocked | WAITLISTED_promotable + admin auth |
| S14 promote freed | rollback ADMITTED_consumer → promote |

## Integration với workflow

### Pre-push local smoke (1 dev, 1 lap)

```bash
# 1. Verify core data (optional, slow nếu chưa có)
docker compose exec backend python -m scripts.seed_from_xlsx --dry-run

# 2. Layer smoke fixtures (fast, idempotent ~20s)
docker compose exec backend python -m scripts.seed_smoke_dev

# 3. Chrome MCP smoke 18 scenarios (assistant-driven)
# Hoặc skill /test với smoke scope

# 4. (Optional) cleanup post-push
docker compose exec backend python -m scripts.seed_smoke_dev --reset
```

### CI integration — KHÔNG

CI test có fixture pytest dedicate, không cần seed runtime DB. Script này
chỉ cho LOCAL dev DB.

### Nightly Playwright

Nếu nightly-regression cần extended coverage cho mobile responsive +
empty state UI, có thể thêm step seed_smoke_dev sau seed_from_xlsx trong
`.github/workflows/nightly-regression.yml`. Hiện tại chưa wire.

## Caveats + Lessons

### Constraint UNIQUE đã hit trong development

1. `round_code VARCHAR(20)` — `SMOKE_DEV_ACTIVE_MULTI` (21 chars) overflow.
   Fix: prefix `SMK_` (4 chars).
2. `uq_admission_profile_lead_year` — 1 lead / 1 academic_year. Fix: seed
   N leads (1 per profile fixture).
3. `uq_active_token_per_profile_action` — 1 profile / 1 action_type unique.
   Fix: spread token spec qua different profiles.

### `applied_rules_immutability_trigger`

Memory `applied_rules_immutability_trigger`: trigger block UPDATE on
applied_rules. Script này chỉ INSERT (initial state), KHÔNG UPDATE
applied_rules. State transition mutate `status` field, không touch
applied_rules. → No trigger conflict.

### State transition + dispatch

`admission_state_service.transition()` mặc định fire notification dispatch
+ outbox. Script gọi với `skip_dispatch=True` để seed silent (memory
`notification-payload-design`). Audit log VẪN created — status_history
chain preserved → realistic data cho PR-4 rollback smoke.

### Trigger PR-1 cascade engine

Group 4 ADMITTED_consumer + WAITLISTED_promotable set `choice.decision`
trực tiếp, KHÔNG qua cascade engine. Means: real cascade re-publish khi
test S10 sẽ RE-EVALUATE — có thể flip decision. Đây là intended cho smoke
(test engine thực sự).

Nếu muốn lock decision immutable, additional flag cần consider.

### Lead pipeline_stage_id

VARCHAR(20) string FK to pipeline_stage.id. Script picks first available
via `select(...).limit(1)` — relies on `seed_categories.py` đã run.

## Failure modes + troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `value too long for type character varying(20)` | round_code prefix dài | Script đã fix `SMK_` |
| `duplicate key value violates unique constraint "uq_admission_profile_lead_year"` | 2 profiles cùng lead+year | Reset rồi re-seed (script đã spread leads) |
| `Need ≥3 active admission_methods` | Methods chưa seed | Run `seed_admission_config` trước |
| `No published academic_info found` | Offerings chưa seed | Run `seed_from_xlsx` hoặc `seed_sample_data` trước |
| Profile transition raise BusinessRuleViolation | State machine không allow chain | Verify `admission_state_machine.ALLOWED_TRANSITIONS` |
| Transition fire dispatch ngoài ý muốn | Forgot `skip_dispatch=True` | Already set ở Group 4 |

## Reset semantic

`--reset` cascade delete theo FK order:
1. `admission_confirmation_token` WHERE profile ở smoke marker
2. `admission_profile_choice` WHERE profile ở smoke marker
3. `admission_profile` WHERE `applied_rules->>'smoke_marker' = 'SMOKE_DEV'`
4. `admission_path` WHERE round LIKE `SMK_*`
5. `offering_admission_round` WHERE code LIKE `SMK_*`

**KHÔNG delete**: leads (`09000xxxxx` phone marker preserved), academic_info
(annual_quota mutate ở Group 3 KHÔNG revert), pipeline stages, users, casbin,
methods, subjects, programs. Nếu cần full reset, dùng `seed_from_xlsx` lại.

## Reference

- PR #345 (admin rollback row lock) — S14 anchor
- PR #346 (round cutoff 410) — S7-S9 anchor
- PR #347 (quota guard) — S10-S14 anchor
- PR #348 (storefront fail-closed) — S1-S4b anchor
- Memory `chrome-mcp-pre-push-smoke` — policy mandate
- Memory `pattern-change-impact-audit` — anchor test design philosophy
