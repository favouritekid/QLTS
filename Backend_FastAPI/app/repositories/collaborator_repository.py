# app/repositories/collaborator_repository.py
"""
Collaborator Repository - Data access layer for Collaborator model.

All query methods filter `deleted_at IS NULL` by default (consistent with Lead repo pattern).
"""
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


ALLOWED_SORT_COLUMNS = {"created_at", "updated_at", "full_name", "code", "status", "phone"}


class CollaboratorRepository(BaseRepository[models.Collaborator]):
    """Repository for Collaborator model operations."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.Collaborator)

    async def get_by_id(self, collaborator_id: int) -> Optional[models.Collaborator]:
        """Get collaborator by ID with relationships, excluding soft-deleted."""
        result = await self.db.execute(
            select(models.Collaborator)
            .options(
                selectinload(models.Collaborator.unit),
                selectinload(models.Collaborator.managed_by_officer),
                selectinload(models.Collaborator.user),
                selectinload(models.Collaborator.approved_by),
            )
            .where(
                models.Collaborator.id == collaborator_id,
                models.Collaborator.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def get_by_code(self, code: str) -> Optional[models.Collaborator]:
        """Get collaborator by code."""
        result = await self.db.execute(
            select(models.Collaborator).where(
                models.Collaborator.code == code,
                models.Collaborator.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def get_by_user_id(self, user_id: int) -> Optional[models.Collaborator]:
        """Get collaborator linked to a user."""
        result = await self.db.execute(
            select(models.Collaborator)
            .options(
                selectinload(models.Collaborator.unit),
                selectinload(models.Collaborator.managed_by_officer),
            )
            .where(
                models.Collaborator.user_id == user_id,
                models.Collaborator.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def get_by_phone(self, phone: str) -> Optional[models.Collaborator]:
        """Get collaborator by phone number."""
        result = await self.db.execute(
            select(models.Collaborator).where(
                models.Collaborator.phone == phone,
                models.Collaborator.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def get_by_email(self, email: str) -> Optional[models.Collaborator]:
        """Get collaborator by email (soft-delete aware)."""
        result = await self.db.execute(
            select(models.Collaborator).where(
                models.Collaborator.email == email,
                models.Collaborator.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def check_phone_unique(
        self, phone: str, exclude_id: Optional[int] = None
    ) -> bool:
        """Check if phone is unique among active collaborators. Returns True if unique."""
        query = select(func.count(models.Collaborator.id)).where(
            models.Collaborator.phone == phone,
            models.Collaborator.deleted_at.is_(None),
        )
        if exclude_id:
            query = query.where(models.Collaborator.id != exclude_id)
        result = await self.db.execute(query)
        count = result.scalar_one_or_none() or 0
        return count == 0

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 10,
        status: Optional[str] = None,
        unit_id: Optional[int] = None,
        managed_by_officer_id: Optional[int] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> Tuple[int, List[models.Collaborator]]:
        """Get filtered list of collaborators with pagination."""
        base_query = select(models.Collaborator)
        count_query = select(func.count(models.Collaborator.id))

        filters = [models.Collaborator.deleted_at.is_(None)]

        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if statuses:
                filters.append(models.Collaborator.status.in_(statuses))

        if unit_id is not None:
            filters.append(models.Collaborator.unit_id == unit_id)

        if managed_by_officer_id is not None:
            filters.append(models.Collaborator.managed_by_officer_id == managed_by_officer_id)

        if search:
            normalized_search = unicodedata.normalize('NFC', search.strip())
            search_term = f"%{normalized_search}%"
            filters.append(
                or_(
                    models.Collaborator.full_name.ilike(search_term),
                    models.Collaborator.phone.ilike(search_term),
                    models.Collaborator.email.ilike(search_term),
                    models.Collaborator.code.ilike(search_term),
                )
            )

        base_query = base_query.where(*filters)
        count_query = count_query.where(*filters)

        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar_one_or_none() or 0

        if total_count == 0:
            return 0, []

        if sort_by not in ALLOWED_SORT_COLUMNS:
            sort_by = "created_at"
        sort_column = getattr(models.Collaborator, sort_by, models.Collaborator.created_at)
        if order.lower() == "desc":
            base_query = base_query.order_by(sort_column.desc(), models.Collaborator.id.desc())
        else:
            base_query = base_query.order_by(sort_column.asc(), models.Collaborator.id.desc())

        base_query = (
            base_query.options(
                selectinload(models.Collaborator.unit),
                selectinload(models.Collaborator.managed_by_officer),
            )
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(base_query)
        collaborators = list(result.scalars().all())

        return total_count, collaborators

    async def generate_next_code(self, year: int) -> str:
        """
        Generate next collaborator code: CTV-YYYY-XXXX using PostgreSQL sequence.

        Uses nextval() for race-condition-free code generation.
        """
        prefix = f"CTV-{year}-"
        result = await self.db.execute(text("SELECT nextval('collaborator_code_seq')"))
        next_seq = result.scalar_one()
        return f"{prefix}{next_seq:04d}"
