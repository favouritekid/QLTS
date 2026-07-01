"""Per-user rate-limit key (``get_user_id_key``) — design prerequisite for
flipping AUTHENTICATED routes to enforced limits (deferred: bước 2c).

Why per-user and not per-IP: the default key (``get_remote_address``) resolves to
the nginx container IP in production (``client_ip.py`` Hotfix R8) or the office
NAT egress IP, and SSR fetches collapse onto the frontend container IP — so a
per-IP limit on authenticated endpoints becomes a GLOBAL bucket shared by every
user (prod-wide 429). ``get_user_id_key`` keys on ``user_{id}`` instead.

``get_current_user`` (deps.py) now sets ``request.state.user`` so this key
resolves per-user; the limiter decorator runs INSIDE the endpoint (after the
dependency), so the value is set in time. If that wiring is ever removed,
``get_user_id_key`` SILENTLY falls back to the collapsing IP key —
``test_get_current_user_wires_request_state_user`` fails loudly in that case, so
authenticated routes are never flipped on top of a broken per-user key.
"""
import inspect
from types import SimpleNamespace

import pytest

from app.core.rate_limits import get_user_id_key


class _FakeRequest:
    """Minimal stand-in exposing the attributes get_user_id_key touches."""

    def __init__(self, user=None, host="203.0.113.9"):
        self.state = SimpleNamespace()
        if user is not None:
            self.state.user = user
        self.client = SimpleNamespace(host=host)
        self.headers = {}


@pytest.mark.security
def test_per_user_key_when_authenticated():
    req = _FakeRequest(user=SimpleNamespace(id=42))
    assert get_user_id_key(req) == "user_42"


@pytest.mark.security
def test_falls_back_to_ip_without_user():
    """DANGEROUS fallback documented: with no request.state.user the key becomes
    the per-IP value that collapses in prod. An authenticated route flipped to
    enforcement MUST have get_current_user set request.state.user (guarded below)
    so this branch is never taken in production."""
    req = _FakeRequest(user=None, host="203.0.113.9")
    assert get_user_id_key(req) == "203.0.113.9"


@pytest.mark.security
def test_get_current_user_wires_request_state_user():
    """Guard: get_current_user MUST set request.state.user, otherwise per-user
    keying on authenticated routes silently degrades to the collapsing IP key."""
    from app.core.deps import get_current_user

    src = inspect.getsource(get_current_user)
    assert "request.state.user = user" in src, (
        "get_current_user no longer sets request.state.user → get_user_id_key "
        "falls back to the per-IP (nginx / frontend-container) key on "
        "authenticated routes. Re-add the wiring BEFORE flipping auth routes."
    )
