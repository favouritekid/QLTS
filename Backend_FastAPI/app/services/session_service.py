# app/services/session_service.py
"""
Service layer for managing user sessions.
Handles session creation, tracking, anomaly detection, and revocation.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent

from .. import models, schemas
from ..config import settings
from ..database import safe_redis_set, safe_redis_delete  # ✅ FIX: Import safe_redis_delete

log = structlog.get_logger(__name__)


async def create_session(
    db: AsyncSession,
    user_id: int,
    refresh_jti: str,
    ip_address: Optional[str],
    user_agent_string: Optional[str],
    expires_at: datetime,
) -> models.UserSession:
    """
    Create a new session record when user logs in.
    
    Args:
        db: Database session
        user_id: User ID
        refresh_jti: Refresh token JTI
        ip_address: Client IP address
        user_agent_string: User-Agent header string
        expires_at: Session expiration time (same as refresh token expiry)
    
    Returns:
        Created UserSession instance
    """
    # Parse User-Agent to extract device info
    device_type = "unknown"
    browser = "Unknown"
    os = "Unknown"
    
    if user_agent_string:
        try:
            user_agent = parse_user_agent(user_agent_string)
            
            # Determine device type
            if user_agent.is_mobile:
                device_type = "mobile"
            elif user_agent.is_tablet:
                device_type = "tablet"
            elif user_agent.is_pc:
                device_type = "desktop"
            else:
                device_type = "bot" if user_agent.is_bot else "unknown"
            
            # Extract browser info
            browser_family = user_agent.browser.family
            browser_version = user_agent.browser.version_string
            browser = f"{browser_family} {browser_version}" if browser_version else browser_family
            
            # Extract OS info
            os_family = user_agent.os.family
            os_version = user_agent.os.version_string
            os = f"{os_family} {os_version}" if os_version else os_family
            
        except Exception as e:
            await log.warning(
                "Failed to parse User-Agent",
                user_agent=user_agent_string,
                error=str(e)
            )
    
    # Create session record
    session = models.UserSession(
        user_id=user_id,
        refresh_jti=refresh_jti,
        ip_address=ip_address,
        user_agent=user_agent_string,
        device_type=device_type,
        browser=browser,
        os=os,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
        is_suspicious=False,
    )
    
    db.add(session)
    await db.flush()  # Get session.id without committing
    
    await log.info(
        "Session created",
        session_id=session.id,
        user_id=user_id,
        ip_address=ip_address,
        device_type=device_type,
        browser=browser,
        os=os
    )
    
    return session


async def check_new_ip_address(db: AsyncSession, user_id: int, ip_address: Optional[str]) -> bool:
    """
    Check if this IP address has been used before by this user.
    
    Args:
        db: Database session
        user_id: User ID
        ip_address: IP address to check
    
    Returns:
        True if this is a new IP address, False otherwise
    """
    if not ip_address:
        return False
    
    # Query for any previous session from this IP
    result = await db.execute(
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
        await log.warning(
            "New IP address detected for user",
            user_id=user_id,
            ip_address=ip_address
        )
    
    return is_new


async def get_active_sessions(
    db: AsyncSession,
    user_id: int,
    current_refresh_jti: Optional[str] = None
) -> list[models.UserSession]:
    """
    Get all active sessions for a user.
    
    Args:
        db: Database session
        user_id: User ID
        current_refresh_jti: Current refresh token JTI (to mark as current)
    
    Returns:
        List of active UserSession instances
    """
    now = datetime.now(timezone.utc)
    
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None),
                models.UserSession.expires_at > now
            )
        )
        .order_by(models.UserSession.last_activity_at.desc())
    )
    
    sessions = result.scalars().all()
    
    await log.info(
        "Retrieved active sessions",
        user_id=user_id,
        session_count=len(sessions)
    )
    
    return list(sessions)


async def revoke_session(
    db: AsyncSession,
    session_id: int,
    user_id: int
) -> bool:
    """
    Revoke a specific session.

    Args:
        db: Database session
        session_id: Session ID to revoke
        user_id: User ID (for authorization check)

    Returns:
        True if session was revoked, False if not found
    """
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.id == session_id,
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None)  # Only revoke active sessions
            )
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        await log.warning(
            "Session not found for revocation or already revoked",
            session_id=session_id,
            user_id=user_id
        )
        return False

    # Mark as revoked
    session.revoked_at = datetime.now(timezone.utc)
    db.add(session)

    # Blacklist the refresh token in Redis AND delete session key
    try:
        ttl = int((session.expires_at - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            # Add to blacklist
            await safe_redis_set(
                f"blacklist:{session.refresh_jti}",
                "revoked_by_user",
                ex=ttl
            )
            # ✅ FIX: Delete session key from Redis for immediate revocation
            await safe_redis_delete(f"session:{session.refresh_jti}")
            await log.info(
                "Session key deleted from Redis",
                session_id=session_id,
                refresh_jti=session.refresh_jti[:8] + "..."
            )
    except Exception as redis_error:
        await log.warning(
            "Failed to blacklist/delete refresh token in Redis",
            session_id=session_id,
            error=str(redis_error)
        )
        # Continue anyway - database revocation is sufficient

    await db.commit()

    await log.info(
        "Session revoked",
        session_id=session_id,
        user_id=user_id,
        refresh_jti=session.refresh_jti
    )

    return True


async def update_session_activity(
    db: AsyncSession,
    old_refresh_jti: str,
    new_refresh_jti: str,
    user_id: int
) -> Optional[models.UserSession]:
    """
    Update session's last_activity_at and refresh_jti when token is refreshed.
    
    Args:
        db: Database session
        old_refresh_jti: Old refresh token JTI
        new_refresh_jti: New refresh token JTI
        user_id: User ID
    
    Returns:
        Updated UserSession instance, or None if not found
    """
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.refresh_jti == old_refresh_jti,
                models.UserSession.user_id == user_id
            )
        )
    )
    session = result.scalar_one_or_none()
    
    if session:
        session.last_activity_at = datetime.now(timezone.utc)
        session.refresh_jti = new_refresh_jti
        db.add(session)
        
        await log.debug(
            "Session activity updated",
            session_id=session.id,
            user_id=user_id,
            old_jti=old_refresh_jti[:8],
            new_jti=new_refresh_jti[:8]
        )
    else:
        await log.warning(
            "Session not found for activity update",
            old_refresh_jti=old_refresh_jti[:8],
            user_id=user_id
        )
    
    return session


async def revoke_all_other_sessions(
    db: AsyncSession,
    user_id: int,
    except_session_id: Optional[int] = None
) -> int:
    """
    Revoke all sessions except optionally one specific session.

    Args:
        db: Database session
        user_id: User ID
        except_session_id: Optional session ID to keep active (usually current session)

    Returns:
        Number of sessions revoked
    """
    now = datetime.now(timezone.utc)

    # Build query conditions
    conditions = [
        models.UserSession.user_id == user_id,
        models.UserSession.revoked_at.is_(None)
    ]

    # Exclude specific session if provided
    if except_session_id is not None:
        conditions.append(models.UserSession.id != except_session_id)

    # Get all active sessions (except the one to preserve)
    result = await db.execute(
        select(models.UserSession).where(and_(*conditions))
    )
    sessions = result.scalars().all()

    # Revoke all
    revoked_count = 0
    for session in sessions:
        session.revoked_at = now
        db.add(session)

        # Blacklist in Redis AND delete session key
        try:
            ttl = int((session.expires_at - now).total_seconds())
            if ttl > 0:
                # Add to blacklist
                await safe_redis_set(
                    f"blacklist:{session.refresh_jti}",
                    "revoked_by_user",
                    ex=ttl
                )
                # ✅ FIX: Delete session key from Redis for immediate revocation
                await safe_redis_delete(f"session:{session.refresh_jti}")
        except Exception as redis_error:
            await log.warning(
                "Failed to blacklist/delete refresh token in Redis",
                session_id=session.id,
                error=str(redis_error)
            )
            # Continue anyway

        revoked_count += 1

    await db.commit()

    await log.info(
        "Revoked all other sessions",
        user_id=user_id,
        except_session_id=except_session_id,
        revoked_count=revoked_count
    )

    return revoked_count

