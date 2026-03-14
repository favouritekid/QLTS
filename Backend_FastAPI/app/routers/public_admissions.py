"""
Public admissions endpoints for the external recruitment site.

No authentication is required. Responses are intentionally scoped to
published/active data only and safe for cache-friendly public consumption.
"""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.rate_limits import RateLimits, limiter
from app.schemas.public_admissions import (
    PublicAdmissionsDocumentsResponse,
    PublicAdmissionsMethodsResponse,
    PublicAdmissionsProgramsResponse,
    PublicAdmissionsTuitionResponse,
)
from app.services import public_admissions_service

router = APIRouter(prefix="/api/public/admissions", tags=["Public Admissions"])


def _set_public_cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=300"


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/programs", response_model=PublicAdmissionsProgramsResponse)
async def get_public_programs_catalog(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "nganh hoc" page.

    Exposes:
    - active major programs
    - active offerings
    - latest published academic info per offering
    - public admission methods per offering
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_programs_catalog(db)


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/methods", response_model=PublicAdmissionsMethodsResponse)
async def get_public_methods_catalog(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "phuong thuc" page.

    Contract is grouped around:
    - admission methods actually used by public active paths
    - subject groups referenced by those paths
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_methods_catalog(db)


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/documents", response_model=PublicAdmissionsDocumentsResponse)
async def get_public_documents_catalog(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "ho so" page.

    Contract is grouped around:
    - offering-type level shared document checklists
    - method-specific overrides actually used by public paths
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_documents_catalog(db)


@limiter.limit(RateLimits.PUBLIC_READ)
@router.get("/tuition", response_model=PublicAdmissionsTuitionResponse)
async def get_public_tuition_catalog(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public catalog for the "hoc phi - hoc bong" page.

    Contract is grouped around:
    - latest published tuition data per public offering
    - tuition ranges by degree level
    - active tuition discount policies referenced by published offerings
    """
    _set_public_cache_headers(response)
    return await public_admissions_service.get_public_tuition_catalog(db)
