# app/repositories/document_group_repository.py
"""
Document Group Repository.

Data access for DocumentGroup entities with:
- Eager loading of relationships (selectinload)
- No business logic (pure data access)
"""

from typing import List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.admission_config import DocumentGroup, DocumentGroupItem
from app.models.config import ConfigDocumentType
from app.repositories.base import BaseRepository


class DocumentGroupRepository(BaseRepository[DocumentGroup]):
    """Repository for DocumentGroup entities."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, DocumentGroup)

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_by_id_with_items(
        self,
        group_id: int
    ) -> Optional[DocumentGroup]:
        """Get group by ID with items and document types loaded."""
        query = (
            select(DocumentGroup)
            .where(DocumentGroup.id == group_id)
            .options(
                selectinload(DocumentGroup.offering_type),
                selectinload(DocumentGroup.admission_method),
                selectinload(DocumentGroup.items)
                .selectinload(DocumentGroupItem.document_type),
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_code(self, code: str) -> Optional[DocumentGroup]:
        """Get group by code."""
        result = await self.db.execute(
            select(DocumentGroup).where(DocumentGroup.code == code)
        )
        return result.scalars().first()

    async def list_by_offering_type(
        self,
        offering_type_id: int,
        active_only: bool = True
    ) -> List[DocumentGroup]:
        """
        Get all document groups for an offering type.
        
        Returns both shared (method_id=NULL) and method-specific groups.
        """
        query = (
            select(DocumentGroup)
            .where(DocumentGroup.offering_type_id == offering_type_id)
            .options(
                selectinload(DocumentGroup.admission_method),
                selectinload(DocumentGroup.items)
                .selectinload(DocumentGroupItem.document_type),
            )
            .order_by(DocumentGroup.code)
        )
        
        if active_only:
            query = query.where(DocumentGroup.is_active == True)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_shared_groups(
        self,
        offering_type_id: int
    ) -> List[DocumentGroup]:
        """Get shared groups (admission_method_id = NULL)."""
        query = (
            select(DocumentGroup)
            .where(
                DocumentGroup.offering_type_id == offering_type_id,
                DocumentGroup.admission_method_id.is_(None),
                DocumentGroup.is_active == True,
            )
            .options(
                selectinload(DocumentGroup.items)
                .selectinload(DocumentGroupItem.document_type),
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_method_specific_group(
        self,
        offering_type_id: int,
        method_id: int
    ) -> Optional[DocumentGroup]:
        """Get method-specific override group."""
        query = (
            select(DocumentGroup)
            .where(
                DocumentGroup.offering_type_id == offering_type_id,
                DocumentGroup.admission_method_id == method_id,
                DocumentGroup.is_active == True,
            )
            .options(
                selectinload(DocumentGroup.items)
                .selectinload(DocumentGroupItem.document_type),
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    # =========================================================================
    # WRITE OPERATIONS
    # =========================================================================

    async def create_group(
        self,
        offering_type_id: int,
        code: str,
        name: str,
        description: str | None = None,
        admission_method_id: int | None = None,
        is_active: bool = True,
    ) -> DocumentGroup:
        """Create new document group."""
        group = DocumentGroup(
            offering_type_id=offering_type_id,
            admission_method_id=admission_method_id,
            code=code,
            name=name,
            description=description,
            is_active=is_active,
        )
        self.db.add(group)
        await self.db.flush()
        return group

    async def update_group(
        self,
        group: DocumentGroup,
        **updates
    ) -> DocumentGroup:
        """Update existing document group."""
        allowed_fields = {"name", "description", "is_active"}
        
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(group, field, value)
        
        await self.db.flush()
        return group

    async def delete_group(self, group_id: int) -> bool:
        """Delete document group by ID."""
        group = await self.db.get(DocumentGroup, group_id)
        if not group:
            return False
        
        await self.db.delete(group)
        await self.db.flush()
        return True

    async def add_item_to_group(
        self,
        group_id: int,
        document_type_id: int,
        is_mandatory: bool = True,
        requires_upload: bool = True,
        submission_format: str | None = None,
        display_order: int = 0,
    ) -> DocumentGroupItem:
        """Add document item to group."""
        item = DocumentGroupItem(
            group_id=group_id,
            document_type_id=document_type_id,
            is_mandatory=is_mandatory,
            requires_upload=requires_upload,
            submission_format=submission_format,
            display_order=display_order,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def remove_all_items_from_group(self, group_id: int) -> int:
        """Remove all items from a group."""
        stmt = delete(DocumentGroupItem).where(
            DocumentGroupItem.group_id == group_id
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount
