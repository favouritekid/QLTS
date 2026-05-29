"""PR-CO-2-BE / PR-3E (Phase 3 close-out): per-token rate limit for the
multi-action magic-link consume endpoint.

Cap: ≤5 consume attempts per token in any trailing-edge 60s window.

Defence-in-depth alongside the existing CCCD brute-force cooldown ladder
(``admission_confirmation_cooldown``) and per-profile resend cap
(``admission_confirmation_resend_limit``):

  - Resend cap (per profile, 24h)        — stops free SMTP fanout
  - Cooldown ladder (per token row, DB)  — stops CCCD brute force
  - This module (per token VALUE, Redis) — stops endpoint hammering
                                            from a single token URL

Window shape: trailing-edge (TTL re-armed on every hit), identical to
``admission_confirmation_resend_limit``. Burst then wait 60s
quiet-period to reset. Matches plan v2 PR-CO-2-BE spec "Redis rate limit
``mlt:{token}`` max 5/60s".

Failure-mode policy: fail closed. When Redis is unavailable,
``consume_attempt`` returns ``None`` and the caller MUST refuse the
request. A brittle Redis is not an excuse to lift a rate cap — same
reasoning as the resend cap.
"""
from __future__ import annotations

import structlog
from typing import Final, Optional

from ..database import safe_redis_expire, safe_redis_incr
from ..utils.token_logging import token_fingerprint

log = structlog.get_logger(__name__)


ATTEMPTS_CAP_PER_WINDOW: Final[int] = 5
WINDOW_SECONDS: Final[int] = 60


def _key(token_value: str, key_namespace: str = "mlt:") -> str:
    """Build a hashed Redis key for ``token_value`` under ``key_namespace``.

    Token is 256-bit URL-safe random — unguessable on the wire, but the
    plaintext form can still leak via Redis operational surfaces:
    ``redis-cli MONITOR`` (debug streaming), ``SLOWLOG`` snapshots, and
    RDB/AOF dumps all record the raw command incl. key name. Hashing
    truncates that exposure: the leak becomes a one-way hash, useless
    for impersonating the magic link inside the 60s rate window.

    Namespace strategy (PR-5 2026-05-28):
      - ``mlt:`` — multi-action magic-link consume (default, original)
      - ``cft:`` — legacy ``/api/admissions/confirm/{token}`` POST
    Namespaces are mutually exclusive so a single token used across both
    endpoints does NOT share quota — each surface gets its own 5/60s cap.
    """
    return f"{key_namespace}{token_fingerprint(token_value)}"


async def consume_attempt(
    token_value: str,
    key_namespace: str = "mlt:",
) -> Optional[int]:
    """Atomically count + consume one attempt slot for ``token_value``.

    Args:
        token_value: raw token from URL path / query.
        key_namespace: Redis key prefix to scope the counter. Default
            ``"mlt:"`` keeps the original magic-link behaviour. Pass
            ``"cft:"`` for the legacy confirm endpoint (PR-5).

    Returns:
        - Post-increment count when Redis is healthy. Caller checks
          ``count <= ATTEMPTS_CAP_PER_WINDOW`` to decide whether to
          proceed; ``count > cap`` means rate-limit lockout.
        - ``None`` when the Redis breaker is open or EXPIRE arms fail.
          Caller MUST fail closed (refuse the request).
    """
    key = _key(token_value, key_namespace=key_namespace)
    count = await safe_redis_incr(key)
    if count is None:
        log.warning(
            "Magic-link rate limit check failed: Redis INCR breaker open — failing closed",
            token_fp=token_fingerprint(token_value),
            key_namespace=key_namespace,
        )
        return None

    # Re-arm TTL every hit so the window is trailing-edge (60s of
    # quiet required to clear). Mirrors the resend limit shape.
    expire_ok = await safe_redis_expire(key, WINDOW_SECONDS)
    if not expire_ok:
        log.warning(
            "Magic-link rate limit check failed: Redis EXPIRE returned falsy — failing closed",
            token_fp=token_fingerprint(token_value),
            key_namespace=key_namespace,
            count_after_incr=count,
        )
        return None
    return count
