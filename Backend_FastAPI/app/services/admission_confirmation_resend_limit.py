"""ADM-023 / Q9-C2 (2026-04-29): per-profile magic-link resend rate limit.

Cap: ≤3 resends within any 24h trailing-edge window. Keeps the magic-
link inbox from being abused as a free SMTP fanout (each resend
triggers an email or Zalo template send) and gives operators a useful
audit when applicants legitimately need help.

Window shape (revised 2026-04-29 per P3 review):
  Redis ``INCR`` increments a per-profile counter; ``EXPIRE`` is
  re-armed on EVERY hit (not just the first). The bucket therefore
  clears 24h after the MOST RECENT resend — i.e. attempts 1-3 inside
  any sliding 24h trailing-edge keep the counter alive; only a
  full 24h of silence resets it. This is STRICTER than the original
  "fixed 24h from first hit" shape (which would let an abuser burst
  3 → wait 24h → 3 again every 24h cleanly); the new shape forces
  every burst to cool the entire window before it can repeat.

  For a 3-in-24h cap that's appropriate — legitimate applicants who
  hit the limit once typically wait through the 24h naturally
  anyway, and the strictness makes the audit signal cleaner ("4th
  attempt in <24h since the last" is a single rule).

Failure-mode policy: when the Redis breaker is open (``safe_redis_*``
returns ``None`` / falsy), this helper returns ``None`` and the
caller MUST fail closed — refuse the resend rather than fail-open.
This mirrors the F-2 hardening on the Zalo bot rate limiter (memory
``zalo-bot-audit-gap``); a brittle Redis is not an excuse to lift a
spam cap. The audit log row records the breaker-open reason so ops
can see Redis flapped during user reports.

Companion of ``admission_confirmation_cooldown`` — that module covers
the CCCD brute-force ladder; this one covers the resend-spam ladder.
They run on different counters and never share state.
"""
from __future__ import annotations

import structlog
from typing import Final, Optional

from ..database import safe_redis_expire, safe_redis_incr


log = structlog.get_logger(__name__)


# Cap chosen by Q9 decision 2026-04-28. If product later wants to
# differentiate by role (e.g. admin can resend more), pull this into
# a per-actor helper rather than parameterising — the single value
# matches the audit trail's "resend was blocked because we already
# sent N" message verbatim.
RESEND_CAP_PER_24H: Final[int] = 3
RESEND_WINDOW_SECONDS: Final[int] = 24 * 60 * 60


def _resend_key(profile_id: int) -> str:
    return f"admission:confirm:resend:{profile_id}"


async def consume_resend_quota(profile_id: int) -> Optional[int]:
    """Atomically count and consume one resend slot for ``profile_id``.

    Returns:
        - The post-increment count when Redis is up. Caller checks
          ``count <= RESEND_CAP_PER_24H`` to decide whether to send.
        - ``None`` when the Redis breaker is open OR the TTL arm
          fails. Caller MUST fail closed (block the resend).

    Window semantics: TTL is (re-)armed on EVERY hit, so the bucket
    clears 24h after the most recent resend — see module docstring
    for why this trailing-edge shape was chosen over a fixed window
    from first hit. Cost is one extra Redis roundtrip per attempt
    (negligible at 3/24h).

    Why fail-closed on EXPIRE failure (P3 review 2026-04-29):
        The previous shape only armed the 24h TTL on the first hit
        (``count == 1``). If ``INCR`` succeeded but ``EXPIRE``
        immediately after failed (Redis flap between calls), the key
        survived without a TTL — once the cap was crossed, that
        profile would be locked out indefinitely until manual cleanup.
        Now ``EXPIRE`` is called on every hit and any failure is
        treated as a quota-service failure: bail with ``None`` so the
        caller can decline the request.
    """
    key = _resend_key(profile_id)
    count = await safe_redis_incr(key)
    if count is None:
        log.warning(
            "Resend quota check failed: Redis INCR breaker open — failing closed",
            profile_id=profile_id,
        )
        return None

    # Re-arm TTL on every hit. Three effects:
    #   1. The bucket becomes trailing-edge (24h from MOST RECENT
    #      hit) — see module docstring for why we chose this over
    #      "fixed 24h from first hit".
    #   2. A missing/expired TTL on a stray legacy key gets healed.
    #   3. An EXPIRE failure on the FIRST hit can no longer leave a
    #      permanent counter (the bug the previous shape had).
    # EXPIRE failure here means the bucket may not bound to 24h —
    # fail-closed rather than risk an indefinite lockout.
    expire_ok = await safe_redis_expire(key, RESEND_WINDOW_SECONDS)
    if not expire_ok:
        log.warning(
            "Resend quota check failed: Redis EXPIRE returned falsy — failing closed",
            profile_id=profile_id,
            count_after_incr=count,
        )
        return None
    return count


async def peek_resend_count(profile_id: int) -> Optional[int]:
    """Read the current resend count WITHOUT consuming a slot.

    Useful for status / diagnostic endpoints. ``None`` when Redis is
    down (callers should treat as "unknown", not "zero").
    """
    from ..database import safe_redis_get

    key = _resend_key(profile_id)
    val = await safe_redis_get(key)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        # Defensive — Redis stored something we didn't write. Treat
        # as unknown so we don't authorise on bad data.
        return None
