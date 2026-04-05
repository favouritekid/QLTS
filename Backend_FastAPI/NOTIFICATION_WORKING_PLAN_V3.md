# Notification Working Plan v3

> Status: Active
> Updated: 2026-03-26
> Branch: `feature/zalo-zns-phase1`
> Checklist: 12-item standard notification checklist (see bottom)

## Summary

Plan this replaces the previous phase understanding after splitting `C0/C1`. This is the coverage map for **remaining work** after completed phases:
- `Phase A`: done
- `Phase B`: done
- `Phase C0`: done
- `Phase C1`: done (commit `19cb022a`, 2026-03-26)

From here forward, mapped to the original plan:
- `Phase C2` = remaining items of **original Phase C (Operational)**
- `Phase D` = **original Phase D (Mature)**
- `Track T` = test infra, runs in parallel, does not change product phase order

## Audit vs original plan

| Original plan | Current status | This plan |
|---|---|---|
| Phase A Stabilize | Done | Closed |
| Phase B Basic | Done | Closed |
| Phase C Operational | C0 + C1 done | Remaining = `C2` |
| Phase D Mature | Not started | Kept as `D` |
| Out of original plan | `Consent history`, `Template per action` identified | `Extensions` after core backlog |

## Checklist coverage map

| Checklist # | Requirement | Covered by | Status after C1 |
|---|---|---|---|
| 1 | Channel management | Done (A/B/C0/C1) | Complete |
| 2 | Trigger | Done (A/B) | Complete |
| 3 | Recipient selection | Done (A/B/C1) | Complete |
| 4 | Template management | Done (B), E2 extends | Complete (basic), E2 for per-action |
| 5 | Rules & conditions | Done (B/C0) | Complete |
| 6 | Preference & consent | Done (B/C1), E1 extends | Complete (runtime), E1 for history |
| 7 | Delivery tracking | Done (B/C1), **C2-7 extends** | Partial — needs `delivered`/`read` status |
| 8 | Retry & error handling | Partial (C1), **C2-1 + C2-2** | Basic retry only |
| 9 | Anti-spam | Partial, **C2-3 + C2-4** | dedupe_key only |
| 10 | Audit & monitoring | Partial, **C2-5 + C2-6** | structlog only |
| 11 | Admin authorization | Done (B), D4 extends | Complete (basic), D4 for scoping |
| 12 | Extensibility & ops | Partial, **D1 + D2 + D3** | Channel abstraction only |

---

## Phase C2 — Remaining Operational Backlog

Goal: complete all items from **original Phase C** still missing after C0/C1.

**C2-1 Retry + dead-letter**
- `BE2`: retry policy per channel with exponential backoff; terminal failure goes to dead-letter.
- New columns: `next_retry_at`, `max_retries`, `dead_lettered_at` or equivalent.
- Acceptance: transient errors retry with backoff; permanent failures clearly marked.

**C2-2 Manual replay**
- `BE2`: replay API for failed/dead-letter deliveries that qualify.
- Acceptance: admin can replay eligible delivery; replay does not create uncontrolled duplicate sends.

**C2-3 Dedupe + cooldown**
- `BE1`: standardize `dedupe_key` path; add min-interval per event/user.
- Acceptance: same event in quick succession does not flood; dedupe behavior is consistent.

**C2-4 Per-user rate limit**
- `BE1`: frequency cap via Redis counters/TTL.
- Acceptance: bulk action does not create burst exceeding threshold for a single user.

**C2-5 Audit log + dashboard API**
- `BE1`: notification-specific audit trail and aggregate API `queued/sent/failed/skipped`.
- Acceptance: queryable by channel/event/time/user/source.

**C2-6 Admin dashboard UI**
- `FE1`: dashboard showing health/failure/backlog/channel breakdown.
- Acceptance: admin sees backlog, fail rate, top errors, time-based filters.

**C2-7 Delivery lifecycle completion + webhook reconciliation**
- `BE2`: extend delivery status enum to include `delivered` and `read` (provider-confirmed states).
  - `delivered`: provider confirms message reached recipient (Zalo DLR callback, email delivery receipt).
  - `read`: recipient opened/read the message (Zalo `user_received_message`, email open tracking pixel).
  - These are **optional terminal states** — `sent` remains valid final state when provider doesn't report further.
- `BE2`: reconcile job for callback miss/stale deliveries (mark as `sent` if no DLR after configurable timeout).
- Acceptance: delivery status reflects full lifecycle; stale deliveries don't stay stuck indefinitely.

**Definition of Done C2**
- Retry/dead-letter/replay operational.
- Anti-spam guards complete.
- Audit/reporting/dashboard available.
- Delivery status covers full lifecycle (queued → sent → delivered → read | failed | skipped).
- Webhook reconciliation prevents stale deliveries.
- Completion of C2 = **original Phase C (Operational) done**.

---

## Phase D — Mature Operations

Goal: complete **original Phase D** as designed.

**D1 Quota/budget**
- `BE2`: quota per provider/channel, especially for Zalo/SMS.
- Acceptance: can block or degrade when over quota/budget.

**D2 Circuit breaker**
- `BE2`: auto-disable channel/provider on sustained failures.
- Acceptance: provider flap does not cause infinite retry storm.

**D3 Alerting**
- `BE2`: alerts on fail spike, backlog spike, webhook lag, breaker open.
- Acceptance: ops receives actionable alert.

**D4 Resource-level auth**
- `BE1`: manager can only view/replay deliveries within their scope.
- Acceptance: delivery ops follows IDOR-style scoping, not all-admin by default.

**D5 Monitoring dashboard (mature)**
- `FE1`: mature dashboard for daily operations.
- Acceptance: sufficient for ops to monitor health, cost, failures, backlog.

**Definition of Done D**
- Notification subsystem has guards for cost, health, alerting, authorization.
- Completion of D = **original Phase D (Mature) done**.

---

## Extensions (post-core)

These items appeared in worklog but are not part of core `Working Plan v2`. Only implement after C2 stabilizes, unless business pulls them to higher priority.

- `E1 Consent history`: add `NotificationConsentHistory` for compliance/audit trail.
- `E2 Template per action`: unlock `template_code` reject, allow per-action template rendering.

---

## Explicitly deferred / out-of-scope

| Item | Rationale | Revisit when |
|---|---|---|
| **Channel fallback** (e.g., Zalo fail → auto-switch to email) | Adds routing complexity; current retry + dead-letter + manual replay covers most failure cases. Business has not requested cross-channel fallback. | After D2 (circuit breaker) if business identifies need |
| **SMS channel implementation** | Registered in CANONICAL_CHANNELS but no provider contract yet. | When SMS provider is selected |
| **Email open tracking** (for `read` status on email) | Requires tracking pixel infrastructure; privacy implications. | C2-7 prepares the status field; implementation deferred |
| **Template versioning** | Current template CRUD is sufficient; no audit requirement for version history yet. | If compliance requires template change history |

---

## Public interfaces that change

- `NotificationDelivery.status`: add `delivered`, `read` values in C2-7.
- `NotificationDelivery`: add retry fields (`next_retry_at`, `max_retries`, `dead_lettered_at`) in C2-1.
- Replay API endpoint in C2-2.
- Dashboard aggregate API in C2-5.
- Webhook reconciliation job in C2-7.

---

## Test plan

**C2**
- Retry/backoff/dead-letter lifecycle.
- Manual replay (success, duplicate guard, eligibility check).
- Dedupe/cooldown/rate limit enforcement.
- Dashboard aggregate API correctness.
- Reconciliation job handles stale + missed webhooks.
- Delivery status transitions including `delivered`/`read`.

**D**
- Quota enforcement and degradation.
- Circuit breaker state transitions.
- Alert generation on thresholds.
- Resource-scoped delivery ops auth.
- Monitoring dashboard behavior.

---

## Ownership and execution order

- `BE1`: C2-3, C2-4, C2-5, D4, Track T
- `BE2`: C2-1, C2-2, C2-7, D1, D2, D3
- `FE1`: C2-6, D5

Required order:
1. `C2` (start from C2-1 and C2-7 in parallel)
2. `D`
3. `Extensions`

Parallel track:
- `Track T`: test infra cleanup in `tests/conftest.py` and `tests/services/conftest.py`

---

## Assumptions

- `C0` and `C1` are signed off.
- `template_code` remains rejected until `E2`.
- `Consent history` does not block Zalo Phase 1 (already live).
- Browser remains inline path; email/zalo/sms use worker path (established in C1).
- `UNIT_* / PROGRAM_* / OFFERING_*` continue as broadcast-only, not part of user notification contract.
- Channel fallback is explicitly deferred (see deferred table above).

---

## Appendix: 12-item Standard Checklist

| # | Requirement | Verification question |
|---|---|---|
| 1 | Channel management | Can the system configure channels (browser, email, sms, zalo) and toggle each on/off? |
| 2 | Notification trigger | Does the system allow triggering notifications from clear actions or events? |
| 3 | Recipient selection | Can the system select recipients by individual, role, unit, owner, applicant, collaborator? |
| 4 | Template management | Does the system have per-type templates with dynamic content, editable without code changes? |
| 5 | Rules & conditions | Can the system configure send conditions, when to send, when not to send, which rule? |
| 6 | Preference & consent | Can recipients toggle notifications by channel or type? Is external consent managed? |
| 7 | Delivery tracking | Does the system track statuses: queued, sent, delivered, read, failed, skipped? |
| 8 | Retry & error handling | On failure, does the system retry, mark as failed, or fallback appropriately? |
| 9 | Anti-spam | Does the system have dedupe, rate limit, cooldown, or frequency caps? |
| 10 | Audit & monitoring | Can the system log who configured, who triggered, sent to whom, which rule, when? |
| 11 | Admin authorization | Does the system limit who can create/edit rules, templates, channels, audiences, view delivery logs? |
| 12 | Extensibility & ops | Can the system easily add channels/providers, track quota/budget, alert on bulk failures? |
