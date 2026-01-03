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
