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
from sqlalchemy.orm import selectinload

from app.models import User
from app.models.admission_config import DocumentGroup
from app.models.admission_config.admission_path import AdmissionPath
from app.models.offering_academic_info import OfferingAcademicInfo
from app.models.program_offering import ProgramOffering
from app.repositories.document_group_repository import DocumentGroupRepository
from app.schemas.document_group import (
    DocumentGroupCreate,
    DocumentGroupUpdate,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    DuplicateResourceError,
    BusinessRuleViolation,
)


async def _noop_callback():
    """No-op callback for operations without side effects."""
    pass


async def _validate_path_invariant(
    db: AsyncSession,
    *,
    admission_path_id: int,
    offering_type_id: int,
    admission_method_id: int | None,
) -> None:
    """phase1_06 (#184 Wave 1 PR-1C') invariant — when a DocumentGroup
    references a path, its offering_type + method MUST be consistent
    with the path's. PLAN line 2671-2682.

    The 3-tier resolution rule chooses path-level groups BEFORE
    looking at offering_type or method, so an inconsistent group
    would silently leak into a profile that doesn't match. Cheaper
    to catch here than to silently corrupt resolution.

    Raises:
        ResourceNotFoundError: ``admission_path_id`` doesn't exist.
        BusinessRuleViolation: offering_type or method drift detected.
    """
    # Eager-load the chain path → academic_info → offering so the
    # offering_type comparison runs without a per-attribute round trip.
    from sqlalchemy import select

    query = (
        select(AdmissionPath)
        .where(AdmissionPath.id == admission_path_id)
        .options(
            selectinload(AdmissionPath.academic_info)
            .selectinload(OfferingAcademicInfo.offering)
        )
    )
    result = await db.execute(query)
    path = result.scalars().first()

    if path is None:
        raise ResourceNotFoundError(
            f"AdmissionPath id={admission_path_id} không tồn tại"
        )

    # offering_type comparison — path's offering_type comes from the
    # ProgramOffering linked through OfferingAcademicInfo.
    path_offering_type_id = (
        path.academic_info.offering.offering_type_id
        if path.academic_info and path.academic_info.offering
        else None
    )
    if path_offering_type_id != offering_type_id:
        raise BusinessRuleViolation(
            f"DocumentGroup.offering_type_id={offering_type_id} lệch path "
            f"(path offering_type_id={path_offering_type_id})"
        )

    # admission_method comparison — DocumentGroup may have method
    # NULL (= applies to all methods of the path) or a specific method
    # MATCHING the path's method. Anything else is drift.
    if (
        admission_method_id is not None
        and admission_method_id != path.admission_method_id
    ):
        raise BusinessRuleViolation(
            f"DocumentGroup.admission_method_id={admission_method_id} lệch "
            f"path (path method_id={path.admission_method_id})"
        )


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

        # phase1_06 invariant — when admin opts into path-level tier,
        # offering_type + method MUST be consistent with the path's.
        # Skip when path is NULL (legacy method/shared override).
        if data.admission_path_id is not None:
            await _validate_path_invariant(
                self.db,
                admission_path_id=data.admission_path_id,
                offering_type_id=data.offering_type_id,
                admission_method_id=data.admission_method_id,
            )

        # Create group
        group = await self.repo.create_group(
            offering_type_id=data.offering_type_id,
            code=data.code,
            name=data.name,
            description=data.description,
            admission_method_id=data.admission_method_id,
            admission_path_id=data.admission_path_id,
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
        # phase1_06 — distinguish "key absent" (= leave path
        # unchanged) from "key=null" (= clear path FK). Schema
        # ``model_dump(exclude_unset=True)`` is the canonical way;
        # use it once and bind into ``updates``.
        update_data = data.model_dump(exclude_unset=True)

        # Build update dict — only the explicitly-set keys flow through.
        updates = {}

        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.is_active is not None:
            updates["is_active"] = data.is_active

        # phase1_06 — admin re-targets group to a different path
        # (or clears with explicit ``null``). Validate invariant
        # against the EFFECTIVE state (new path id + existing
        # offering_type + admission_method since those are immutable
        # post-create per repo allowlist).
        if "admission_path_id" in update_data:
            new_path_id = update_data["admission_path_id"]
            updates["admission_path_id"] = new_path_id
            if new_path_id is not None:
                await _validate_path_invariant(
                    self.db,
                    admission_path_id=new_path_id,
                    offering_type_id=group.offering_type_id,
                    admission_method_id=group.admission_method_id,
                )

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
