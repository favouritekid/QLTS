# app/repositories/session_repository.py
"""
✅ PHASE 2: Session Repository

Repository pattern implementation for UserSession model.
Provides clean data access layer for session management operations.

Created as part of Auth Module Refactor to achieve Pattern A compliance:
Router → Service → Repository
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSession
from app.repositories.base import BaseRepository


class SessionRepository(BaseRepository[UserSession]):
    """
    Repository for UserSession model.

    Provides methods for:
    - Session lookup by JTI
    - Active session queries
    - Device-specific session management
    - Pessimistic locking for safe revocation
    """

    def __init__(self, db: AsyncSession):
        """Initialize repository with database session."""
        super().__init__(db, UserSession)

    async def get_by_jti(self, jti: str) -> Optional[UserSession]:
        """
        Find session by refresh token JTI.

        Args:
            jti: Refresh token JTI (unique identifier)

        Returns:
            UserSession if found, None otherwise
        """
        result = await self.db.execute(
            select(UserSession).where(UserSession.refresh_jti == jti)
        )
        return result.scalar_one_or_none()

    async def get_active_by_user(self, user_id: int) -> List[UserSession]:
        """
        Get all active sessions for a user.

        Active = not revoked AND not expired.

        Args:
            user_id: User ID

        Returns:
            List of active UserSession instances
        """
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(UserSession)
            .where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
            )
            .order_by(UserSession.last_activity_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_on_device(
        self,
        user_id: int,
        device_type: str,
        browser: str,
        os: str
    ) -> List[UserSession]:
        """
        Find active sessions on the same device.

        Used to revoke old sessions when user logs in again on same device.
        Prevents session leak (zombie sessions).

        Args:
            user_id: User ID
            device_type: Device type (mobile, desktop, tablet)
            browser: Browser name and version
            os: Operating system name and version

        Returns:
            List of active sessions matching device criteria
        """
        result = await self.db.execute(
            select(UserSession).where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.device_type == device_type,
                    UserSession.browser == browser,
                    UserSession.os == os,
                    UserSession.revoked_at.is_(None),
                )
            )
        )
        return list(result.scalars().all())

    async def get_for_update(
        self,
        session_id: int,
        user_id: int
    ) -> Optional[UserSession]:
        """
        Get session with pessimistic lock for safe update.

        Uses SELECT ... FOR UPDATE to prevent concurrent modifications.
        Essential for revocation to prevent race conditions.

        Args:
            session_id: Session ID to lock
            user_id: User ID for ownership verification

        Returns:
            Locked UserSession if found and owned by user, None otherwise
        """
        result = await self.db.execute(
            select(UserSession)
            .where(
                and_(
                    UserSession.id == session_id,
                    UserSession.user_id == user_id,
                )
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_refresh_jti_and_user(
        self,
        jti: str,
        user_id: int
    ) -> Optional[UserSession]:
        """
        Find active session by refresh JTI and user ID.

        Used for session validation in deps.py fallback.

        Args:
            jti: Refresh token JTI
            user_id: User ID for verification

        Returns:
            Active UserSession if found and valid, None otherwise
        """
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(UserSession).where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.refresh_jti == jti,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_ip(
        self,
        user_id: int,
        ip_address: str
    ) -> Optional[UserSession]:
        """
        Check if IP address was used before by this user.

        Used for anomaly detection (new IP login alerts).

        Args:
            user_id: User ID
            ip_address: IP address to check

        Returns:
            UserSession if IP was used before, None if new IP
        """
        result = await self.db.execute(
            select(UserSession)
            .where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.ip_address == ip_address,
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> tuple[int, List[UserSession]]:
        """
        Get filtered sessions with pagination.

        Required by BaseRepository abstract method.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            **filters: Optional filters (user_id, is_active, etc.)

        Returns:
            Tuple of (total_count, sessions)
        """
        conditions = []

        if "user_id" in filters:
            conditions.append(UserSession.user_id == filters["user_id"])

        if filters.get("is_active"):
            now = datetime.now(timezone.utc)
            conditions.append(UserSession.revoked_at.is_(None))
            conditions.append(UserSession.expires_at > now)

        # Build query
        query = select(UserSession)
        if conditions:
            query = query.where(and_(*conditions))

        # Get total count
        total = await self.count(and_(*conditions) if conditions else None)

        # Get paginated results
        query = query.offset(skip).limit(limit).order_by(
            UserSession.created_at.desc()
        )
        result = await self.db.execute(query)
        sessions = list(result.scalars().all())

        return total, sessions
