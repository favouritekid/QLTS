"""Regression guard — public admissions catalog endpoints must have their
slowapi rate-limit applied in the CORRECT decorator order.

Context (2026-07): a large set of routers stacked the decorators as::

    @limiter.limit(RateLimits.PUBLIC_READ)   # WRONG — outermost
    @router.get("/programs")
    async def ...

Python applies decorators bottom-up, so ``@router.get`` registers the UNWRAPPED
function first and the slowapi wrapper (applied afterwards) is never what the
router holds. With NO ``SlowAPIMiddleware`` registered (decorator-only mode),
the limit is then SILENTLY NOT ENFORCED. Correct order puts ``@router`` on top,
``@limiter.limit`` directly above the function.

Detection: slowapi wraps the endpoint with ``functools.wraps(func)``
(``slowapi/extension.py``), so a correctly-ordered route's ``APIRoute.endpoint``
carries ``__wrapped__``. A wrong-ordered route's endpoint is the bare function
without it. These 4 endpoints are PUBLIC (no auth) so an unenforced limit is a
real abuse/scraping surface — lock the order here.
"""
from app.core.rate_limits import limiter
from app.main import fastapi_app

import pytest

_PUBLIC_LIMITED_PATHS = [
    "/api/public/admissions/programs",
    "/api/public/admissions/methods",
    "/api/public/admissions/documents",
    "/api/public/admissions/tuition",
]


def _route_for(path: str):
    for route in fastapi_app.routes:
        if getattr(route, "path", None) == path:
            return route
    return None


@pytest.mark.parametrize("path", _PUBLIC_LIMITED_PATHS)
def test_public_catalog_endpoint_rate_limit_correct_order(path: str):
    route = _route_for(path)
    assert route is not None, f"public route {path} is not registered"

    # Correct order (@router outer, @limiter.limit inner) → the app route's
    # endpoint IS the slowapi wrapper (functools.wraps sets __wrapped__).
    # Wrong order → bare function, no __wrapped__ → limit silently unenforced.
    assert hasattr(route.endpoint, "__wrapped__"), (
        f"{path}: endpoint is NOT slowapi-wrapped → rate limit NOT enforced. "
        f"Put @router.get(...) ABOVE @limiter.limit(...) (limiter innermost)."
    )


def test_public_catalog_limits_registered_on_limiter():
    """The 4 endpoints must each carry a registered PUBLIC_READ limit — proves
    ``@limiter.limit`` actually ran (complements the order check above)."""
    limited_names = set(limiter._route_limits.keys())
    for name in (
        "get_public_programs_catalog",
        "get_public_methods_catalog",
        "get_public_documents_catalog",
        "get_public_tuition_catalog",
    ):
        matched = any(name in key for key in limited_names)
        assert matched, f"{name}: no slowapi limit registered (@limiter.limit missing)"
