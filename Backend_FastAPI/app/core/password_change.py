# app/core/password_change.py
"""F128 — "the user must change the password before using the system".

ONE source for the predicate behind ``User.password_reset_required`` and for
what a flagged user may still reach. Read by:

- ``deps.get_current_user`` (HTTP, the gate owner): every route except the
  ``ALLOWED_ROUTES`` below answers 403 ``PASSWORD_CHANGE_REQUIRED``;
- ``socket_manager`` (Socket.IO): connect refuses, ``revalidate_auth`` and the
  per-worker watchdog cut a flagged user's sockets.

The Python predicate and the SQL one must agree; ``tests/security/
test_password_reset_enforced.py`` locks them together.
"""
from typing import FrozenSet, Optional, Tuple

from fastapi import Request

from .. import models

PASSWORD_CHANGE_REQUIRED_CODE = "PASSWORD_CHANGE_REQUIRED"

# (HTTP method, route template as FastAPI registers it — prefix included).
# Matched against ``request.scope["route"].path``, never the raw URL: a
# trailing slash, an encoded byte or a longer path cannot reach an entry.
#
# Deliberately NOT here:
# - ``/api/auth/logout``, ``/login``, ``/verify-mfa``, ``/refresh``: they do not
#   authenticate through ``get_current_user`` at all;
# - ``GET /api/sessions`` (the form skips it while forced), session revoke
#   (change-password already revokes every session);
# - ``/api/security/*``: ``confirm-login`` CLEARS the flag ("that was me"), so
#   a flagged session could lift it without changing the password;
# - ``/api/auth/mfa/*``, ``/api/auth/check-status`` (no frontend caller).
ALLOWED_ROUTES: FrozenSet[Tuple[str, str]] = frozenset(
    {
        ("POST", "/api/auth/change-password"),
        ("GET", "/api/users/me"),
    }
)


def password_change_required(user) -> bool:
    """True unless the flag is exactly ``False``: ``None`` or any other value
    blocks (the column is NOT NULL, so only a bug produces one)."""
    return getattr(user, "password_reset_required", False) is not False


def password_change_required_sql():
    """SQL form of ``password_change_required``: ``IS NOT false`` keeps NULL on
    the blocking side, like ``is not False`` does in Python."""
    return models.User.password_reset_required.is_not(False)


def route_key(request: Request) -> Optional[Tuple[str, str]]:
    """``(METHOD, route template)`` of the matched route, or None when the
    request carries no matched route (then nothing is allowlisted)."""
    path = getattr(request.scope.get("route"), "path", None)
    if not isinstance(path, str):
        return None
    return (request.method.upper(), path)


def is_allowed_while_forced(request: Request) -> bool:
    key = route_key(request)
    return key is not None and key in ALLOWED_ROUTES
