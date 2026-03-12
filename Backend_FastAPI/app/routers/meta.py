# app/routers/meta.py
"""
Public metadata endpoints — no auth required, cache-friendly.

Follows collaborators.public_router pattern (no admin router).
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.kpi_catalog import get_catalog_api_response

router = APIRouter(prefix="/api/meta", tags=["Public Metadata"])


@router.get("/kpi-catalog")
async def get_kpi_catalog():
    """Return canonical KPI metadata. No auth required. Cache-friendly."""
    data = get_catalog_api_response()
    return JSONResponse(
        content=data,
        headers={"Cache-Control": "public, max-age=86400"},
    )
