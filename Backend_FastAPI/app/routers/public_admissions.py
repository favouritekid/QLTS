"""
Public admissions endpoints for the external recruitment site.

No authentication is required. Responses are intentionally scoped to
published/active data only and safe for cache-friendly public consumption.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.rate_limits import RateLimits, limiter
from app.schemas.public_admissions import (
    PublicAdmissionsAudience,
    PublicAdmissionsDocumentsResponse,
    PublicAdmissionsMethodsResponse,
    PublicAdmissionsProgramsResponse,
    PublicAdmissionsTuitionResponse,
)
from app.services import public_admissions_service

router = APIRouter(prefix="/api/public/admissions", tags=["Public Admissions"])


def _set_public_cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=300"


# phase1_03 (#184 Wave 6 PR-17 Phase 1 portion) — audience query
# narrows paths via JSONB containment on AdmissionPath.applicable_to.
# Phase 2 portion adds an admission_round filter (paired với
# phase2_01/phase2_02). Until then, audience is the only public
# narrowing knob beyond the always-on status=active+visibility=public
# pair.
_AUDIENCE_QUERY = Query(
    None,
    description=(
        "Optional audience filter. When set, narrows the returned paths to "
        "those whose applicable_to ARRAY contains the value (NULL "
        "applicable_to is preserved as legacy / applies to every audience)."
    ),
)


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/programs", response_model=PublicAdmissionsProgramsResponse)
async def get_public_programs_catalog(
    request: Request,
    response: Response,
    audience: Optional[PublicAdmissionsAudience] = _AUDIENCE_QUERY,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "nganh hoc" page.

    Exposes:
    - active major programs
    - active offerings
    - latest published academic info per offering
    - public admission methods per offering (narrowed by ``audience``
      when provided)
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_programs_catalog(
        db, audience=audience
    )


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/methods", response_model=PublicAdmissionsMethodsResponse)
async def get_public_methods_catalog(
    request: Request,
    response: Response,
    audience: Optional[PublicAdmissionsAudience] = _AUDIENCE_QUERY,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "phuong thuc" page.

    Contract is grouped around:
    - admission methods actually used by public active paths
    - subject groups referenced by those paths

    The ``audience`` query narrows paths via applicable_to containment.
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_methods_catalog(
        db, audience=audience
    )


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/documents", response_model=PublicAdmissionsDocumentsResponse)
async def get_public_documents_catalog(
    request: Request,
    response: Response,
    audience: Optional[PublicAdmissionsAudience] = _AUDIENCE_QUERY,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "ho so" page.

    Contract is grouped around:
    - offering-type level shared document checklists
    - method-specific overrides actually used by public paths

    Document resolution follows the 3-tier rule (path → method →
    shared) per phase1_06 / Wave 1 PR-1C'; the response source field
    surfaces which tier each document set comes from. ``audience``
    narrows paths before resolution.
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_documents_catalog(
        db, audience=audience
    )


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/tuition", response_model=PublicAdmissionsTuitionResponse)
async def get_public_tuition_catalog(
    request: Request,
    response: Response,
    audience: Optional[PublicAdmissionsAudience] = _AUDIENCE_QUERY,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "hoc phi - hoc bong" page.

    Contract is grouped around:
    - latest published tuition data per public offering
    - tuition ranges by degree level
    - active tuition discount policies referenced by published offerings

    ``audience`` is accepted for API uniformity. Tuition data is
    offering-keyed (not path-keyed), so the parameter is currently a
    no-op here; Phase 2 storefront PR will narrow offerings via
    round+audience joins.
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_tuition_catalog(
        db, audience=audience
    )
