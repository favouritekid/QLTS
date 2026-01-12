# app/services/document_group_service.py
"""
Document Group Service.

Business logic for Document Group management.
Follows MASTER_ARCHITECTURE.md:
- No HTTPException (domain exceptions only)
- No db.commit() (caller commits)
- Returns (result, callback) tuple
"""

from typing import Callable, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.admission_config import DocumentGroup
from app.repositories.document_group_repository import DocumentGroupRepository
from app.schemas.document_group import (
    DocumentGroupCreate,
    DocumentGroupUpdate,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    DuplicateResourceError,
)


async def _noop_callback():
    """No-op callback for operations without side effects."""
    pass


class DocumentGroupService:
    """
    Service for Document Group management.
    
    Handles business logic for:
    - DocumentGroup CRUD
    - Document item management
    - Override rule logic
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DocumentGroupRepository(db)

    # =========================================================================
    # CRUD OPERATIONS
    # =========================================================================

    async def create_group(
        self,
        data: DocumentGroupCreate,
        user: User,
    ) -> tuple[DocumentGroup, Callable[[], Any]]:
        """
        Create new DocumentGroup.
        
        Validation:
        - code must be unique
        - offering_type_id must exist (TODO: add validation)
        
        Returns:
            Tuple of (created group, callback)
        """
        # Check for duplicate code
        existing = await self.repo.get_by_code(data.code)
        if existing:
            raise DuplicateResourceError(f"DocumentGroup with code '{data.code}' already exists")

        # Create group
        group = await self.repo.create_group(
            offering_type_id=data.offering_type_id,
            code=data.code,
            name=data.name,
            description=data.description,
            admission_method_id=data.admission_method_id,
            is_active=data.is_active if data.is_active is not None else True,
        )

        # Add items if provided
        if data.items:
            for item_data in data.items:
                await self.repo.add_item_to_group(
                    group_id=group.id,
                    document_type_id=item_data.document_type_id,
                    is_mandatory=item_data.is_mandatory if item_data.is_mandatory is not None else True,
                    requires_upload=item_data.requires_upload if item_data.requires_upload is not None else True,
                    submission_format=item_data.submission_format,
                    display_order=item_data.display_order if item_data.display_order is not None else 0,
                )

        return group, _noop_callback

    async def update_group(
        self,
        group: DocumentGroup,
        data: DocumentGroupUpdate,
        user: User,
    ) -> tuple[DocumentGroup, Callable[[], Any]]:
        """
        Update existing DocumentGroup.
        
        Note: code and offering_type_id cannot be changed.
        
        Returns:
            Tuple of (updated group, callback)
        """
        # Build update dict
        updates = {}
        
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.is_active is not None:
            updates["is_active"] = data.is_active

        # Apply updates
        if updates:
            group = await self.repo.update_group(group, **updates)

        # Update items if provided (replace all)
        if data.items is not None:
            await self.repo.remove_all_items_from_group(group.id)
            for item_data in data.items:
                await self.repo.add_item_to_group(
                    group_id=group.id,
                    document_type_id=item_data.document_type_id,
                    is_mandatory=item_data.is_mandatory if item_data.is_mandatory is not None else True,
                    requires_upload=item_data.requires_upload if item_data.requires_upload is not None else True,
                    submission_format=item_data.submission_format,
                    display_order=item_data.display_order if item_data.display_order is not None else 0,
                )

        return group, _noop_callback

    async def delete_group(
        self,
        group: DocumentGroup,
        user: User,
    ) -> tuple[bool, Callable[[], Any]]:
        """
        Delete DocumentGroup.
        
        Returns:
            Tuple of (success, callback)
        """
        success = await self.repo.delete_group(group.id)
        return success, _noop_callback

    async def list_by_offering_type(
        self,
        offering_type_id: int,
        active_only: bool = True
    ) -> list[DocumentGroup]:
        """Get all groups for an offering type."""
        return await self.repo.list_by_offering_type(offering_type_id, active_only)

    async def get_group(
        self,
        group_id: int
    ) -> DocumentGroup | None:
        """Get group by ID with items loaded."""
        return await self.repo.get_by_id_with_items(group_id)
