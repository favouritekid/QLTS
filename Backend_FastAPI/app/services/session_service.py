# app/services/session_service.py
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import NoResultFound  # ✅ Thêm exception
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent
from fastapi import HTTPException, status

from .. import models
from ..database import safe_redis_delete, safe_redis_set
from ..database import AsyncSessionLocal  # ✅ 1. IMPORT SESSION MỚI
from ..socket_manager import sio
from ..socket_metrics import socket_emit_failures_total  # ✅ Thêm Metrics
from ..socket_metrics import (
    socket_events_emitted_total,
    track_event_latency,
)

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
    # ❌ 2. XÓA `db: AsyncSession,`
    session_id: int, 
    user_id: int
) -> bool:
    session_to_emit = None  # Biến để lưu session JTI ra ngoài transaction

    # ✅ 3. TẠO SESSION CỦA RIÊNG HÀM NÀY
    async with AsyncSessionLocal() as db:
        try:
            # ✅ 4. SỬA THÀNH `db.begin()`
            async with db.begin(): # Bắt đầu transaction MỚI
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

                # 1. Cập nhật CSDL
                session.revoked_at = datetime.now(timezone.utc)
                db.add(session)
                session_to_emit = session.refresh_jti # Lưu JTI

                # 2. Cập nhật REDIS (NẰM TRONG TRANSACTION)
                ttl = int(
                    (session.expires_at - datetime.now(timezone.utc)).total_seconds()
                )
                if ttl > 0:
                    await safe_redis_set(
                        f"blacklist:{session.refresh_jti}", "revoked_by_user", ex=ttl
                    )
                
                await safe_redis_delete(f"session:{session.refresh_jti}")
                log.info("Session DB marked and Redis keys updated (in transaction)", 
                         session_id=session_id)

            # 3. COMMIT TỰ ĐỘNG
            log.info("Revoke transaction committed", session_id=session_id, user_id=user_id)

        except NoResultFound:
            log.warning(
                "Session not found or doesn't belong to user",
                session_id=session_id,
                user_id=user_id,
            )
            return False # Thất bại (an toàn)
        except Exception as e:
            # Bất kỳ lỗi nào (CSDL hoặc Redis) đều sẽ bị bắt ở đây
            # db.rollback() được tự động gọi
            log.error(
                "Failed to revoke session (transaction rolled back)",
                session_id=session_id,
                user_id=user_id,
                error=str(e),
            )
            # 💡 Trả về lỗi 500 cho Frontend (Device A) biết là đã thất bại
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to revoke session due to service error: {e}"
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
    # ❌ 1. XÓA `db: AsyncSession,`
    user_id: int, 
    except_session_id: Optional[int] = None
) -> int:
    revoked_jtis = []
    revoked_count = 0
    
    # ✅ 2. TẠO SESSION CỦA RIÊNG HÀM NÀY
    async with AsyncSessionLocal() as db:
        try:
            # ✅ 3. SỬA THÀNH `db.begin()`
            async with db.begin():
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
                    
                    # Cập nhật Redis (Nếu đây là lỗi, exception sẽ văng ra
                    # và db.begin() sẽ tự động rollback)
                    ttl = int((session.expires_at - now).total_seconds())
                    if ttl > 0:
                        await safe_redis_set(
                            f"blacklist:{session.refresh_jti}",
                            "revoked_by_user",
                            ex=ttl,
                        )
                    await safe_redis_delete(f"session:{session.refresh_jti}")
                    
                    revoked_count += 1
            
            # ✅ 4. COMMIT TỰ ĐỘNG (Chỉ khi CSDL và Redis đều thành công)
            log.info("Revoked all other sessions and updated Redis", 
                     user_id=user_id, 
                     revoked_count=revoked_count)

        except Exception as e:
            # ✅ 5. BẮT LỖI VÀ NÉM LẠI
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