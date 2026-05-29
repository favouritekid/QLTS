"""Log-safe token identifier helper.

PR-5 (2026-05-28) hardening: replaces the legacy ``token[:8]`` /
``token[:10]`` substring patterns sprinkled across magic-link + confirm
+ socket logging. Substring leaks partial token entropy into structured
log streams; SHA-256 fingerprint truncated to 16 hex characters is one-way
(no entropy leak) but still stable per token value so log correlation /
incident triage continues to work.

Window choice: 16 hex characters = 64 bits, same width as the Redis key
hash used by ``magic_link_rate_limit._key``. Collision probability at the
scale of QLTS token cardinality (live tokens bounded by active
candidates) is negligible.

Stable across processes — search by fingerprint to follow a single token
across services without ever recording the raw value.
"""
from __future__ import annotations

import hashlib


def token_fingerprint(token_value: str | None) -> str:
    """Return a log-safe identifier for ``token_value``.

    Returns ``"none"`` for empty / falsy input so callers do not need a
    null check before emitting structured fields.
    """
    if not token_value:
        return "none"
    return hashlib.sha256(token_value.encode()).hexdigest()[:16]
