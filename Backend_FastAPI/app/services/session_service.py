# app/services/session_service.py
"""
✅ PHASE 2: Session Service - Refactored to use SessionRepository

This service manages user sessions following the Repository Pattern:
Router → Service → Repository

No direct SQL queries - all data access through SessionRepository.
"""
from datetime import datetime, timezone
from typing import Optional, Callable, Coroutine, Any, Tuple
PostCommitCallback = Callable[[], Coroutine[Any, Any, None]]

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent

from .. import models
from ..database import safe_redis_delete, safe_redis_set
from ..repositories import SessionRepository  # ✅ PHASE 2: Use Repository Pattern
from ..utils.exceptions import (
    SessionRevocationError,
    SessionServiceError,
)
from ..core.events import dispatcher, TransportEvents
from ..socket_metrics import socket_emit_failures_total
from ..socket_metrics import (
    socket_events_emitted_total,
    track_event_latency,
)
from .geoip_service import get_geoip_service

log = structlog.get_logger(__name__)


async def _emit_session_updated(user_id: int):
    """Emit session_updated event to refresh frontend session list."""
    try:
        from ..socket_manager import sio
        room = f"user_room_{user_id}"
        await sio.emit("session_updated", {
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, room=room)
        log.debug("Emitted session_updated event", user_id=user_id)
    except Exception as e:
        log.error(f"Failed to emit session_updated: {e}")



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
        # ✅ PHASE 2: Use SessionRepository instead of direct SQL
        repo = SessionRepository(db)
        old_sessions = await repo.get_active_on_device(
            user_id=user_id,
            device_type=device_type,
            browser=browser,
            os=os
        )

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


async def _enforce_max_sessions(
    db: AsyncSession,
    user_id: int,
):
    """
    ✅ H1: Enforce maximum concurrent sessions per user (FIFO eviction).

    If user has >= ANOMALY_MAX_SESSIONS_PER_USER active sessions,
    revoke the oldest sessions until under the limit, leaving room for
    the new session about to be created.
    """
    from ..config import settings

    max_sessions = settings.ANOMALY_MAX_SESSIONS_PER_USER
    try:
        repo = SessionRepository(db)
        active_sessions = await repo.get_active_by_user(user_id)
        active_count = len(active_sessions)

        if active_count < max_sessions:
            return

        # Sessions are ordered by last_activity_at DESC, so oldest are at the end
        # Revoke oldest sessions to make room for the new one
        sessions_to_revoke = active_sessions[max_sessions - 1:]  # Keep max-1, new one will be added
        now = datetime.now(timezone.utc)
        revoked_count = 0

        for session in sessions_to_revoke:
            session.revoked_at = now
            db.add(session)

            try:
                await safe_redis_delete(f"session:{session.refresh_jti}")
                ttl = int((session.expires_at - now).total_seconds())
                if ttl > 0:
                    await safe_redis_set(
                        f"blacklist:{session.refresh_jti}",
                        "max_sessions_exceeded",
                        ex=ttl,
                    )
            except Exception as redis_error:
                log.warning(
                    "Failed to clean Redis for evicted session",
                    session_id=session.id,
                    error=str(redis_error),
                )

            revoked_count += 1

        await db.flush()

        log.warning(
            "Concurrent session limit enforced (FIFO eviction)",
            user_id=user_id,
            active_before=active_count,
            revoked_count=revoked_count,
            max_allowed=max_sessions,
            security_event="MAX_SESSIONS_ENFORCED",
        )

    except Exception as e:
        log.error(
            "Failed to enforce max sessions (non-critical, continuing)",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )


async def create_session(
    db: AsyncSession,
    user_id: int,
    refresh_jti: str,
    ip_address: Optional[str],
    user_agent_string: Optional[str],
    expires_at: datetime,
) -> Tuple[models.UserSession, PostCommitCallback]:
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
        Tuple[UserSession, PostCommitCallback]: Created session and callback to emit socket event
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

    # ✅ H1: Enforce concurrent session limit (FIFO eviction)
    await _enforce_max_sessions(db=db, user_id=user_id)

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

    async def callback():
        await _emit_session_updated(user_id)

    return session, callback


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

    # ✅ PHASE 2: Use SessionRepository instead of direct SQL
    repo = SessionRepository(db)
    existing_session = await repo.get_by_ip(user_id, ip_address)

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
    # ✅ PHASE 2: Use SessionRepository instead of direct SQL
    repo = SessionRepository(db)
    sessions = await repo.get_active_by_user(user_id)

    log.info("Retrieved active sessions", user_id=user_id, session_count=len(sessions))

    return sessions


async def revoke_session(
    db: AsyncSession,  # ✅ PHASE 1: Accept db parameter (DI pattern)
    session_id: int,
    user_id: int
) -> Tuple[bool, Optional[PostCommitCallback]]:
    """
    Revoke a user session.

    Args:
        db: Database session (injected via DI)
        session_id: ID of session to revoke
        user_id: User ID for ownership verification

    Returns:
        Tuple[bool, Optional[PostCommitCallback]]: Success status and callback to emit socket events

    Raises:
        SessionRevocationError: If revocation fails
    """
    session_to_emit = None  # Store session JTI for socket emission

    try:
        # ✅ PHASE 2: Use SessionRepository with pessimistic lock
        repo = SessionRepository(db)
        # ✅ FIX: Use begin_nested() (savepoint) to avoid conflict with router's transaction
        async with db.begin_nested():
            session = await repo.get_for_update(session_id, user_id)

            if not session:
                log.warning(
                    "Session not found or doesn't belong to user",
                    session_id=session_id,
                    user_id=user_id,
                )
                return False, None

            if session.revoked_at is not None:
                log.warning("Session already revoked, skipping", session_id=session_id)
                return False, None

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

    # 4. Prepare Callback (Dispatch event sau khi router commit)
    async def callback():
        if session_to_emit:
            async with track_event_latency("force_logout_batch"):
                try:
                    await dispatcher.dispatch(
                        TransportEvents.USER_FORCE_LOGOUT,
                        user_id=user_id,
                        revoked_jtis=[session_to_emit]
                    )
                    socket_events_emitted_total.labels(event_type="force_logout_batch").inc()
                    log.info("Dispatched force_logout event (single)", session_id=session_id)
                except Exception as e_dispatch:
                    socket_emit_failures_total.labels(event_type="force_logout_batch").inc()
                    log.error("Failed to dispatch logout event", error=str(e_dispatch))
        
        await _emit_session_updated(user_id)

    return True, callback


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
    # ✅ PHASE 2: Use SessionRepository instead of direct SQL
    repo = SessionRepository(db)
    session = await repo.get_by_jti(old_refresh_jti)

    # Verify ownership
    if session and session.user_id != user_id:
        log.warning(
            "Session JTI found but belongs to different user",
            old_refresh_jti=old_refresh_jti[:8],
            session_user_id=session.user_id,
            requested_user_id=user_id,
        )
        return None

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
) -> Tuple[int, PostCommitCallback]:
    """
    Revoke all other sessions for a user except optionally one.

    Args:
        db: Database session (injected via DI)
        user_id: User ID
        except_session_id: Optional session ID to preserve

    Returns:
        Tuple[int, PostCommitCallback]: Number of sessions revoked and callback
    """
    revoked_jtis = []
    revoked_count = 0

    try:
        # ✅ PHASE 2: Use SessionRepository instead of direct SQL
        repo = SessionRepository(db)
        now = datetime.now(timezone.utc)

        # Get all active sessions for user
        sessions = await repo.get_active_by_user(user_id)

        # Filter out the session to preserve
        if except_session_id is not None:
            sessions = [s for s in sessions if s.id != except_session_id]

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


    # Dispatch event (Sau khi đã commit) - Event Dispatcher Pattern
    async def callback():
        if revoked_jtis:
            async with track_event_latency("force_logout_batch_all"):
                try:
                    await dispatcher.dispatch(
                        TransportEvents.USER_FORCE_LOGOUT,
                        user_id=user_id,
                        revoked_jtis=revoked_jtis
                    )
                    socket_events_emitted_total.labels(event_type="force_logout_batch").inc(
                        len(revoked_jtis)
                    )
                    log.info(
                        "Dispatched force_logout event (multiple)",
                        user_id=user_id,
                        revoked_count=revoked_count
                    )
                except Exception as e_dispatch:
                    socket_emit_failures_total.labels(event_type="force_logout_batch").inc()
                    log.error(
                        "Failed to emit socket event for revoke-all",
                        error=str(e_dispatch)
                    )
        
        await _emit_session_updated(user_id)

    return revoked_count, callback


async def revoke_session_by_jti(
    db: AsyncSession,
    refresh_jti: str,
    user_id: int
) -> Tuple[bool, Optional[PostCommitCallback]]:
    """
    ✅ PHASE 2: Revoke a session by its refresh token JTI.

    This is a wrapper function for the /logout endpoint to use instead of
    direct SQL queries in the router layer.

    Args:
        db: Database session
        refresh_jti: Refresh token JTI to revoke
        user_id: User ID for ownership verification

    Returns:
        Tuple[bool, Optional[PostCommitCallback]]: Success status and callback
    """
    repo = SessionRepository(db)
    session = await repo.get_by_refresh_jti_and_user(refresh_jti, user_id)

    if not session:
        log.warning(
            "Session not found for JTI revocation",
            refresh_jti=refresh_jti[:8] + "..." if refresh_jti else None,
            user_id=user_id,
        )
        return False, None

    # Already revoked
    if session.revoked_at is not None:
        log.warning(
            "Session already revoked",
            session_id=session.id,
            refresh_jti=refresh_jti[:8] + "...",
        )
        return False, None

    # Revoke the session
    session.revoked_at = datetime.now(timezone.utc)
    db.add(session)
    await db.flush()

    log.info(
        "Session revoked by JTI",
        session_id=session.id,
        user_id=user_id,
        refresh_jti=refresh_jti[:8] + "...",
    )

    async def callback():
        await _emit_session_updated(user_id)

    return True, callback