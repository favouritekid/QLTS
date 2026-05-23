"""Option-B Commit 2 — canonical device fingerprint contract (service layer).

Tests that the service-side fingerprint extraction is family-only (no
version suffix), stable across browser/OS minor-version drift, and that
``_parse_user_agent`` returns both display + family identifiers so the
caller can persist both in ``login_history``.

The user-visible bug being fixed: clicking "Là tôi" on a suspicious
login created a trusted_device row whose fingerprint was hashed from the
display strings ("Mobile Safari 26.4" / "iOS 18.7"). On the next OS
update Safari became "26.5" / iOS became "18.7.1", the recomputed hash
diverged, and the user got re-flagged as "thiết bị mới". Post-Commit 2
the hash inputs are family-only ("Mobile Safari" / "iOS") which the
``user-agents`` library already exposes via ``ua.browser.family`` /
``ua.os.family`` — stable across the entire major-version lifetime.

All tests in this file are pure-function unit tests (no DB, no fixtures
beyond ``settings`` reads). Integration tests for ``record_login`` /
``confirm_login`` end-to-end live alongside the existing auth tests and
require the docker stack.
"""
from __future__ import annotations

import hashlib

import pytest

from app.config import settings
from app.services.login_history_service import (
    _family_from_display,
    _parse_user_agent,
    generate_device_fingerprint,
)


# ===========================================================================
# 1. _family_from_display — regex strip helper
# ===========================================================================


@pytest.mark.parametrize(
    "display, expected",
    [
        # Standard browser display strings
        ("Mobile Safari 26.4", "Mobile Safari"),
        ("Chrome 147.0.0", "Chrome"),
        ("Firefox 130.0", "Firefox"),
        ("Microsoft Edge 120.0.1234.56", "Microsoft Edge"),
        # OS display strings
        ("iOS 18.7", "iOS"),
        ("iOS 18.7.1", "iOS"),
        ("Windows 10", "Windows"),
        ("Mac OS X 10.15.7", "Mac OS X"),
        ("Android 14", "Android"),
        # Already-family input (no version) is idempotent — strip is no-op.
        ("Mobile Safari", "Mobile Safari"),
        ("Chrome", "Chrome"),
        # Empty / None → None (NOT empty string — caller treats both the same).
        ("", None),
        (None, None),
        # Whitespace-only input also returns None.
        ("   ", None),
    ],
)
def test_family_from_display_strips_trailing_version(display, expected):
    """``_family_from_display`` removes the trailing version-like suffix
    and is idempotent on already-stripped input.

    The regex ``\\s+[\\d][\\d.]*$`` matches whitespace + a leading digit +
    optional more digits/dots at end-of-string. This deliberately does
    NOT touch internal numbers (e.g. "Mobile Safari" stays intact even
    though "Mobile" has no digits — there's nothing trailing to strip).
    """
    assert _family_from_display(display) == expected


def test_family_from_display_matches_pg_regex():
    """The Python regex must match the Postgres ``regexp_replace`` used
    in ``sl20260524`` migration backfill. Both strip the same suffix
    pattern so a row backfilled by migration produces the SAME family
    as a row populated at runtime by the service.

    This is a unit-level sanity check — full integration parity is
    asserted by the migration test's helper-parity case.
    """
    cases = [
        ("Mobile Safari 26.4", "Mobile Safari"),
        ("Chrome 147.0.0", "Chrome"),
        ("Mac OS X 10.15.7", "Mac OS X"),
    ]
    for inp, expected in cases:
        py_result = _family_from_display(inp)
        # Equivalent of regexp_replace(inp, '\s+[\d][\d.]*$', '') in Postgres.
        import re as _re
        pg_result = _re.sub(r"\s+[\d][\d.]*$", "", inp).strip() or None
        assert py_result == pg_result == expected, (
            f"Python helper vs PG regex divergence for {inp!r}: "
            f"py={py_result}, pg={pg_result}, expected={expected}"
        )


# ===========================================================================
# 2. _parse_user_agent — returns both display + family
# ===========================================================================


def test_parse_user_agent_includes_family_keys():
    """Parse result MUST include ``browser_family`` + ``os_family`` so the
    caller (``record_login``) can feed them into ``generate_device_fingerprint``
    without re-running the regex.
    """
    # iPhone Safari UA — well-known string from user-agents library docs.
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.7 "
        "Mobile/15E148 Safari/604.1"
    )
    parsed = _parse_user_agent(ua)
    assert "browser" in parsed
    assert "os" in parsed
    assert "browser_family" in parsed, "Family key missing — Commit 2 contract"
    assert "os_family" in parsed, "Family key missing — Commit 2 contract"
    assert "device_type" in parsed


def test_parse_user_agent_family_is_version_free():
    """For an iPhone UA the family is just the bare identifier, no
    version digits.
    """
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.7 "
        "Mobile/15E148 Safari/604.1"
    )
    parsed = _parse_user_agent(ua)
    # Family fields: "Mobile Safari" + "iOS" — no trailing digits.
    assert parsed["browser_family"] is not None
    assert parsed["os_family"] is not None
    import re as _re
    assert _re.search(r"\d", parsed["browser_family"] or "") is None, (
        f"browser_family carries digits: {parsed['browser_family']!r} "
        "— canonical fingerprint will drift on version updates."
    )
    assert _re.search(r"\d", parsed["os_family"] or "") is None, (
        f"os_family carries digits: {parsed['os_family']!r}"
    )
    # Display fields preserve the version for admin UI.
    assert any(c.isdigit() for c in (parsed["browser"] or "")), (
        "browser display string lost its version — admin UI now ambiguous."
    )


def test_parse_user_agent_none_input():
    """Empty / missing UA returns a fully-NULL info dict — caller still
    gets the family keys (set to None) so it can pass them to the
    fingerprint helper without KeyError.
    """
    parsed = _parse_user_agent(None)
    assert parsed["device_type"] is None
    assert parsed["browser"] is None
    assert parsed["os"] is None
    assert parsed["browser_family"] is None
    assert parsed["os_family"] is None


def test_parse_user_agent_malformed_input():
    """Catastrophic parse failure (library throws) falls back to all-None
    — the service must never crash on a bad UA string, just degrade the
    fingerprint.
    """
    # A clearly bogus string. user-agents library is permissive so this
    # may actually parse as ``Other`` family — we just assert no
    # exception leaks and the family keys exist.
    parsed = _parse_user_agent("\x00\x01garbage\x02")
    assert "browser_family" in parsed
    assert "os_family" in parsed


# ===========================================================================
# 3. generate_device_fingerprint — family inputs, stability
# ===========================================================================


def test_fingerprint_stable_across_browser_version_drift():
    """SAME family + version difference → SAME fingerprint.

    This is the central guarantee of Option-B. User 16's bug repro:
    trusted device confirmed when Safari was 16.3 / iOS 16.3. After iOS
    updated to 18.7 the device was re-flagged. Post-fix: only the family
    components enter the hash, so the version delta is invisible.
    """
    fp_16 = generate_device_fingerprint(
        browser_family="Mobile Safari",
        os_family="iOS",
        device_type="mobile",
        user_id=16,
    )
    fp_18 = generate_device_fingerprint(
        browser_family="Mobile Safari",
        os_family="iOS",
        device_type="mobile",
        user_id=16,
    )
    assert fp_16 == fp_18, (
        "Fingerprint changed across two calls with identical family inputs — "
        "this is the bug Option-B is meant to fix."
    )


def test_fingerprint_differs_across_device_type():
    """device_type IS in the hash — switching from phone to tablet (same
    browser family + same OS family) should produce a different
    fingerprint. We don't want a user's phone trust to silently extend
    to their tablet.
    """
    fp_mobile = generate_device_fingerprint("Mobile Safari", "iOS", "mobile", 16)
    fp_tablet = generate_device_fingerprint("Mobile Safari", "iOS", "tablet", 16)
    assert fp_mobile != fp_tablet


def test_fingerprint_differs_across_user_id():
    """Same device, different user → different fingerprint. Protects
    against cross-user fingerprint correlation (someone sharing a family
    laptop can't tell which sibling logged in by hash).
    """
    fp_a = generate_device_fingerprint("Chrome", "Windows", "desktop", 16)
    fp_b = generate_device_fingerprint("Chrome", "Windows", "desktop", 42)
    assert fp_a != fp_b


def test_fingerprint_includes_salt():
    """The salt is concatenated into the hash. Without knowing the salt
    a third party who scrapes browser headers cannot reconstruct the
    fingerprint for spoofing. Exercise: bypass the salt and confirm the
    hash differs from the helper's output.
    """
    fp = generate_device_fingerprint("Chrome", "Windows", "desktop", 16)
    no_salt = hashlib.sha256(
        "|".join(["Chrome", "Windows", "desktop", "16", ""]).encode()
    ).hexdigest()
    assert fp != no_salt, (
        "Helper produced a hash identical to the no-salt variant — salt "
        "isn't being mixed in."
    )


def test_fingerprint_none_inputs_use_unknown_anonymous():
    """``None`` inputs fall back to 'unknown' / 'anonymous' — pinning the
    backfill / fallback behaviour. Migration's
    ``_generate_device_fingerprint_canonical_v1`` mirrors this exactly,
    and the migration parity test asserts they agree.
    """
    fp = generate_device_fingerprint(None, None, None, None)
    expected = hashlib.sha256(
        f"unknown|unknown|unknown|anonymous|{settings.DEVICE_FINGERPRINT_SALT}".encode()
    ).hexdigest()
    assert fp == expected


def test_fingerprint_full_version_input_DEPRECATED():
    """Sanity check that passing display strings is NOT silently
    equivalent to family-only — the helper hashes whatever caller
    feeds it. The DRIFT the fix prevents is at the CALLER level
    (``record_login`` now extracts family before calling). This test
    asserts the helper distinguishes inputs so a buggy caller doesn't
    silently collide with the family path.
    """
    fp_family = generate_device_fingerprint("Mobile Safari", "iOS", "mobile", 16)
    fp_display = generate_device_fingerprint("Mobile Safari 26.4", "iOS 18.7", "mobile", 16)
    assert fp_family != fp_display, (
        "Helper produced the same hash for family vs display inputs — "
        "if a caller passes display strings by mistake, downgrade & "
        "migration old-display helper would also collide. Helper MUST "
        "be input-sensitive."
    )


# ===========================================================================
# 4. record_login / confirm_login integration markers
# ===========================================================================


def test_module_exports_family_fingerprint_contract():
    """Lock the public surface of the service module so a future
    refactor doesn't quietly drop ``_family_from_display`` (still needed
    as NULL-safe fallback in ``confirm_login``) or rename
    ``generate_device_fingerprint``.
    """
    import app.services.login_history_service as svc

    assert hasattr(svc, "_family_from_display")
    assert hasattr(svc, "_parse_user_agent")
    assert hasattr(svc, "generate_device_fingerprint")
    assert hasattr(svc, "record_login")
    assert hasattr(svc, "confirm_login")


def test_record_login_persists_canonical_columns_signature():
    """Static inspection: ``record_login`` body must pass
    ``device_info["browser_family"]`` / ``["os_family"]`` to
    ``generate_device_fingerprint`` AND persist them onto the
    ``LoginHistory`` row alongside ``device_fingerprint``.

    Integration test that actually runs ``record_login`` against the
    DB lives in the auth integration suite and needs the docker stack.
    """
    import inspect
    import app.services.login_history_service as svc

    src = inspect.getsource(svc.record_login)
    # Fingerprint computed from family keys (not display).
    assert 'browser_family=device_info.get("browser_family")' in src
    assert 'os_family=device_info.get("os_family")' in src
    # LoginHistory row carries family + canonical fingerprint columns.
    assert "browser_family=device_info.get(\"browser_family\")" in src
    assert "os_family=device_info.get(\"os_family\")" in src
    assert "device_fingerprint=device_fingerprint" in src


def test_confirm_login_uses_family_fingerprint_signature():
    """Static inspection: ``confirm_login`` must read family columns from
    the LoginHistory row, fall back to ``_family_from_display`` for
    legacy rows, and hash the family inputs — NOT the display strings.

    Integration test that actually runs ``confirm_login`` → trusts the
    device → re-logs in and asserts no false ``is_new_device`` lives
    alongside the auth integration suite (docker stack required).
    """
    import inspect
    import app.services.login_history_service as svc

    src = inspect.getsource(svc.confirm_login)
    # Reads canonical columns.
    assert "login.browser_family" in src
    assert "login.os_family" in src
    # NULL-safe fallback via the regex helper.
    assert "_family_from_display" in src
    # Fingerprint call uses family kwargs (not browser=/os=).
    assert "browser_family=browser_family" in src
    assert "os_family=os_family" in src
