# Cleanup Audit — 2026-04-20

**Scope**: deliverable của W4 (TODO triage) + W1b' (metadata/registry gap quantify) trong cleanup plan đã chốt (không feature mới).

**Audit method**:
- W4: grep `TODO|FIXME|XXX|HACK` trên `Backend_FastAPI/app/**/*.py` + `frontend/src/**/*.{ts,tsx}`
- W1b': runtime introspect `SystemEvents` enum vs `EVENT_CATALOG` vs `EVENT_METADATA_REGISTRY` vs `NOTIFICATION_REGISTRY`, plus grep consumers

**Không thực hiện cleanup nào trong PR này** — chỉ list và phân loại. Actionable items sẽ mở issue/PR riêng.

---

## W1b' — Metadata / Registry gap

### Coverage (đã verify runtime)

| Source | Count | Note |
|---|---:|---|
| `SystemEvents` enum | 58 | Ground truth |
| `EVENT_CATALOG` (new) | 58 | Strictly equal to enum |
| `EVENT_METADATA_REGISTRY` (legacy) | 38 | Missing 20 events |
| `NOTIFICATION_REGISTRY` (legacy) | 47 | Missing 11 events |

### Missing-from-catalog gap

- **0 events** trong registry mà catalog không có
- **0 events** trong metadata mà catalog không có

→ Catalog là strict superset. **Data coverage không còn là blocker** cho việc delete legacy modules.

### Catalog-only events (10)

Events chỉ tồn tại trong catalog, không có ở metadata/registry (confirming catalog đã được dùng cho tất cả greenfield events):

```
application_survey_due (Phase E, 2026-04-20)
offering_created / offering_updated / offering_deleted
program_created / program_updated / program_deleted
unit_created / unit_updated / unit_deleted
```

### Consumer blockers (cần migrate TRƯỚC khi delete)

> **Audit rule**: only files with actual ``from ... import`` statements or
> identifier references count. Mentions inside module docstrings or code
> comments are not consumers and don't block deletion.

`NOTIFICATION_REGISTRY` — **4 real consumers**:

| Consumer | Type | Migrate path |
|---|---|---|
| `app/scripts/seed_notification_rules.py` | seed script | Switch to catalog; retire registry import |
| `app/scripts/reset_notification_rules_dev.py` | dev-only reset script | Same as above |
| `tests/unit/test_notification_parity.py` | test | Replace registry refs với catalog |
| `tests/unit/test_registry_actions_compat.py` | test | Delete (registry will no longer exist) |

`EVENT_METADATA_REGISTRY` — **4 real consumers**:

| Consumer | Type | Migrate path |
|---|---|---|
| `tests/integration/test_notification_core_v2.py` | test | Replace metadata refs với catalog |
| `tests/services/test_payment_service.py` | test | Same |
| `tests/unit/test_condition_metadata_parity.py` | test | Rename test to catalog-vs-something else |
| `tests/unit/test_notification_parity.py` | test | Same |

Earlier draft of this table listed `event_catalog.py`, `event_metadata.py`,
`test_lead_notification_flow.py`, `test_notification_contract.py` as
consumers; those were docstring/comment mentions only and have been
removed after re-verifying with strict `from ... import` grep.

### Recommendation

Hai file legacy **không delete-ready trong một sweep**. Thứ tự đề xuất:
1. **Split PR** migrate 2 seed scripts khỏi `NOTIFICATION_REGISTRY` — low risk, không đụng test
2. **Split PR** migrate 6 test files (2 reference registry, 4 reference metadata, `test_notification_parity.py` counted once — it imports both) — medium (touches contract test semantics)
3. **Split PR** delete 2 legacy modules once consumers are gone

Mỗi split PR ~1–2h, tổng ~3–4h. **Out of scope cleanup wave hiện tại** — ghi nhận như tech debt tiếp theo.

---

## W4 — TODO/FIXME triage

> **Units**: ``raw match`` = one grep hit for `TODO|FIXME|XXX|HACK`.
> Multiple hits on the same concern get grouped into one ``bucket``
> below. Totals are raw matches; buckets are disposition-oriented.

Raw match counts (strict grep, 2026-04-20):
- Backend `Backend_FastAPI/app/**/*.py`: **16 raw matches**
- Frontend `frontend/src/**/*.{ts,tsx}`: **31 raw matches**

### Backend — 16 raw matches, grouped

#### 🔴 Actionable — should fix or convert to issue (7)

| Location | Content | Disposition |
|---|---|---|
| `repositories/admission_repository.py:1213` | `# TODO: Caching mechanism for Subject IDs if performance needed` | **Leave as-is** — speculative; keep until measured perf issue. |
| `repositories/officer_repository.py:1662` | `"conversion_rate": None, # TODO: Calculate from transitions` | **Convert to issue** — blocks funnel report accuracy. |
| `routers/kpi_config.py:429` | `# TODO: Implement aggregation for unit/global targets` | **Convert to issue** — KPI feature gap. |
| `services/admission_path_service.py:241` | `# TODO: Move query to repo if complex` | **Leave as-is** — advisory refactor signal, low urgency. |
| `services/admission_service.py:4426` | `# TODO: Implement proper audit log table` | **Stale** — `entity_audit_log` table exists now. Remove comment. |
| `services/document_group_service.py:62` | `TODO: add validation (offering_type_id must exist)` | **Convert to issue** — silent data integrity hole. |
| `services/notification_resolvers.py:291,339` | `# TODO: Implement when Dorm module is available` | **Leave as-is** — contingent on Dorm roadmap decision. |

#### 🟡 Scheduled / future-tag (2)

| Location | Content | Disposition |
|---|---|---|
| `services/notification_channels/__init__.py:15,97` | `# TODO: Future` (SMS channel) | **Keep** — placeholder for Phase C SMS roadmap. |

#### ⚪ Not actual TODOs (4) — grep noise

```
models/finance/invoice.py:6,55        — docstring "INV-YYYY-XXXXXX format"
repositories/collaborator_repository.py:177 — "Generate next CTV-YYYY-XXXX"
services/invoice_service.py:21,768    — docstring repeat of invoice format
scripts/generate_notification_template_intake_workbook.py:162 — TODO in audit worksheet text (not a code TODO)
```

Không cần xử lý.

### Frontend — 31 raw matches, grouped

#### 🔴 `[TODO_BACKEND]` markers (24 raw hits across `frontend/src`) — chờ BE shipping thêm field

Tất cả tập trung ở `finance.types.ts` (11) + `finance.ts` (11). Pattern đồng nhất: FE đã khai báo Zod/TS interface sẵn sàng nhận field, chờ BE expose.

Missing fields (grouped by domain):

- **Invoice**: `description`, `has_fee`, `fee_status`, `overdue_amount`, `last_payment_date`
- **Payment**: `updated_at`, `completed_at`, `callback_received_at`, `callback_data`, `gateway_response`, `idempotency_key`, `reference_code`, `method_name`
- **RefundRequest**: `requested_by_name`, permission flags `can_approve`/`can_reject`/`can_process`
- **AccountingPeriod**: `notes`, permission flag `can_close`
- **FinanceAuditLog**: `performed_by_name`, `gateway_response`, `idempotency_key`
- **PaymentCallback / Issue**: `can_resolve`, profile nested object
- **Profile context**: `has_fee`, `fee_status`, `overdue_amount`, `last_payment_date`

**Disposition**: **convert thành 1 issue** — "Finance API: missing response fields for FE-declared interfaces". Không sprawl thành N issues, 1 consolidated tracker. Scope feature, out of cleanup wave.

#### 🔴 `permissions.ts` — 6 raw hits (P4 FE-quality)

```
permissions.ts:8,60,70,80,90,100 — "TODO: Replace with API permission flags when backend supports it"
```

FE đang hardcode 6 permission checks bằng `user.role`. Blueprint Notification Refactor P4 (FE architecture) flag là debt. **Convert thành issue** — khi backend ship `can_*` flags trên response, FE gỡ hardcode.

#### 🟡 Single-page features (3)

| Location | Content | Disposition |
|---|---|---|
| `admissions/[id]/_components/tabs/AdmissionScoresTab.tsx:90` | `// TODO: Implement weighted scoring with weights from snapshot` | **Real gap — do NOT remove**. Weighted branch (line 93) still returns plain `sum(scores)` with the weights ignored, and that total is rendered at lines 318 + 363. `ScoreSnapshot.tsx` has the correct weighted display elsewhere, but this local tab total needs the same wiring. Convert to issue. |
| `useInvoiceViewModel.ts:39` | `[TODO_BACKEND] Add penalty_amount, total_due` | Gộp vào tracker finance fields |
| `usePaymentMethods.ts:102` | `[TODO_BACKEND] Add description` | Gộp vào tracker finance fields |

### Recommendation W4

- **Remove 1 stale comment** ngay (nhỏ):
  - `admission_service.py:4426` (audit log đã tồn tại — `entity_audit_log` table verified present)
- **Open 4 issues** tracker:
  - Backend: `officer conversion_rate` + `kpi aggregation` + `document_group offering_type validation` → 1 issue "Backend TODO cluster — 3 gaps"
  - Finance: 24 `[TODO_BACKEND]` finance fields missing → 1 issue "Finance API: FE-declared fields awaiting backend ship"
  - FE permissions: 6 `TODO: Replace with API flag` → 1 issue "FE hardcoded permission checks — migrate to API flags"
  - Admission weighted scoring: `AdmissionScoresTab.tsx:90` weighted branch returns plain sum instead of applying subject weights → 1 issue "AdmissionScoresTab: weighted total ignores subject weights"
- **Leave as-is**: SMS future placeholder + Dorm-contingent TODOs + speculative caching comment.

**Tổng actionable cleanup: 1 remove-comment line + 4 issues**. Phần lớn TODO là feature placeholder, không phải cleanup target.

---

## Summary — PR3 outcome

| Wave | Finding | Actionable next |
|---|---|---|
| **W1b'** | Catalog strict superset (58/58). Legacy modules ra được về coverage, nhưng bị block bởi 4 real `NOTIFICATION_REGISTRY` consumers + 4 real `EVENT_METADATA_REGISTRY` consumers (docstring mentions NOT counted) | 3 split PRs (~3–4h tổng) — **out of current cleanup wave** |
| **W4** | 16 backend + 31 FE raw grep matches. Phần lớn là feature placeholder hoặc grep noise. 1 comment stale có thể remove ngay; 4 issue trackers cho real debt (weighted-scoring gap confirmed, không stale) | 1 comment deletion + 4 issue mở — không gộp vào PR3 (tránh scope creep) |

PR3 là audit doc only. Next steps là các issue tracker + follow-up PRs có scope rõ ràng.
