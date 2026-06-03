# Notification Module Refactor Blueprint

> **Status:** v7 — round 3 review complete, Zalo pre-merge + frontend follow-up tracked
> **Last updated:** 2026-04-03

## Mục tiêu

Loại bỏ "dual source of truth" giữa registry code và DB rules. Thiết lập kiến trúc rõ ràng:

- **Code sở hữu** event semantics (existence, resolver options, dedup, priority, link strategy)
- **DB sở hữu** admin-configurable behavior (enabled, title/message, channels, recipient groups)
- **Dispatcher chỉ có 1 đường runtime** — không còn hidden fallback

## Bối cảnh vấn đề

### Hiện trạng (trước refactor)

3 nguồn cùng quyết định behavior:

| Nguồn | File | Vai trò | Số events (approx.) |
|-------|------|---------|---------------------|
| SystemEvents enum | `app/core/events.py` | Event existence + payload docs | ~50 |
| Event metadata | `app/core/event_metadata.py` | Display name, variables, conditions (cho frontend) | ~27 |
| Notification registry | `app/services/notification_registry.py` | Resolver, dedup, priority, link, template (runtime fallback) | ~42 |
| DB rules (seeded) | `notification_rule` table | Admin-configurable: enabled, title/message, channels | ~26 |
| Frontend constants | `wizard-constants.ts` | Hardcoded event list (fallback) | ~25 |

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

### Event classification (3-tier)

Không phải mọi `SystemEvents` đều là notification events. Catalog phân 3 lớp:

| Classification | Mô tả | DB rule | Metadata API | Admin UI | Invariant test | Ví dụ |
|---|---|---|---|---|---|---|
| **`user`** | Event có dispatch thật + admin cần config notification | Bắt buộc (sync tạo) | Có | Có | `all_notifiable_events_have_db_rule` | `lead_assigned`, `payment_received`, `suspicious_login` |
| **`broadcast_only`** | Socket.IO real-time UI refresh, không phải user notification | Cấm tạo | Không | Không | Excluded | `unit_created`, `lead_updated`, `program_updated` |
| **`internal_future`** | Business intent ghi nhận, chưa có dispatch/module thật | Không sync | Không | Không | Excluded | `dorm_room_assigned`, `ctv_lead_converted`, `fee_fully_paid` (future) |

**Promotion rule:** Event chỉ được promote từ `internal_future` → `user` khi:
- có dispatch implementation thật
- có payload contract rõ
- có resolver semantics rõ
- có lý do nghiệp vụ để admin cấu hình notification

**Existing code reference:** `BROADCAST_ONLY_EVENTS` frozenset đã tồn tại trong `notification_rule_crud_service.py:197-201` (9 org events). Catalog mở rộng thêm `lead_updated` vào broadcast_only (decision D1).

### EVENT_AUDIT_MATRIX classification mapping

Source: `Backend_FastAPI/EVENT_AUDIT_MATRIX.md` (2026-04-03)

**`user` events (~33 events có dispatch thật):**

| Phase | Events | Notes |
|---|---|---|
| Lead | `lead_created`, `lead_assigned`, `lead_assignment_failed`, `lead_reassigned`, `lead_status_changed`, `lead_deleted`, `lead_restored`, `lead_imported`, `officer_availability_changed` | L9 `lead_updated` excluded → broadcast_only |
| Consultation | `consultation_created`, `consultation_updated`, `consultation_deleted`, `consultation_reminder` | |
| Admission | `application_created`, `application_status_changed`, `application_deleted` | A12/E3 dedupe cần chuẩn hóa |
| Finance | `payment_received`, `payment_verified` | Only 2 with real dispatch |
| CTV | `ctv_claim_submitted`, `ctv_claim_approved`, `ctv_claim_rejected`, `ctv_approved`, `ctv_suspended`, `ctv_commission_created`, `ctv_attribution_expiring`, `ctv_attribution_expired`, `ctv_weekly_summary` | CTV10 `ctv_lead_converted` excluded → internal_future |
| System | `system_alert`, `system_announcement`, `user_role_changed`, `user_deactivated`, `pipeline_config_updated`, `holiday_calendar_incomplete` | |
| Security | `suspicious_login` | |

**`broadcast_only` events (10 events):**

| Event | Reason |
|---|---|
| `unit_created`, `unit_updated`, `unit_deleted` | Org broadcast (existing BROADCAST_ONLY_EVENTS) |
| `program_created`, `program_updated`, `program_deleted` | Org broadcast |
| `offering_created`, `offering_updated`, `offering_deleted` | Org broadcast |
| `lead_updated` | D1: UI real-time sync, quá rộng cho notification (L9) |

**`internal_future` events (~8+ events):**

| Event | Reason | Promote khi |
|---|---|---|
| `dorm_room_assigned` | Module chưa build | Dorm module implemented |
| `dorm_maintenance_request` | Module chưa build | Dorm module implemented |
| `asset_maintenance_alert` | Module chưa build | Asset module implemented |
| `asset_checked_out` | Module chưa build | Asset module implemented |
| `dorm_fee_created` | Module chưa build, wrong domain (F4) | Dorm module, fix category |
| `ctv_lead_converted` | Dead config, không ai dispatch (CTV10) | Dispatch implementation |
| `payment_overdue` | Registry-only, không có beat task (F3) | Beat task implemented |
| Future finance events | F5-F10: `fee_calculated`, `invoice_issued`, `payment_rejected`, `fee_fully_paid`, `refund_processed`, `application_fee_paid` | Dispatch implemented per event |

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

Merge data từ `event_metadata.py` (display/variables) + `notification_registry.py` (resolver/dedup/priority/link).

> **BLOCKER — CTV metadata khuyết:** `event_metadata.py` hiện thiếu 10 CTV events (`ctv_claim_submitted` … `ctv_weekly_summary`). Registry có runtime config, nhưng catalog cần display_name, variables, condition_fields cho frontend wizard. **PR1 phải thêm CTV metadata trước khi build catalog entries.** Xem section 1.9.

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

    # Classification (3-tier)
    notification_class: str = "user"       # "user" | "broadcast_only" | "internal_future"
    retired: bool = False                  # True = event permanently decommissioned
```

Public API:
- `get_event(event) -> Optional[EventDefinition]`
- `get_event_by_key(key: str) -> Optional[EventDefinition]`
- `get_notifiable_events() -> List[EventDefinition]` — only `notification_class="user"` + not retired
- `get_active_events() -> List[EventDefinition]` — all non-retired (including broadcast)
- `render_dedup_key(event, payload) -> Optional[str]`
- `render_link(event, payload) -> Optional[str]`

**File structure (~500 lines):**
```
1. Imports + EventDefinition dataclass + helpers (render_link, render_dedup_key)
2. Lead events (~9 entries)
3. Consultation events (~4 entries)
4. Admission events (~3 entries)
5. Finance events — user (~2 entries) + internal_future (~6 entries)
6. CTV events — user (~9 entries) + internal_future (~1 entry)
7. System / Security events (~7 entries)
8. Broadcast-only events (~10 entries)
9. Internal/future events — Dorm, Asset (~4 entries)
10. EVENT_CATALOG dict assembly
11. Public API functions
```

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

**Sync output contract** — script phải log summary sau khi chạy:
```
Sync result: created=3, skipped=30, archived=0, missing_user_rules=0, orphan_rules=0
```
- `missing_user_rules > 0` → log ERROR (sync failed to create a rule cho user event)
- `orphan_rules > 0` → log WARNING (DB has rules for events not in catalog)
- Entrypoint `set -e` sẽ fail container nếu sync script exit non-zero

Lý do chọn entrypoint thay vì alembic data migration:
- Sync là idempotent operation, chạy mỗi deploy — phù hợp với entrypoint
- Alembic data migration chỉ chạy 1 lần rồi đánh dấu applied — không tự heal nếu ai đó delete rule
- Entrypoint chạy trước exec (single process) → không race condition giữa workers
- Sync script dùng async DB, cần `asyncio.run()` wrapper — dễ implement hơn inline alembic

**`sync_notification_rules` CLI wrapper:**

```python
# app/scripts/sync_notification_rules.py — CLI entrypoint (bottom of file):

async def main():
    import sys
    from app.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as db:
        result = await sync_notification_rules(db)
        print(f"Sync result: {result}")
    await engine.dispose()

    if result.get("missing_user_rules", 0) > 0:
        print(f"ERROR: {result['missing_user_rules']} user events still missing rules")
        sys.exit(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
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

> **Note:** `BadRequest` là service-layer domain exception (`app/utils/exceptions.py`), không phải `HTTPException`. Router exception handler translate → HTTP 400. Implementation thật nên cân nhắc dùng `BusinessRuleViolation` nếu muốn sạch semantics hơn, vì đây là business rule chứ không phải input validation.

#### 1.6 Metadata endpoint serve từ catalog

File: `app/routers/notification_rules.py`

```python
from app.core.event_catalog import get_notifiable_events

# Response thêm: allowed_resolvers, link_strategy per event
# Chỉ serve "user" notification events, không broadcast
```

#### 1.7 EVENT_AUDIT_MATRIX items addressed in PR1

| Matrix ID | Issue | PR1 action |
|---|---|---|
| L9 | `lead_updated` semantics unclear | Set `notification_class="broadcast_only"` in catalog |
| L6, L10, L11 | Resolver recipient-fit partial | Document correct `allowed_resolvers` in catalog; actual resolver config is DB-owned |
| A12 / E3 | Enrollment dedupe_key conflict | Standardize `dedup_key_template` in catalog: `app:${application_id}:status:enrolled` for both paths |
| Finding 4 | `LEAD_STATUS_CHANGED` dual semantics | Document in catalog `description`; no event split |
| CTV10 | `ctv_lead_converted` dead config | Set `notification_class="internal_future"` — no DB rule, no UI |
| F4 | `dorm_fee_created` wrong domain | Set `category="dorm"`, `notification_class="internal_future"` |
| Dorm/Asset | 4 events, modules not built | Set `notification_class="internal_future"` |
| F3 | `payment_overdue` registry-only | Set `notification_class="internal_future"` — promote when beat task exists |
| F5-F10 | Future finance events | Add to catalog as `internal_future` if needed for intent tracking |

**Not in PR1 scope** (follow-up PRs):
- Arch-2: `payment_service` `safe_dispatch()` pattern fix
- Arch-3: Admission atomic double-dispatch
- A15/A16: Missing `withdrawn`/`overridden` dispatch
- GAP-C1/C2/C3: Consultation → lead cascade
- F3/F8: Beat task + finance event implementation

#### 1.8 Deprecate files cũ

| File | Action |
|------|--------|
| `notification_registry.py` | Deprecation header, xóa runtime imports |
| `event_metadata.py` | Deprecation header, redirect sang catalog |
| `notification_rule_loader.py` | Xóa `has_rule_override_for_event()` |

#### 1.9 Expanded scope — runtime fixes gộp vào PR1

Các fix dưới đây phát hiện từ full codebase review, đều chạm cùng dispatcher/loader path mà PR1 đang refactor. Gộp vào PR1 thay vì mở PR riêng.

**1.9a — Thêm CTV metadata (BLOCKER)**

`event_metadata.py` hiện thiếu 10 CTV events mà `notification_registry.py` đã có runtime config. Catalog cần display_name, variables, condition_fields cho mỗi event.

Events cần thêm: `ctv_claim_submitted`, `ctv_claim_approved`, `ctv_claim_rejected`, `ctv_approved`, `ctv_suspended`, `ctv_lead_converted`, `ctv_commission_created`, `ctv_attribution_expiring`, `ctv_attribution_expired`, `ctv_weekly_summary`.

Source data: payload schemas trong `events.py` (lines 718-900) + resolver config trong `notification_registry.py` (lines 630-780).

**1.9b — Bỏ nested `db.commit()` trong dispatcher `_post_commit`**

File: `notification_dispatcher.py:~1081`

Hiện tại: `_post_commit` callback gọi `await db.commit()` lần 2 sau khi router đã commit. Vi phạm "caller owns transaction" contract (line 477).

Fix: Move browser delivery status updates vào trước flush trong main dispatch path, hoặc dùng separate DB session trong callback:

```python
# Option: separate session trong callback
async def _post_commit():
    async with AsyncSessionLocal() as new_db:
        await notification_delivery_service.mark_delivery_ids_sent(new_db, sent_ids)
        await new_db.commit()
```

**1.9c — Cooldown race condition → atomic `SET NX`**

File: `notification_dispatcher.py` — 6 locations (lines 659/669, 860/877, 927/973)

Hiện tại: check `EXISTS` rồi `SET` tách rời → concurrent dispatches có thể duplicate.

Fix: Thay thế tất cả cooldown check+set bằng atomic `SET NX`:

```python
# Trước (2 calls, race window):
if await safe_redis_exists(cooldown_key):
    continue
# ... later ...
await safe_redis_set(cooldown_key, "1", ex=cooldown_seconds)

# Sau (1 atomic call):
acquired = await safe_redis_set(cooldown_key, "1", nx=True, ex=cooldown_seconds)
if not acquired:
    continue  # user already in cooldown
```

**1.9d — Template N+1 query trong rule loader**

File: `notification_rule_loader.py:~655-695`

Hiện tại: `get_rule_for_event()` dùng `selectinload(actions)` nhưng không load `template`. Nếu rule có `template_id`, query thứ 2 chạy mỗi dispatch.

Fix: Thêm eager load:
```python
result = await db.execute(
    select(models.NotificationRule)
    .options(
        selectinload(models.NotificationRule.actions),
        selectinload(models.NotificationRule.template),  # ADD
    )
    .where(...)
)
```

**1.9e — Template update không invalidate rule cache**

File: `notification_template_service.py:~114`

Hiện tại: Admin update template → CRUD service post-commit callback không invalidate cached rules dùng template đó.

Fix: Khi update template, query rules có `template_id` → invalidate mỗi event:
```python
# Trong template update post-commit callback:
rules = await db.execute(
    select(models.NotificationRule.event)
    .where(models.NotificationRule.template_id == template.id)
)
for (event_name,) in rules.all():
    await invalidate_rule_cache(event_name)
```

**1.9f — Resolver deserialization fail → explicit error thay vì silent None**

File: `notification_rule_loader.py:672-683`

Hiện tại: `deserialize_resolver()` fail → `return None` → caller treats as "no rule" → fallback behavior.

Fix: Raise explicit error, dispatcher handles:
```python
except Exception as e:
    log.error("Failed to deserialize resolver for rule", rule_id=rule.id, error=str(e))
    raise NotificationConfigError(f"Rule {rule.id} has invalid recipient_config: {e}")
```

Dispatcher catch `NotificationConfigError` → log error + skip (no fallback, no silent behavior).

#### PR1 files (expanded)

| File | Action |
|------|--------|
| `app/core/event_catalog.py` | New (~550 lines, +50 for CTV entries) |
| `docker-entrypoint.sh` | Add sync command before exec (~2 lines) |
| `app/services/notification_dispatcher.py` | Modify: single path + remove nested commit + atomic cooldown (~80 lines) |
| `app/services/notification_rule_crud_service.py` | Remove browser constraint + add delete guard (~15 lines) |
| `app/services/notification_rule_loader.py` | Remove `has_rule_override_for_event` + add template eager load + explicit resolver error (-17, +10 lines) |
| `app/services/notification_template_service.py` | Add rule cache invalidation on template update (~10 lines) |
| `app/scripts/sync_notification_rules.py` | New (~120 lines) |
| `app/services/notification_registry.py` | Deprecate header |
| `app/core/event_metadata.py` | Deprecate redirect |
| `app/routers/notification_rules.py` | Modify metadata endpoint |
| `app/utils/exceptions.py` | Add `NotificationConfigError` if not exists (~5 lines) |

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

> **Safety:** Preview output PHẢI render như plain text trên frontend. Không dùng `dangerouslySetInnerHTML`. Backend preview endpoint không sanitize HTML — contract là text/template preview. Nếu sau này hỗ trợ rich HTML email preview, cần sanitize policy riêng.

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
TestCatalogClassification:
    - test_user_events_have_dispatch_in_codebase          # "user" events must have real emitters
    - test_broadcast_only_events_excluded_from_notifiable  # broadcast_only never in get_notifiable_events()
    - test_internal_future_events_excluded_from_notifiable # internal_future never in get_notifiable_events()
    - test_no_duplicate_event_keys
    - test_active_events_have_required_fields              # display_name, category, default_resolver

TestCatalogDBParity:
    - test_all_user_events_have_db_rule       # ONLY notification_class="user"
    - test_no_orphan_db_rules                 # no DB rule for events not in catalog
    - test_no_enabled_rules_for_retired_events
    - test_internal_future_events_have_no_rules  # internal_future must not sync rules

TestDedup:
    - test_dedup_templates_use_valid_variables    # dedup template vars ⊆ event variables
    - test_dedup_templates_unique_per_event_family # A12/E3: no conflicting patterns

TestDispatcherInvariants:
    - test_missing_rule_does_not_fallback
    - test_no_registry_import_in_dispatcher
    - test_retired_event_does_not_dispatch
    - test_broadcast_event_emits_domain_only
    - test_internal_future_event_does_not_dispatch
    - test_cross_action_user_dedup_step_order_precedence

TestDeleteGuard:
    - test_cannot_delete_user_event_rule      # active user event → 400
    - test_can_delete_retired_event_rule
    - test_can_delete_orphan_rule
```

**Invariant scope rule:**
- Hard invariant (CI fail): chỉ `notification_class="user"` events
- `broadcast_only`: excluded from all parity checks
- `internal_future`: excluded — no DB rule, no dispatch, no UI. Chỉ ghi nhận intent trong catalog
- Dead config warning (không fail CI): event trong catalog `internal_future` nhưng có enabled DB rule → warning log

#### 3.3 E2E selector fixes (initial targeted, not exhaustive)

Known fragile selectors to fix first:

| Spec | Fix |
|------|-----|
| `notification-dashboard.spec.ts:125` | `locator("h1")` → `getByRole("heading", { level: 1 })` |
| `notification-dashboard.spec.ts:130,152` | `.text-muted-foreground` → `getByTestId("status-*")` |
| `notification-dashboard.spec.ts:131` | `getByText("Active Alerts")` → `getByTestId("alerts-section")` |
| `notification-rule-create.spec.ts:140` | Vietnamese text → `getByTestId("event-required-error")` |
| `notification-rule-create.spec.ts:147` | Vietnamese text → `getByTestId("add-recipient-group")` |

Components cần thêm `data-testid` attributes (~8 files).

> **Note:** Danh sách trên là initial targeted fixes. Khi implement, audit full spec files cho additional brittle text/CSS selectors.

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

## Rollback Strategy

**Fail mode: fail-closed.** Chấp nhận container không start còn hơn silently gửi notification sai.

**`docker-entrypoint.sh` dùng `set -e`:**
- Nếu `alembic upgrade head` fail → container exit, app không start
- Nếu `sync_notification_rules` fail → container exit, app không start
- Không có trạng thái nửa vời: hoặc chạy đúng hoặc không chạy

**Rollback procedure nếu deploy fail:**
1. Deploy lại image/commit trước PR1 (`git checkout` + rebuild)
2. Sync là idempotent + additive — rerun an toàn sau khi fix
3. DB rules đã tạo bởi sync sẽ giữ nguyên (không xung đột với code cũ vì code cũ fallback registry)

**Runtime fail guard:**
- Dispatcher log `"No enabled DB rule for active event"` = signal cần monitor
- Production nên alert nếu log này xuất hiện sau PR1 deploy
- Monitoring layers: CI chặn drift ở build time → sync chặn ở deploy time → dispatcher error log chặn ở runtime

## Verification Checklist

### Sau PR1 deploy:
- [ ] Entrypoint log shows "Syncing notification rules" before "Starting application"
- [ ] Dispatcher không import `notification_registry` runtime
- [ ] `has_rule_override_for_event` không tồn tại
- [ ] Event disabled = không gửi, không fallback
- [ ] Delete active event rule → 400 Bad Request
- [ ] Multi-browser actions pass CRUD validation
- [ ] Cross-action dedup: user ở 2 groups chỉ nhận 1 browser notification (step thấp thắng)
- [ ] CTV events có đầy đủ metadata trong catalog (display_name, variables, condition_fields)
- [ ] Dispatcher `_post_commit` callback không chứa `db.commit()` trực tiếp
- [ ] Cooldown dùng atomic `SET NX` — không còn tách `EXISTS` + `SET`
- [ ] Template update invalidates cached rules dùng template đó
- [ ] Resolver deserialization fail → explicit error, không return None im lặng

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
| D1: `lead_updated` = broadcast_only | UI real-time sync, quá rộng cho notification. Nếu cần notify, tạo event hẹp hơn. | 2026-04-03 |
| D2: Unimplemented modules = internal_future | Giữ business intent, không tạo dead admin-facing rules. Promote khi module build. | 2026-04-03 |
| D3: `finance_events.py` dead code = separate PR | Không nhồi vào refactor. Ưu tiên remove nếu không plan wire-up. | 2026-04-03 |
| D4: Future finance events = internal_future | Chỉ promote sang `user` khi có dispatch implementation thật. | 2026-04-03 |
| 3-tier classification = final | `user` / `broadcast_only` / `internal_future`. Scope rule chốt. | 2026-04-03 |
| D5: Expand PR1 scope, no PR0 | Runtime fixes (cooldown, commit, template cache, CTV metadata) cùng chạm dispatcher/loader path → gộp vào PR1 thay vì PR riêng. | 2026-04-03 |
| D6: CTV metadata = blocker | 10 CTV events thiếu metadata. Catalog merge metadata+registry → CTV entries sẽ khuyết display info nếu không thêm. | 2026-04-03 |
| D7: Cooldown atomic SET NX | Check+set tách rời có race condition. PR1 touching dispatcher → fix luôn. | 2026-04-03 |
| D8: Nested commit = architecture violation | `_post_commit` callback commit lần 2 vi phạm "caller owns transaction". Fix trong PR1 dispatcher refactor. | 2026-04-03 |
| D9: Round 3 confirms module health | Full codebase review (delivery, channels, resolvers, preferences, consents, dispatch callers, Zalo, frontend inbox): no new critical issues. 52 router dispatch calls all correct. | 2026-04-03 |
| D10: Zalo polish ≠ blueprint scope | ZNS-1/2/3 belong to `feature/zalo-zns-phase1` branch, not blueprint PRs. Track separately. | 2026-04-03 |
| D11: Frontend race conditions = P4 | Socket listener cleanup + mark-as-read races are real but don't block PR1/PR2/PR3. Tracked as FE-7/FE-8. | 2026-04-03 |

## Follow-up Roadmap (outside blueprint PRs)

### P1 — Business-critical notification gaps

| ID | Gap | Scope | Trigger |
|---|---|---|---|
| F3 | `payment_overdue` Celery Beat task | New beat task + promote event to `user` | Finance sprint |
| F8 | `fee_fully_paid` SystemEvent + dispatch | New event + dispatch in `payment_service` | Finance sprint |
| A15 | `profile_withdrawn` dispatch missing | 2x `safe_dispatch()` in admission router | Admission sprint |
| A16 | `profile_overridden` dispatch missing | 2x `safe_dispatch()` in admission router | Admission sprint |
| GAP-C1/C2/C3 | Consultation → `lead_status_changed` cascade | Conditional dispatch when `status_updated=True` | Consultation sprint |

### P2 — Coverage expansion

| ID | Gap | Scope |
|---|---|---|
| F5-F10 | Finance events (fee_calculated, invoice_issued, payment_rejected, refund_processed, application_fee_paid) | New SystemEvents + dispatch + promote to `user` |
| CTV10 | `ctv_lead_converted` dispatch | Dispatch when lead status changes for referrer leads |
| E5 | Drop student → `APP_STATUS_CHANGED` | Add dispatch for consistency |
| A12/E3 | Enrollment dedupe normalization | Catalog fix in PR1, verify runtime |

### P3 — Architecture cleanup

| ID | Gap | Scope |
|---|---|---|
| Arch-1 | `finance_events.py` DomainEvent dead code | Decision: remove or wire-up. Recommend remove. |
| Arch-2 | `payment_service` uses `safe_dispatch()` in service | Refactor to `dispatch()` + callback pattern |
| Arch-3 | Admission double-dispatch not atomic | Bundle into savepoint |

### P4 — Frontend quality (PR2+ scope)

| ID | Gap | Scope |
|---|---|---|
| FE-1 | `Control<any>` + `z.unknown()` defeats type safety | Type form schema properly in DefaultContentSection, NotificationRuleEditor |
| FE-2 | NaN coercion in condition builder | `parseInt("abc") \|\| 0` → silent 0. Add `isNaN()` check + user feedback |
| FE-3 | Missing metadata loading/error state | Show skeleton/error banner when useNotificationMetadata fails |
| FE-4 | Accessibility: icon-only buttons | StepIndicator buttons need `aria-label`, screen reader text |
| FE-5 | E2E: comprehensive `data-testid` audit | All wizard interactive elements need test IDs |
| FE-6 | E2E: Vietnamese text selector hacks | `notification-rule-create.spec.ts` partial text matching (lines 203-211) |
| FE-7 | Socket listener cleanup race condition | `SocketHandler.tsx:1020-1098` — 30+ listeners, re-run trước cleanup → memory leak. Guard via Set |
| FE-8 | Mark-as-read mutation race with Socket.IO | `useNotifications.ts:88-119` — optimistic update + socket event cùng lúc → count sai. Server nên return state |
| FE-9 | Quiet hours frontend validation missing | `NotificationSettingsClient.tsx:60-61` — no start < end check |
| FE-10 | Delivery dashboard no auto-refresh | `DeliveryCharts.tsx` — stale data tới 5min. Set `refetchInterval: 15_000` |
| FE-11 | Alert banner dismissal per-global | `AlertBanner.tsx:20-24` — dismiss 1 alert = suppress all 5min. Fix: per-issue tracking |
| FE-12 | Event group toggle race condition | `NotificationSettingsClient.tsx:99-114` — rapid clicks → out-of-order mutations |

### P5 — Operational improvements (deferred)

| ID | Gap | Scope |
|---|---|---|
| Ops-1 | Redis key bloat from per-user rate limiting | Switch to hash buckets per hour |
| Ops-2 | No optimistic locking on rule update | Add `updated_at` conflict detection in CRUD service |
| Ops-3 | Exception taxonomy (`BadRequest` for everything) | Use `BusinessRuleViolation`, `ConflictError`, `ResourceNotFoundError` per domain |
| Ops-4 | `app/tasks/__init__.py` missing delivery_tasks exports | Add exports for clarity (autodiscover works but unclear) |
| Ops-5 | External resolver queries load full objects | `notification_recipients.py:77` — change to scalar select for email/phone only |
| Ops-6 | `is_quiet_hours()` await unnecessary | `notification_preference_service.py:260` — sync function, remove `await` |
| Ops-7 | `type_preferences` JSON no schema validation | `notification_preference.py` — malformed JSON → silent `True` fallback |
| Ops-8 | `bulk_upsert()` consent not truly bulk | `notification_consent_repository.py:111-132` — loops individual upserts |

### Zalo ZNS pre-merge checklist (`feature/zalo-zns-phase1`)

Items to address before merging the Zalo ZNS branch. Independent of blueprint refactor PRs.

| ID | Issue | File(s) | Action |
|---|---|---|---|
| ZNS-1 | Error classification uses string matching on `ChannelResult.error_message` | `delivery_tasks.py:29-53` | Refactor to use `ZaloSendResult.error_code` (int) passed through `ChannelResult`. Zalo channel already returns structured `error_code` via `ZaloSendResult` (`zalo.py:40,248`); issue is downstream classification in `delivery_tasks.py` still string-matches `"Zalo error -216"` etc. |
| ZNS-2 | Webhook test coverage minimal | `test_zalo_webhook.py` (57 lines) | Add tests: delivery status update (msg_id lookup), tracking_id fallback, error_code != 0 → failed transition, quota sync after send |
| ZNS-3 | No startup validation for Zalo credentials | `config.py:441-458` | Add cross-field check: if `ZALO_ENABLED=True` then `ZALO_APP_SECRET`, `ZALO_OA_ID`, `ZALO_REFRESH_TOKEN` must be non-empty. Fail fast at startup. |

## Residual After Refactor

- `notification_registry.py` — deprecated file, xóa sau khi confirm stable (1-2 sprint)
- `event_metadata.py` — deprecated, redirect imports
- `reset_notification_rules_dev.py` — replace bằng `sync_notification_rules` cho dev seed
- `seed_notification_rules.py` — deprecated, sync command thay thế
- `link_template` DB column — dead data, xóa trong migration riêng khi sẵn sàng

## Scope Rule

Blueprint refactor này không cố fix toàn bộ missing business events.

Nó làm 3 việc:
1. Chốt source of truth (catalog + DB, single path)
2. Làm sạch dispatcher/runtime (no fallback, no hidden behavior)
3. Tạo nền catalog + UI + invariant để business event work sau này không drift

Business events chỉ promote thành `user` notification events khi:
- có dispatch implementation thật
- có payload contract rõ
- có resolver semantics rõ
- có lý do nghiệp vụ để admin cấu hình notification
