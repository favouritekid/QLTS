"""Regression guard: no endpoint may ship with ``@limiter.limit`` in the WRONG
decorator order (silently unenforced).

Root cause (2026-07): ~351 routes stacked ``@limiter.limit`` ABOVE ``@router.*``.
Python applies decorators bottom-up, so ``@router`` registers the UNWRAPPED
function and the slowapi wrapper never runs. Adding ``SlowAPIMiddleware`` does NOT
help — it calls ``_check_request_limit(in_middleware=True)`` which skips loading
the per-route ``_route_limits`` (verified: a wrong-order route returns 200/200
under a 1/min limit even with the middleware on). So the ONLY enforcement path is
the decorator, which requires the correct order.

Authoritative signal: the function FastAPI actually serves is ``route.endpoint``.
Correct order → it is slowapi's ``functools.wraps`` wrapper (has ``__wrapped__``).
Wrong order → the bare function. ``_route_limits`` registration alone does NOT
distinguish the two (the decorator body registers the limit regardless of order),
so this guard checks ``__wrapped__`` on the LIVE route table, not registration.

``ratelimit_wrong_order_allowlist.txt`` freezes the known debt. Flip an endpoint
to the correct order → delete its line. A NEW wrong-order endpoint (not in the
file) fails ``test_no_new_unenforced_rate_limit``.
"""
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.core.rate_limits import limiter
from app.main import fastapi_app

_ALLOWLIST_PATH = Path(__file__).parent / "ratelimit_wrong_order_allowlist.txt"


def _load_allowlist() -> set[str]:
    names: set[str] = set()
    for raw in _ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            names.add(line)
    return names


def _current_unenforced() -> set[str]:
    """Routes that HAVE a registered rate limit but whose served endpoint is the
    bare (unwrapped) function → limit silently unenforced (wrong decorator order)."""
    rl = limiter._route_limits
    debt: set[str] = set()
    for route in fastapi_app.routes:
        if not isinstance(route, APIRoute):
            continue
        name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        if name in rl and not hasattr(route.endpoint, "__wrapped__"):
            debt.add(name)
    return debt


@pytest.mark.security
def test_no_new_unenforced_rate_limit():
    allow = _load_allowlist()
    current = _current_unenforced()

    new_debt = sorted(current - allow)
    assert not new_debt, (
        "New endpoint(s) have @limiter.limit in the WRONG order → limit SILENTLY "
        "unenforced. Put @router.* ABOVE @limiter.limit (limiter innermost):\n  "
        + "\n  ".join(new_debt)
    )

    stale = sorted(allow - current)
    assert not stale, (
        "Allowlist entries are no longer unenforced (fixed/removed). Delete these "
        "lines from ratelimit_wrong_order_allowlist.txt:\n  " + "\n  ".join(stale)
    )


@pytest.mark.security
def test_allowlist_names_are_registered_routes():
    """Every allowlisted name must map to a route with a registered limit — guards
    against typos / stale format that would make the guard silently vacuous."""
    rl = limiter._route_limits
    unknown = sorted(n for n in _load_allowlist() if n not in rl)
    assert not unknown, (
        "Allowlist contains names with no registered rate limit (typo/stale):\n  "
        + "\n  ".join(unknown)
    )
