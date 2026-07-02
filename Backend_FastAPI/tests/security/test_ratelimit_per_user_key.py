"""Per-user rate-limit key (``get_user_id_key``) — design prerequisite for
flipping AUTHENTICATED routes to enforced limits (deferred: bước 2c).

Why per-user and not per-IP: the default key is get_client_ip (real client
X-Real-IP — correct and non-spoofable behind nginx), but it still groups ALL
staff sharing one office NAT / VPN egress IP into a SINGLE per-IP bucket. On a
low tier (e.g. DATA_WRITE 200/hour, DATA_EXPORT 20/hour) a busy shared-IP office
can 429 legitimate colleagues. ``get_user_id_key`` keys on ``user_{id}`` instead,
so each authenticated user gets an independent bucket.

``get_current_user`` (deps.py) now sets ``request.state.user`` so this key
resolves per-user; the limiter decorator runs INSIDE the endpoint (after the
dependency), so the value is set in time. If that wiring is ever removed,
``get_user_id_key`` falls back to the per-IP key (get_client_ip) →
authenticated routes silently collapse to the office-NAT bucket again.
``test_get_current_user_wires_request_state_user`` fails loudly in that case, so
authenticated routes are never flipped on top of a broken per-user key.
"""
import ast
import inspect
import textwrap
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
    """Fallback documented: with no request.state.user the key becomes the per-IP
    value (get_client_ip), which groups a whole office NAT / VPN into one bucket.
    An authenticated route flipped to enforcement MUST have get_current_user set
    request.state.user (guarded below) so per-user keying actually applies."""
    req = _FakeRequest(user=None, host="203.0.113.9")
    assert get_user_id_key(req) == "203.0.113.9"


@pytest.mark.security
def test_get_current_user_wires_request_state_user():
    """Guard: get_current_user MUST set request.state.user, otherwise per-user
    keying on authenticated routes silently degrades to the shared office-NAT
    per-IP key.

    AST-based (not a substring on the source): a commented-out
    ``# request.state.user = user`` line is NOT an assignment node, so it cannot
    false-pass the guard, and reformatting/whitespace cannot false-fail it."""
    from app.core.deps import get_current_user

    tree = ast.parse(textwrap.dedent(inspect.getsource(get_current_user)))

    def _assigns_request_state_user(target: ast.expr) -> bool:
        # matches `request.state.user = ...`
        return (
            isinstance(target, ast.Attribute)
            and target.attr == "user"
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "state"
            and isinstance(target.value.value, ast.Name)
            and target.value.value.id == "request"
        )

    wired = any(
        isinstance(node, ast.Assign)
        and any(_assigns_request_state_user(t) for t in node.targets)
        for node in ast.walk(tree)
    )
    assert wired, (
        "get_current_user no longer has a real `request.state.user = user` "
        "assignment → get_user_id_key falls back to the per-IP key on "
        "authenticated routes. Re-add the wiring BEFORE flipping auth routes."
    )
