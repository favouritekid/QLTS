# app/services/anomaly_detection.py
"""
Anomaly detection service for identifying suspicious login activities.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..config import settings

log = structlog.get_logger(__name__)


class AnomalyDetector:
    """
    Detects suspicious login patterns and anomalies.
    
    Configuration now comes from settings (see config.py).
    These can be overridden via environment variables:
      ANOMALY_MAX_FAILED_LOGINS_PER_HOUR, ANOMALY_MAX_SESSIONS_PER_USER,
      ANOMALY_SUSPICIOUS_COUNTRY_CHANGE_HOURS, ANOMALY_UNUSUAL_LOGIN_START_HOUR,
      ANOMALY_UNUSUAL_LOGIN_END_HOUR
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_new_ip_address(
        self, user_id: int, ip_address: Optional[str]
    ) -> bool:
        """
        Check if this IP address has been used before by this user.

        Args:
            user_id: User ID
            ip_address: IP address to check

        Returns:
            True if this is a new IP address, False otherwise
        """
        if not ip_address:
            return False

        # Query for any previous session from this IP
        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.ip_address == ip_address,
                )
            )
            .limit(1)
        )
        existing_session = result.scalar_one_or_none()

        is_new = existing_session is None

        if is_new:
            log.warning(
                "New IP address detected", user_id=user_id, ip_address=ip_address
            )

        return is_new

    async def check_new_device(
        self,
        user_id: int,
        device_type: Optional[str],
        browser: Optional[str],
        os: Optional[str],
    ) -> bool:
        """
        Check if this device/browser/OS combination is new for this user.

        Args:
            user_id: User ID
            device_type: Device type (PC, Mobile, Tablet)
            browser: Browser name
            os: Operating system

        Returns:
            True if this is a new device combination
        """
        if not all([device_type, browser, os]):
            return False

        # Query for any previous session with same device fingerprint
        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.device_type == device_type,
                    models.UserSession.browser == browser,
                    models.UserSession.os == os,
                )
            )
            .limit(1)
        )
        existing_session = result.scalar_one_or_none()

        is_new = existing_session is None

        if is_new:
            log.warning(
                "New device detected",
                user_id=user_id,
                device_type=device_type,
                browser=browser,
                os=os,
            )

        return is_new

    async def check_impossible_travel(
        self, user_id: int, current_country: Optional[str], current_city: Optional[str]
    ) -> bool:
        """
        Detect impossible travel: login from different countries in short time.

        This is a simplified version. In production, you would:
        - Calculate actual distance between locations
        - Consider realistic travel time
        - Use geolocation APIs

        Args:
            user_id: User ID
            current_country: Current login country
            current_city: Current login city

        Returns:
            True if impossible travel detected
        """
        if not current_country:
            return False

        # Get most recent session (within last N hours)
        time_threshold = datetime.now(timezone.utc) - timedelta(
            hours=settings.ANOMALY_SUSPICIOUS_COUNTRY_CHANGE_HOURS
        )

        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.created_at >= time_threshold,
                    models.UserSession.country.isnot(None),
                    models.UserSession.country != current_country,
                )
            )
            .order_by(models.UserSession.created_at.desc())
            .limit(1)
        )
        recent_session = result.scalar_one_or_none()

        if recent_session:
            log.warning(
                "Impossible travel detected",
                user_id=user_id,
                previous_country=recent_session.country,
                current_country=current_country,
                time_diff_hours=(
                    datetime.now(timezone.utc) - recent_session.created_at
                ).total_seconds()
                / 3600,
            )
            return True

        return False

    async def check_excessive_sessions(self, user_id: int) -> bool:
        """
        Check if user has too many active sessions.

        Args:
            user_id: User ID

        Returns:
            True if user has excessive active sessions
        """
        result = await self.db.execute(
            select(func.count(models.UserSession.id)).where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.revoked_at.is_(None),
                )
            )
        )
        session_count = result.scalar()

        is_excessive = session_count >= settings.ANOMALY_MAX_SESSIONS_PER_USER

        if is_excessive:
            log.warning(
                "Excessive active sessions detected",
                user_id=user_id,
                session_count=session_count,
                threshold=self.MAX_SESSIONS_PER_USER,
            )

        return is_excessive

    async def check_unusual_login_time(
        self, user_id: int, login_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if login time is unusual compared to user's typical pattern.

        This is a simplified version. In production, you would:
        - Build user behavior profile
        - Detect logins outside typical hours
        - Consider timezone

        Args:
            user_id: User ID
            login_time: Login timestamp (default: now in UTC)

        Returns:
            True if login time is unusual
        """
        if login_time is None:
            login_time = datetime.now(timezone.utc)

        # ✅ FIX: Convert UTC time to configured timezone (e.g., Asia/Ho_Chi_Minh)
        # This prevents false positives when server is in UTC but users are in Vietnam
        try:
            app_timezone = ZoneInfo(settings.TIMEZONE)
            local_time = login_time.astimezone(app_timezone)
            hour = local_time.hour
        except Exception as e:
            # Fallback to UTC if timezone conversion fails
            log.warning(
                "Failed to convert timezone for anomaly detection",
                error=str(e),
                timezone=settings.TIMEZONE,
            )
            hour = login_time.hour

        # Consider 2 AM - 6 AM (local time) as unusual (this is very simplified)
        is_unusual = settings.ANOMALY_UNUSUAL_LOGIN_START_HOUR <= hour < settings.ANOMALY_UNUSUAL_LOGIN_END_HOUR

        if is_unusual:
            log.info(
                "Unusual login time detected",
                user_id=user_id,
                hour=hour,
                timezone=settings.TIMEZONE,
                utc_time=login_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                local_time=local_time.strftime("%Y-%m-%d %H:%M:%S") if 'local_time' in locals() else None,
            )

        return is_unusual

    async def analyze_login(
        self,
        user_id: int,
        ip_address: Optional[str],
        device_type: Optional[str],
        browser: Optional[str],
        os: Optional[str],
        country: Optional[str] = None,
        city: Optional[str] = None,
        login_time: Optional[datetime] = None,
    ) -> Dict[str, bool]:
        """
        Comprehensive anomaly analysis for a login attempt.

        Args:
            user_id: User ID
            ip_address: IP address
            device_type: Device type
            browser: Browser name
            os: Operating system
            country: Country (optional)
            city: City (optional)
            login_time: Login timestamp (optional)

        Returns:
            Dictionary of anomaly flags:
            {
                "new_ip": bool,
                "new_device": bool,
                "impossible_travel": bool,
                "excessive_sessions": bool,
                "unusual_time": bool,
                "is_suspicious": bool  # True if ANY anomaly detected
            }
        """
        anomalies = {
            "new_ip": await self.check_new_ip_address(user_id, ip_address),
            "new_device": await self.check_new_device(
                user_id, device_type, browser, os
            ),
            "impossible_travel": await self.check_impossible_travel(
                user_id, country, city
            ),
            "excessive_sessions": await self.check_excessive_sessions(user_id),
            "unusual_time": await self.check_unusual_login_time(user_id, login_time),
        }

        # Mark as suspicious if ANY anomaly detected
        anomalies["is_suspicious"] = any(anomalies.values())

        if anomalies["is_suspicious"]:
            log.warning(
                "Suspicious login detected", user_id=user_id, anomalies=anomalies
            )

        return anomalies
