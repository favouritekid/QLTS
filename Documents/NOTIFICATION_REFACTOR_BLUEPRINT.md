# Notification Module Refactor Blueprint

> **Status:** Draft v3 — rollout safety + preview API fixed
> **Last updated:** 2026-04-03

## Mục tiêu

Loại bỏ "dual source of truth" giữa registry code và DB rules. Thiết lập kiến trúc rõ ràng:

- **Code sở hữu** event semantics (existence, resolver options, dedup, priority, link strategy)
- **DB sở hữu** admin-configurable behavior (enabled, title/message, channels, recipient groups)
- **Dispatcher chỉ có 1 đường runtime** — không còn hidden fallback

## Bối cảnh vấn đề

### Hiện trạng (trước refactor)

3 nguồn cùng quyết định behavior:

| Nguồn | File | Vai trò | Số events |
|-------|------|---------|-----------|
| SystemEvents enum | `app/core/events.py` | Event existence + payload docs | 51+ |
| Event metadata | `app/core/event_metadata.py` | Display name, variables, conditions (cho frontend) | 43+ |
| Notification registry | `app/services/notification_registry.py` | Resolver, dedup, priority, link, template (runtime fallback) | 42 |
| DB rules (seeded) | `notification_rule` table | Admin-configurable: enabled, title/message, channels | 26 |
| Frontend constants | `wizard-constants.ts` | Hardcoded event list (fallback) | 25 |

### Dispatcher decision flow (3 đường — vấn đề)

```
1. DB rule exists + enabled    → dùng DB rule
2. DB rule exists + disabled   → SUPPRESS tất cả (im lặng, không fallback)
3. Không có DB rule            → fallback registry (English content, khác behavior)
```

### Vấn đề cụ thể

**Content lẫn lộn EN/VI:**
- `LEAD_ASSIGNED` qua DB: "Lead được phân công: $lead_name" (VI)
- `LEAD_REASSIGNED` qua registry fallback: "Lead Reassigned" (EN)
- Cùng 1 user, 2 notification liên tiếp, 2 ngôn ngữ khác nhau

**Disable = biến mất, không phải tắt:**
- Admin disable rule → `has_rule_override_for_event()` return True → registry suppress → event im lặng 100%
- Admin delete rule → registry sống lại → notification bật lại bằng tiếng Anh
- Behavior không predictable

**Metadata drift:**
- Registry có `dedup_key_template`, `priority` (1-150). DB rules không sync
- 24 events chạy registry fallback với content cũ, 23 events chạy DB rules

**"Max one browser" constraint:**
- `notification_rule_crud_service.py:97-101` chặn >1 browser action per rule
- Nhưng seed script tạo multi-group rules với nhiều browser actions (bypass validation)
- Flow wizard yêu cầu multi-group browser → bị API chặn

---

## Thiết kế đích

### Event classification

Không phải mọi `SystemEvents` đều là notification events. Phân loại:

| Classification | Events | Có DB rule? |
|----------------|--------|-------------|
| **User-notification events** | lead_assigned, payment_received, suspicious_login, ... (~42) | Bắt buộc |
| **Broadcast-only events** | unit_created, program_updated, offering_deleted, ... (9) | Cấm tạo rule |
| **Internal/future events** | Chưa có notification logic | Không bắt buộc |

`BROADCAST_ONLY_EVENTS` đã tồn tại trong `notification_rule_crud_service.py:197-201`. Catalog sẽ tôn trọng classification này.

### Phân quyền dữ liệu

```
Code owns (event_catalog.py):          DB owns (notification_rule + actions):
├── event existence                    ├── enabled (on/off)
├── event classification               ├── title_template (localized)
├── payload contract (variables)       ├── message_template (localized)
├── resolver OPTIONS (allowed list)    ├── selected channels per group
├── dedup key strategy                 ├── selected resolver per group
├── priority                           ├── content overrides per channel
├── link strategy (code-owned)         ├── conditions
├── category                           └── action workflow (steps, delays)
├── retired flag
└── condition field definitions
```

### Link ownership — chốt dứt điểm

**Link là code-owned.** Lý do:
- Link là contract với frontend route. Nếu route đổi, chỉ sửa 1 chỗ trong catalog.
- Bài học từ `/applications/{id}` — DB chứa link template, route bị xóa, phải quét data.

**Số phận `link_template` DB column:**
- **Giữ column** trong model (không drop) — tránh migration rủi ro
- **Dispatcher ignore** column này — luôn dùng `event_catalog.render_link()`
- **CRUD ignore** trên write — không lưu giá trị mới vào column
- **Legacy rows** giữ nguyên data cũ — chỉ là dead data, không ảnh hưởng runtime
- **Frontend** không hiển thị/edit `link_template` — hiển thị `link_strategy` từ metadata API (read-only)

### Delete rule semantics — chốt

**Hiện tại:** `delete_rule()` hard delete → active event mất notification hoàn toàn.

**Sau refactor:** Chặn hard delete cho active catalog events.

```python
async def delete_rule(db, rule):
    from app.core.event_catalog import get_event_by_key
    defn = get_event_by_key(rule.event)

    if defn and not defn.retired:
        raise BadRequest(
            f"Cannot delete rule for active event '{rule.event}'. "
            f"Use disable (toggle) instead. Delete is only allowed for retired/orphan events."
        )

    # Orphan hoặc retired event → cho phép delete
    await repo.delete_rule(rule)
```

Admin muốn tắt → toggle disable. Admin muốn xóa → chỉ được nếu event đã retired hoặc là orphan rule.

### Dispatcher single path

```
1. Event phải tồn tại trong catalog     → nếu không: log warning, skip
2. Event không retired                   → nếu retired: skip
3. DB rule phải tồn tại + enabled        → nếu không: log error, domain event only
4. Merge: technical từ catalog + content từ DB rule
5. Per-action resolution, cross-action dedup, delivery
```

Không còn fallback registry. `enabled=false` = tắt thật. Delete rule bị chặn cho active events.

### Multi-group browser — precedence rule

- Bỏ "max one browser" constraint trong CRUD validation
- Thêm cross-action user dedup trong dispatcher
- **Precedence: step order thấp thắng.** Nếu user xuất hiện ở Group 1 (step 1, browser) và Group 2 (step 3, browser), Group 1 thắng vì step thấp hơn. Content + branch_key của step 1 được dùng.
- **Frontend preview phải hiển thị:** "User thuộc nhiều nhóm sẽ nhận notification từ nhóm có step thấp nhất cho mỗi kênh."

```python
# Dispatcher: cross-action dedup
seen_by_channel: Dict[str, Set[int]] = defaultdict(set)
for action in sorted(action_configs, key=lambda a: a.step):  # step order
    users = action_filtered_map.get(action.step, [])
    deduped = [uid for uid in users if uid not in seen_by_channel[action.channel]]
    seen_by_channel[action.channel].update(deduped)
    action_filtered_map[action.step] = deduped
```

---

## Implementation — 3 PRs

### PR1: Backend — Event Catalog + Dispatcher

**Branch:** `refactor/notification-catalog-pr1`

#### 1.1 Tạo `app/core/event_catalog.py`

Merge data từ `event_metadata.py` (display/variables) + `notification_registry.py` (resolver/dedup/priority/link):

```python
@dataclass(frozen=True)
class EventDefinition:
    # Identity
    event: SystemEvents
    category: str                          # "lead", "consultation"...

    # Display (cho frontend metadata API)
    display_name: str                      # "Lead được phân công"
    description: str
    variables: List[EventVariable]
    condition_fields: List[ConditionField]

    # Technical (code-owned, admin không sửa)
    default_resolver: str                  # "lead_owner"
    allowed_resolvers: List[str]           # ["lead_owner", "unit_managers", "all_admins"]
    default_channels: List[str]            # ["browser", "email"]
    priority: int = 100
    dedup_key_template: Optional[str] = None
    link_strategy: Optional[str] = None    # "/leads/${lead_id}"

    # Classification
    notification_class: str = "user"       # "user" | "broadcast_only" | "internal"
    retired: bool = False
```

Public API:
- `get_event(event) -> Optional[EventDefinition]`
- `get_notifiable_events() -> List[EventDefinition]` — only `notification_class="user"` + not retired
- `get_active_events() -> List[EventDefinition]` — all non-retired (including broadcast)
- `render_dedup_key(event, payload) -> Optional[str]`
- `render_link(event, payload) -> Optional[str]`

#### 1.2 Sync chạy trong entrypoint, trước server start

**Rollout safety:** Giữa "deploy new dispatcher (no fallback)" và "sync tạo missing rules" có khoảng trống nguy hiểm. Sync phải chạy TRƯỚC khi gunicorn workers nhận traffic.

**Tại sao không dùng `lifespan` hay `on_event("startup")`:**
- App dùng `lifespan=lifespan` context manager → `on_event("startup")` bị ignore (FastAPI docs)
- Gunicorn chạy `workers=2` với `preload_app=False` → lifespan chạy 2 lần song song, race condition
- Cần hook single-process chạy đúng 1 lần

**Giải pháp: `docker-entrypoint.sh`** — đã chạy `alembic upgrade head` trước exec, thêm sync vào cùng chỗ:

```bash
#!/bin/bash
set -e

echo "=== Running Alembic migrations ==="
alembic upgrade head

echo "=== Syncing notification rules ==="
python -m app.scripts.sync_notification_rules

echo "=== Migrations complete. Starting application ==="
exec "$@"
```

Lý do chọn entrypoint thay vì alembic data migration:
- Sync là idempotent operation, chạy mỗi deploy — phù hợp với entrypoint
- Alembic data migration chỉ chạy 1 lần rồi đánh dấu applied — không tự heal nếu ai đó delete rule
- Entrypoint chạy trước exec (single process) → không race condition giữa workers
- Sync script dùng async DB, cần `asyncio.run()` wrapper — dễ implement hơn inline alembic

**`sync_notification_rules` CLI wrapper:**

```python
# app/scripts/sync_notification_rules.py
# Cuối file — CLI entrypoint:

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

async def main():
    from app.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as db:
        result = await sync_notification_rules(db)
        print(f"Sync result: {result}")
    await engine.dispose()
```

#### 1.3 Dispatcher single path

File: `app/services/notification_dispatcher.py`

Thay thế lines 493-542 (3-way decision):

```python
from app.core.event_catalog import get_event, render_dedup_key, render_link

definition = get_event(event)
if not definition or definition.retired:
    log.warning("Unknown or retired event", event_type=event.value)
    return [], None

if definition.notification_class != "user":
    # broadcast-only or internal — emit domain event only
    async def _domain_only():
        await _emit_domain_event(event, payload)
    return [], _domain_only

db_rule = await get_rule_for_event(db, event)
if not db_rule:
    log.error("No enabled DB rule for active event", event_type=event.value)
    async def _domain_only():
        await _emit_domain_event(event, payload)
    return [], _domain_only

# Merge: technical từ catalog, content từ DB
dedupe_key = dedupe_key or render_dedup_key(event, payload)
link = render_link(event, payload)       # code-owned
title = db_rule.render_title(payload)    # DB-owned
message = db_rule.render_message(payload) # DB-owned
```

Xóa:
- Import `get_event_config` từ `notification_registry`
- Import/call `has_rule_override_for_event` từ `rule_loader`

#### 1.4 Bỏ max-one-browser + thêm cross-action dedup

File: `notification_rule_crud_service.py` — xóa lines 97-101

File: `notification_dispatcher.py` — thêm sau preference filtering, trước cooldown:

```python
# Cross-action user dedup — step order determines precedence
seen_by_channel: Dict[str, Set[int]] = defaultdict(set)
for action in sorted(action_configs, key=lambda a: a.step):
    users = action_filtered_map.get(action.step, [])
    deduped = [uid for uid in users if uid not in seen_by_channel[action.channel]]
    if len(users) != len(deduped):
        log.info("Cross-action dedup", step=action.step, channel=action.channel,
                 original=len(users), after=len(deduped))
    seen_by_channel[action.channel].update(deduped)
    action_filtered_map[action.step] = deduped
```

#### 1.5 Delete rule guard

File: `notification_rule_crud_service.py` — `delete_rule()`:

```python
async def delete_rule(db, rule):
    from app.core.event_catalog import get_event_by_key
    defn = get_event_by_key(rule.event)

    if defn and not defn.retired:
        raise BadRequest(
            f"Cannot delete rule for active event '{rule.event}'. "
            f"Use disable (toggle) instead."
        )

    repo = NotificationRuleRepository(db)
    await repo.delete_rule(rule)
    # ... post_commit callback unchanged
```

#### 1.6 Metadata endpoint serve từ catalog

File: `app/routers/notification_rules.py`

```python
from app.core.event_catalog import get_notifiable_events

# Response thêm: allowed_resolvers, link_strategy per event
# Chỉ serve "user" notification events, không broadcast
```

#### 1.7 Deprecate files cũ

| File | Action |
|------|--------|
| `notification_registry.py` | Deprecation header, xóa runtime imports |
| `event_metadata.py` | Deprecation header, redirect sang catalog |
| `notification_rule_loader.py` | Xóa `has_rule_override_for_event()` |

#### PR1 files

| File | Action |
|------|--------|
| `app/core/event_catalog.py` | New (~500 lines) |
| `docker-entrypoint.sh` | Add sync command before exec (~2 lines) |
| `app/services/notification_dispatcher.py` | Modify (~50 lines) |
| `app/services/notification_rule_crud_service.py` | Remove browser constraint + add delete guard (~15 lines) |
| `app/services/notification_rule_loader.py` | Remove `has_rule_override_for_event` (-17 lines) |
| `app/scripts/sync_notification_rules.py` | New (~120 lines) |
| `app/services/notification_registry.py` | Deprecate header |
| `app/core/event_metadata.py` | Deprecate redirect |
| `app/routers/notification_rules.py` | Modify metadata endpoint |

---

### PR2: Frontend Editor + Preview API

**Branch:** `refactor/notification-catalog-pr2`
**Depends on:** PR1 merged

#### 2.1 Preview API endpoint (new)

File: `app/routers/notification_rules.py`

**Sample payload source:** Frontend gửi lên, không phải backend tự generate.

Lý do: `EventDefinition` chỉ có `variables` (tên + type), không có sample values.
Sample values phụ thuộc context mà chỉ admin biết (ví dụ lead_name="Nguyễn Văn A").
Frontend đã có variables metadata từ `/metadata` API — dùng để sinh sample payload
với placeholder values (`$lead_name`, `$actor_name`...) hoặc cho admin nhập.

Schema:

```python
class NotificationRulePreview(BaseModel):
    event: str
    title_template: str
    message_template: str
    sample_payload: Dict[str, str] = {}  # {"lead_name": "Nguyễn Văn A", "lead_id": "123"}
    actions: Optional[List[NotificationActionCreate]] = []
```

Endpoint:

```python
@router.post("/preview")
async def preview_notification_rule(
    rule_data: schemas.NotificationRulePreview,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    Render preview of notification content for each action/branch.

    Frontend sends sample_payload with concrete values for template variables.
    Backend renders templates and returns per-action previews.
    """
    from app.core.event_catalog import get_event_by_key, render_link

    definition = get_event_by_key(rule_data.event)
    if not definition:
        raise HTTPException(404, f"Unknown event: {rule_data.event}")

    payload = rule_data.sample_payload
    link = render_link(definition.event, payload)

    previews = []
    for action in rule_data.actions or []:
        if action.content_mode == "inline_override" and action.content_override:
            title = Template(action.content_override.get("title_template", "")).safe_substitute(payload)
            message = Template(action.content_override.get("message_template", "")).safe_substitute(payload)
        else:
            title = Template(rule_data.title_template).safe_substitute(payload)
            message = Template(rule_data.message_template).safe_substitute(payload)

        previews.append({
            "step": action.step,
            "channel": action.channel,
            "branch_key": action.branch_key,
            "rendered_title": title,
            "rendered_message": message,
            "rendered_link": link,
            "content_mode": action.content_mode,
            "delay_minutes": action.delay_minutes,
        })

    return {
        "event": rule_data.event,
        "link_strategy": definition.link_strategy,
        "rendered_link": link,
        "actions": previews,
    }
```

Frontend Step 4 (FinalPreviewSection):
- Khi user vào Step 4, frontend builds `sample_payload` từ event variables metadata
- Default: dùng variable name làm placeholder value (e.g. `{"lead_name": "lead_name"}`)
- Optional: cho admin nhập sample values để preview realistic hơn
- Gọi `POST /notification-rules/preview` với payload → hiển thị rendered content per action

#### 2.2 Bỏ SYSTEM_EVENTS fallback

File: `wizard-constants.ts` — xóa SYSTEM_EVENTS array, giữ category/resolver/channel display metadata

File: `NotificationRuleEditor.tsx`:
```typescript
// Trước: if (!metadata?.events) return SYSTEM_EVENTS;
// Sau:   if (!metadata?.events) return [];  // loading state
```

#### 2.3 Bỏ "only 1 browser" validation

File: `wizard-utils.ts` — xóa browser count check trong `validateGroups()`

File: `WizardStepRecipientGroups.tsx` — cho phép multi-group browser, hiển thị info text:
"User thuộc nhiều nhóm sẽ nhận notification từ nhóm đầu tiên cho mỗi kênh."

#### 2.4 Resolver picker filter

File: `ResolverPicker.tsx` — filter options theo `selectedEvent.allowed_resolvers`

#### 2.5 Link field → read-only + preview

File: `DefaultContentSection.tsx`:
- Xóa `link_template` text input
- Hiển thị `link_strategy` từ metadata (read-only badge)

File: `FinalPreviewSection.tsx`:
- Gọi `POST /notification-rules/preview` khi user vào Step 4
- Hiển thị rendered title/message/link per action step
- Hiển thị "cross-group dedup" info nếu >1 group dùng cùng channel

#### PR2 files

| File | Action |
|------|--------|
| `app/routers/notification_rules.py` | Add preview endpoint (~50 lines) |
| `app/schemas/notification.py` | Add NotificationRulePreview schema (~10 lines) |
| `wizard-constants.ts` | Remove SYSTEM_EVENTS (-80 lines) |
| `NotificationRuleEditor.tsx` | Remove fallback (~5 lines) |
| `wizard-utils.ts` | Remove browser validation (~5 lines) |
| `WizardStepRecipientGroups.tsx` | Allow multi-browser, info text (~15 lines) |
| `ResolverPicker.tsx` | Filter by allowed_resolvers (~10 lines) |
| `DefaultContentSection.tsx` | Link read-only (~15 lines) |
| `FinalPreviewSection.tsx` | Preview API integration (~40 lines) |
| `useNotificationRules.ts` | Add usePreviewMutation hook (~10 lines) |

---

### PR3: Data Migration + Test/CI Invariants

**Branch:** `refactor/notification-catalog-pr3`
**Depends on:** PR1 merged, PR2 can be parallel for backend tests

#### 3.1 Production data sync

Sync tự chạy trong `docker-entrypoint.sh` trước gunicorn start (từ PR1). Verify:

```bash
docker compose logs backend --tail=20 | grep "Notification rules synced"
# Expected: created=~16, skipped=~26, archived=0
```

Nếu cần chạy lại thủ công:
```bash
docker compose exec backend python -m app.scripts.sync_notification_rules
```

#### 3.2 Contract tests

File: `tests/unit/test_notification_contract.py` (new)

```
TestCatalogCompleteness:
    - test_all_notifiable_events_in_catalog
    - test_broadcast_events_excluded_from_notifiable
    - test_no_duplicate_event_keys
    - test_active_events_have_required_fields
    - test_dedup_templates_use_valid_variables

TestCatalogDBParity:
    - test_all_notifiable_events_have_db_rule    # chỉ "user" class, không broadcast
    - test_no_orphan_db_rules
    - test_no_enabled_rules_for_retired_events

TestDispatcherInvariants:
    - test_missing_rule_does_not_fallback
    - test_no_registry_import_in_dispatcher
    - test_retired_event_does_not_dispatch
    - test_broadcast_event_emits_domain_only
    - test_cross_action_user_dedup_step_order_precedence

TestDeleteGuard:
    - test_cannot_delete_active_event_rule
    - test_can_delete_retired_event_rule
    - test_can_delete_orphan_rule
```

Invariant scope: `get_notifiable_events()` (chỉ `notification_class="user"`), không phải mọi `SystemEvents`.

#### 3.3 E2E selector fixes

| Spec | Fix |
|------|-----|
| `notification-dashboard.spec.ts:125` | `locator("h1")` → `getByRole("heading", { level: 1 })` |
| `notification-dashboard.spec.ts:130,152` | `.text-muted-foreground` → `getByTestId("status-*")` |
| `notification-dashboard.spec.ts:131` | `getByText("Active Alerts")` → `getByTestId("alerts-section")` |
| `notification-rule-create.spec.ts:140` | Vietnamese text → `getByTestId("event-required-error")` |
| `notification-rule-create.spec.ts:147` | Vietnamese text → `getByTestId("add-recipient-group")` |

Components cần thêm `data-testid` attributes (~8 files).

#### 3.4 Playwright config

Thêm `notification-dashboard.spec.ts` vào default test match pattern.

#### 3.5 Stale test triage

| Test file | Expected issue | Action |
|-----------|---------------|--------|
| `test_registry_fallback_dispatch.py` | Fallback path xóa | Rewrite → test no-fallback |
| `test_notification_parity.py` | Import registry | Update imports → catalog |
| `test_per_action_dispatch.py` | Có thể OK | Verify |
| `test_notification_c2.py` | Có thể OK | Verify |

#### PR3 files

| File | Action |
|------|--------|
| `tests/unit/test_notification_contract.py` | New (~200 lines) |
| `tests/unit/test_registry_fallback_dispatch.py` | Rewrite (~60 lines) |
| `notification-dashboard.spec.ts` | Fix selectors (~8 lines) |
| `notification-rule-create.spec.ts` | Fix selectors (~4 lines) |
| Frontend components (~4 files) | Add data-testid (~8 attrs) |
| `playwright.config.ts` | Add dashboard spec to match |

---

## PR Dependency + Deploy Sequence

```
PR1 (backend)
  │ merge + deploy backend
  │ sync runs in docker-entrypoint.sh (before gunicorn fork)
  ▼
PR2 (frontend + preview API)    PR3 (tests — backend part can start parallel)
  │ merge                        │ merge
  │ deploy frontend              │ verify CI green
  ▼                              ▼
Production stable with single source of truth
```

**Rollout safety:** PR1 deploy = backend restart = `docker-entrypoint.sh` runs `alembic upgrade head` + `sync_notification_rules` (single process, before gunicorn fork). Sync tạo missing rules TRƯỚC khi workers nhận traffic. Không có khoảng trống, không race condition.

## Verification Checklist

### Sau PR1 deploy:
- [ ] Entrypoint log shows "Syncing notification rules" before "Starting application"
- [ ] Dispatcher không import `notification_registry` runtime
- [ ] `has_rule_override_for_event` không tồn tại
- [ ] Event disabled = không gửi, không fallback
- [ ] Delete active event rule → 400 Bad Request
- [ ] Multi-browser actions pass CRUD validation
- [ ] Cross-action dedup: user ở 2 groups chỉ nhận 1 browser notification (step thấp thắng)

### Sau PR2 deploy:
- [ ] Frontend không dùng SYSTEM_EVENTS fallback
- [ ] EventSelector hiện loading khi metadata chưa load
- [ ] ResolverPicker filter theo allowed_resolvers
- [ ] Link field read-only, render từ catalog
- [ ] Preview API render đúng per-action content
- [ ] Preview hiển thị cross-group dedup info

### Sau PR3:
- [ ] Contract tests pass trong CI
- [ ] Invariant scope = notifiable events, không phải all SystemEvents
- [ ] E2E notification specs pass
- [ ] Không còn stale test fail vì registry imports
- [ ] Playwright config include dashboard spec
- [ ] Delete guard test pass

## Decisions Log

| Decision | Rationale | Date |
|----------|-----------|------|
| Link ownership = code | Route changes không cần DB migration. Bài học từ `/applications/{id}`. | 2026-04-03 |
| `link_template` DB column giữ, ignore runtime | Tránh migration risk. Dead data, không ảnh hưởng runtime. | 2026-04-03 |
| Delete rule = blocked cho active events | Admin có thể vô tình xóa rule, làm event mất notification. Disable thay thế. | 2026-04-03 |
| Multi-browser precedence = step order | Deterministic, admin kiểm soát bằng cách sắp xếp groups. | 2026-04-03 |
| Sync chạy trong docker-entrypoint.sh | `lifespan` + 2 workers = race condition. Entrypoint = single process trước fork. | 2026-04-03 |
| Invariant scope = notifiable events only | Broadcast-only events (9 org events) cấm tạo rule. | 2026-04-03 |
| Preview API trong PR2 | Flow nhiều group/channel cần preview thật, không đủ nếu chỉ UI static. | 2026-04-03 |
| Preview sample_payload = frontend-provided | EventDefinition không có sample values; admin biết context. | 2026-04-03 |

## Residual After Refactor

- `notification_registry.py` — deprecated file, xóa sau khi confirm stable (1-2 sprint)
- `event_metadata.py` — deprecated, redirect imports
- `reset_notification_rules_dev.py` — replace bằng `sync_notification_rules` cho dev seed
- `seed_notification_rules.py` — deprecated, sync command thay thế
- `link_template` DB column — dead data, xóa trong migration riêng khi sẵn sàng
