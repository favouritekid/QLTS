# ADR-001: Remove finance_events.py DomainEvent system

## Status

Accepted (2026-04-09)

## Context

QLTS introduced `app/core/finance_events.py` in commit `db28a24d` (2026-01-31)
as Phase 3 of the finance module, defining 18 `DomainEvent` dataclasses with an
`emit_event()` function, `@event_handler` decorator, and an
`IdempotentEventHandler` helper backed by a `processed_event` PostgreSQL table
for deduplication.

The intent was to provide a Domain-Driven Design event layer for cross-module
finance flows (fee calculated, fee fully paid, payment verified, period closed).

5 months later (2026-03-31 audit, documented in `EVENT_AUDIT_MATRIX.md`
Finding 1 / Arch-1):

- **0 production `emit_event()` calls** outside the dead files themselves
- **0 `@event_handler` registrations** in any production code path
- **0 rows** in the `processed_event` table (all environments, verified)
- **0 consumers** (BI, ETL, replication, external systems)

The notification dispatch needs these events were meant to serve are fulfilled
by the `SystemEvents` enum + `notification_dispatcher.py` path, which has been
the canonical production system since its introduction.

## Decision

Remove the dead code cluster:
- `app/core/finance_events.py` (544 LOC, 18 DomainEvent dataclasses)
- `app/core/idempotent_handler.py` (424 LOC)
- `app/schemas/finance_events.py` (330 LOC)
- `EventIdempotencyService` class in `app/services/accounting_service.py`
- `ProcessedEvent` ORM model in `app/models/finance/accounting.py`
- `processed_event` PostgreSQL table (via Alembic migration)
- `tests/unit/test_finance_events.py` (573 LOC, 29 tests)
- Related test functions in `tests/integration/test_finance_workflow.py`

Two-PR split: Phase B1 (source cleanup, no migration) ships first; Phase B2
(table drop via migration) ships after preflight verification across all
environments.

## Alternatives considered

1. **Wire up DomainEvent properly**: ~1000+ LOC refactor across payment_service,
   accounting_service, fee_calculation_service to emit events + add bridge
   handlers to convert to SystemEvents. 5 months of zero usage signal suggests
   this investment will not happen. Rejected.

2. **Leave dead code with deprecation comment**: Doesn't reduce maintenance
   burden, still confuses every audit/refactor cycle. Rejected.

3. **Mark deprecated, stop writing tests**: Half-measure that leaves code
   technically importable. Rejected.

## Consequences

### Positive

- -1871 LOC source/test burden removed (v6-verified count)
- Single canonical event path (SystemEvents + dispatcher + notification_rule)
- Less developer confusion ("which event system do I use?")
- Less audit churn in future cycles

### Negative

- Lose `ProcessedEvent` table primitive for durable idempotency tracking.
  **Mitigation**: Redis dedupe keys in dispatcher already serve equivalent
  production needs. If a future flow requires durable idempotency, add a
  focused table at that time.

- Lose `IdempotentEventHandler` decorator pattern.
  **Mitigation**: Never used in production. Can be reintroduced if needed.

- Lose `DomainEvent` base class as a future event sourcing primitive.
  **Mitigation**: If event sourcing becomes a real requirement, build with
  proper infrastructure (Kafka/RabbitMQ/EventStoreDB) rather than in-process
  scaffolding.

### Neutral

- DB migration is destructive but reversible (downgrade recreates schema
  with empty rows).

## Post-migration replacements

Some of the 18 dead `DomainEvent` dataclasses had spiritual successors
promoted into the live `SystemEvents` path:

| Dead DomainEvent | Live SystemEvents replacement | Reference |
|---|---|---|
| `PaymentVerified` | `SystemEvents.PAYMENT_VERIFIED` | `events.py:~361-365` (inline comment: "Bridged from finance domain event PaymentVerified"). Route: `safe_dispatch()` from `payment_service.py:380` post-commit closure via `payment_router.verify_payment`. |
| `FeeCalculated` | No direct bridge | Fee calculation remains a pure service-internal flow. The dead `# TODO: Emit FeeCalculated domain event` at `fee_calculation_service.py:~193` is removed in B1. |
| `FeeFullyPaid` | Partially via `PAYMENT_VERIFIED` | `PAYMENT_VERIFIED` payload includes an `is_fully_paid` flag. Not all fully-paid states produce a notification. |
| `PeriodClosed` | No bridge needed | Period closure is admin-UI concern, writes to audit log directly. |
| 14 others | Never wired up | No user-visible behavior lost. |

**Rule**: to re-enable notification for any of the non-bridged events, add
a new `SystemEvents` member + `EventDefinition` + seed a `notification_rule`
row. Do NOT reintroduce `DomainEvent` / `emit_event()`.

## Migration path

- **Phase B1**: Source deletes + validator update + design doc historical banner.
  Fully recoverable via `git revert`. No DB change.
- **Phase B2**: Explicit `DROP TABLE processed_event` via manually-written
  Alembic migration with pinned revision IDs (NOT `alembic downgrade -1`).
  Downgrade recreates schema (rows lost). Gated by preflight: all envs must
  show 0 rows + zero BI/ETL consumers.
- **Rollback**: Code revert + (B2 only) `alembic downgrade <pinned_parent_rev>`
  — downgrade FIRST (while migration file still on disk), revert SECOND.

## References

- `EVENT_AUDIT_MATRIX.md` — Finding 1 (Arch-1): dead code classification
- `docs/EVENT_ARCHITECTURE.md` — Section 8: "Why no DomainEvent system?"
- `MASTER_ARCHITECTURE.md` PART 7 — Canonical notification rules
- Original commit: `db28a24d` (2026-01-31)
- Plan: `velvet-swinging-moore.md` (v6, 2026-04-09)
