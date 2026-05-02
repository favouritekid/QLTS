"""Admission Freeze Middleware (T0-2 cold-cutover prerequisite).

When ``settings.ADMISSION_FROZEN`` is True, this middleware rejects mutating
HTTP methods (POST/PUT/PATCH/DELETE) on the admission API path prefixes with
503 Service Unavailable. Read methods (GET/HEAD/OPTIONS) pass through so
officers can still inspect existing data during the maintenance window.

Defense-in-depth pair with the Nginx admission block (T0-3) shipped later:
Nginx is the edge layer; this middleware is the application-level fallback
for traffic that bypasses Nginx (internal Docker, healthchecks, smoke tests).

Reload semantics: ``Settings`` is loaded once at module import
(``app/config.py``). Flipping ``ADMISSION_FROZEN`` requires
``docker compose restart backend`` — there is no hot-reload mechanism.
See ``Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`` §6.1.
"""

from typing import Final, Iterable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

# Verified against Backend_FastAPI/app/routers/{admissions,admission_config,
# admission_paths,public_admissions}.py at branch feat/admission-full-cutover
# HEAD 2c57e5d6: 4 router files share 3 distinct prefixes (admission_config.py
# and admission_paths.py both register under /api/admission-config).
FROZEN_PREFIXES: Final[tuple[str, ...]] = (
    "/api/admissions",
    "/api/admission-config",
    "/api/public/admissions",
)

FROZEN_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AdmissionFreezeMiddleware(BaseHTTPMiddleware):
    """Block admission writes with 503 while ``settings.ADMISSION_FROZEN`` is True."""

    def __init__(self, app, *, prefixes: Iterable[str] = FROZEN_PREFIXES) -> None:
        super().__init__(app)
        self._prefixes: tuple[str, ...] = tuple(prefixes)

    async def dispatch(self, request: Request, call_next):
        if settings.ADMISSION_FROZEN and request.method in FROZEN_METHODS:
            path = request.url.path
            matched = next(
                (prefix for prefix in self._prefixes if _path_under(path, prefix)),
                None,
            )
            if matched is not None:
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "detail": (
                            "Admission intake is frozen for maintenance. "
                            "Please retry after the maintenance window completes."
                        ),
                        "code": "ADMISSION_FROZEN",
                        "frozen_prefix": matched,
                    },
                )
        return await call_next(request)


def _path_under(path: str, prefix: str) -> bool:
    # Path-segment match so `/api/admissionsfoo` does not match `/api/admissions`.
    return path == prefix or path.startswith(prefix + "/")
