# app/repositories/base.py
"""
✅ PHASE 2 - WEEK 1: Base Repository Pattern

Base repository providing common CRUD operations for all models.
Implements Repository Pattern to separate data access logic from business logic.

Benefits:
- Separation of concerns: Services don't know about SQL queries
- Testability: Easy to mock repositories
- Reusability: Common query patterns in one place
- Maintainability: Query optimization in single location
"""

from abc import ABC, abstractmethod
from typing import Any, Generic, List, Optional, Tuple, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(ABC, Generic[ModelType]):
    """
    Abstract base repository providing common CRUD operations.

    All concrete repositories should inherit from this class.
    """

    def __init__(self, db: AsyncSession, model: Type[ModelType]):
        """
        Initialize repository with database session and model.

        Args:
            db: SQLAlchemy async session
            model: SQLAlchemy model class
        """
        self.db = db
        self.model = model

    async def get_by_id(self, id: int) -> Optional[ModelType]:
        """
        Get a single record by ID.

        Args:
            id: Record ID

        Returns:
            Model instance or None if not found
        """
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalars().first()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[Any] = None
    ) -> List[ModelType]:
        """
        Get all records with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            order_by: SQLAlchemy order by clause (optional)

        Returns:
            List of model instances
        """
        query = select(self.model).offset(skip).limit(limit)

        if order_by is not None:
            query = query.order_by(order_by)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count(self, where_clause: Optional[Any] = None) -> int:
        """
        Count total records matching optional filter.

        Args:
            where_clause: SQLAlchemy where clause (optional)

        Returns:
            Total count
        """
        query = select(func.count()).select_from(self.model)

        if where_clause is not None:
            query = query.where(where_clause)

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def create(self, obj_in: dict) -> ModelType:
        """
        Create a new record.

        Args:
            obj_in: Dictionary of field values

        Returns:
            Created model instance
        """
        db_obj = self.model(**obj_in)
        self.db.add(db_obj)
        await self.db.flush()
        await self.db.refresh(db_obj)
        return db_obj

    async def update(self, db_obj: ModelType, obj_in: dict) -> ModelType:
        """
        Update an existing record.

        Args:
            db_obj: Existing model instance
            obj_in: Dictionary of fields to update

        Returns:
            Updated model instance
        """
        for field, value in obj_in.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        await self.db.flush()
        await self.db.refresh(db_obj)
        return db_obj

    async def delete(self, db_obj: ModelType) -> None:
        """
        Delete a record (hard delete).

        Args:
            db_obj: Model instance to delete
        """
        await self.db.delete(db_obj)
        await self.db.flush()

    async def soft_delete(self, db_obj: ModelType) -> ModelType:
        """
        Soft delete a record (set deleted_at timestamp).

        Args:
            db_obj: Model instance to soft delete

        Returns:
            Updated model instance

        Raises:
            AttributeError: If model doesn't have deleted_at field
        """
        if hasattr(db_obj, 'deleted_at'):
            from datetime import datetime, timezone
            db_obj.deleted_at = datetime.now(timezone.utc)
        elif hasattr(db_obj, 'is_active'):
            db_obj.is_active = False
        else:
            raise AttributeError(
                f"{self.model.__name__} doesn't support soft delete (no deleted_at or is_active field)"
            )

        await self.db.flush()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_with_relations(
        self,
        id: int,
        relations: List[str]
    ) -> Optional[ModelType]:
        """
        Get a record by ID with eager-loaded relationships.

        Args:
            id: Record ID
            relations: List of relationship names to load

        Returns:
            Model instance with loaded relations or None
        """
        query = select(self.model).where(self.model.id == id)

        # Add selectinload for each relation
        for relation in relations:
            if hasattr(self.model, relation):
                query = query.options(selectinload(getattr(self.model, relation)))

        result = await self.db.execute(query)
        return result.scalars().first()

    @abstractmethod
    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[ModelType]]:
        """
        Abstract method for filtered queries.

        Each repository must implement its own filtering logic.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            **filters: Model-specific filter parameters

        Returns:
            Tuple of (total_count, records)
        """
        pass
