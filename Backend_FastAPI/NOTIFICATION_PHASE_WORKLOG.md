# Notification System — Full Phase Worklog

> **Status**: Phase A/B/C0 done, C1 next
> **Branch**: `feature/zalo-zns-phase1`
> **Updated**: 2026-03-25

---

## Table of Contents

1. [Phase B Punch List (B1-B12)](#phase-b-punch-list)
2. [Phase C0 Spec](#phase-c0-spec)
3. [Phase C1 Plan](#phase-c1-plan)
4. [Runtime Flow (post-C0)](#runtime-flow)
5. [Preexisting Test Infra Issues](#preexisting-test-infra-issues)
6. [Architecture Decisions](#architecture-decisions)
7. [Commit History](#commit-history)
8. [Key File Map](#key-file-map)

---

## Phase B Punch List

**Mục tiêu**: delivery persistence, consent foundation, external recipient foundation, admin delivery status visibility.

### B1. Bảng `notification_delivery`

- Model: `app/models/notification_delivery.py`
- 18 fields: id, notification_id (FK nullable), event, channel, recipient_kind, user_id (FK nullable), source_type, source_id, destination, status (queued/sent/failed/skipped), error_reason, payload_snapshot (JSONB), provider_message_id, dedupe_key, rule_id (C0), action_step (C0), template_code (C0), created_at, updated_at, sent_at
- 6 indexes: channel+status+created_at, event+created_at, user_id+created_at, source_type+source_id+created_at, notification_id, rule_id+action_step+created_at (C0)
- **Status**: Done

### B2. Bảng `notification_consent`

- Model: `app/models/notification_consent.py`
- 14 fields: id, channel, source_type, source_id, normalized_phone, normalized_email, consent_status (granted/revoked), consent_source (manual/csv_import/system_seed), granted_by (FK nullable), granted_at, revoked_at, notes, created_at, updated_at
- Unique constraint: `(channel, source_type, source_id)`
- **Status**: Done

### B3. Repository layer

- `app/repositories/notification_delivery_repository.py`: create_delivery, bulk_create_deliveries, bulk_update_status (ID-scoped), update_status, get_by_notification_id, list_deliveries (with filters)
- `app/repositories/notification_consent_repository.py`: get_latest, upsert_latest (with db.refresh for stale fix), bulk_upsert, list_consents, is_consent_granted
- **Status**: Done

### B4. Delivery service

- `app/services/notification_delivery_service.py`
- Functions: build_payload_snapshot, prepare_external_deliveries, create_deliveries_for_dispatch (returns Dict[str, List[int]]), mark_delivery_ids_sent/failed/skipped (ID-scoped), legacy mark_channel_sent/failed/skipped (backward compat)
- **Status**: Done

### B5. Dispatcher integration

- Dispatcher step 6.5: creates delivery rows per action/channel with rule_id, action_step, source_type/source_id
- Post-commit: updates delivery status using channel_delivery_ids (not re-queried)
- _extract_source_from_payload() derives source_type/source_id from payload keys
- Error resilience: rollback in _bulk_create_notifications, step 6.5, safe_dispatch
- **Status**: Done

### B6. External recipient abstraction

- `app/services/notification_recipients.py`
- `ResolvedRecipient` dataclass (frozen): recipient_kind, user_id, source_type, source_id, destination_email, destination_phone
- External resolvers: resolve_lead_contact, resolve_admission_contact, resolve_collaborator_contact
- `EXTERNAL_RESOLVER_REGISTRY` mapping
- Foundation only — not live-routed in dispatcher yet
- **Status**: Done (foundation)

### B7. Consent API

- Router: `app/routers/notification_consents.py`
- Endpoints: GET /api/notification-consents, POST /upsert, POST /bulk-import
- Auth: RequireAdmin (direct role check, no Casbin)
- CSV import: validates required columns, line-by-line error reporting
- **Status**: Done

### B8. Delivery ops API

- Router: `app/routers/notification_delivery_ops.py`
- Endpoints: GET /api/notification-deliveries (filters: event, channel, status, user_id, source_type, source_id, date_from, date_to), GET /{delivery_id}
- Auth: RequireAdmin
- **Status**: Done

### B9. Freeze live scope

- Backend metadata returns channels as `{value, status}` objects (live/planned)
- NotificationRuleForm: zalo/sms checkboxes disabled + "Planned" badge
- NotificationRuleWizard: planned channels disabled with reduced opacity
- MultiStepActionEditor: zalo/sms show "(Planned)" label, muted colors, availableChannels filters to live-only
- **Status**: Done

### B10. Frontend types + endpoints + hooks

- Types: NotificationDelivery, NotificationDeliveriesPage, NotificationConsent, NotificationConsentsPage, NotificationConsentUpsert, NotificationConsentImportResult, ChannelInfo
- Endpoints: NOTIFICATION_DELIVERIES (LIST, DETAIL), NOTIFICATION_CONSENTS (LIST, UPSERT, BULK_IMPORT)
- Hooks: useNotificationDeliveries (list + detail), useNotificationConsents (list), useUpsertConsent, useBulkImportConsents
- **Status**: Done

### B11. Frontend admin UI

- `DeliveryOpsTable.tsx`: filter bar (event, channel, status) + data table with status badges + pagination
- `ConsentImportDialog.tsx`: ConsentManager with list table + ImportDialog (CSV upload + result summary) + UpsertDialog (single consent form)
- Page routes: /admin/notification-deliveries, /admin/notification-consents
- Navigation: 2 nav items (Delivery Ops, Consent) under Notifications group
- **Status**: Done

### B12. Tests

- Unit: `test_notification_delivery_service.py` (14 tests) — payload snapshot, create/mark functions, legacy compat
- API: `test_notification_deliveries.py` (7 tests) — list + filters + detail + auth
- API: `test_notification_consents.py` (9 tests) — list + upsert + bulk-import + CSV errors
- Integration: `test_notification_delivery_persistence.py` (8 tests) — CRUD lifecycle, consent upsert cycle, external recipient
- Frontend: DeliveryOpsTable.test.tsx, ConsentImportDialog.test.tsx
- **Status**: Done

### Phase B Definition of Done (all met)

- dispatch() creates delivery rows for browser/email ✅
- Admin API views delivery status ✅
- Consent latest-state + bulk import ✅
- External recipient foundation in code ✅
- UI admin views delivery, imports consent ✅
- zalo/sms not advertised as live ✅
- Tests pass ✅

---

## Phase C0 Spec

**Mục tiêu**: Biến `NotificationAction[]` thành runtime truth. Browser và email chạy qua action model mới. Rule cũ chỉ có channels không vỡ.

### Scope

- Làm: loader support actions, fallback channels→synthetic actions, dispatcher build execution plan theo action, NotificationDelivery ghi rule_id/action_step, migration backfill, browser/email qua action model mới
- Không làm: worker delayed execution, retry/dead-letter, webhook, live Zalo adapter, deprecate/xóa cột channels

### Ràng buộc C0

- `delay_minutes` chỉ support `0`
- `template_code` per action bị reject (dùng rule-level template_id)
- `browser` và `email` là live actions; `zalo` và `sms` vẫn `planned`
- `channels` top-level = derived / backward-compat

### Implementation

**ActionConfig dataclass** (`notification_rule_loader.py`):
```python
@dataclass(frozen=True)
class ActionConfig:
    step: int
    channel: str
    delay_minutes: int = 0
    template_code: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
```

**Helper functions**:
- `synthesize_actions_from_channels(channels) -> List[ActionConfig]` — backward compat
- `derive_channels_from_actions(actions) -> List[str]` — keeps channels in sync

**DatabaseRuleConfig changes**:
- `.actions` property = runtime truth (List[ActionConfig])
- `.channels` property = derived from actions
- Constructor: if actions not provided, synthesize from channels

**Loader changes**:
- Eager-load `rule.actions` with `selectinload`
- Build ActionConfig list from DB actions or synthesize
- Cache actions in Redis alongside rule data
- Deserialize cached actions on cache hit

**CRUD validation (_validate_actions_c0)**:
- reject delay_minutes > 0
- reject template_code (per-action template not implemented)
- reject duplicate steps
- reject duplicate channels
- steps must be contiguous 1..n

**Dispatcher changes**:
- Step 3: iterate `config.actions` (not `config.channel_values`)
- Step 6.5: pass `rule_id`, `channel_step_map`, `channel_template_map` to delivery service

**Delivery service changes**:
- `create_deliveries_for_dispatch()` accepts rule_id, channel_step_map, channel_template_map
- Each delivery row gets rule_id, action_step, template_code

**Migration**:
- Add rule_id, action_step, template_code to notification_delivery
- Backfill notification_action for rules with channels but no actions
- Sync channels from actions (GROUP BY channel ORDER BY MIN(step))

### Acceptance Criteria (all met)

- C0-1: Rule with actions → dispatch uses actions, not channels ✅
- C0-2: Legacy rule (channels only) → dispatch via synthetic actions ✅
- C0-3: New delivery rows have rule_id, action_step ✅
- C0-4: browser/email run through action model ✅
- C0-5: Create/update rule with actions syncs channels ✅
- C0-6: delay_minutes > 0 rejected ✅
- C0-7: UI only allows immediate live actions ✅

---

## Phase C1 Plan

### C1-1: Email tách khỏi Notification row

- EmailChannel hiện dùng Notification row (user_id → lookup email) ở `email_channel.py:72`
- Đổi: email adapter đọc từ `NotificationDelivery.payload_snapshot` + resolve email từ user_id
- External recipients: dùng `NotificationDelivery.destination` trực tiếp
- Mục tiêu: email không cần inbox Notification row để gửi

### C1-2: Worker delayed execution

- Celery task: `execute_notification_delivery(delivery_id)`
- Worker flow: load delivery → check scheduled_for → re-check preference/consent → call channel adapter → update status
- Dispatcher: actions với delay_minutes > 0 → enqueue thay vì execute inline
- Mở CRUD validation: cho phép delay_minutes > 0
- Thêm fields: scheduled_for, attempt_count, last_attempt_at
- Browser vẫn inline (delay=0), email/zalo/sms qua worker

### C1-3: Zalo adapter + webhook

- Channel adapter cho Zalo ZNS (Template Message API, OAuth v4)
- Resolve external recipient qua consent → normalized_phone
- Webhook endpoint nhận delivery status từ Zalo → update delivery row
- provider_message_id đã có sẵn trên delivery model
- Config: Zalo OA credentials trong settings
- Reference: `ZALO_INTEGRATION_PLAN.md`

### C1-4: Deprecate channels

- Bỏ channels khỏi runtime path
- Giữ channels read-only trên API response
- Xóa channels khỏi create/update schemas (hoặc ignore)
- Migration: mark column deprecated (chưa drop)

### C1 Ràng buộc

- Browser vẫn inline (không qua worker) vì cần real-time
- delay_minutes=0 actions vẫn có thể execute inline
- Consent check trước external send
- Zalo rate limits
- Recipient freeze at dispatch, eligibility re-check at send

### C1 Thứ tự khuyến nghị

1. C1-1 email separation (unblocks external delivery)
2. C1-2 worker (unblocks delayed actions)
3. C1-3 Zalo adapter (plugs into worker pipeline)
4. C1-4 deprecate channels (cleanup)

---

## Runtime Flow (post-C0)

```
ROUTER (business action)
  │
  ▼
STEP 1: LOAD RULE
  notification_rule_loader.get_rule_for_event()
  → Redis cache or DB query (eager-load actions)
  → Output: DatabaseRuleConfig with .actions, .resolver, .condition
  │
  ▼
STEP 1.5: CHECK CONDITION
  config.should_activate(payload)
  → False? emit domain event only, skip dispatch
  │
  ▼
STEP 2: RESOLVE RECIPIENTS
  config.resolver.resolve_users(db, payload)
  → [user_id_1, user_id_2, ...]
  → Exclude actor_id
  │
  ▼
STEP 3: PER-ACTION PREFERENCE FILTERING
  For each action in config.actions:
    filter_users_by_group(user_ids, group, action.channel)
    → channel_recipient_map[channel] = [filtered_ids]
  inbox_user_ids = union(all channel recipients)
  │
  ▼
STEP 4: DEDUPLICATION
  Check existing Notification with same dedupe_key + user
  │
  ▼
STEP 5: RENDER CONTENT
  title, message, link from rule template (or referenced template)
  │
  ▼
STEP 6: CREATE NOTIFICATION (inbox)
  Bulk INSERT notification rows (1 per user for bell icon)
  │
  ▼
STEP 6.5: CREATE DELIVERY RECORDS
  For each action × each recipient:
    INSERT notification_delivery with:
      event, channel, user_id, status=queued,
      rule_id, action_step, template_code,
      source_type, source_id, payload_snapshot
  Output: channel_delivery_ids {channel: [delivery_ids]}
  │
  ▼
  await db.flush()
═══════════ COMMIT ═══════════
  │
  ▼
POST-COMMIT CALLBACK:
  7.25: Emit domain event (Socket.IO broadcast)
  7.5:  Redis inbox cache prepend (browser)
  8:    PER-ACTION CHANNEL DELIVERY
        For each action (sorted by step):
          _send_via_channel(channel, recipients)
          → success: mark_delivery_ids_sent(delivery_ids)
          → fail:    mark_delivery_ids_failed(delivery_ids)
          → not impl: mark_delivery_ids_skipped(delivery_ids)
        await db.commit()  ← delivery status updates
```

---

## Preexisting Test Infra Issues

### 1. Deadlock during TRUNCATE

- Location: `tests/conftest.py:462`
- Cause: TRUNCATE ALL CASCADE + app engine connections holding locks
- Fix applied: NullPool engine for truncate + pg_terminate_backend before DROP SCHEMA
- Status: Significantly reduced but not 100% eliminated

### 2. `discount_type_enum already exists`

- Location: `tests/conftest.py:385` + `app/models/tuition_discount_policy.py:66`
- Cause: asyncpg prepared statement cache + SQLAlchemy create_all re-creating enum
- Fix applied: `create_type=False` on model + manual CREATE TYPE in conftest before create_all
- Status: Fixed

### 3. FK violation in suspicious_login dispatch

- Location: `app/routers/auth.py:172`
- Cause: Login dispatch reused login session; FK error corrupted session state; PendingRollbackError cascaded
- Fix applied: Dispatch uses dedicated AsyncSessionLocal() session; user data snapshot before callbacks; removed db.rollback() from callback error handler
- Status: Fixed

### 4. MissingGreenlet errors

- Location: `tests/conftest.py:538`
- Cause: Casbin async adapter greenlet context loss in nested lifespan
- Fix applied: NullPool for DDL engines reduces frequency
- Status: Intermittent (preexisting)

### 5. Login fixture returning 401

- Location: `tests/conftest.py:674`
- Cause: Fixture ordering race + connection pool snapshot timing
- Fix applied: Fixtures depend on admin_token_headers (guarantees user committed); nullable FKs in seed fixtures
- Status: Improved

### 6. seeded_dependencies FK violation

- Location: `tests/services/conftest.py:153`
- Cause: Fixture ordering (OrganizationUnit not committed before User with unit_id)
- Status: Preexisting, not addressed in Phase B/C0

### Test Results Summary

- Phase B unit tests: 14/14 pass (stable)
- Phase B API tests: 16/16 pass (solo), flaky multi-file
- Phase B integration: 8/8 pass (stable)
- Full suite improvement: +168 pass, -25 fail, -143 errors vs baseline

---

## Architecture Decisions

### Actions as runtime truth (C0)

- `NotificationRule.actions → ActionConfig[]` is runtime truth
- `NotificationRule.channels` is derived from actions (backward compat)
- If rule has no actions, `synthesize_actions_from_channels()` creates synthetic ones
- CRUD derives channels from actions on create/update
- Update excludes `channels` from update_data (prevent drift)

### RequireAdmin for Phase B routes

- delivery-ops and consent routes use `RequireAdmin` (not `CasbinAuth`)
- Direct `user.role == "admin"` check, no Casbin enforcer dependency
- Reason: CasbinAuth state can be corrupted by session errors in test env

### Session isolation for suspicious_login

- `auth.py` login callback creates fresh `AsyncSessionLocal()` for dispatch
- User data snapshot to plain dict before callbacks
- No db.rollback() in callback error handler (callbacks use own sessions)

### NullPool for test engines

- `_init_schema_once()` and `_truncate_all_tables()` use NullPool engines
- Eliminates connection pool contention and asyncpg cache pollution
- `pg_terminate_backend()` before DROP SCHEMA to prevent deadlocks

### Delivery status scoping

- Status updates use `bulk_update_status(delivery_ids, status)` — single UPDATE WHERE id IN (...)
- Not re-queried by event+channel (prevents cross-batch contamination)
- Dispatcher builds channel_delivery_ids mapping in step 6.5

---

## Commit History

```
feature/zalo-zns-phase1 branch:

Phase A (prior):
  1b35aeb4 fix: Phase A final — block org event rules at API boundary
  88ecbc59 test: A3 test now calls create_rule() and asserts BadRequest

Phase B:
  1caf8b4a feat: Phase B1+B2 — NotificationDelivery + NotificationConsent models
  8bbd54e7 feat: Phase B3+B4+B5 — repositories, delivery service, dispatcher integration
  2444e115 fix: add missing notification_id index on notification_delivery
  2eb84715 feat: Phase B6-B12 — consent API, delivery ops, external recipients, admin UI
  f952cdf1 chore: remove unused get_current_active_user import
  95b62c96 fix: switch delivery/consent routes from CasbinAuth to RequireAdmin
  244e4919 fix: test harness stabilization (session isolation, NullPool, enum fix)
  ce0cb2c3 feat: B9 freeze live scope — mark zalo/sms as planned

Phase C0:
  d5c95a6e feat: Phase C0 — promote NotificationAction as runtime truth
  a78629ea fix: C0 fixes — migration SQL, template_code scope, channels drift
```

---

## Key File Map

### Backend — Core

| File | Purpose |
|------|---------|
| `app/services/notification_dispatcher.py` | Main dispatch orchestrator (resolve → filter → create → deliver) |
| `app/services/notification_rule_loader.py` | Load rules from DB/cache, ActionConfig, DatabaseRuleConfig |
| `app/services/notification_delivery_service.py` | Delivery lifecycle (create, mark sent/failed/skipped) |
| `app/services/notification_rule_crud_service.py` | Rule CRUD with C0 validation |
| `app/services/notification_recipients.py` | ResolvedRecipient + external contact resolvers |
| `app/services/notification_resolvers.py` | BaseResolver + all resolver implementations |
| `app/services/notification_registry.py` | Hardcoded fallback rule registry |

### Backend — Models

| File | Purpose |
|------|---------|
| `app/models/notification.py` | Notification, NotificationRule, NotificationAction, NotificationTemplate |
| `app/models/notification_delivery.py` | NotificationDelivery (per-channel tracking) |
| `app/models/notification_consent.py` | NotificationConsent (latest-state) |
| `app/models/notification_preference.py` | NotificationPreference (per-user channel prefs) |

### Backend — API

| File | Purpose |
|------|---------|
| `app/routers/notification_delivery_ops.py` | GET /api/notification-deliveries (admin read-only) |
| `app/routers/notification_consents.py` | Consent CRUD + CSV bulk import |
| `app/routers/notification_rules.py` | Rule CRUD + metadata API |
| `app/routers/notification_templates.py` | Template CRUD |
| `app/routers/notifications.py` | User inbox API |

### Backend — Channels

| File | Purpose |
|------|---------|
| `app/services/notification_channels/socket_channel.py` | Browser/Socket.IO delivery |
| `app/services/notification_channels/email_channel.py` | Email delivery (SMTP) |

### Frontend

| File | Purpose |
|------|---------|
| `src/components/admin/notifications/DeliveryOpsTable.tsx` | Delivery tracking table |
| `src/components/admin/notifications/ConsentImportDialog.tsx` | Consent management + CSV import |
| `src/components/admin/notifications/NotificationRuleWizard.tsx` | Rule creation wizard |
| `src/components/admin/notifications/MultiStepActionEditor.tsx` | Action step editor |
| `src/components/admin/notifications/NotificationRuleForm.tsx` | Legacy rule form (stale) |
| `src/hooks/useNotificationDeliveries.ts` | Delivery query hooks |
| `src/hooks/useNotificationConsents.ts` | Consent query + mutation hooks |
| `src/types/api.types.ts` | All notification types + ChannelInfo |
| `src/lib/api/endpoints.ts` | API endpoint constants |
| `src/lib/config/navigation.ts` | Admin nav items |

### Tests

| File | Purpose |
|------|---------|
| `tests/unit/test_notification_delivery_service.py` | Delivery service unit tests (14) |
| `tests/api/test_notification_deliveries.py` | Delivery ops API tests (7) |
| `tests/api/test_notification_consents.py` | Consent API tests (9) |
| `tests/integration/test_notification_delivery_persistence.py` | Delivery + consent persistence (8) |
| `tests/unit/test_notification_parity.py` | Event parity checks |
| `tests/services/test_notification_dispatcher.py` | Dispatcher integration tests |

### Config / Migration

| File | Purpose |
|------|---------|
| `alembic/versions/zw2c3d4e5f6g7_add_delivery_and_consent.py` | Phase B tables |
| `alembic/versions/zx3d4e5f6g7h8_add_delivery_notification_id_index.py` | notification_id index |
| `alembic/versions/zy4e5f6g7h8i9_phase_c0_promote_actions_runtime_truth.py` | C0 columns + backfill |
| `auth_model.conf` | Casbin model (keyMatch4 matcher) |
| `app/casbin_config/policy_templates.py` | Role policy templates |

---

## Phase C1 Execution Checklist

### C1-1: Email separation

| ID | File | Action | Acceptance |
|---|---|---|---|
| C1-1a | `app/services/notification_channels/email_channel.py` | Đổi email adapter đọc từ `NotificationDelivery.payload_snapshot` thay vì query `Notification` row theo user_id | Email gửi đúng content từ payload_snapshot |
| C1-1b | `app/services/notification_channels/email_channel.py` | External recipients: dùng `NotificationDelivery.destination` trực tiếp | Email gửi được cho recipient không có user_id |
| C1-1c | `app/services/notification_dispatcher.py` | Email channel không còn phụ thuộc `Notification` row tồn tại | Dispatch email-only (không có browser) vẫn gửi được |
| C1-1d | Tests | Email sends from payload_snapshot, not Notification row | Unit + integration test pass |

### C1-2: Worker delayed execution

| ID | File | Action | Acceptance |
|---|---|---|---|
| C1-2a | `app/models/notification_delivery.py` | Thêm `scheduled_for` (DateTime nullable), `attempt_count` (Integer default 0), `last_attempt_at` (DateTime nullable) | Migration chạy, model có fields |
| C1-2b | `alembic/versions/` | Migration add columns | Upgrade/downgrade clean |
| C1-2c | `app/tasks/notification_tasks.py` (new) | Celery task `execute_notification_delivery(delivery_id)`: load delivery → check scheduled_for ≤ now → re-check preference/consent → call channel adapter → update status sent/failed | Worker executes delivery correctly |
| C1-2d | `app/services/notification_dispatcher.py` | Actions với `delay_minutes > 0`: set `scheduled_for = now + delay`, enqueue Celery task thay vì execute inline | Delayed actions enqueued, không execute inline |
| C1-2e | `app/services/notification_rule_crud_service.py` | Mở validation: cho phép `delay_minutes > 0` | Create/update rule với delay pass |
| C1-2f | `app/services/notification_delivery_service.py` | Thêm `prepare_delayed_deliveries()` hoặc update existing function | Delivery rows có scheduled_for cho delayed actions |
| C1-2g | Tests | Worker picks up delayed delivery, consent revoked → skipped, retry on transient failure | Unit + integration pass |

### C1-3: Zalo adapter + webhook

| ID | File | Action | Acceptance |
|---|---|---|---|
| C1-3a | `app/services/notification_channels/zalo_channel.py` (new) | Channel adapter: OAuth v4 token, ZNS Template Message API, send by phone number | Zalo message sent via API |
| C1-3b | `app/core/config.py` | Zalo OA credentials settings: `ZALO_OA_ID`, `ZALO_OA_SECRET`, `ZALO_APP_ID` | Config loads from env |
| C1-3c | `app/services/notification_dispatcher.py` | Register zalo channel trong `_send_via_channel()` | Dispatcher routes to zalo adapter |
| C1-3d | `app/routers/webhooks.py` (new or extend) | Webhook endpoint nhận delivery status từ Zalo → update `NotificationDelivery.status` + `provider_message_id` | Webhook updates delivery row |
| C1-3e | `app/repositories/notification_consent_repository.py` | Consent check trước gửi: `is_consent_granted(channel="zalo", source_type, source_id)` | No consent = no send |
| C1-3f | `app/services/notification_recipients.py` | External recipient resolution: lead_contact → normalized_phone | Phone resolved from lead/admission/collaborator |
| C1-3g | Tests | Zalo send success/fail, webhook update, consent blocked, external recipient resolution | Integration pass |

### C1-4: Deprecate channels

| ID | File | Action | Acceptance |
|---|---|---|---|
| C1-4a | `app/services/notification_rule_loader.py` | Loader chỉ dùng `config.actions`, không đọc `rule.channels` | channels field ignored in runtime |
| C1-4b | `app/schemas/notification.py` | Bỏ `channels` khỏi `NotificationRuleCreate`/`NotificationRuleUpdate` hoặc mark ignored | API không nhận channels mới |
| C1-4c | `app/schemas/notification.py` | Giữ `channels` read-only trên `NotificationRule` response | Backward compat cho existing clients |
| C1-4d | `app/models/notification.py` | Comment `channels` column deprecated (chưa drop) | Doc rõ |
| C1-4e | Tests | Rule CRUD without channels field still works | API test pass |

### C1 Definition of Done

- Email gửi được từ payload_snapshot, không cần Notification row
- Worker Celery executes delayed deliveries
- Zalo ZNS message gửi được qua API, webhook cập nhật status
- Consent gate enforced cho external channels
- `channels` không còn trong runtime path
- Toàn bộ suite C1 pass

### C1 Test Checklist

| Suite | Cases |
|---|---|
| Unit: email adapter | Email sends from payload_snapshot; external destination works |
| Unit: worker task | Load delivery → execute → update status; consent revoked → skipped |
| Unit: zalo adapter | Mock ZNS API call, verify payload format |
| Integration: delayed delivery | dispatch with delay → worker executes after scheduled_for |
| Integration: zalo e2e | consent granted → zalo sent → webhook → status=sent |
| Integration: consent gate | no consent → delivery skipped; revoked between dispatch and send → skipped |
| API: webhook | POST /api/webhooks/zalo → delivery status updated |
| API: rule CRUD | Create rule with delay > 0 → accepted (C1 unlocks delay) |

---

## Phase D: Operational Backlog

Hạng mục sau C1, theo thứ tự ưu tiên. Nguồn: `NOTIFICATION_SCORECARD.md`.

### D1: Retry + dead-letter pipeline

| Item | Detail |
|---|---|
| Scope | Celery retry policy per channel (exponential backoff), dead-letter queue for permanently failed deliveries |
| Files | `app/tasks/notification_tasks.py`, `app/models/notification_delivery.py` (thêm `next_retry_at`, `max_retries`) |
| Effort | ~4d |
| Depends | C1-2 (worker) |

### D2: Rate limit + cooldown

| Item | Detail |
|---|---|
| Scope | Per-user rate limit (max N notifications/hour), per-event-type cooldown (min interval between same event for same user) |
| Files | `app/services/notification_dispatcher.py`, Redis counters |
| Effort | ~2d |
| Depends | None (can start after C0) |

### D3: Notification audit log + delivery dashboard API

| Item | Detail |
|---|---|
| Scope | Full audit trail (who dispatched, when, to whom, via which channel, result), dashboard API for aggregate stats (sent/failed/skipped counts by channel/event/time) |
| Files | `app/routers/notification_delivery_ops.py` (extend), new dashboard schemas |
| Effort | ~3d |
| Depends | C1-1 (email separation — for accurate channel-level stats) |

### D4: Admin monitoring dashboard UI

| Item | Detail |
|---|---|
| Scope | Frontend dashboard: delivery volume charts, failure rate, channel breakdown, recent errors, real-time status |
| Files | New page `admin/notification-dashboard/`, new components |
| Effort | ~3d |
| Depends | D3 (dashboard API) |

### D5: Quota/budget + circuit breaker + alerting

| Item | Detail |
|---|---|
| Scope | Per-channel send quota (monthly SMS/Zalo budget), circuit breaker (auto-disable channel on sustained failures), alerting to admin on threshold breach |
| Files | Config models, `app/services/notification_channels/`, monitoring |
| Effort | ~3d |
| Depends | C1-3 (Zalo live — to have a real external channel to budget) |

### D6: Resource-level permission cho delivery ops

| Item | Detail |
|---|---|
| Scope | Manager can view deliveries for own unit only (IDOR-style scoping), not all deliveries |
| Files | `app/routers/notification_delivery_ops.py`, `app/core/deps.py` |
| Effort | ~2d |
| Depends | None |

### D7: Consent history table

| Item | Detail |
|---|---|
| Scope | Full consent change history (not just latest-state), audit trail for compliance |
| Files | New model `NotificationConsentHistory`, migration, repo |
| Effort | ~2d |
| Depends | C1-3 (consent actively used for Zalo) |

### D8: Template per action (C0 deferred)

| Item | Detail |
|---|---|
| Scope | Per-action `template_code` render — each action step can use a different template |
| Files | `app/services/notification_dispatcher.py` (step 5 render per action), `app/services/notification_rule_crud_service.py` (remove template_code rejection) |
| Effort | ~2d |
| Depends | C1-1 (email uses payload_snapshot — template rendered per action) |

---

## Test Infra Remaining Actions

### Fixed (no further action)

| Issue | Fix | Status |
|---|---|---|
| `discount_type_enum already exists` | `create_type=False` + manual CREATE TYPE in conftest | Done |
| FK violation suspicious_login | Separate AsyncSessionLocal in auth.py callback | Done |
| Callback session corruption | Rollback in dispatcher error handlers | Done |

### Improved but not fully resolved

| Issue | Current state | Remaining action |
|---|---|---|
| Deadlock during TRUNCATE | NullPool engines + pg_terminate_backend | Monitor — if still occurs, consider per-worker test DBs |
| MissingGreenlet | NullPool reduces frequency | Root cause is Casbin adapter greenlet context; consider pinning casbin-async-sqlalchemy-adapter version or patching |
| Login fixture 401 | Fixture ordering improved (admin_token_headers dependency) | If still flaky, consider mocking login instead of real HTTP login in non-auth tests |
| seeded_dependencies FK | Not addressed | Fix fixture ordering in `tests/services/conftest.py` — ensure OrganizationUnit committed before User with unit_id |

### Not started

| Issue | Action | Priority |
|---|---|---|
| Test parallelism (pytest-xdist) | Per-worker test DB (`qlts_test_gw0`, `qlts_test_gw1`) + advisory locks | Low — only needed if CI time becomes bottleneck |
| Cleanup stale test files | Remove legacy test files that duplicate coverage | Low |
