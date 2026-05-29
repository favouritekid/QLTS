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

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services import magic_link_rate_limit
from app.utils.token_logging import token_fingerprint


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


# ---------------------------------------------------------------------
# PR-5 (2026-05-28) — token_fingerprint helper + namespace isolation
# ---------------------------------------------------------------------


def test_token_fingerprint_deterministic() -> None:
    """Same token MUST produce same fingerprint across calls so log
    correlation by token_fp works across services + retries."""
    token = "PR-5-determinism-anchor"
    assert token_fingerprint(token) == token_fingerprint(token)


def test_token_fingerprint_no_plaintext_leak() -> None:
    """A leaked log line must NOT reveal the raw token. Fingerprint is
    one-way hash truncated to 16 hex chars."""
    token = "this-is-a-256-bit-magic-link-token-leak-guard"
    fp = token_fingerprint(token)

    assert token not in fp, (
        f"token_fingerprint leaked the plaintext token into the output. "
        f"fp={fp!r} contains token={token!r}"
    )
    assert len(fp) == 16, (
        f"token_fingerprint output must be 16-char hex; got len={len(fp)} value={fp!r}"
    )
    assert all(c in "0123456789abcdef" for c in fp), (
        f"token_fingerprint output must be lowercase hex; got {fp!r}"
    )


def test_token_fingerprint_handles_empty_or_none() -> None:
    """Helper must tolerate falsy input so call sites can skip null
    guards before emitting structured fields."""
    assert token_fingerprint("") == "none"
    assert token_fingerprint(None) == "none"


def test_key_namespace_isolated_mlt_vs_cft() -> None:
    """⭐ PR-5: a single token used at BOTH endpoints (multi-action
    magic-link + legacy confirm) MUST land on DIFFERENT Redis buckets.

    Otherwise a spammer hitting one surface would lock the candidate
    out of the other — defeats the defence-in-depth intent.
    """
    token = "shared-token-across-endpoints"
    mlt_key = magic_link_rate_limit._key(token, key_namespace="mlt:")
    cft_key = magic_link_rate_limit._key(token, key_namespace="cft:")

    assert mlt_key != cft_key, (
        f"Namespace isolation broken — same token landed on the same "
        f"Redis key across mlt: and cft: buckets. "
        f"mlt_key={mlt_key!r} cft_key={cft_key!r}"
    )
    assert mlt_key.startswith("mlt:")
    assert cft_key.startswith("cft:")
    # The hash suffix MUST be identical (deterministic) so the only
    # difference is the namespace prefix.
    assert mlt_key.split(":", 1)[1] == cft_key.split(":", 1)[1]


def test_key_default_namespace_stays_mlt() -> None:
    """Backward-compat anchor: existing magic-link callers do NOT pass
    key_namespace; default MUST remain 'mlt:' so legacy buckets are
    preserved."""
    assert magic_link_rate_limit._key("legacy-token").startswith("mlt:")


@pytest.mark.asyncio
async def test_consume_attempt_uses_namespace_in_redis_key() -> None:
    """consume_attempt MUST forward key_namespace into the Redis key
    name so the legacy /confirm endpoint and multi-action magic-link
    track separate buckets at the Redis layer (not just helper layer).
    """
    incr_calls: list[str] = []

    async def fake_incr(key: str) -> int:
        incr_calls.append(key)
        return 1

    with patch(
        "app.services.magic_link_rate_limit.safe_redis_incr",
        new=AsyncMock(side_effect=fake_incr),
    ), patch(
        "app.services.magic_link_rate_limit.safe_redis_expire",
        new=AsyncMock(return_value=True),
    ):
        await magic_link_rate_limit.consume_attempt(
            "ns-anchor-token", key_namespace="cft:"
        )

    assert len(incr_calls) == 1
    assert incr_calls[0].startswith("cft:"), (
        f"consume_attempt(key_namespace='cft:') wrote a Redis key without "
        f"the cft: prefix. Actual key={incr_calls[0]!r}. The legacy "
        f"confirm endpoint would silently share quota with magic-link."
    )


# ---------------------------------------------------------------------
# PR-5 — static-source scan: no plaintext token prefix slices remain
# ---------------------------------------------------------------------


def test_no_residual_token_prefix_in_app_source() -> None:
    """⭐ Anchor against regression: scan ``app/`` for the legacy
    ``token[:8]`` / ``token[:10]`` / ``token_value[:8]`` patterns + the
    ``token_prefix`` log field. PR-5 swept all real call sites; if a
    future change re-introduces one, this test fails immediately.

    Allowlist:
      - ``app/utils/token_logging.py`` docstring references the legacy
        pattern as historical context.
      - ``app/socket_manager.py`` contains a comment referencing the
        pattern in the PR-5 fix note.

    Both files are inspected and only the docstring/comment lines may
    contain the pattern; any source line elsewhere fails the test.
    """
    app_dir = Path(__file__).resolve().parents[2] / "app"
    assert app_dir.is_dir(), f"Could not locate app/ at {app_dir}"

    patterns = ("token[:8]", "token_value[:8]", "token[:10]", "token_prefix=")
    allow_files = {
        app_dir / "utils" / "token_logging.py",
        app_dir / "socket_manager.py",
    }

    offenders: list[str] = []
    for path in app_dir.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not any(p in stripped for p in patterns):
                continue
            # Comments + docstring lines are allowed in the allowlist
            # files only.
            if path in allow_files and (
                stripped.startswith("#")
                or stripped.startswith('"""')
                or stripped.startswith("``")
                or "``" in stripped
            ):
                continue
            offenders.append(f"{path.relative_to(app_dir.parent)}:{lineno}: {stripped}")

    assert not offenders, (
        "Found residual plaintext token prefix usages in app/ — PR-5 "
        "sweep regressed. Replace with token_fingerprint(token) and "
        "rename the log field to token_fp.\n"
        + "\n".join(offenders)
    )
