# app/routers/document_groups.py
"""
Document Groups Router.

REST API endpoints for DocumentGroup management.

MASTER_ARCHITECTURE.md Compliance:
- No business logic in router
- All deps via Depends()
- response_model on every endpoint
- db.commit() in router, not service
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin_or_manager
from app.schemas.document_group import (
    DocumentGroupCreate,
    DocumentGroupUpdate,
    DocumentGroupResponse,
    DocumentGroupListResponse,
)
from app.services.document_group_service import DocumentGroupService
from app.repositories.document_group_repository import DocumentGroupRepository

router = APIRouter(prefix="/admission-config/document-groups", tags=["Document Groups"])


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================

@router.get("", response_model=DocumentGroupListResponse)
async def list_document_groups(
    offering_type_id: int = Query(..., description="Filter by offering type ID"),
    active_only: bool = Query(True, description="Only return active groups"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    List all document groups for an offering type.
    
    Requires: Admin or Manager role.
    """
    service = DocumentGroupService(db)
    groups = await service.list_by_offering_type(offering_type_id, active_only)
    
    items = [DocumentGroupResponse.model_validate(g) for g in groups]
    return DocumentGroupListResponse(total=len(items), items=items)


@router.get("/{group_id}", response_model=DocumentGroupResponse)
async def get_document_group(
    group_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Get document group by ID with items.
    
    Requires: Admin or Manager role.
    """
    service = DocumentGroupService(db)
    group = await service.get_group(group_id)
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocumentGroup with ID {group_id} not found"
        )
    
    return DocumentGroupResponse.model_validate(group)


@router.post("", response_model=DocumentGroupResponse, status_code=201)
async def create_document_group(
    data: DocumentGroupCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Create new document group.
    
    Requires: Admin or Manager role.
    
    Override Rule:
    - admission_method_id = NULL means shared (applies to all methods)
    - admission_method_id = X means override for that specific method
    """
    service = DocumentGroupService(db)
    group, callback = await service.create_group(data, current_user)
    await db.commit()
    await callback()
    
    # Reload with relationships
    repo = DocumentGroupRepository(db)
    group = await repo.get_by_id_with_items(group.id)
    
    return DocumentGroupResponse.model_validate(group)


@router.put("/{group_id}", response_model=DocumentGroupResponse)
async def update_document_group(
    group_id: int,
    data: DocumentGroupUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Update existing document group.
    
    Requires: Admin or Manager role.
    """
    repo = DocumentGroupRepository(db)
    group = await repo.get_by_id_with_items(group_id)
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocumentGroup with ID {group_id} not found"
        )
    
    service = DocumentGroupService(db)
    group, callback = await service.update_group(group, data, current_user)
    await db.commit()
    await callback()
    
    # Reload with relationships
    group = await repo.get_by_id_with_items(group.id)
    
    return DocumentGroupResponse.model_validate(group)


@router.delete("/{group_id}", status_code=204)
async def delete_document_group(
    group_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Delete document group.
    
    Requires: Admin or Manager role.
    """
    repo = DocumentGroupRepository(db)
    group = await repo.get_by_id_with_items(group_id)
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocumentGroup with ID {group_id} not found"
        )
    
    service = DocumentGroupService(db)
    success, callback = await service.delete_group(group, current_user)
    await db.commit()
    await callback()
    
    return None
