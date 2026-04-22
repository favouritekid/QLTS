"""
Local lead/consultation-status ID constants used by test fixtures.

Wave 5 (2026-04-22) — these are the literal values the deprecated
`settings.DEFAULT_*_LEAD_STATUS*` constants used to hold. They live
in `tests/` now (not in `app/config.py`) because production code
never reads them: production looks statuses up via
`StatusHelper.get_initial_status()` / `get_rejected_status()` and
records assignment progression via the `AssignmentStatus` enum
(`app/services/status_helper.py`). Tests still need stable literal
values so fixtures can seed `ConsultationStatus(id=...)` rows and
assert on `lead.status` strings.

Semantic note: the `UNASSIGNED_LEAD_STATUS` / `ASSIGNED_LEAD_STATUS`
strings here are NOT the same as `AssignmentStatus.FAILED` /
`AssignmentStatus.ASSIGNED` — the deprecated constants tracked an
older `lead.status` field with different string values. Keeping the
literals unchanged preserves current test behavior; migrating to
`AssignmentStatus` would change what the assertions check.
`DEFAULT_REASSIGN_LEAD_STATUS` had zero consumers and was dropped
outright with no replacement here.
"""

# ConsultationStatus row IDs seeded by test fixtures.
# Used as `ConsultationStatus(id=INITIAL_LEAD_STATUS_ID, ...)` seeds
# and referenced elsewhere in test setup by the same string.
INITIAL_LEAD_STATUS_ID: str = "TTHV000"
LOST_LEAD_STATUS_ID: str = "TTHV004"

# Literal `lead.status` strings asserted by assignment-flow tests.
# Production sets these values through flows that are orthogonal to
# `AssignmentStatus`, so we keep the historical strings verbatim.
UNASSIGNED_LEAD_STATUS: str = "unassigned_pending"
ASSIGNED_LEAD_STATUS: str = "assigned"
