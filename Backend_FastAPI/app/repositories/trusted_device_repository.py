# app/repositories/trusted_device_repository.py
"""
Repository for TrustedDevice model.

Provides data access methods for managing trusted devices,
following the Pattern A architecture (Router → Service → Repository).
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from .base import BaseRepository


class TrustedDeviceRepository(BaseRepository[models.TrustedDevice]):
    """Repository for TrustedDevice model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.TrustedDevice)

    async def get_by_user_id(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[int, List[models.TrustedDevice]]:
        """
        Get paginated trusted devices for a user.
        
        Returns:
            Tuple of (total_count, list of devices)
        """
        # Count total
        count_query = select(func.count(self.model.id)).where(
            self.model.user_id == user_id
        )
        total = await self.db.scalar(count_query) or 0

        # Get devices
        query = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.last_used_at.desc().nullslast())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        devices = list(result.scalars().all())

        return total, devices

    async def get_by_fingerprint(
        self,
        user_id: int,
        device_fingerprint: str,
    ) -> Optional[models.TrustedDevice]:
        """
        Get a trusted device by user and fingerprint.
        
        Returns:
            TrustedDevice if found, None otherwise
        """
        query = select(self.model).where(
            and_(
                self.model.user_id == user_id,
                self.model.device_fingerprint == device_fingerprint
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def is_device_trusted(
        self,
        user_id: int,
        device_fingerprint: str,
    ) -> bool:
        """
        Check if a device is trusted for a user.
        
        Returns:
            True if device is trusted, False otherwise
        """
        query = select(func.count(self.model.id)).where(
            and_(
                self.model.user_id == user_id,
                self.model.device_fingerprint == device_fingerprint
            )
        )
        count = await self.db.scalar(query)
        return (count or 0) > 0

    async def trust_device(
        self,
        user_id: int,
        device_fingerprint: str,
        name: Optional[str] = None,
        browser: Optional[str] = None,
        os: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> models.TrustedDevice:
        """
        Add a device to the trusted list.
        
        If the device already exists, updates the trust timestamp.
        
        Returns:
            The created or updated TrustedDevice
        """
        existing = await self.get_by_fingerprint(user_id, device_fingerprint)
        
        if existing:
            # Update existing trust
            existing.trusted_at = datetime.now(timezone.utc)
            existing.last_used_at = datetime.now(timezone.utc)
            if name:
                existing.name = name
            if ip_address:
                existing.trusted_from_ip = ip_address
            return existing
        
        # Create new trusted device
        now = datetime.now(timezone.utc)
        device = models.TrustedDevice(
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            name=name,
            browser=browser,
            os=os,
            first_seen_at=now,
            trusted_at=now,
            last_used_at=now,
            trusted_from_ip=ip_address,
        )
        self.db.add(device)
        return device

    async def update_last_used(
        self,
        user_id: int,
        device_fingerprint: str,
    ) -> Optional[models.TrustedDevice]:
        """
        Update the last_used_at timestamp for a trusted device.
        
        Returns:
            Updated TrustedDevice if found, None otherwise
        """
        device = await self.get_by_fingerprint(user_id, device_fingerprint)
        if device:
            device.last_used_at = datetime.now(timezone.utc)
        return device

    async def remove_device(
        self,
        user_id: int,
        device_id: int,
    ) -> bool:
        """
        Remove a device from the trusted list.
        
        Returns:
            True if device was removed, False if not found
        """
        query = delete(self.model).where(
            and_(
                self.model.user_id == user_id,
                self.model.id == device_id
            )
        )
        result = await self.db.execute(query)
        return result.rowcount > 0

    async def remove_all_devices(self, user_id: int) -> int:
        """
        Remove all trusted devices for a user (e.g., when securing account).
        
        Returns:
            Number of devices removed
        """
        query = delete(self.model).where(self.model.user_id == user_id)
        result = await self.db.execute(query)
        return result.rowcount

    async def count_by_user(self, user_id: int) -> int:
        """
        Get the total count of trusted devices for a user.
        
        Returns:
            Count of trusted devices
        """
        query = select(func.count(self.model.id)).where(
            self.model.user_id == user_id
        )
        return await self.db.scalar(query) or 0

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters,
    ) -> Tuple[int, List[models.TrustedDevice]]:
        """
        Get filtered trusted devices with pagination.
        
        Required by BaseRepository abstract method.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            **filters: Filter parameters (user_id supported)
            
        Returns:
            Tuple of (total_count, list of devices)
        """
        user_id = filters.get("user_id")
        if user_id:
            return await self.get_by_user_id(user_id, skip, limit)
        
        # Admin view: all trusted devices
        total = await self.count()
        query = (
            select(self.model)
            .order_by(self.model.trusted_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return total, list(result.scalars().all())

