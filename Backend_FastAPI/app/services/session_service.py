# app/services/session_service.py
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import NoResultFound  # ✅ Thêm exception
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent
from fastapi import status

from .. import models
from ..database import safe_redis_delete, safe_redis_set
# ✅ PHASE 1: Removed AsyncSessionLocal import (DI pattern - db injected via parameter)
from ..utils.exceptions import (  # ✅ PHASE 1: Custom exceptions (protocol-independent)
    SessionRevocationError,
    SessionServiceError,
)
from ..socket_manager import sio
from ..socket_metrics import socket_emit_failures_total  # ✅ Thêm Metrics
from ..socket_metrics import (
    socket_events_emitted_total,
    track_event_latency,
)
from .geoip_service import get_geoip_service  # ✅ Import GeoIP service

log = structlog.get_logger(__name__)


async def _revoke_previous_sessions_on_device(
    db: AsyncSession,
    user_id: int,
    device_type: str,
    browser: str,
    os: str
):
    """
    ✅ SECURITY FIX: Auto-revoke old sessions on same device to prevent session leak.

    VULNERABILITY: Session Leak (CVSS 6.5 MEDIUM)
    - Old behavior: Create new session every login → hundreds of zombie sessions
    - Attack: Memory exhaustion, audit log pollution, anomaly detection bypass
    - Fix: Auto-revoke previous sessions on same device before creating new one

    This prevents:
    - Session table bloat (38+ sessions per user)
    - Redis memory leak (session: keys never cleaned)
    - Anomaly detection false positives (legitimate re-login looks suspicious)
    - Audit trail pollution (can't distinguish real vs. ghost sessions)

    Args:
        db: Database session (must be in transaction)
        user_id: User ID
        device_type: Device type (mobile, desktop, tablet)
        browser: Browser name and version
        os: Operating system name and version

    Returns:
        None (modifies database state)
    """
    try:
        # Find all active sessions on same device
        stmt = select(models.UserSession).where(
            and_(
                models.UserSession.user_id == user_id,
                models.UserSession.device_type == device_type,
                models.UserSession.browser == browser,
                models.UserSession.os == os,
                models.UserSession.revoked_at.is_(None)
            )
        )
        result = await db.execute(stmt)
        old_sessions = result.scalars().all()

        if not old_sessions:
            log.debug(
                "No previous sessions on this device to revoke",
                user_id=user_id,
                device_type=device_type
            )
            return

        # Revoke all old sessions
        now = datetime.now(timezone.utc)
        revoked_count = 0

        for session in old_sessions:
            # Mark as revoked in DB
            session.revoked_at = now
            db.add(session)

            # Clean up Redis keys
            try:
                await safe_redis_delete(f"session:{session.refresh_jti}")

                # Add to blacklist so old tokens can't be used
                ttl = int((session.expires_at - now).total_seconds())
                if ttl > 0:
                    await safe_redis_set(
                        f"blacklist:{session.refresh_jti}",
                        "auto_revoked_on_relogin",
                        ex=ttl
                    )
            except Exception as redis_error:
                log.warning(
                    "Failed to clean Redis for old session (continuing anyway)",
                    session_id=session.id,
                    error=str(redis_error)
                )

            revoked_count += 1

        # Flush to DB (will be committed by parent transaction)
        await db.flush()

        log.info(
            "Auto-revoked previous sessions on same device",
            user_id=user_id,
            device_type=device_type,
            browser=browser[:20],  # Truncate for log
            os=os[:20],
            revoked_count=revoked_count
        )

    except Exception as e:
        # Log error but don't fail the login process
        # Session leak is better than login failure
        log.error(
            "Failed to auto-revoke old sessions (non-critical, continuing)",
            user_id=user_id,
            error=str(e),
            exc_info=True
        )


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
            browser = (
                f"{browser_family} {browser_version}"
                if browser_version
                else browser_family
            )

            # Extract OS info
            os_family = user_agent.os.family
            os_version = user_agent.os.version_string
            os = f"{os_family} {os_version}" if os_version else os_family

        except Exception as e:
            log.warning(
                "Failed to parse User-Agent", user_agent=user_agent_string, error=str(e)
            )

    # Lookup geographic location from IP address
    country = None
    city = None
    if ip_address:
        try:
            geoip = get_geoip_service()
            country, city = geoip.lookup(ip_address)
            if country or city:
                log.info(
                    "GeoIP lookup successful",
                    user_id=user_id,
                    ip_address=ip_address,
                    country=country,
                    city=city,
                )
        except Exception as e:
            log.warning("GeoIP lookup failed", ip_address=ip_address, error=str(e))

    # ✅ SECURITY FIX: Auto-revoke old sessions on same device before creating new one
    # This prevents session leak (38+ zombie sessions per user)
    await _revoke_previous_sessions_on_device(
        db=db,
        user_id=user_id,
        device_type=device_type,
        browser=browser,
        os=os
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
        country=country,
        city=city,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
        is_suspicious=False,
    )

    db.add(session)
    await db.flush()  # Get session.id without committing

    log.info(
        "Session created",
        session_id=session.id,
        user_id=user_id,
        ip_address=ip_address,
        device_type=device_type,
        browser=browser,
        os=os,
    )

    return session


async def check_new_ip_address(
    db: AsyncSession, user_id: int, ip_address: Optional[str]
) -> bool:
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
        log.warning(
            "New IP address detected for user", user_id=user_id, ip_address=ip_address
        )

    return is_new


async def get_active_sessions(
    db: AsyncSession, user_id: int, current_refresh_jti: Optional[str] = None
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
                models.UserSession.expires_at > now,
            )
        )
        .order_by(models.UserSession.last_activity_at.desc())
    )

    sessions = result.scalars().all()

    log.info("Retrieved active sessions", user_id=user_id, session_count=len(sessions))

    return list(sessions)


async def revoke_session(
    db: AsyncSession,  # ✅ PHASE 1: Accept db parameter (DI pattern)
    session_id: int,
    user_id: int
) -> bool:
    """
    Revoke a user session.

    Args:
        db: Database session (injected via DI)
        session_id: ID of session to revoke
        user_id: User ID for ownership verification

    Returns:
        True if session was revoked, False if not found

    Raises:
        SessionRevocationError: If revocation fails
    """
    session_to_emit = None  # Store session JTI for socket emission

    try:
        # ✅ PHASE 1: Use injected db session (no AsyncSessionLocal creation)
        async with db.begin():  # Start transaction
            result = await db.execute(
                select(models.UserSession)
                .where(
                    and_(
                        models.UserSession.id == session_id,
                        models.UserSession.user_id == user_id,
                    )
                )
                .with_for_update()
            )
            session = result.scalar_one_or_none()

            if not session:
                raise NoResultFound("Session not found")

            if session.revoked_at is not None:
                log.warning("Session already revoked, skipping", session_id=session_id)
                return False

            # 1. Update database
            session.revoked_at = datetime.now(timezone.utc)
            db.add(session)
            session_to_emit = session.refresh_jti  # Store JTI for socket event

            # 2. Update Redis (within transaction)
            ttl = int(
                (session.expires_at - datetime.now(timezone.utc)).total_seconds()
            )
            if ttl > 0:
                await safe_redis_set(
                    f"blacklist:{session.refresh_jti}", "revoked_by_user", ex=ttl
                )

            await safe_redis_delete(f"session:{session.refresh_jti}")
            log.info(
                "Session marked in DB and Redis keys updated (in transaction)",
                session_id=session_id
            )

        # Transaction committed automatically
        log.info("Revoke transaction committed", session_id=session_id, user_id=user_id)

    except NoResultFound:
        log.warning(
            "Session not found or doesn't belong to user",
            session_id=session_id,
            user_id=user_id,
        )
        return False  # Session not found (safe failure)
    except Exception as e:
        # Any error (database or Redis) will be caught here
        # db.rollback() is called automatically by db.begin() context manager
        log.error(
            "Failed to revoke session (transaction rolled back)",
            session_id=session_id,
            user_id=user_id,
            error=str(e),
        )
        # ✅ PHASE 1: Raise custom exception for router to handle
        raise SessionRevocationError(
            detail="Failed to revoke session",
            context={
                "session_id": session_id,
                "user_id": user_id,
                "error": str(e),
            }
        )

    # 4. Gửi Socket.IO (Chỉ khi transaction thành công)
    if session_to_emit:
        async with track_event_latency("force_logout_batch"):
            try:
                room_name = f"user_room_{user_id}"
                await sio.emit(
                    "force_logout_batch",
                    {"revoked_jtis": [session_to_emit]},
                    room=room_name,
                )
                socket_events_emitted_total.labels(event_type="force_logout_batch").inc()
                log.info("Emitted 'force_logout_batch' event (single)", session_id=session_id)
            except Exception as e_socket:
                socket_emit_failures_total.labels(event_type="force_logout_batch").inc()
                log.error("Failed to emit socket event for revoke", error=str(e_socket))

    return True


async def update_session_activity(
    db: AsyncSession, old_refresh_jti: str, new_refresh_jti: str, user_id: int
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
        select(models.UserSession).where(
            and_(
                models.UserSession.refresh_jti == old_refresh_jti,
                models.UserSession.user_id == user_id,
            )
        )
    )
    session = result.scalar_one_or_none()

    if session:
        session.last_activity_at = datetime.now(timezone.utc)
        session.refresh_jti = new_refresh_jti
        db.add(session)

        log.debug(
            "Session activity updated",
            session_id=session.id,
            user_id=user_id,
            old_jti=old_refresh_jti[:8],
            new_jti=new_refresh_jti[:8],
        )
    else:
        log.warning(
            "Session not found for activity update",
            old_refresh_jti=old_refresh_jti[:8],
            user_id=user_id,
        )

    return session


async def revoke_all_other_sessions(
    db: AsyncSession,  # ✅ PHASE 1: Accept db parameter (DI pattern)
    user_id: int,
    except_session_id: Optional[int] = None
) -> int:
    """
    Revoke all other sessions for a user except optionally one.

    Args:
        db: Database session (injected via DI)
        user_id: User ID
        except_session_id: Optional session ID to preserve

    Returns:
        Number of sessions revoked

    Raises:
        Exception: If revocation fails (caught and re-raised for router handling)
    """
    revoked_jtis = []
    revoked_count = 0

    try:
        # ✅ FIX: Use existing transaction from caller (don't start new one)
        # The db session already has an active transaction from the endpoint
        now = datetime.now(timezone.utc)
        conditions = [
            models.UserSession.user_id == user_id,
            models.UserSession.revoked_at.is_(None),
        ]
        if except_session_id is not None:
            conditions.append(models.UserSession.id != except_session_id)

        result = await db.execute(
            select(models.UserSession).where(and_(*conditions)).with_for_update()
        )
        sessions = result.scalars().all()

        for session in sessions:
            session.revoked_at = now
            db.add(session)
            revoked_jtis.append(session.refresh_jti)

            # Cập nhật Redis
            ttl = int((session.expires_at - now).total_seconds())
            if ttl > 0:
                await safe_redis_set(
                    f"blacklist:{session.refresh_jti}",
                    "revoked_by_user",
                    ex=ttl,
                )
            await safe_redis_delete(f"session:{session.refresh_jti}")

            revoked_count += 1

        # Commit changes (caller's transaction will handle commit)
        await db.flush()

        log.info("Revoked all other sessions and updated Redis",
                 user_id=user_id,
                 revoked_count=revoked_count)

    except Exception as e:
        log.error(
            "Failed to revoke all other sessions (service level)",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise e # Ném lại lỗi để router xử lý (trả về 500)


    # Gửi sự kiện Socket.IO (Sau khi đã commit)
    if revoked_jtis:
        async with track_event_latency("force_logout_batch_all"):
            try:
                room_name = f"user_room_{user_id}"
                await sio.emit(
                    "force_logout_batch", {"revoked_jtis": revoked_jtis}, room=room_name
                )
                socket_events_emitted_total.labels(event_type="force_logout_batch").inc(
                    len(revoked_jtis)
                )
                # ✅ 6. SỬA LỖI GHI LOG
                log.info(
                    "Emitted 'force_logout_batch' event (multiple)",
                    user_id=user_id,
                    revoked_count=revoked_count
                )
            except Exception as e_socket:
                socket_emit_failures_total.labels(event_type="force_logout_batch").inc()
                log.error(
                    "Failed to emit socket event for revoke-all", 
                    error_message=str(e_socket)
                )

    return revoked_count