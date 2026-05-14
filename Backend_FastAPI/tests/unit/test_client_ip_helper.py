"""Hotfix R8 (Phase 3 close-out): anchor tests for the XFF-aware
``get_client_ip`` helper.

The helper underpins the ``100/day`` per-IP slowapi cap on the
public magic-link consume endpoints (both the legacy
``/api/admissions/confirm/{token}`` and the new v2
``/api/v2/admissions/magic-link/{action}/{token}``). Behind nginx in
production, ``request.client.host`` is the nginx container IP for
every candidate, so a naive helper collapses the per-IP cap to a
single bucket shared across all real clients.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.client_ip import get_client_ip


def _make_request(*, xff: str | None = None, client_host: str | None = None):
    """Build a minimal Starlette-shaped Request mock for the helper.

    The helper only touches ``request.headers.get`` and ``request.client.host``
    — so a SimpleNamespace with those two attributes is enough.
    """
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    client = SimpleNamespace(host=client_host) if client_host is not None else None
    return SimpleNamespace(headers=headers, client=client)


def test_returns_first_hop_when_xff_set():
    """X-Forwarded-For: 1.2.3.4 → 1.2.3.4 (not the nginx hop)."""
    req = _make_request(xff="1.2.3.4", client_host="172.18.0.5")
    assert get_client_ip(req) == "1.2.3.4"


def test_returns_first_hop_when_xff_chain():
    """X-Forwarded-For: <client>, <proxy>, <proxy> → first hop wins.

    Per RFC 7239 / nginx ``$proxy_add_x_forwarded_for`` semantics the
    leftmost entry is the original client. Critical for rate-limit
    keying so the cap really counts per-candidate.
    """
    req = _make_request(xff="203.0.113.10, 10.0.0.1, 10.0.0.2", client_host="172.18.0.5")
    assert get_client_ip(req) == "203.0.113.10"


def test_strips_whitespace_around_first_hop():
    """X-Forwarded-For: '  203.0.113.10 , 10.0.0.1' → '203.0.113.10'."""
    req = _make_request(xff="  203.0.113.10 , 10.0.0.1", client_host=None)
    assert get_client_ip(req) == "203.0.113.10"


def test_falls_back_to_client_host_when_xff_missing():
    """No X-Forwarded-For → ``request.client.host`` (test bench / direct hit)."""
    req = _make_request(xff=None, client_host="10.0.0.99")
    assert get_client_ip(req) == "10.0.0.99"


def test_falls_back_to_client_host_when_xff_empty():
    """Empty X-Forwarded-For header → ``request.client.host``."""
    req = _make_request(xff="", client_host="10.0.0.99")
    assert get_client_ip(req) == "10.0.0.99"


def test_returns_unknown_when_no_client_and_no_xff():
    """Defensive: missing both → 'unknown' (no AttributeError)."""
    req = _make_request(xff=None, client_host=None)
    assert get_client_ip(req) == "unknown"


def test_returns_unknown_when_xff_only_commas_and_spaces():
    """Pathological header → falls through to client fallback."""
    req = _make_request(xff="   ,   ", client_host="10.0.0.99")
    # First split[0] = "   " → strip = "" → falsy → fall through
    assert get_client_ip(req) == "10.0.0.99"
