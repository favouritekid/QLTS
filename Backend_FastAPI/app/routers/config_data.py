from typing import List

import structlog
from fastapi import APIRouter, Depends, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.services import config_service
from app.core import deps

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Config Data"])

@router.get(
    "/config/categories",
    response_model=List[schemas.SystemCategory],
)
async def get_system_categories(
    type: str,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user), # Any authenticated user
):
    """
    Get system categories by type (e.g., 'ethnicity', 'religion').
    """
    return await config_service.get_system_categories(db, type=type)

@router.post(
    "/config/categories/import",
    status_code=status.HTTP_200_OK,
)
async def import_system_categories(
    type: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
    # Only Admin/Manager should import
    # Only Admin/Manager should import
    current_user: models.User = deps.AdminManagerRequired, 
):
    """
    Import categories from Excel.
    """
    content = await file.read()
    result = await config_service.import_system_categories(db, type_key=type, file_content=content)
    return {
        "message": "Import successful",
        "details": result
    }


# =============================================================================
# SUBJECT GROUPS (Phase 6: Dynamic Admission Scoring)
# =============================================================================

@router.get(
    "/config/subject-groups",
    response_model=List[schemas.SubjectGroupResponse],
)
async def get_subject_groups(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Get all active subject groups for admission scoring.
    
    Returns list of subject groups (e.g., A00, D01) with their details.
    Used by frontend to populate dropdowns in admission forms.
    """
    return await config_service.get_subject_groups(db)


@router.get(
    "/config/subject-groups/{code}",
    response_model=schemas.SubjectGroupResponse,
)
async def get_subject_group_by_code(
    code: str,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Get a specific subject group by code.
    
    Example: GET /config/subject-groups/A00
    """
    from fastapi import HTTPException
    
    result = await config_service.get_subject_group_by_code(db, code=code)
    if not result:
        raise HTTPException(status_code=404, detail=f"Subject group '{code}' not found")
    return result

