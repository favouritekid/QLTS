# app/repositories/login_history_repository.py
"""
✅ PATTERN A COMPLIANT - Login History Repository

Repository for LoginHistory model.
Handles all database access for login history.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.base import BaseRepository


class LoginHistoryRepository(BaseRepository[models.LoginHistory]):
    """Repository for LoginHistory model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.LoginHistory)

    async def get_by_user_id(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[int, List[models.LoginHistory]]:
        """Get paginated login history for a user."""
        # Count total
        count_query = select(func.count(self.model.id)).where(
            self.model.user_id == user_id
        )
        total = await self.db.scalar(count_query) or 0

        # Get records
        query = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(desc(self.model.login_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return total, list(result.scalars().all())

    async def get_recent_logins(
        self,
        user_id: int,
        days: int = 30,
    ) -> List[models.LoginHistory]:
        """Get login history within last N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = (
            select(self.model)
            .where(
                and_(
                    self.model.user_id == user_id,
                    self.model.login_at >= cutoff,
                )
            )
            .order_by(desc(self.model.login_at))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_suspicious_logins(
        self,
        user_id: int,
        pending_only: bool = True,
    ) -> List[models.LoginHistory]:
        """Get suspicious logins for a user."""
        filters = [
            self.model.user_id == user_id,
            or_(
                self.model.is_new_ip == True,
                self.model.is_new_device == True,
                self.model.is_new_location == True,
            ),
        ]
        
        if pending_only:
            filters.append(self.model.user_response.is_(None))

        query = (
            select(self.model)
            .where(and_(*filters))
            .order_by(desc(self.model.login_at))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_last_login(
        self,
        user_id: int,
    ) -> Optional[models.LoginHistory]:
        """Get most recent login for a user."""
        query = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(desc(self.model.login_at))
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def check_ip_seen_before(
        self,
        user_id: int,
        ip_address: str,
    ) -> bool:
        """
        Check if this IP address has been used before by this user.

        SECURITY FIX: Excludes logins marked 'secured' (user confirmed as
        attack) so the attacker's IP keeps triggering alerts on re-login
        after the victim clicks "Not Me".

        OPTION-B FIX (sl20260524): ``user_response != "secured"`` evaluates
        to NULL when ``user_response IS NULL`` (Postgres three-valued
        logic), and NULL is falsy in a WHERE — so pending (unresponded)
        rows were silently excluded from the "seen" history. We use
        ``is_distinct_from("secured")`` which is NULL-safe and matches
        both pending (NULL) and confirmed rows while still excluding
        secured.
        """
        if not ip_address:
            return True  # Unknown IP treated as "seen" (no flag)

        query = select(self.model.id).where(
            and_(
                self.model.user_id == user_id,
                self.model.ip_address == ip_address,
                # NULL-safe: matches NULL (pending) + 'confirmed', excludes 'secured'
                self.model.user_response.is_distinct_from("secured"),
            )
        ).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def check_device_seen_before(
        self,
        user_id: int,
        device_fingerprint: str,
    ) -> bool:
        """
        Check if this device has been used before by this user.

        OPTION-B FIX (sl20260524): query is now an exact-hash match on
        ``login_history.device_fingerprint`` (the canonical SHA-256 from
        the family + device_type + user_id + salt — see
        ``app.services.login_history_service.generate_device_fingerprint``).

        Pre-PR the signature was a ``device_info`` dict and the query
        compared the display-string columns (``browser`` / ``os`` /
        ``device_type``) for equality — that meant every browser/OS
        version bump broke the match. The canonical fingerprint baked in
        by sl20260524's backfill restores stability across version drift.

        Index: ``ix_login_history_user_fp_response`` on
        ``(user_id, device_fingerprint, user_response)`` powers this path.

        SECURITY FIX + NULL fix: same ``is_distinct_from("secured")``
        semantics as ``check_ip_seen_before`` — pending rows count as
        seen, secured rows do not.
        """
        if not device_fingerprint:
            return True

        query = select(self.model.id).where(
            and_(
                self.model.user_id == user_id,
                self.model.device_fingerprint == device_fingerprint,
                self.model.user_response.is_distinct_from("secured"),
            )
        ).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def check_country_seen_before(
        self,
        user_id: int,
        country: str,
    ) -> bool:
        """
        Check if user has logged in from this country before.

        See ``check_ip_seen_before`` for the NULL-safe predicate rationale.
        """
        if not country:
            return True

        query = select(self.model.id).where(
            and_(
                self.model.user_id == user_id,
                self.model.country == country,
                # NULL-safe: matches NULL (pending) + 'confirmed', excludes 'secured'
                self.model.user_response.is_distinct_from("secured"),
            )
        ).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def count_pending_suspicious(
        self,
        user_id: int,
    ) -> int:
        """Count this user's suspicious logins that are still pending review.

        Mirrors the ``get_suspicious_logins(pending_only=True)`` filter
        but returns a scalar — used by the ``/auth/login`` response to
        populate ``suspicious_login_count`` so the FE banner shows the
        real number instead of a hardcoded ``1``.

        "Suspicious" = ``is_new_ip OR is_new_device OR is_new_location``
        (matches ``LoginHistory.is_suspicious`` property). "Pending" =
        ``user_response IS NULL``.
        """
        query = select(func.count(self.model.id)).where(
            and_(
                self.model.user_id == user_id,
                or_(
                    self.model.is_new_ip == True,
                    self.model.is_new_device == True,
                    self.model.is_new_location == True,
                ),
                self.model.user_response.is_(None),
            )
        )
        return await self.db.scalar(query) or 0

    async def mark_as_confirmed(
        self,
        login_id: int,
    ) -> Optional[models.LoginHistory]:
        """Mark a suspicious login as confirmed by the user."""
        login = await self.get_by_id(login_id)
        if login:
            login.user_response = "confirmed"
            login.responded_at = datetime.now(timezone.utc)
            await self.db.flush()
            await self.db.refresh(login)
        return login

    async def mark_as_secured(
        self,
        login_id: int,
    ) -> Optional[models.LoginHistory]:
        """Mark that user secured their account after this suspicious login."""
        login = await self.get_by_id(login_id)
        if login:
            login.user_response = "secured"
            login.responded_at = datetime.now(timezone.utc)
            await self.db.flush()
            await self.db.refresh(login)
        return login

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters,
    ) -> Tuple[int, List[models.LoginHistory]]:
        """Get filtered login history with pagination."""
        user_id = filters.get("user_id")
        if user_id:
            return await self.get_by_user_id(user_id, skip, limit)
        
        # Admin view: all logins
        total = await self.count()
        query = (
            select(self.model)
            .order_by(desc(self.model.login_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return total, list(result.scalars().all())
