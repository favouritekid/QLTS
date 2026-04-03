# Cleanup Plan: `Application` Legacy → `AdmissionProfile` Source of Truth

> **Revision:** v4 (2026-03-31)
> **v1→v2:** Gộp Phase 2+3 vì frontend đã migrate; bổ sung dual-creation guard, Casbin gap
> **v2→v2.1:** Bổ sung `User.applications_handled`, `lead_repository.py` selectinload, DB drop strategy
> **v2.1→v3:** Sửa 3 findings: Casbin wording, main.py import step, Phase 1 breaking change
> **v3→v4:** Deep scan — "DO NOT TOUCH" list, alembic trap, SocketHandler/DocumentChecklist/init cleanup
> **v4 addendum:** Fix SQL audit query schema, timeline wording, models/__init__ barrel, DocumentChecklist import chain, retire DOCUMENTS_UPDATED frontend cleanup, doc/test residue step

---

## Mục tiêu

- Chốt `AdmissionProfile` là **source of truth duy nhất** cho nghiệp vụ hồ sơ xét tuyển
- Ngăn dual-creation (Lead có cả Application lẫn AdmissionProfile)
- Xoá dead code legacy khỏi runtime
- Chỉ hard remove DB table khi không còn data concern

---

## Kết quả verify (2026-03-31)

Trước khi lập plan, toàn bộ codebase đã được verify bằng agent search. Các nhận định chính:

### Frontend: ĐÃ MIGRATE XONG

| Component | Status | Evidence |
|---|---|---|
| `LeadApplicationTab.tsx` | **ORPHANED** | Không import ở đâu |
| `LeadApplicationForm.tsx` | **ORPHANED** | Không render ở đâu |
| `useApplication.ts` | **ORPHANED** | Chỉ import bởi 2 component orphaned trên |
| Lead detail page | **ĐÃ MIGRATE** | Dùng `lead.admission_profile`, link `/admissions/{id}` |
| Admission hooks/pages | **ĐÃ DEPLOY** | `useAdmissions.ts`, `/admissions/` pages đầy đủ |
| `API_ENDPOINTS.APPLICATIONS` | **DEAD CONFIG** | CREATE → legacy, UPDATE/GET/DELETE → admissions (mismatch, không ai gọi) |

**Kết luận:** Không cần "migrate frontend callers" — chỉ cần xoá dead code.

### Backend: Functional nhưng không ai gọi

| Component | Status | Evidence |
|---|---|---|
| `applications.py` router | 4 endpoints functional | Nhưng frontend không gọi, không có test |
| `application_service.py` | Dispatch 3 SystemEvents | `APPLICATION_CREATED`, `STATUS_CHANGED`, `DOCUMENTS_UPDATED` |
| `application_repository.py` | Chỉ import từ application_service | Không ai khác dùng |
| Casbin policies | **Partial** — `GET/POST /api/leads/{id}/applications` có trong policy template (`policy_templates.py:~277`), nhưng `GET/PUT/DELETE /api/applications/{id}` **KHÔNG CÓ** template riêng | Create path được Casbin bảo vệ; read/update/delete path thiếu policy |
| Cross-imports | **KHÔNG CÓ** | admission_service ↔ application_service hoàn toàn tách biệt |

### Data model: 2 table riêng, risk dual-creation

| Fact | Detail |
|---|---|
| Tables | `application` và `admission_profile` — riêng biệt |
| FK constraint | Cả hai unique FK tới `lead_id` — nhưng **không cross-check** |
| Risk | Lead có thể có CẢ Application LẪN AdmissionProfile cùng lúc |
| Migration data | Không có logic sync Application → AdmissionProfile |

### Event ownership sau khi remove legacy

| Event | Dispatch từ legacy? | Dispatch từ admissions? | Sau cleanup |
|---|---|---|---|
| `APPLICATION_CREATED` | `application_service.py:95` | `admissions.py:282` | **An toàn** — admissions router tiếp tục dispatch |
| `APPLICATION_STATUS_CHANGED` | `application_service.py:223` | `admissions.py` (12+ points) | **An toàn** — admissions router tiếp tục dispatch |
| `APPLICATION_DOCUMENTS_UPDATED` | `application_service.py:244` | **KHÔNG** — chỉ có ở legacy | **Cần quyết định** — retire hoặc migrate sang admission flow |

---

## DO NOT TOUCH — chứa "application" nhưng KHÔNG phải legacy

> **CRITICAL:** Khi cleanup, dev/AI thấy từ "application" → dễ tưởng legacy → xoá nhầm.
> Các items dưới đây **PHẢI GIỮ NGUYÊN**.

### Business terms (lệ phí xét tuyển)

"Application fee" = lệ phí xét tuyển — thuật ngữ nghiệp vụ, không liên quan Application model.

| File | Reference | Ý nghĩa |
|---|---|---|
| `admission_service.py:~3341` | `check_application_fee_status()` | Kiểm tra lệ phí xét tuyển trên AdmissionProfile |
| `admission_service.py:~3688` | `record_application_fee_payment()` | Ghi nhận thanh toán lệ phí |
| `fee_compatibility_service.py:~64` | `get_application_fee_status()` | Đọc `applied_rules.requires_application_fee` |
| `admissions.py:~1361,~1416` | Check-fee + record-fee-payment endpoints | Active admission endpoints |
| `admission_event_mapping.py:~138` | `"application_fee_paid"` event | Pipeline sync khi lệ phí thanh toán → sts13 |
| `frontend/lib/zod/finance.ts:~21` | fee_type `"application"` | Loại phí trong form validation |
| `frontend/types/pipeline.types.ts:~455,~468` | `application_submitted` timeline event | Icon/color cho event "nộp hồ sơ" |

### Event namespace APPLICATION_* (active — dispatch từ admissions.py)

Tên event dùng "application" nhưng payload `application_id` = `AdmissionProfile.id`.

| File | Reference | Vẫn cần? |
|---|---|---|
| `core/events.py:~258-307` | `APPLICATION_CREATED`, `STATUS_CHANGED`, `DELETED` enums | **CÓ** — admissions.py dispatch |
| `core/event_groups.py:~39,~89-92` | `NotificationEventGroup.APPLICATION` + mappings | **CÓ** — preference UI |
| `core/event_metadata.py:~418-475` | Metadata cho APPLICATION_* events | **CÓ** — admin wizard |
| `notification_registry.py:~352-415` | Registry config (resolver, template, channels) | **CÓ** — active dispatch |
| `notification_dispatcher.py:~197` | `("application_id", "admission_profile")` source mapping | **CÓ** — delivery tracking |
| `scripts/reset_notification_rules_dev.py:~151-173` | Seed rules cho application_* events | **CÓ** — dev reset |

### Payload key `application_id` (DO NOT RENAME)

`"application_id"` trong notification payloads = `AdmissionProfile.id` — **KHÔNG PHẢI** `Application.id`.

Dùng ở:
- `admissions.py` (12+ dispatch points) — payload key
- `notification_dispatcher.py:~197` — source mapping `("application_id", "admission_profile")`
- `notification_registry.py` — template strings `${application_id}`
- **Frontend** `SocketHandler.tsx` — socket listeners match event payloads
- **Frontend** `wizard-constants.ts:~148-155` — template variable `$application_id`

Nếu rename thành `admission_profile_id` → **break** dispatcher mapping, socket handlers, notification templates.

### Frontend socket handlers + notification admin UI (active)

| File | Reference | Vẫn cần? |
|---|---|---|
| `SocketHandler.tsx:~509-571,~1052` | Listeners cho `application_created/status_changed/deleted` | **CÓ** — real-time cache invalidation |
| `wizard-constants.ts:~58-61,~88` | Event options + category "Sự kiện Hồ sơ" | **CÓ** — admin notification UI |
| `NotificationRuleList.tsx`, `TemplateForm.tsx`, `TemplateList.tsx` | Category filter `"application"` | **CÓ** — admin UI grouping |

### Tests cho active business logic

| File | Vẫn cần? | Lý do |
|---|---|---|
| `tests/unit/test_notification_parity.py:~26-65` | **CÓ** | Test APPLICATION_* event semantics |
| `tests/services/test_admission_application_fee.py` | **CÓ** | Test fee gate logic |
| `tests/services/test_fee_compatibility_service.py` | **CÓ** | Test compatibility layer |

---

## Phạm vi legacy cần xử lý

### Backend

| File | Loại | Action |
|---|---|---|
| `app/routers/applications.py` | Router | Xoá |
| `app/services/application_service.py` | Service | Xoá |
| `app/repositories/application_repository.py` | Repository | Xoá |
| `app/core/deps.py` ~line 1001 | `get_application_for_user` dep | Xoá function |
| `app/main.py` ~line 734 | `applications.router` include | Xoá line |
| `app/models/lead.py` ~line 252 | `application` relationship | Xoá relationship |
| `app/models/lead.py` ~line 329 | `class Application(Base)` | Xoá model class |
| `app/schemas/lead.py` ~line 500-622 | `ApplicationBase/Create/Update/Shallow/Application` | Xoá schemas |
| `app/schemas/lead.py` ~line 410-411 | `application` field trong `Lead` response | Xoá field |
| `app/models/user.py` ~line 123 | `applications_handled` relationship | Xoá relationship |
| `app/repositories/lead_repository.py` ~line 87, 152, 463 | `selectinload(Lead.application)` | Xoá 3 selectinload chains |

### Frontend

| File | Loại | Action |
|---|---|---|
| `src/hooks/useApplication.ts` | Hook | Xoá file |
| `src/components/leads/LeadApplicationTab.tsx` | Component | Xoá file |
| `src/components/leads/LeadApplicationForm.tsx` | Component | Xoá file |
| `src/lib/api/endpoints.ts` ~APPLICATIONS block | API config | Xoá block |
| `src/types/lead.types.ts` ~line 115-392 | `Application` + related types | Xoá types |
| `src/components/leads/DocumentChecklist.tsx` ~line 28-29 | Imports `ChecklistItem` + `ApplicationFormValues` từ dead files | Verify: nếu orphaned → xoá. Nếu active → refactor imports |

---

# Phase 1: Freeze & Guard

## Mục tiêu

Ngăn legacy gây hại **ngay lập tức** mà chưa cần xoá code.

## Việc cần làm

### 1.1 Verify traffic trước khi thay đổi behavior (PHẢI LÀM TRƯỚC 1.2)

Kiểm tra xem có external consumer nào đang gọi legacy endpoints không:

```bash
# Option A: Check access logs (nếu có nginx/backend logging)
docker compose logs backend --since 168h 2>/dev/null | grep "POST.*applications" | head -20
docker compose logs nginx --since 168h 2>/dev/null | grep "/api/leads/.*/applications\|/api/applications/" | head -20

# Option B: Check DB — có Application nào được tạo gần đây không?
docker compose exec -T postgres psql -U qlts -d qlts_dev -c \
  "SELECT id, lead_id, created_at FROM application WHERE created_at > NOW() - INTERVAL '30 days' ORDER BY created_at DESC LIMIT 10;"
```

- Nếu **không có traffic / không có records gần đây**: an toàn để thêm guard ở 1.2
- Nếu **có traffic**: cần xác định consumer trước, thông báo breaking change

> **Kết quả audit (2026-03-31):** 0 traffic trong 168h logs. 0 rows trong table `application`. 0 legacy creates 30 ngày gần đây. → An toàn để tiến hành.

### 1.2 Chặn dual-creation (BREAKING CHANGE cho legacy create path)

> **⚠️ LƯU Ý:** Bước này **thay đổi runtime behavior** — `POST /api/leads/{id}/applications` sẽ trả 409 Conflict nếu Lead đã có AdmissionProfile. Đây là breaking change có chủ đích, chấp nhận sau khi 1.1 confirm không có active consumer.

Thêm cross-check trong `application_service.create_application()`:

```python
# application_service.py — trong create_application(), trước khi tạo
from app.models.admission import AdmissionProfile
from app.utils.exceptions import ConflictError  # ← cần thêm import nếu chưa có

# NOTE: AdmissionProfile KHÔNG có cột deleted_at (chỉ Application có)
existing_profile = await db.execute(
    select(AdmissionProfile).where(
        AdmissionProfile.lead_id == lead_id,
    )
)
if existing_profile.scalar_one_or_none():
    raise ConflictError(
        f"Lead {lead_id} already has an AdmissionProfile. "
        f"Cannot create legacy Application."
    )
```

**Lý do:** Nếu ai đó gọi legacy CREATE endpoint → tạo Application cho Lead đã có AdmissionProfile → 2 hồ sơ xét tuyển, notification bị phân mảnh.

### 1.3 Audit DB: kiểm tra dual records hiện tại

```sql
-- Chạy trong postgres container
-- NOTE: admission_profile KHÔNG có cột deleted_at (chỉ application có)
SELECT l.id AS lead_id, a.id AS app_id, ap.id AS profile_id
FROM lead l
JOIN application a ON a.lead_id = l.id AND a.deleted_at IS NULL
JOIN admission_profile ap ON ap.lead_id = l.id;
```

- Nếu **0 rows**: an toàn, không có dual records
- Nếu **có rows**: cần quyết định giữ Application hay AdmissionProfile cho mỗi lead

> **Kết quả audit (2026-03-31):** 0 rows — không có dual records. Table `application` có 0 rows tổng. `admission_profile` có 101 rows.

### 1.4 Đánh dấu deprecated trong code

Thêm deprecation header vào 3 file backend:

**`app/routers/applications.py`** — đầu file:
```python
"""
╔══════════════════════════════════════════════════════════════╗
║  DEPRECATED — Legacy Application Router                      ║
║                                                              ║
║  Source of truth: admissions.py + admission_service.py        ║
║  This router will be removed. Do NOT add features here.      ║
║  See: APPLICATION_LEGACY_CLEANUP.md                          ║
╚══════════════════════════════════════════════════════════════╝
"""
```

**`app/services/application_service.py`** — đầu file:
```python
"""
╔══════════════════════════════════════════════════════════════╗
║  DEPRECATED — Legacy Application Service                     ║
║                                                              ║
║  Source of truth: admission_service.py                        ║
║  This service will be removed. Do NOT add features here.     ║
║  See: APPLICATION_LEGACY_CLEANUP.md                          ║
╚══════════════════════════════════════════════════════════════╝
"""
```

**`app/repositories/application_repository.py`** — đầu file:
```python
"""
╔══════════════════════════════════════════════════════════════╗
║  DEPRECATED — Legacy Application Repository                  ║
║                                                              ║
║  Source of truth: admission repositories in admission_service ║
║  This repository will be removed. Do NOT add features here.  ║
║  See: APPLICATION_LEGACY_CLEANUP.md                          ║
╚══════════════════════════════════════════════════════════════╝
"""
```

### 1.5 Cập nhật architecture guardrails

**`Backend_FastAPI/CLAUDE.md`** — thêm section:

```markdown
## Legacy Application Stack (DEPRECATED)

`AdmissionProfile` is the **sole source of truth** for admission workflows.

DO NOT modify these files (scheduled for removal):
- `app/routers/applications.py`
- `app/services/application_service.py`
- `app/repositories/application_repository.py`

For admission tasks, ONLY use:
- `app/routers/admissions.py`
- `app/services/admission_service.py`

See `APPLICATION_LEGACY_CLEANUP.md` for full context.
```

### 1.6 Quyết định `APPLICATION_DOCUMENTS_UPDATED`

Hai lựa chọn — chọn **một** trước khi vào Phase 2:

**Option A: Retire**
- Nếu active admissions flow không cần "documents updated" event riêng
- Xoá khỏi `notification_registry.py` và `event_metadata.py` khi remove legacy
- `APPLICATION_STATUS_CHANGED` với condition `new_status` đã cover phần lớn document flows

**Option B: Migrate**
- Nếu cần notify khi documents thay đổi trên AdmissionProfile
- Thêm dispatch `APPLICATION_DOCUMENTS_UPDATED` trong `admissions.py` router khi document upload/update
- Giữ registry entry, đổi resolver nếu cần

**Khuyến nghị:** Option A (Retire) — vì active flow đã có `APPLICATION_STATUS_CHANGED(revision_requested)` và `APPLICATION_STATUS_CHANGED(resubmitted)` cover document lifecycle. Event riêng cho "documents updated" là granularity thừa.

## Definition of Done — Phase 1

- [ ] Traffic verification đã chạy (1.1), kết quả documented
- [ ] Cross-check dual-creation đã thêm (1.2)
- [ ] DB audit query đã chạy (1.3), kết quả documented
- [ ] 3 file backend có deprecation header (1.4)
- [ ] `Backend_FastAPI/CLAUDE.md` có guardrail section (1.5)
- [ ] `APPLICATION_DOCUMENTS_UPDATED` có quyết định rõ: A hoặc B (1.6)
- [ ] AI/dev mới nhìn vào biết không code tiếp vào legacy

## Rủi ro Phase 1

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Dual-creation guard (1.2) là **breaking change** cho legacy create path | Low (frontend đã orphaned) | `POST /api/leads/{id}/applications` trả 409 nếu Lead đã có AdmissionProfile | Traffic verification (1.1) chạy trước để confirm không có consumer |
| External consumer gọi legacy API mà không biết | Low | Bị 409 bất ngờ | Access logs + DB audit ở 1.1 phát hiện trước |
| Documentation changes (1.4, 1.5) | None | Không đổi runtime | — |

---

# Phase 2: Hard Remove

## Mục tiêu

Xoá toàn bộ legacy Application khỏi runtime. Tách rõ "remove code" và "drop DB table".

## Preconditions

- [ ] Phase 1 hoàn tất (bao gồm traffic verification + DB audit)
- [ ] `APPLICATION_DOCUMENTS_UPDATED` đã có quyết định (A hoặc B từ Phase 1.6)

## Việc cần làm

### 2.1 Remove backend runtime (một PR)

Thứ tự xoá để tránh import errors:

**Step 1 — Bỏ import + router registration trong main.py:**
```python
# app/main.py:
#   Line ~43: XOÁ import — applications (trong block import routers)
#   Line ~734: XOÁ — fastapi_app.include_router(applications.router, prefix="/api")
#
# ⚠️ PHẢI xoá import TRƯỚC hoặc CÙNG LÚC với xoá file router.
#    Nếu xoá file trước mà giữ import → from app.main import fastapi_app sẽ crash.
```

**Step 2 — Xoá router file:**
```
DELETE app/routers/applications.py
```

**Step 3 — Xoá service + repository:**
```
DELETE app/services/application_service.py
DELETE app/repositories/application_repository.py
```

**Step 4 — Xoá dependency:**
```python
# app/core/deps.py — xoá function get_application_for_user (~line 1001-1040)
# Xoá khỏi __all__ list
```

**Step 5 — Xoá model + relationships + schemas:**
```python
# app/models/lead.py:
#   - Xoá class Application(Base) (~line 329-380)
#   - Xoá relationship: application = relationship("Application", ...) (~line 252-257)

# app/models/user.py:
#   - Xoá relationship: applications_handled = relationship("Application", ...) (~line 123-125)
#   ⚠️ CRITICAL: Nếu không xoá, SQLAlchemy sẽ crash khi load User vì Application model không còn

# app/schemas/lead.py:
#   - Xoá ApplicationDocuments, ApplicationBase, ApplicationShallow,
#     ApplicationCreate, ApplicationUpdate, Application (~line 500-622)
#   - Xoá field: application: Optional["ApplicationShallow"] = None (~line 411)
#   - Xoá Application.model_rebuild() (~line 622)
```

**Step 6 — Xoá selectinload Application trong lead_repository.py:**
```python
# app/repositories/lead_repository.py — 3 chỗ:
#
#   Line ~87-88 (get_by_id_full):
#     XOÁ: selectinload(models.Lead.application).options(
#              selectinload(models.Application.officer)
#          )
#
#   Line ~152-153 (get_by_id_shallow):
#     XOÁ: selectinload(models.Lead.application).options(
#              selectinload(models.Application.officer)
#          )
#
#   Line ~463 (khác):
#     XOÁ: selectinload(models.Lead.application),
#
#   ⚠️ CRITICAL: Nếu không xoá, mọi query fetch Lead sẽ crash vì relationship không còn
```

**Step 7 — Xoá references trong __init__ / barrel files:**
```python
# app/models/__init__.py:
#   Line ~32: XOÁ — from .lead import Application
#   Line ~151: XOÁ — "Application" từ __all__ list
#   ⚠️ CRITICAL: Nếu không xoá, `from app import models` → ImportError vì class đã xoá ở Step 5

# app/routers/__init__.py — KHÔNG CẦN SỬA (file chỉ có 2 dòng comment, không barrel export)
# app/repositories/__init__.py — xoá ApplicationRepository import + __all__ entry

# app/schemas/__init__.py:
#   Line ~134-139: XOÁ — Application, ApplicationBase, ApplicationCreate,
#                          ApplicationUpdate, ApplicationDocuments,
#                          ChecklistItem từ __all__
#   (ApplicationShallow KHÔNG có trong __init__ — chỉ tồn tại ở schemas/lead.py, không re-export)
#   ⚠️ ChecklistItem (schemas/lead.py:~490) nằm trong legacy Application block — xoá cùng
```

**Step 8 — Clean notification registry (nếu retire DOCUMENTS_UPDATED):**
```python
# app/services/notification_registry.py — xoá entry APPLICATION_DOCUMENTS_UPDATED
# app/core/event_metadata.py — xoá APPLICATION_DOCUMENTS_UPDATED metadata
# app/core/events.py — xoá APPLICATION_DOCUMENTS_UPDATED enum value
# app/core/event_groups.py — xoá APPLICATION_DOCUMENTS_UPDATED mapping
```

**Step 9 — Clean Casbin policy templates:**
```python
# app/casbin_config/policy_templates.py:
#   ~Line 277: XOÁ entries cho GET/POST /api/leads/{id}/applications
#   (GET/PUT/DELETE /api/applications/{id} KHÔNG CÓ template — chỉ create path có)
#
# Verify sau khi xoá:
#   grep -n "applications" app/casbin_config/policy_templates.py  # should return 0
```

### 2.2 Remove frontend dead code (cùng PR hoặc PR riêng)

```
DELETE frontend/src/hooks/useApplication.ts
DELETE frontend/src/components/leads/LeadApplicationTab.tsx
DELETE frontend/src/components/leads/LeadApplicationForm.tsx
```

```typescript
// frontend/src/lib/api/endpoints.ts — xoá block:
// APPLICATIONS: { CREATE: ..., UPDATE: ..., GET: ..., DELETE: ... }

// frontend/src/types/lead.types.ts — xoá:
// - ApplicationStatus type (~line 318)
// - ChecklistItem interface (~line 336)
// - ApplicationDocuments interface (~line 347)
// - Application interface (~line 355)
// - ApplicationCreate interface (~line 379)
// - ApplicationUpdate interface (~line 386)
// - application field trong Lead interface (~line 116)
```

**Step — Xử lý `DocumentChecklist.tsx` (import chain đứt):**
```typescript
// frontend/src/components/leads/DocumentChecklist.tsx:
//   Line ~28: import { ChecklistItem } from "@/types/lead.types"  ← sẽ gãy khi xoá type
//   Line ~29: import { ApplicationFormValues } from "./LeadApplicationForm"  ← sẽ gãy khi xoá file
//
// Verify: grep -r "DocumentChecklist" frontend/src/ (trừ file chính nó)
//   - Nếu KHÔNG CÓ active importer → xoá file cùng lúc với LeadApplicationForm.tsx
//   - Nếu CÓ active importer → refactor: xoá 2 import trên, thay bằng inline type hoặc admission types
```

**Step — Clean frontend notification UI (nếu retire APPLICATION_DOCUMENTS_UPDATED):**
```typescript
// frontend/src/components/admin/notifications/wizard-constants.ts:
//   Line ~60: XOÁ — "application_documents_updated" khỏi event options list
//   (GIỮ 3 events còn lại: application_created, application_status_changed, application_deleted)

// frontend/src/components/layouts/SocketHandler.tsx:
//   Line ~551-571: XOÁ — handleApplicationDocumentsUpdated handler function
//   Line ~1053: XOÁ — socket.on("application_documents_updated", ...) listener
//   Line ~1098 (tương ứng): XOÁ — socket.off("application_documents_updated", ...) cleanup
//   (GIỮ 3 handlers còn lại: application_created, application_status_changed, application_deleted)
//
//   ⚠️ ĐẶC BIỆT: handleApplicationDeleted (line ~920-936) PHẢI GIỮ NGUYÊN
//      Line 933: queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) })
//      Đây là cache invalidation ACTIVE — lead detail page cần refresh khi profile bị xoá.
//      Nếu xoá handler này → lead UI sẽ stale sau khi xoá admission profile.
```

### 2.3 Clean doc & test residue (P3 — không chặn runtime nhưng giữ docs đúng)

```markdown
# Backend docs — xoá/update references tới /api/applications/*:
#   AUTHORIZATION_GUIDELINES.md ~line 94
#   AUTHORIZATION_MATRIX.md ~line 112
#   AUTHORIZATION_DECISIONS.md ~line 34
#
#   ⚠️ KHÔNG SỬA monitoring/README.md ~line 188-191
#      Đây là event names (application_created, application_status_changed, ...)
#      = active APPLICATION_* events, KHÔNG phải legacy Application model.
#      Thuộc DO NOT TOUCH list.

# Backend tests — xoá Application model references (GIỮ event/fee tests):
#   tests/security/test_idor_protection.py ~line 7
#     - Xoá get_application_for_user từ dependency list
#     - GIỮ phần test AdmissionProfile IDOR

# Misc:
#   socket_manager.py ~line 592-594: Xoá TODO comments cho emit_application_*()
```

### 2.4 Verify sau khi remove

```bash
# Backend: confirm no import errors
docker compose exec backend python -c "from app.main import fastapi_app; print('OK')"

# Backend: run existing tests
docker compose exec backend pip install -r requirements-dev.txt
docker compose exec backend pytest tests/ -v --tb=short

# Frontend: type-check
docker compose exec frontend npm run type-check

# Frontend: build
docker compose exec frontend npm run build
```

### 2.5 Database table: KHÔNG DROP trong Phase 2

Table `application` **không cần drop ngay** vì:

| Kiểm tra | Kết quả |
|---|---|
| Table khác có FK trỏ TỚI `application`? | **Không** — chỉ có FK từ application trỏ RA |
| View/trigger nào reference? | **Không** |
| Reporting/admin query nào? | **Không** |
| AdmissionProfile có `legacy_application_id`? | **Không** |

Sau Phase 2, table vẫn nằm trong DB nhưng:
- Không có SQLAlchemy model → app không thể query
- Không có router → không thể tạo/sửa records
- Data an toàn, không ảnh hưởng runtime

### 2.6 Database table: Drop khi sẵn sàng (PR RIÊNG, sau 1-2 sprint)

**Preconditions:**
- [ ] Phase 2 đã merge và chạy ổn định ít nhất 1 sprint
- [ ] Confirm không có reporting/BI tool nào query `application` table
- [ ] Confirm data đã archive hoặc không cần

**Steps:**
```sql
-- 1. Kiểm tra data
SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE deleted_at IS NULL) AS active FROM application;

-- 2. Archive nếu có data (optional)
CREATE TABLE application_archive AS SELECT * FROM application;

-- 3. Drop table via alembic migration
```

```bash
docker compose exec backend alembic revision --autogenerate -m "drop_legacy_application_table"
# Review migration file — đảm bảo chỉ drop table + indexes, không ảnh hưởng bảng khác
docker compose exec backend alembic upgrade head
```

**⚠️ ALEMBIC SAFETY — áp dụng NGAY SAU Phase 2 merge:**

Sau khi xoá Application model class, bất kỳ `alembic revision --autogenerate` nào (cho feature khác) sẽ **TỰ ĐỘNG** detect orphan table → generate `op.drop_table('application')` + drop 8 indexes.

```
Quy tắc cho team sau Phase 2:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Khi tạo migration mới cho feature khác:
   - LUÔN review file autogenerate trước khi apply
   - Xoá bất kỳ op.drop_table('application') nếu chưa sẵn sàng drop
   - Hoặc tạo migration thủ công: alembic revision -m "description" (không dùng --autogenerate)

2. Khi SẴN SÀNG drop table:
   - Dùng autogenerate, review chỉ có drop application + indexes
   - Hoặc viết tay: op.drop_table('application') + op.drop_index cho 8 indexes
```

## Definition of Done — Phase 2

- [ ] Backend: `python -c "from app.main import fastapi_app"` thành công
- [ ] Backend: `pytest tests/ -v` pass
- [ ] Frontend: `npm run type-check` pass
- [ ] Frontend: `npm run build` pass
- [ ] Không còn file legacy nào trong runtime
- [ ] `APPLICATION_DOCUMENTS_UPDATED` đã retire hoặc migrate (theo quyết định Phase 1)
- [ ] PR review pass, merge vào main
- [ ] DB table: soft retired (giữ data, xoá model)

## Rủi ro Phase 2

| Risk | Likelihood | Mitigation |
|---|---|---|
| Import error cascade khi xoá | Medium | Xoá theo thứ tự: router → service → repo → model → schema |
| External consumer gọi legacy API | Low | Verify access logs trước khi xoá |
| Test failure do Application reference | Medium | Grep toàn bộ test files cho `Application` trước khi xoá |
| Type-check failure frontend | Low | Frontend components đã orphaned, ít reference |
| Drop DB table mất data | N/A | Tách riêng, chỉ làm khi confirm xong |

---

# Timeline khuyến nghị

```
Phase 1: Freeze & Guard ───── 1-2 ngày (low risk, minor breaking change cho legacy create path)
    ↓
Phase 2: Hard Remove ───────── 1-2 ngày (1 backend PR + 1 frontend PR)
    ↓
DB soft retire ─────────────── Immediate (table ở lại DB, code đã xoá)
    ↓
DB full removal ────────────── Sau 1-2 sprint khi confirm không cần data
```

> **Note:** Phase 1 guard dual-creation (1.2) là breaking change cho `POST /api/leads/{id}/applications`.
> Audit 2026-03-31 confirm: 0 traffic + 0 data → risk thực tế negligible.

---

# Appendix: Sơ đồ trước và sau cleanup

## Trước cleanup

```
Lead ──┬── application (FK unique)      ← LEGACY, 4 endpoints, 3 events
       │   └── Application model        ← Separate table "application"
       │
       └── admission_profile (FK unique) ← ACTIVE, 20+ endpoints, 14+ events
           └── AdmissionProfile model    ← Separate table "admission_profile"
           └── Student (FK)
           └── Fee → Invoice → Payment

2 stacks chạy song song, không cross-check, risk dual-creation
```

## Sau cleanup

```
Lead ──── admission_profile (FK unique)  ← SOLE SOURCE OF TRUTH
          └── AdmissionProfile model
          └── Student (FK)
          └── Fee → Invoice → Payment

Table "application" vẫn tồn tại trong DB (archived)
Không còn code runtime nào reference nó
```

---

# Appendix: Checklist cho reviewer

Khi review PR Phase 2, verify:

**Backend — legacy code đã xoá sạch:**
- [ ] `grep -r "application_service" app/` trả 0 results
- [ ] `grep -r "application_repository" app/` trả 0 results
- [ ] `grep -r "get_application_for_user" app/` trả 0 results
- [ ] `grep -r "from.*applications import" app/` trả 0 results (trừ admissions event dispatch)
- [ ] `grep -r "class Application" app/models/` trả 0 results
- [ ] `grep -r "ApplicationShallow\|ApplicationCreate\|ApplicationUpdate" app/schemas/` trả 0 results
- [ ] `grep -r "applications_handled" app/models/` trả 0 results
- [ ] `grep -r "selectinload.*Lead.application" app/repositories/` trả 0 results
- [ ] `grep -r "applications" app/casbin_config/` trả 0 results
- [ ] `grep -n "Application" app/models/__init__.py` trả 0 results (barrel export đã dọn)

**Frontend — dead code đã xoá sạch:**
- [ ] `grep -r "useApplication" frontend/src/` trả 0 results
- [ ] `grep -r "LeadApplicationTab\|LeadApplicationForm" frontend/src/` trả 0 results
- [ ] `grep -r "APPLICATIONS:" frontend/src/lib/api/` trả 0 results
- [ ] `grep -r "ApplicationFormValues" frontend/src/` trả 0 results (DocumentChecklist đã xoá/refactor)

**Frontend — nếu retire APPLICATION_DOCUMENTS_UPDATED:**
- [ ] `grep -r "application_documents_updated" frontend/src/` trả **0 results** (đã xoá khỏi wizard-constants + SocketHandler theo Step 2.2)

**Doc/test residue:**
- [ ] `grep -r "/api/applications" Backend_FastAPI/*.md Backend_FastAPI/**/*.md` trả 0 results (docs đã update)
- [ ] `get_application_for_user` không còn trong `test_idor_protection.py`

**Runtime verification:**
- [ ] `docker compose exec backend python -c "from app.main import fastapi_app; print('OK')"` thành công
- [ ] `docker compose exec backend pytest tests/ -v --tb=short` pass
- [ ] `docker compose exec frontend npm run type-check` pass
- [ ] `docker compose exec frontend npm run build` pass
