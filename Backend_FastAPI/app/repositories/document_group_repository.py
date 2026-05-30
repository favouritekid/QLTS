# app/repositories/document_group_repository.py
"""
Document Group Repository.

Data access for DocumentGroup entities with:
- Eager loading of relationships (selectinload)
- No business logic (pure data access)
"""

from typing import List, Optional, Tuple
from sqlalchemy import select, delete, func
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
        """Get group by ID with items and document types loaded.

        ``populate_existing`` (feat/document-group-audience-merge): upsert
        làm bulk DELETE items + add → object trong identity map còn giữ
        collection ``.items`` CŨ (bulk delete KHÔNG sync ORM). Refetch phải
        OVERWRITE state cũ bằng DB truth, nếu không response trả item stale
        (bug pre-existing: upsert refetch hiện old+new).
        """
        query = (
            select(DocumentGroup)
            .where(DocumentGroup.id == group_id)
            .options(
                selectinload(DocumentGroup.offering_type),
                selectinload(DocumentGroup.admission_method),
                selectinload(DocumentGroup.items)
                .selectinload(DocumentGroupItem.document_type),
            )
            .execution_options(populate_existing=True)
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
            # Deterministic order (feat/document-group-audience-merge config
            # panel): sau ĐỢT B mỗi offering_type có nhiều shared group (NỀN +
            # lớp audience). Resolve merge order-independent, nhưng config
            # lookup/list cần thứ tự ổn định — id ASC ⇒ group NỀN (tạo trước)
            # luôn đứng đầu. KHÔNG đổi tập trả về (resolve giữ nguyên).
            .order_by(DocumentGroup.id)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_shared_group_by_audience(
        self,
        offering_type_id: int,
        audience: Optional[str],
    ) -> Optional[DocumentGroup]:
        """Lookup CHÍNH XÁC 1 shared group theo (offering_type, audience).

        feat/document-group-audience-merge §10.8 (fix R10 ``groups[0]`` +
        G4 NỀN-theo-code). Tier shared = ``admission_method_id`` +
        ``admission_path_id`` đều NULL.

        - ``audience=None`` → group NỀN (``applicable_audience`` NULL/rỗng).
          G4: match THEO ``(ot, audience IS NULL)``, KHÔNG theo code (seed dùng
          ``HS_CHINH_QUY`` còn upsert sinh ``SHARED_DOC_OT_{id}`` → tránh tạo
          2 NỀN/ot).
        - ``audience=<X>`` → group có X trong ``applicable_audience``.

        Filter trong Python trên ``get_shared_groups`` (≤6 group/ot, low-freq
        config) → tránh SQL enum-array ``&&`` + tự lọc ``path IS NULL`` mà
        KHÔNG đụng query resolve. Deterministic nhờ ORDER BY id.
        """
        groups = await self.get_shared_groups(offering_type_id)
        for group in groups:
            if group.admission_path_id is not None:
                continue  # path-override KHÔNG phải tier shared thuần
            aud = group.applicable_audience
            if audience is None:
                if not aud:  # NULL hoặc [] = lớp NỀN
                    return group
            elif aud and audience in aud:
                return group
        return None

    async def get_offering_type_code(
        self,
        offering_type_id: int,
    ) -> Optional[str]:
        """Lấy ``code`` của offering type (cho preview chiều VLVH §5b)."""
        from app.models.config import ConfigOfferingType

        result = await self.db.execute(
            select(ConfigOfferingType.code).where(
                ConfigOfferingType.id == offering_type_id
            )
        )
        return result.scalar_one_or_none()

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
        admission_path_id: int | None = None,
        is_active: bool = True,
        applicable_audience: list[str] | None = None,
    ) -> DocumentGroup:
        """Create new document group.

        ``applicable_audience`` (feat/document-group-audience-merge): NULL = lớp
        NỀN tier shared; ``[..]`` = lớp theo đối tượng/trình độ.
        """
        group = DocumentGroup(
            offering_type_id=offering_type_id,
            admission_method_id=admission_method_id,
            admission_path_id=admission_path_id,
            code=code,
            name=name,
            description=description,
            is_active=is_active,
            applicable_audience=applicable_audience,
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
        # phase1_06 (#184 Wave 1 PR-1C') — admission_path_id editable
        # so admin can re-target a group between path / method / shared
        # tiers. Service layer is responsible for the invariant check
        # before this method runs.
        allowed_fields = {"name", "description", "is_active", "admission_path_id"}

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

    # =========================================================================
    # FILTERED QUERIES (Required by BaseRepository)
    # =========================================================================

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[DocumentGroup]]:
        """
        Get filtered document groups with pagination.

        Filters:
            - offering_type_id: int
            - admission_method_id: int (use None for shared groups)
            - is_active: bool
        """
        query = select(DocumentGroup)
        count_query = select(func.count()).select_from(DocumentGroup)

        # Apply filters
        if filters.get("offering_type_id") is not None:
            query = query.where(
                DocumentGroup.offering_type_id == filters["offering_type_id"]
            )
            count_query = count_query.where(
                DocumentGroup.offering_type_id == filters["offering_type_id"]
            )

        if "admission_method_id" in filters:
            method_id = filters["admission_method_id"]
            if method_id is None:
                query = query.where(DocumentGroup.admission_method_id.is_(None))
                count_query = count_query.where(DocumentGroup.admission_method_id.is_(None))
            else:
                query = query.where(DocumentGroup.admission_method_id == method_id)
                count_query = count_query.where(DocumentGroup.admission_method_id == method_id)

        if filters.get("is_active") is not None:
            query = query.where(DocumentGroup.is_active == filters["is_active"])
            count_query = count_query.where(DocumentGroup.is_active == filters["is_active"])

        # Add eager loading
        query = query.options(
            selectinload(DocumentGroup.offering_type),
            selectinload(DocumentGroup.admission_method),
            selectinload(DocumentGroup.items)
            .selectinload(DocumentGroupItem.document_type),
        )

        # Pagination and ordering
        query = query.offset(skip).limit(limit).order_by(
            DocumentGroup.code
        )

        # Execute
        total = await self.db.execute(count_query)
        result = await self.db.execute(query)

        return (total.scalar() or 0, list(result.scalars().all()))
