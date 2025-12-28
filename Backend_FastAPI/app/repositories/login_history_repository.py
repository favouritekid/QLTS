# app/repositories/login_history_repository.py
"""
✅ PATTERN A COMPLIANT - Login History Repository

Repository for LoginHistory model.
Handles all database access for login history.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, desc, func, select
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
            (
                self.model.is_new_ip == True
                | self.model.is_new_device == True
                | self.model.is_new_location == True
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
        
        SECURITY FIX: Excludes logins marked 'secured' (user confirmed as attack).
        This ensures attacker's IP triggers alerts on re-login after victim
        clicks 'Not Me'.
        """
        if not ip_address:
            return True  # Unknown IP treated as "seen" (no flag)
            
        query = select(self.model.id).where(
            and_(
                self.model.user_id == user_id,
                self.model.ip_address == ip_address,
                # SECURITY FIX: Don't count 'secured' logins as legitimate history
                self.model.user_response != "secured",
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
        Check if this device has been used before.
        Device fingerprint = hash of (browser + os + device_type).
        
        SECURITY FIX: Excludes logins marked 'secured' (user confirmed as attack).
        This ensures attacker's device triggers alerts on re-login after victim
        clicks 'Not Me'.
        """
        if not device_fingerprint:
            return True
            
        query = select(self.model.id).where(
            and_(
                self.model.user_id == user_id,
                self.model.browser == device_fingerprint.get("browser", ""),
                self.model.os == device_fingerprint.get("os", ""),
                self.model.device_type == device_fingerprint.get("device_type", ""),
                # SECURITY FIX: Don't count 'secured' logins as legitimate history
                self.model.user_response != "secured",
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
        
        SECURITY FIX: Excludes logins marked 'secured' (user confirmed as attack).
        This ensures attacker's country triggers alerts on re-login after victim
        clicks 'Not Me'.
        """
        if not country:
            return True
            
        query = select(self.model.id).where(
            and_(
                self.model.user_id == user_id,
                self.model.country == country,
                # SECURITY FIX: Don't count 'secured' logins as legitimate history
                self.model.user_response != "secured",
            )
        ).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

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
