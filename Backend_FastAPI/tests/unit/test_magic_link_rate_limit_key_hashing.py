"""B2 M2 hardening: ``magic_link_rate_limit._key`` must hash the token
before embedding it in the Redis key.

Why this anchor matters
-----------------------
The magic-link token is a 256-bit URL-safe random value used in CCCD-
verified profile actions (confirm / submit / resubmit / withdraw).
Pre-hardening the Redis key was ``mlt:{raw_token}``; an operator running
``redis-cli MONITOR`` for diagnostic purposes — or a leaked RDB/AOF
snapshot — would expose the token in plaintext. Inside the 60-second
rate window a leaked token can still be used to impersonate the
applicant, so we hash before namespacing.

The hash anchor is intentionally **non-tautological**: it does not
re-implement the hashing inside the assertion. Instead it asserts the
two operational properties we care about:
  (a) plaintext token MUST NOT appear in the Redis key, and
  (b) two different tokens MUST produce different keys (collision
      resistance at our cardinality).

A drift to plaintext (e.g. someone reverts the hashing in a hot-fix)
trips (a) immediately. A drift to a non-keyed hash (e.g. constant-key
bug) trips (b).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import magic_link_rate_limit


# ---------------------------------------------------------------------
# _key() — hash anchor
# ---------------------------------------------------------------------


def test_key_does_not_embed_plaintext_token() -> None:
    """A leaked Redis MONITOR / RDB dump must not reveal the raw token."""
    token = "this-is-a-super-secret-magic-link-token-256bits"
    key = magic_link_rate_limit._key(token)

    assert token not in key, (
        "Redis key still embeds the plaintext token — operator "
        "MONITOR/SLOWLOG/RDB would leak the credential. "
        f"key={key!r} contains token={token!r}"
    )
    assert key.startswith("mlt:"), (
        f"Redis key lost its ``mlt:`` namespace prefix — operators "
        f"can no longer identify magic-link entries: key={key!r}"
    )


def test_key_is_deterministic_for_same_token() -> None:
    """INCR + EXPIRE on retries must land on the same bucket."""
    token = "deterministic-anchor-token"
    assert magic_link_rate_limit._key(token) == magic_link_rate_limit._key(token)


def test_key_differs_across_tokens() -> None:
    """Two distinct tokens must NOT share a rate-limit bucket
    (otherwise an attacker spamming one token would lock out a
    second legitimate user)."""
    k1 = magic_link_rate_limit._key("token-alpha")
    k2 = magic_link_rate_limit._key("token-bravo")
    assert k1 != k2, (
        f"_key collided across distinct tokens: both produced {k1!r}. "
        "Rate limit would now lock unrelated users out."
    )


def test_key_shape_is_namespace_plus_short_hex() -> None:
    """Anchor the post-hash key shape so a future drift (e.g. someone
    base64-encodes instead of hex, blowing past 16 chars and creating
    long Redis keys) trips the test."""
    token = "shape-anchor"
    key = magic_link_rate_limit._key(token)
    prefix, _, suffix = key.partition(":")
    assert prefix == "mlt"
    # 16 hex chars = 64 bits, plenty for live-token cardinality.
    assert len(suffix) == 16, f"key suffix should be 16-char hex, got {suffix!r}"
    assert all(c in "0123456789abcdef" for c in suffix), (
        f"key suffix should be lowercase hex, got {suffix!r}"
    )


# ---------------------------------------------------------------------
# consume_attempt — fail-closed contract
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_attempt_returns_count_on_healthy_redis() -> None:
    with patch(
        "app.services.magic_link_rate_limit.safe_redis_incr",
        new=AsyncMock(return_value=2),
    ), patch(
        "app.services.magic_link_rate_limit.safe_redis_expire",
        new=AsyncMock(return_value=True),
    ):
        result = await magic_link_rate_limit.consume_attempt("happy-path-token")

    assert result == 2


@pytest.mark.asyncio
async def test_consume_attempt_fails_closed_when_incr_breaker_open() -> None:
    """``safe_redis_incr`` returning ``None`` (breaker open) → contract
    says caller must refuse. Verify the helper signals ``None`` rather
    than fail-open with a synthetic count."""
    with patch(
        "app.services.magic_link_rate_limit.safe_redis_incr",
        new=AsyncMock(return_value=None),
    ):
        result = await magic_link_rate_limit.consume_attempt("breaker-token")

    assert result is None


@pytest.mark.asyncio
async def test_consume_attempt_fails_closed_when_expire_arm_fails() -> None:
    """INCR ok but EXPIRE returns falsy → still fail-closed (else a
    counter could survive without a TTL and lock the token forever)."""
    with patch(
        "app.services.magic_link_rate_limit.safe_redis_incr",
        new=AsyncMock(return_value=1),
    ), patch(
        "app.services.magic_link_rate_limit.safe_redis_expire",
        new=AsyncMock(return_value=False),
    ):
        result = await magic_link_rate_limit.consume_attempt("expire-fail-token")

    assert result is None
