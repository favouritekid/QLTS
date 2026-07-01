"""
Test IP-based rate limiting (OWASP A6: Brute Force Protection).

Validates that slowapi IP-based rate limiting correctly:
1. Blocks requests after exceeding the threshold (HTTP 429)
2. Isolates rate limit counters per IP address
3. Maintains independent limits per endpoint
4. Has proper rate limit annotations on security-sensitive endpoints

Architecture note:
    This tests Layer 1 (IP-based slowapi) only.
    Layer 2 (per-user Redis counter) and Layer 3 (AccountLockoutService)
    are tested in their respective test modules.

How it works:
    slowapi's @limiter.limit() decorator WRAPS each endpoint function.
    On every request, the wrapper calls limiter._check_request_limit()
    which reads limits from limiter._route_limits[func_name] and checks
    the in-memory (test) or Redis (prod) storage.

    In test mode (APP_ENV="test"), main.py skips registering the 429
    exception handler and sets limits to 1000/minute. This fixture:
    - Registers the exception handler so RateLimitExceeded -> 429
    - Overrides _route_limits with tight limits (3/minute)
    - Uses a controllable key_func to simulate different client IPs
"""

import logging

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded
from slowapi.wrappers import LimitGroup
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simulated IP address control
# ---------------------------------------------------------------------------

_test_ip: str = "127.0.0.1"


def _get_test_ip(request) -> str:
    """Custom key function returning the simulated IP address.

    slowapi calls this with the Starlette Request object.
    We ignore the request and return the module-level _test_ip variable,
    allowing tests to control which IP is "making" the request.
    """
    return _test_ip


# ---------------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------------

# Tight limits for test endpoints (override production "1000/minute")
_LOGIN_LIMIT = "3/minute"
_REGISTER_LIMIT = "2/minute"
_PUBLIC_READ_LIMIT = "3/minute"

_OVERRIDDEN_ENDPOINTS = {
    "app.routers.auth.login_for_access_token": _LOGIN_LIMIT,
    "app.routers.auth.verify_mfa": _LOGIN_LIMIT,
    "app.routers.auth.register_user": _REGISTER_LIMIT,
    # Public admissions catalog (unauthenticated). 2026-07 regression: decorator
    # order was `@limiter.limit` ABOVE `@router.get`, so slowapi never wrapped the
    # registered endpoint and PUBLIC_READ was silently unenforced. The behavioural
    # test below proves real 429 emission — which ALSO fails if the wrong order
    # ever returns (the wrapper is not invoked, so no 429).
    "app.routers.public_admissions.get_public_programs_catalog": _PUBLIC_READ_LIMIT,
    "app.routers.public_admissions.get_public_methods_catalog": _PUBLIC_READ_LIMIT,
    "app.routers.public_admissions.get_public_documents_catalog": _PUBLIC_READ_LIMIT,
    "app.routers.public_admissions.get_public_tuition_catalog": _PUBLIC_READ_LIMIT,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def rate_limited_client(setup_test_database):
    """
    AsyncClient with IP rate limiting enabled using tight test limits.

    Lifecycle:
    1. Register RateLimitExceeded -> 429 exception handler on the app
    2. Override targeted endpoint limits (1000/min -> 3/min)
    3. Reset limiter in-memory storage (clean slate)
    4. Run app lifespan & yield the client
    5. Restore original limits & clean up on teardown
    """
    from app.core.rate_limits import limiter
    from app.main import fastapi_app as app, lifespan

    # -- 1. Register 429 exception handler ---------------------------------
    async def _handler_429(request, exc):
        return JSONResponse(
            status_code=429,
            content={"detail": "Qua nhieu yeu cau. Vui long thu lai sau."},
        )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _handler_429)

    # Force middleware stack rebuild so new exception handler is active
    app.middleware_stack = None

    # -- 2. Override route limits with tight test values --------------------
    saved_limits: dict[str, list] = {}
    for endpoint_name, limit_str in _OVERRIDDEN_ENDPOINTS.items():
        # Save original (copy the list, not a reference)
        saved_limits[endpoint_name] = limiter._route_limits.get(
            endpoint_name, []
        )[:]
        # Replace with tight limit using our controllable key function
        limiter._route_limits[endpoint_name] = list(
            LimitGroup(
                limit_str,       # e.g. "3/minute"
                _get_test_ip,    # custom key function for IP simulation
                None,            # scope (None = per-route)
                False,           # per_method
                None,            # methods
                None,            # error_message
                None,            # exempt_when
                1,               # cost
                True,            # override_defaults
            )
        )

    # -- 3. Reset in-memory storage ----------------------------------------
    limiter.reset()

    # -- 4. Set default test IP --------------------------------------------
    global _test_ip
    _test_ip = "127.0.0.1"

    # -- 5. Run app lifespan and yield client ------------------------------
    async with lifespan(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

    # -- 6. Teardown: restore everything -----------------------------------
    for endpoint_name, original in saved_limits.items():
        limiter._route_limits[endpoint_name] = original
    limiter.reset()

    app.exception_handlers.pop(RateLimitExceeded, None)
    if hasattr(app.state, "limiter"):
        delattr(app.state, "limiter")

    # Force middleware stack rebuild for clean state
    app.middleware_stack = None


# ---------------------------------------------------------------------------
# Test: IP rate limiting on /login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.security
class TestIpRateLimitLogin:
    """IP rate limiting on the login endpoint (/api/auth/login)."""

    async def test_blocks_after_threshold(self, rate_limited_client: AsyncClient):
        """
        After 3 requests from the same IP, the 4th must return 429.
        Limit is set to "3/minute" by the fixture.
        """
        global _test_ip
        _test_ip = "10.0.0.1"

        # 3 requests within limit -> expect non-429 (401, 422, etc.)
        for i in range(3):
            res = await rate_limited_client.post(
                "/api/auth/login",
                data={
                    "username": f"attacker_{i}@test.com",
                    "password": "WrongPass1!",
                },
            )
            assert res.status_code != 429, (
                f"Request {i + 1}/3 should be allowed, got {res.status_code}"
            )
            logger.info(
                "Request %d/3 from IP %s -> %d", i + 1, _test_ip, res.status_code
            )

        # 4th request -> 429 (rate limited)
        res = await rate_limited_client.post(
            "/api/auth/login",
            data={
                "username": "attacker_blocked@test.com",
                "password": "WrongPass1!",
            },
        )
        assert res.status_code == 429, (
            f"Request 4 should be rate-limited (429), got {res.status_code}"
        )
        logger.info("Request 4 correctly blocked with 429")

    async def test_ip_isolation(self, rate_limited_client: AsyncClient):
        """
        Hacker A (IP 10.0.0.1) exhausts the limit.
        Hacker B (IP 192.168.1.50) must NOT be affected.
        """
        global _test_ip

        # -- Hacker A exhausts the limit (3 requests) ---------------------
        _test_ip = "10.0.0.1"
        for i in range(3):
            await rate_limited_client.post(
                "/api/auth/login",
                data={
                    "username": f"hacker_a_{i}@test.com",
                    "password": "WrongPass1!",
                },
            )

        # Hacker A is now blocked
        res_a = await rate_limited_client.post(
            "/api/auth/login",
            data={
                "username": "hacker_a_blocked@test.com",
                "password": "WrongPass1!",
            },
        )
        assert res_a.status_code == 429, (
            f"Hacker A should be blocked (429), got {res_a.status_code}"
        )

        # -- Hacker B from different IP is NOT blocked ---------------------
        _test_ip = "192.168.1.50"
        res_b = await rate_limited_client.post(
            "/api/auth/login",
            data={"username": "hacker_b@test.com", "password": "WrongPass1!"},
        )
        assert res_b.status_code != 429, (
            f"Hacker B should NOT be blocked (IP isolation), "
            f"got {res_b.status_code}"
        )
        logger.info(
            "IP isolation verified: A blocked (%d), B allowed (%d)",
            res_a.status_code,
            res_b.status_code,
        )

    async def test_different_endpoints_independent(
        self, rate_limited_client: AsyncClient
    ):
        """
        Exhausting /login limit must NOT affect /register limit.
        Each endpoint has its own independent counter.
        """
        global _test_ip
        _test_ip = "10.0.0.2"

        # Exhaust /login limit (3 requests)
        for i in range(3):
            await rate_limited_client.post(
                "/api/auth/login",
                data={
                    "username": f"cross_{i}@test.com",
                    "password": "WrongPass1!",
                },
            )

        # /login is now blocked
        res_login = await rate_limited_client.post(
            "/api/auth/login",
            data={"username": "cross_blocked@test.com", "password": "WrongPass1!"},
        )
        assert res_login.status_code == 429

        # /register should still work (different endpoint, separate counter)
        res_register = await rate_limited_client.post(
            "/api/auth/register",
            json={
                "email": "fresh_user@test.com",
                "password": "StrongPassword123!",
                "full_name": "Fresh User",
            },
        )
        assert res_register.status_code != 429, (
            f"/register should NOT be affected by /login rate limit, "
            f"got {res_register.status_code}"
        )
        logger.info(
            "Endpoint independence verified: /login=%d, /register=%d",
            res_login.status_code,
            res_register.status_code,
        )

    async def test_429_response_format(self, rate_limited_client: AsyncClient):
        """
        When rate limited, the response body must contain a detail message.
        """
        global _test_ip
        _test_ip = "10.0.0.3"

        # Exhaust limit
        for _ in range(3):
            await rate_limited_client.post(
                "/api/auth/login",
                data={"username": "format_test@test.com", "password": "WrongPass1!"},
            )

        # Trigger 429 and check response body
        res = await rate_limited_client.post(
            "/api/auth/login",
            data={"username": "format_test@test.com", "password": "WrongPass1!"},
        )
        assert res.status_code == 429
        body = res.json()
        assert "detail" in body, "429 response must include 'detail' field"
        assert isinstance(body["detail"], str)
        assert len(body["detail"]) > 0


# ---------------------------------------------------------------------------
# Test: Rate limit configuration verification
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestRateLimitConfiguration:
    """Verify that security-sensitive endpoints have rate limit annotations."""

    @pytest.mark.parametrize(
        "endpoint_key",
        [
            "app.routers.auth.login_for_access_token",
            "app.routers.auth.verify_mfa",
            "app.routers.auth.register_user",
            "app.routers.auth.request_password_reset",
            "app.routers.auth.perform_password_reset",
            "app.routers.auth.perform_change_password",
            "app.routers.auth.refresh_access_token",
            # Public admissions catalog (unauthenticated) — exact-key registration
            # check (order enforcement is covered by the behavioural test below).
            "app.routers.public_admissions.get_public_programs_catalog",
            "app.routers.public_admissions.get_public_methods_catalog",
            "app.routers.public_admissions.get_public_documents_catalog",
            "app.routers.public_admissions.get_public_tuition_catalog",
        ],
    )
    def test_endpoint_has_rate_limit(self, endpoint_key: str):
        """Each security-sensitive endpoint must have rate limit registered."""
        from app.core.rate_limits import limiter

        assert endpoint_key in limiter._route_limits, (
            f"Endpoint '{endpoint_key}' is missing @limiter.limit() decorator"
        )
        assert len(limiter._route_limits[endpoint_key]) > 0, (
            f"Endpoint '{endpoint_key}' has empty rate limit list"
        )

    def test_production_login_limit_is_strict(self):
        """
        In production, AUTH_LOGIN must be <= 10/minute
        to effectively prevent brute force attacks.
        """
        from app.config import settings
        from app.core.rate_limits import RateLimits

        if settings.APP_ENV == "test":
            # In test mode, limits are relaxed by design
            assert RateLimits.AUTH_LOGIN == "1000/minute"
        else:
            amount = int(RateLimits.AUTH_LOGIN.split("/")[0])
            assert amount <= 10, (
                f"Production AUTH_LOGIN should be <= 10/min, "
                f"got {RateLimits.AUTH_LOGIN}"
            )

    def test_production_register_limit_is_strict(self):
        """
        In production, AUTH_REGISTER must be <= 5/minute.
        """
        from app.config import settings
        from app.core.rate_limits import RateLimits

        if settings.APP_ENV == "test":
            assert RateLimits.AUTH_REGISTER == "1000/minute"
        else:
            amount = int(RateLimits.AUTH_REGISTER.split("/")[0])
            assert amount <= 5, (
                f"Production AUTH_REGISTER should be <= 5/min, "
                f"got {RateLimits.AUTH_REGISTER}"
            )

    def test_limiter_uses_memory_storage_in_test(self):
        """In test mode, limiter must use in-memory storage (not Redis)."""
        from app.core.rate_limits import STORAGE_URI

        assert STORAGE_URI == "memory://", (
            f"Expected memory:// storage in test mode, got {STORAGE_URI}"
        )

    def test_limiter_key_func_is_ip_based(self):
        """Default limiter key function must be get_remote_address (IP-based)."""
        from slowapi.util import get_remote_address

        from app.core.rate_limits import limiter

        assert limiter._key_func is get_remote_address, (
            "Default key_func should be get_remote_address for IP-based limiting"
        )


# ---------------------------------------------------------------------------
# Test: IP rate limiting on public admissions catalog (unauthenticated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.security
class TestPublicAdmissionsRateLimit:
    """IP rate limiting on the PUBLIC (unauthenticated) admissions catalog.

    Regression guard for the 2026-07 decorator-order fix: these 4 endpoints had
    ``@limiter.limit`` ABOVE ``@router.get`` so slowapi never wrapped the
    endpoint the router registered and the limit was SILENTLY unenforced (no
    ``SlowAPIMiddleware`` to compensate). A real 429 here proves BOTH correct
    order (wrapper actually invoked) AND runtime enforcement — stronger than a
    structural ``__wrapped__`` inspection, which cannot see either regression.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/api/public/admissions/programs",
            "/api/public/admissions/methods",
            "/api/public/admissions/documents",
            "/api/public/admissions/tuition",
        ],
    )
    async def test_blocks_after_threshold(
        self, rate_limited_client: AsyncClient, path: str
    ):
        """4th GET from the same IP must be 429 (fixture sets 3/minute).

        The limiter runs BEFORE the endpoint body, so the 4th request is 429
        regardless of what the catalog query returns; the first 3 only need to
        be non-429 (200 on an empty test DB, or any non-429 status)."""
        global _test_ip
        _test_ip = "203.0.113.7"

        for i in range(3):
            res = await rate_limited_client.get(path)
            assert res.status_code != 429, (
                f"{path}: request {i + 1}/3 should pass, got {res.status_code}"
            )

        res = await rate_limited_client.get(path)
        assert res.status_code == 429, (
            f"{path}: 4th request should be rate-limited (429), got "
            f"{res.status_code} — decorator order likely wrong (limit unenforced)."
        )
