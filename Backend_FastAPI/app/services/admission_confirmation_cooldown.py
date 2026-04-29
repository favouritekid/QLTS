"""ADM-023 (2026-04-29): hybrid cooldown ladder for magic-link CCCD verification.

Q9 decision (memory ``admission-audit-wave2-2026-04-28``): A3+B1+C2.
The applicant's cooldown after a failed CCCD attempt scales with the
running ``attempt_count``. A pure-function helper keeps the ladder in
one place so service code, tests, and any future admin UI all read
the same thresholds.

Ladder
------

| attempt_count    | cooldown            |
| ---------------- | ------------------- |
| 1, 2             | 5 minutes           |
| 3, 4             | 30 minutes          |
| 5, 6             | 2 hours (120 min)   |
| 7 .. 29          | 24 hours (1440 min) |
| 30 +             | HARD LOCK (admin)   |

The hard-lock branch is signalled by returning ``None`` (not a
sentinel like ``-1``) so the caller's ``Optional[int]`` type makes
the "no more cooldowns, escalate" case explicit at the call site.

Resend rate limit (3 per profile per 24h) is handled separately by
``app/services/admission_confirmation_resend_limit.py`` against
Redis — that ladder doesn't belong here because resends are a
different abuse vector (link spam to inbox), not a CCCD brute-force
defense.
"""
from __future__ import annotations

from typing import Final, Optional


# Threshold for the "this token must be reset by an admin" branch.
# Crossing it sets ``token.locked_at`` and increments
# ``token.lock_count``; further attempts return 403 until reset.
HARD_LOCK_THRESHOLD: Final[int] = 30


# Each tier maps an inclusive attempt-count upper bound to the
# cooldown that should fire for any attempt within that tier.
# Ordered from soft to harsh; the first tier whose upper bound is
# ``>= attempt_count`` wins. Sentinel ``HARD_LOCK_THRESHOLD - 1``
# closes the ladder before the hard-lock branch.
_LADDER: Final[tuple[tuple[int, int], ...]] = (
    (2, 5),
    (4, 30),
    (6, 120),
    (HARD_LOCK_THRESHOLD - 1, 1440),
)


def cooldown_minutes_for(attempt_count: int) -> Optional[int]:
    """Return the cooldown (minutes) for ``attempt_count`` failed attempts.

    Args:
        attempt_count: Cumulative failed attempts on the token,
            **including** the attempt that just failed. ``0`` means no
            failure yet (returns ``0``); ``1`` means "this is the first
            failure".

    Returns:
        Cooldown in minutes, or ``None`` if the count has reached the
        hard-lock threshold (caller must set ``locked_at`` / increment
        ``lock_count`` instead of computing a sliding ``lock_until``).
        ``0`` is returned only for the no-failure case so the caller
        doesn't need to special-case "no cooldown" vs "5-minute
        cooldown".
    """
    if attempt_count <= 0:
        return 0
    if attempt_count >= HARD_LOCK_THRESHOLD:
        return None
    for upper, minutes in _LADDER:
        if attempt_count <= upper:
            return minutes
    # Defensive — should not be reached because the last tier's upper
    # bound covers up to HARD_LOCK_THRESHOLD - 1.
    return None


def is_hard_lock(attempt_count: int) -> bool:
    """Whether ``attempt_count`` triggers the hard-lock branch."""
    return attempt_count >= HARD_LOCK_THRESHOLD
