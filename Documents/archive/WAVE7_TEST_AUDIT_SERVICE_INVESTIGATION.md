# Wave 7 Investigation — `test_audit_service` duplication

**Date**: 2026-04-21
**Scope**: Classify `tests/services/test_audit_service.py` (487 LOC, 26 tests) vs `tests/unit/test_audit_service.py` (458 LOC, 35 tests) — both test `app.services.audit_service`.

---

## Verdict: **real overlap** (plan outcome (a)), not legitimate unit/service split.

Both files are unit-style: 100% mock-based (`AsyncMock`/`MagicMock`), 0 real `AsyncSession` usage. The `tests/services/` location is misleading — the file contains pure unit tests.

## Evidence

### Structural counts

| Signal | `tests/unit/test_audit_service.py` | `tests/services/test_audit_service.py` |
|---|---:|---:|
| Test functions | 35 | 26 |
| `AsyncMock`/`MagicMock` references | 32 | 49 |
| Real `AsyncSession` / `real_session` / `actual_db` | 0 | 0 |
| `pytest.mark.*` | 7 | 11 |
| Passing today | ✓ | ✓ (61/61 passed in 1.49s) |

### Shared test classes (same class names in both)

| Class | UNIT methods | SERVICES methods |
|---|---:|---:|
| `TestSerializeValue` | 9 | 6 |
| `TestDetectChanges` | 9 | 6 |
| `TestExtractAuditFields` | 4 | 3 |
| `TestLogAudit` | 2 | 3 |

UNIT covers more unique scenarios per shared class; SERVICES covers fewer but splits convenience functions into more classes.

### Classes only in UNIT (3)

- `TestToDict` (4 methods) — tests internal `_to_dict()` helper
- `TestConvenienceFunctions` (5 methods) — all 5 conv fns in one class: log_field_change, log_changes, log_created, log_deleted, log_status_change
- `TestAuditServiceIntegration` (2 methods) — workflow-style (not DB integration, just multi-step logic)

### Classes only in SERVICES (5)

- `TestLogFieldChange` (2 methods)
- `TestLogChanges` (2 methods)
- `TestLogCreated` (2 methods)
- `TestLogDeleted` (1 method)
- `TestLogStatusChange` (1 method)

Pattern: SERVICES splits what UNIT consolidates into `TestConvenienceFunctions`. SERVICES methods tend to cover 1 additional variation per fn (e.g. `test_log_field_change_with_custom_source`, `test_log_created_without_actor`).

## Coverage delta summary

- Shared classes: UNIT wider (9 vs 6 on `SerializeValue`, 9 vs 6 on `DetectChanges`).
- Unique to SERVICES: fine-grained variations for convenience functions (custom_source, without_actor, changeset format, etc.) — real extra coverage.
- Unique to UNIT: `TestToDict`, workflow-level integration, full convenience-fn sweep.

No assertion would be lost if both were kept. Both would be lost-assertions-risk if merged naively.

## Merge-direction options (if proceeding)

| Option | Action | Net test-count delta | Risk |
|---|---|---|---|
| Merge into UNIT | Port SERVICES unique classes (`TestLogFieldChange`..`TestLogStatusChange`) into UNIT file, delete SERVICES file | +8 tests unique from SERVICES, total ~43 | Low — file-system only; care with class-name conflicts on `TestLogAudit`/`TestDetectChanges`/`TestExtractAuditFields`/`TestSerializeValue` — need to merge class bodies |
| Merge into SERVICES | Port UNIT unique classes into SERVICES file, delete UNIT file | +11 tests unique from UNIT | Same risk; plus SERVICES location is misleading |
| Rename split | Keep both but rename e.g. `test_audit_service_unit.py` + `test_audit_service_logfn.py` | 0 | Cosmetic only; doesn't address the 4-class-name collision |
| Leave as-is | Document cross-reference in each file's module docstring | 0 | Zero risk; 4-class-name collision stays but tests don't import each other so no pytest conflict |

## Recommendation

**Leave as-is with cross-reference docstrings** (option d, zero-risk variant of plan outcome (c)).

Reasoning:
- Both files pass, 61 tests total, no functional redundancy that blocks builds.
- A naive merge would require careful hand-merging of 4 class bodies to avoid losing the extra scenarios each file covers. That's not cleanup-safe; it's a refactor with real risk of dropped assertions.
- Users/reviewers finding one file should be able to discover the other via the docstring note.
- The merge is a valid follow-up PR with its own review scope — keeping it out of the cleanup-safe wave preserves the "preserve behavior over architectural beauty" guardrail.

## Proposed Wave 7 execution (zero-risk)

Add a 2-line docstring cross-reference at the top of each file:

```
# tests/unit/test_audit_service.py
"""Unit tests for Generic Entity Audit Service.
...
NOTE: Coverage is split across two files pending a future merge PR.
See also: tests/services/test_audit_service.py
"""
```

And matching in the other file. Zero behavior change, only improves discoverability.

## Out-of-scope follow-up

Merging the two files into one (option 1 or 2 above) is a valid follow-up PR. It should:
1. Pick a target file (recommend `tests/unit/test_audit_service.py` — correct location, matches unit-style content).
2. Hand-merge the 4 overlapping classes keeping all unique assertions.
3. Port the 5 SERVICES-only classes verbatim.
4. Delete `tests/services/test_audit_service.py`.
5. Run full suite to verify 61-ish test count preserved.
