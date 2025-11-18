# app/socket_manager.py

import socketio
import structlog
from fastapi import HTTPException

from . import models, security
from .config import settings
from .database import AsyncSessionLocal, redis_client, safe_redis_get
from .services import user_service
from .socket_metrics import track_event_latency  # ✅ Thêm latency tracker
from .socket_metrics import (
    socket_auth_failures_total,
    socket_connections_active,
    socket_events_received_total,
    socket_events_emitted_total,
    socket_emit_failures_total,
)

log = structlog.get_logger(__name__)
is_prod = settings.APP_ENV == "production"

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.CORS_ORIGINS.split(","),
    logger=False,             # 👈 Đặt thành False
    engineio_logger=False,    # 👈 Đặt thành False
)

# === ✅ CẢI TIẾN: Vấn đề #1 - Rate Limiting bằng Redis LUA Script ===
MAX_CONN_PER_MINUTE = 20
RATE_LIMIT_SCRIPT_SHA = None  # Sẽ được load khi khởi động

# LUA script (atomic)
RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call('incr', key)
if current == 1 then
    redis.call('expire', key, ttl)
end

if current > limit then
    return 0
else
    return 1
end
"""


async def load_rate_limit_script():
    """Load LUA script vào Redis và lưu SHA."""
    global RATE_LIMIT_SCRIPT_SHA
    if not redis_client:
        log.error("Redis client not available, cannot load LUA script.")
        return
    try:
        RATE_LIMIT_SCRIPT_SHA = await redis_client.script_load(RATE_LIMIT_SCRIPT)
        log.info("Redis LUA script for rate limiting loaded", sha=RATE_LIMIT_SCRIPT_SHA)
    except Exception as e:
        log.critical("Failed to load Redis LUA script", error=str(e))


async def check_rate_limit(client_ip: str) -> bool:
    """
    Kiểm tra rate limit bằng Redis LUA Script (atomic và hiệu quả).

    ✅ SECURITY FIX (Phase 2): Fail-closed strategy
    - If Redis is unavailable, DENY connection (return False)
    - This prevents rate limit bypass during Redis outage (CVSS 5.3 MEDIUM)
    - Trade-off: Temporary service disruption vs. security

    VULNERABILITY: Socket Rate Limit Bypass
    - Old behavior: return True when Redis fails (fail-open)
    - Attack: Crash Redis → unlimited Socket.IO connections → DoS
    - Fix: return False when Redis fails (fail-closed)
    """
    if not redis_client or not RATE_LIMIT_SCRIPT_SHA:
        log.error(
            "🔒 SECURITY: Redis or LUA script not ready, DENYING connection (fail-closed)",
            client_ip=client_ip
        )
        # ✅ FIX: Return False to deny connection (fail-closed for security)
        return False

    key = f"socket_rate_limit:{client_ip}"
    try:
        # Chạy script bằng SHA (nhanh hơn)
        result = await redis_client.evalsha(
            RATE_LIMIT_SCRIPT_SHA, 1, key, MAX_CONN_PER_MINUTE, 60  # TTL 60 giây
        )
        return bool(result)
    except Exception as e:
        log.error(
            "Redis LUA script (evalsha) failed, falling back to eval",
            error=str(e),
            client_ip=client_ip
        )
        # Fallback: Thử load và chạy lại script (chỉ 1 lần)
        try:
            await load_rate_limit_script()  # Tải lại script
            result = await redis_client.evalsha(
                RATE_LIMIT_SCRIPT_SHA, 1, key, MAX_CONN_PER_MINUTE, 60
            )
            return bool(result)
        except Exception as e2:
            log.error(
                "🔒 SECURITY: Redis rate limit check totally failed, DENYING connection (fail-closed)",
                error=str(e2),
                client_ip=client_ip
            )
            # ✅ FIX: Return False to deny connection (fail-closed for security)
            return False


# === ✅ CẢI TIẾN: Vấn đề #3 - Sanitize Token Log ===
def sanitize_token(token: str) -> str:
    return f"{token[:8]}..." if token and len(token) > 8 else "None"


# === ✅ SECURITY FIX: Parse cookies from Socket.io environ ===
def parse_cookies(cookie_string: str) -> dict[str, str]:
    """
    Parse HTTP Cookie header string into a dictionary.

    Example: "access_token=abc123; refresh_token=xyz789"
    Returns: {"access_token": "abc123", "refresh_token": "xyz789"}
    """
    cookies = {}
    if not cookie_string:
        return cookies

    for cookie in cookie_string.split(";"):
        cookie = cookie.strip()
        if "=" in cookie:
            key, value = cookie.split("=", 1)
            cookies[key.strip()] = value.strip()

    return cookies


async def _get_user_from_token(token: str) -> models.User:
    """
    Hàm helper xác thực token cho WebSocket (V6 - with user blacklist check).

    ✅ FIX-3: Added user blacklist check for security parity with HTTP auth.
    Now checks 3 layers: JWT validity, session validity, user blacklist.
    """
    try:
        payload = security.decode_token(token)
        username: str | None = payload.get("sub")
        refresh_jti: str | None = payload.get("r_jti")

        if not username or not refresh_jti:
            raise HTTPException(status_code=400, detail="Invalid token claims")

        # Check session validity
        stored_user_id = await safe_redis_get(f"session:{refresh_jti}")
        if not stored_user_id:
            raise HTTPException(status_code=401, detail="Session revoked or expired")

        async with AsyncSessionLocal() as db:
            user = await user_service.get_user_by_username(
                db, username=username
            )
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            if user.id != int(stored_user_id):
                raise HTTPException(status_code=401, detail="Token/User mismatch")

            # ✅ FIX-3: Check user blacklist (CRITICAL SECURITY FIX)
            try:
                is_user_blacklisted = await safe_redis_get(f"user_blacklist:{user.id}")
                if is_user_blacklisted:
                    log.warning(
                        "Socket auth rejected: User in global blacklist (password changed?)",
                        user_id=user.id
                    )
                    raise HTTPException(
                        status_code=401,
                        detail="User session invalidated"
                    )
            except HTTPException:
                raise
            except Exception as e:
                log.error(
                    "Redis user blacklist check failed for WebSocket auth",
                    user_id=user.id,
                    error=str(e)
                )
                # Fallback to DB check (same logic as HTTP auth in deps.py)
                from datetime import datetime, timezone
                from sqlalchemy import and_, select

                result = await db.execute(
                    select(models.UserSession)
                    .where(
                        and_(
                            models.UserSession.user_id == user.id,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc),
                        )
                    )
                    .limit(1)
                )
                active_session = result.scalar_one_or_none()
                if active_session is None:
                    log.warning(
                        "DB fallback: No active sessions found for user",
                        user_id=user.id
                    )
                    raise HTTPException(
                        status_code=401,
                        detail="No active sessions"
                    )

            return user

    except Exception as e:
        # Log lỗi mà không log token
        log.warning("Socket auth failed", error=str(e))
        raise ConnectionRefusedError("Auth failed")


@sio.event
async def connect(sid, environ, auth):
    """
    Sự kiện connect (V6) - Cookie-based Authentication.

    ✅ SECURITY FIX: Now reads access_token from httpOnly cookies instead of auth dict.
    This ensures consistent authentication with HTTP requests and prevents XSS attacks.

    Priority:
    1. Read from httpOnly cookie (access_token) - RECOMMENDED
    2. Fallback to auth dict (backwards compatibility during migration)
    """
    async with track_event_latency("connect"):  # ✅ Theo dõi latency
        client_ip = environ.get("REMOTE_ADDR") or "unknown_ip"

        # === ✅ SECURITY FIX: Read token from httpOnly cookie ===
        cookie_string = environ.get("HTTP_COOKIE", "")
        cookies = parse_cookies(cookie_string)
        token = cookies.get("access_token")
        token_source = "cookie"

        # Fallback to auth dict for backwards compatibility
        if not token and auth:
            token = auth.get("token")
            token_source = "auth_dict"

        # === ✅ CẢI TIẾN: Rate Limiting bằng Redis LUA ===
        if not await check_rate_limit(client_ip):
            log.warning("Socket rate limit exceeded", client_ip=client_ip)
            socket_auth_failures_total.inc()
            raise ConnectionRefusedError("Rate limit exceeded")

        try:
            if not token:
                raise ConnectionRefusedError("Authentication failed: No token in cookie or auth")

            user = await _get_user_from_token(token)

            await sio.save_session(sid, {"user_id": user.id, "username": user.username})
            room_name = f"user_room_{user.id}"
            await sio.enter_room(sid, room_name)

            socket_connections_active.inc()

            log.info(
                "Socket client connected",
                sid=sid,
                user_id=user.id,
                username=user.username,
                room=room_name,
                token_source=token_source,  # ✅ Log source for monitoring
                token=sanitize_token(token),  # ✅ Log an toàn
            )

        except Exception as e:
            log.error(
                "Socket connection failed", error=str(e), sid=sid, client_ip=client_ip
            )
            socket_auth_failures_total.inc()
            raise ConnectionRefusedError("Authentication failed")


@sio.event
async def disconnect(sid):
    """Sự kiện disconnect (V5) - Tích hợp Metrics và rời phòng."""
    async with track_event_latency("disconnect"):
        session = await sio.get_session(sid)
        if session:
            user_id = session.get("user_id")
            socket_connections_active.dec()  # Giảm bộ đếm

            # ✅ CẢI TIẾN: Rời phòng một cách tường minh
            room_name = f"user_room_{user_id}"
            await sio.leave_room(sid, room_name)

            log.info(
                "Socket client disconnected",
                sid=sid,
                user_id=user_id,
                username=session.get("username"),
                room=room_name,
            )


@sio.event
async def ping(sid):
    """Xử lý ping (V5) - Tích hợp Metrics và Latency."""
    async with track_event_latency("ping"):
        socket_events_received_total.labels(event_type="ping").inc()
        await sio.emit("pong", to=sid)  # Pong vẫn không cần metric emit


# ✅ CẢI TIẾN: Vấn đề #6 - Thêm event handler cho acknowledgment
@sio.event
async def logout_confirmed(sid, data):
    """Client xác nhận đã nhận được lệnh logout."""
    async with track_event_latency("logout_confirmed"):
        session = await sio.get_session(sid)
        log.info(
            "Client confirmed force_logout",
            sid=sid,
            user_id=session.get("user_id"),
            jti=data.get("jti"),
        )
        socket_events_received_total.labels(event_type="logout_confirmed").inc()


# ✅ FIX-3: Periodic revalidation event handler
@sio.event
async def revalidate_auth(sid):
    """
    Periodic re-validation của user session.
    Client nên gọi mỗi 5 phút để verify session vẫn hợp lệ.

    This catches cases where:
    - User changed password but socket didn't receive force_logout event
    - User was blacklisted by admin
    - Session was revoked by another device
    """
    async with track_event_latency("revalidate_auth"):
        try:
            session = await sio.get_session(sid)
            if not session:
                log.warning("Revalidation failed: No session", sid=sid)
                await sio.disconnect(sid)
                return {"valid": False, "reason": "No session"}

            user_id = session.get("user_id")

            # Check user blacklist
            is_blacklisted = await safe_redis_get(f"user_blacklist:{user_id}")
            if is_blacklisted:
                log.warning(
                    "Revalidation failed: User blacklisted",
                    sid=sid,
                    user_id=user_id
                )
                await sio.disconnect(sid)
                return {"valid": False, "reason": "User session invalidated"}

            # Check if any active sessions exist (fallback check)
            from datetime import datetime, timezone
            from sqlalchemy import and_, select

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(models.UserSession)
                    .where(
                        and_(
                            models.UserSession.user_id == user_id,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc),
                        )
                    )
                    .limit(1)
                )
                active_session = result.scalar_one_or_none()

                if not active_session:
                    log.warning(
                        "Revalidation failed: No active sessions",
                        sid=sid,
                        user_id=user_id
                    )
                    await sio.disconnect(sid)
                    return {"valid": False, "reason": "No active sessions"}

            log.debug("Revalidation successful", sid=sid, user_id=user_id)
            socket_events_received_total.labels(event_type="revalidate_auth").inc()
            return {"valid": True}

        except Exception as e:
            log.error("Socket revalidation error", sid=sid, error=str(e))
            await sio.disconnect(sid)
            return {"valid": False, "reason": "Validation error"}


# =====================================================================
# UTILITY FUNCTIONS FOR ORGANIZATION MODULE
# =====================================================================

async def emit_to_all(event: str, data: dict, namespace: str = "/"):
    """
    Phát sóng một sự kiện đến TẤT CẢ clients đã kết nối.

    Args:
        event: Tên sự kiện (ví dụ: "data_updated")
        data: Dữ liệu cần gửi
        namespace: Socket.IO namespace (mặc định "/")
    """
    try:
        await sio.emit(event, data, namespace=namespace)
        log.info(
            "Emitted event to all clients",
            socket_event=event,
            namespace=namespace,
            data_keys=list(data.keys())
        )
    except Exception as e:
        log.error(
            "Failed to emit event to all clients",
            socket_event=event,
            error=str(e),
            exc_info=True
        )


# =====================================================================
# UTILITY FUNCTIONS FOR LEAD REASSIGNMENT
# =====================================================================

async def emit_lead_reassigned(
    lead_id: int,
    old_officer_id: int | None,
    old_unit_id: int,
    new_unit_id: int,
    reason: str = "Offering changed"
):
    """
    Emit Socket.IO events when a lead is automatically reassigned due to offering change.

    This function notifies:
    1. Old officer (if any): Lead has been removed from their list
    2. New unit admin: New lead has been transferred to their unit

    Args:
        lead_id: ID of the lead being reassigned
        old_officer_id: Previous officer ID (None if unassigned)
        old_unit_id: Previous unit ID
        new_unit_id: New unit ID
        reason: Reason for reassignment (default: "Offering changed")

    Events emitted:
        - "lead_reassigned" to old officer's room
        - "lead_transferred_in" to new unit admin's room
    """
    try:
        # === Event 1: Notify old officer (if exists) ===
        if old_officer_id:
            old_officer_room = f"user_room_{old_officer_id}"
            await sio.emit(
                "lead_reassigned",
                {
                    "lead_id": lead_id,
                    "reason": reason,
                    "old_unit_id": old_unit_id,
                    "new_unit_id": new_unit_id,
                    "message": f"Lead #{lead_id} has been transferred to another unit due to offering change.",
                    "action": "remove_from_list"  # UI should remove lead from officer's list
                },
                room=old_officer_room
            )
            log.info(
                "Lead reassignment notification sent to old officer",
                lead_id=lead_id,
                old_officer_id=old_officer_id,
                old_unit_id=old_unit_id,
                new_unit_id=new_unit_id
            )

        # === Event 2: Notify new unit (broadcast to unit room or admin) ===
        # Option A: Emit to all officers in new unit (if you have unit rooms)
        # new_unit_room = f"unit_room_{new_unit_id}"
        # await sio.emit("lead_transferred_in", {...}, room=new_unit_room)

        # Option B: Emit to all admins (simpler for now)
        # You can filter admins by unit in client-side or create unit-specific admin rooms
        await sio.emit(
            "lead_transferred_in",
            {
                "lead_id": lead_id,
                "reason": reason,
                "old_unit_id": old_unit_id,
                "new_unit_id": new_unit_id,
                "old_officer_id": old_officer_id,
                "message": f"Lead #{lead_id} has been transferred from Unit #{old_unit_id}.",
                "action": "refresh_unassigned_leads"  # UI should refresh unassigned lead list
            },
            namespace="/"  # Broadcast to all connected clients (admins can filter by unit)
        )

        log.info(
            "Lead transfer notification sent to new unit",
            lead_id=lead_id,
            new_unit_id=new_unit_id
        )

    except Exception as e:
        log.error(
            "Failed to emit lead reassignment Socket.IO events",
            lead_id=lead_id,
            old_officer_id=old_officer_id,
            old_unit_id=old_unit_id,
            new_unit_id=new_unit_id,
            error=str(e),
            exc_info=True
        )
        # Don't raise - socket errors should not break lead update logic


# =====================================================================
# UTILITY FUNCTIONS FOR LEAD ASSIGNMENT
# =====================================================================

async def emit_lead_assigned(
    lead_id: int,
    officer_id: int,
    lead_data: dict,
    assignment_type: str = "automatic"
):
    """
    Emit Socket.IO event when a lead is assigned to an officer.

    This function notifies the officer immediately about their new lead assignment,
    enabling real-time updates in the officer's dashboard.

    Args:
        lead_id: ID of the lead being assigned
        officer_id: ID of the officer receiving the assignment
        lead_data: Dictionary containing lead details (name, phone, email, offering, etc.)
        assignment_type: Type of assignment ("automatic" or "manual")

    Events emitted:
        - "lead_assigned" to officer's room

    Payload structure:
        {
            "lead_id": int,
            "lead_name": str,
            "lead_phone": str,
            "lead_email": str,
            "offering_name": str,
            "unit_name": str,
            "assigned_at": str (ISO 8601),
            "assignment_type": "automatic" | "manual",
            "priority": str,
            "message": "You have been assigned a new lead: {lead_name}"
        }
    """
    try:
        from datetime import datetime, timezone

        # Target officer's room
        officer_room = f"user_room_{officer_id}"

        # Prepare event payload
        event_payload = {
            "lead_id": lead_id,
            "lead_name": lead_data.get("name", "Unknown"),
            "lead_phone": lead_data.get("phone", ""),
            "lead_email": lead_data.get("email", ""),
            "offering_name": lead_data.get("offering_name", ""),
            "unit_name": lead_data.get("unit_name", ""),
            "assigned_at": datetime.now(timezone.utc).isoformat(),
            "assignment_type": assignment_type,
            "priority": lead_data.get("priority", "normal"),
            "message": f"You have been assigned a new lead: {lead_data.get('name', 'Unknown')}"
        }

        # Emit event to officer's room
        await sio.emit(
            "lead_assigned",
            event_payload,
            room=officer_room
        )

        # Track metrics
        socket_events_emitted_total.labels(event_type="lead_assigned").inc()

        log.info(
            "Lead assignment notification sent to officer",
            lead_id=lead_id,
            officer_id=officer_id,
            assignment_type=assignment_type,
            officer_room=officer_room
        )

    except Exception as e:
        # Track failure metrics
        socket_emit_failures_total.labels(event_type="lead_assigned").inc()

        log.error(
            "Failed to emit lead assignment Socket.IO event",
            lead_id=lead_id,
            officer_id=officer_id,
            error=str(e),
            exc_info=True
        )
        # Don't raise - socket errors should not break assignment logic


async def emit_application_created(
    application_id: int,
    lead_id: int,
    officer_id: int,
    application_data: dict
):
    """
    Emit Socket.IO event when a new application is created.

    This function notifies the officer immediately about the new application
    creation, enabling real-time updates.

    Args:
        application_id: ID of the application created
        lead_id: ID of the lead
        officer_id: ID of the officer
        application_data: Dictionary containing application details

    Events emitted:
        - "application_created" to officer's room + admin broadcast

    Payload structure:
        {
            "application_id": int,
            "lead_id": int,
            "lead_name": str,
            "officer_id": int,
            "major_program_name": str,
            "status": str,
            "created_at": str (ISO 8601),
            "message": "New application created for {lead_name}"
        }
    """
    try:
        from datetime import datetime, timezone

        # Target rooms: officer + admins
        officer_room = f"user_room_{officer_id}"
        admin_room = "role_admin"

        # Prepare event payload
        event_payload = {
            "application_id": application_id,
            "lead_id": lead_id,
            "lead_name": application_data.get("lead_name", "Unknown"),
            "officer_id": officer_id,
            "major_program_name": application_data.get("major_program_name", "N/A"),
            "status": application_data.get("status", "pending"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": f"New application created for {application_data.get('lead_name', 'Unknown')}"
        }

        # Emit to officer's room
        await sio.emit(
            "application_created",
            event_payload,
            room=officer_room
        )

        # Emit to admin room (broadcast)
        await sio.emit(
            "application_created",
            event_payload,
            room=admin_room
        )

        # Track metrics
        socket_events_emitted_total.labels(event_type="application_created").inc()

        log.info(
            "Application created notification sent",
            application_id=application_id,
            lead_id=lead_id,
            officer_id=officer_id,
            officer_room=officer_room,
            admin_room=admin_room
        )

    except Exception as e:
        # Track failure metrics
        socket_emit_failures_total.labels(event_type="application_created").inc()

        log.error(
            "Failed to emit application_created Socket.IO event",
            application_id=application_id,
            lead_id=lead_id,
            officer_id=officer_id,
            error=str(e),
            exc_info=True
        )
        # Don't raise - socket errors should not break application creation logic


async def emit_application_status_changed(
    application_id: int,
    lead_id: int,
    officer_id: int,
    old_status: str,
    new_status: str,
    changed_by_username: str
):
    """
    Emit Socket.IO event when application status changes.

    This function notifies the officer and admins immediately about status changes,
    enabling real-time tracking of application progress.

    Args:
        application_id: ID of the application
        lead_id: ID of the lead
        officer_id: ID of the officer
        old_status: Previous status
        new_status: New status
        changed_by_username: Username who made the change

    Events emitted:
        - "application_status_changed" to officer's room + admin broadcast

    Payload structure:
        {
            "application_id": int,
            "lead_id": int,
            "old_status": str,
            "new_status": str,
            "changed_by": str,
            "changed_at": str (ISO 8601),
            "message": "Application status changed from {old} to {new}"
        }
    """
    try:
        from datetime import datetime, timezone

        # Target rooms: officer + admins
        officer_room = f"user_room_{officer_id}"
        admin_room = "role_admin"

        # Prepare event payload
        event_payload = {
            "application_id": application_id,
            "lead_id": lead_id,
            "old_status": old_status,
            "new_status": new_status,
            "changed_by": changed_by_username,
            "changed_at": datetime.now(timezone.utc).isoformat(),
            "message": f"Application status changed from {old_status} to {new_status}"
        }

        # Emit to officer's room
        await sio.emit(
            "application_status_changed",
            event_payload,
            room=officer_room
        )

        # Emit to admin room (broadcast)
        await sio.emit(
            "application_status_changed",
            event_payload,
            room=admin_room
        )

        # Track metrics
        socket_events_emitted_total.labels(event_type="application_status_changed").inc()

        log.info(
            "Application status change notification sent",
            application_id=application_id,
            lead_id=lead_id,
            officer_id=officer_id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by_username
        )

    except Exception as e:
        # Track failure metrics
        socket_emit_failures_total.labels(event_type="application_status_changed").inc()

        log.error(
            "Failed to emit application_status_changed Socket.IO event",
            application_id=application_id,
            lead_id=lead_id,
            officer_id=officer_id,
            old_status=old_status,
            new_status=new_status,
            error=str(e),
            exc_info=True
        )
        # Don't raise - socket errors should not break application update logic


async def emit_application_documents_updated(
    application_id: int,
    lead_id: int,
    officer_id: int,
    updated_by_username: str,
    documents_summary: str = "Documents updated"
):
    """
    Emit Socket.IO event when application documents are updated.

    This function notifies the officer and admins immediately about document updates,
    enabling real-time tracking of application completeness.

    Args:
        application_id: ID of the application
        lead_id: ID of the lead
        officer_id: ID of the officer
        updated_by_username: Username who made the update
        documents_summary: Brief summary of the update

    Events emitted:
        - "application_documents_updated" to officer's room + admin broadcast

    Payload structure:
        {
            "application_id": int,
            "lead_id": int,
            "updated_by": str,
            "updated_at": str (ISO 8601),
            "documents_summary": str,
            "message": "Application documents updated"
        }
    """
    try:
        from datetime import datetime, timezone

        # Target rooms: officer + admins
        officer_room = f"user_room_{officer_id}"
        admin_room = "role_admin"

        # Prepare event payload
        event_payload = {
            "application_id": application_id,
            "lead_id": lead_id,
            "updated_by": updated_by_username,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "documents_summary": documents_summary,
            "message": "Application documents updated"
        }

        # Emit to officer's room
        await sio.emit(
            "application_documents_updated",
            event_payload,
            room=officer_room
        )

        # Emit to admin room (broadcast)
        await sio.emit(
            "application_documents_updated",
            event_payload,
            room=admin_room
        )

        # Track metrics
        socket_events_emitted_total.labels(event_type="application_documents_updated").inc()

        log.info(
            "Application documents update notification sent",
            application_id=application_id,
            lead_id=lead_id,
            officer_id=officer_id,
            updated_by=updated_by_username
        )

    except Exception as e:
        # Track failure metrics
        socket_emit_failures_total.labels(event_type="application_documents_updated").inc()

        log.error(
            "Failed to emit application_documents_updated Socket.IO event",
            application_id=application_id,
            lead_id=lead_id,
            officer_id=officer_id,
            error=str(e),
            exc_info=True
        )
        # Don't raise - socket errors should not break application update logic


async def emit_pipeline_config_updated(
    config_type: str,
    operation: str,
    resource_id: str,
    resource_data: dict,
    updated_by_username: str
):
    """
    Emit Socket.IO event when pipeline configuration is updated.

    This function notifies all admins immediately about pipeline config changes,
    enabling real-time UI updates for pipeline management.

    Args:
        config_type: Type of config ("pipeline_stage", "consultation_status", "allowed_transition")
        operation: Operation performed ("create", "update", "delete")
        resource_id: ID of the affected resource
        resource_data: Dictionary containing resource details
        updated_by_username: Username who made the change

    Events emitted:
        - "pipeline_config_updated" to admin broadcast (role_admin)

    Payload structure:
        {
            "config_type": "pipeline_stage" | "consultation_status" | "allowed_transition",
            "operation": "create" | "update" | "delete",
            "resource_id": str | int,
            "resource_data": {
                # Stage/Status/Transition details
            },
            "updated_by": str,
            "updated_at": str (ISO 8601),
            "message": "Pipeline stage '{name}' was created"
        }
    """
    try:
        from datetime import datetime, timezone

        # Target: Broadcast to all admins
        admin_room = "role_admin"

        # Generate human-readable message
        operation_text = {
            "create": "created",
            "update": "updated",
            "delete": "deleted"
        }.get(operation, operation)

        config_type_text = {
            "pipeline_stage": "Pipeline stage",
            "consultation_status": "Consultation status",
            "allowed_transition": "Allowed transition"
        }.get(config_type, config_type)

        resource_name = resource_data.get("name", resource_data.get("id", str(resource_id)))
        message = f"{config_type_text} '{resource_name}' was {operation_text}"

        # Prepare event payload
        event_payload = {
            "config_type": config_type,
            "operation": operation,
            "resource_id": resource_id,
            "resource_data": resource_data,
            "updated_by": updated_by_username,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message": message
        }

        # Emit to admin room (broadcast)
        await sio.emit(
            "pipeline_config_updated",
            event_payload,
            room=admin_room
        )

        # Track metrics
        socket_events_emitted_total.labels(event_type="pipeline_config_updated").inc()

        log.info(
            "Pipeline config update notification sent to admins",
            config_type=config_type,
            operation=operation,
            resource_id=resource_id,
            updated_by=updated_by_username,
            admin_room=admin_room
        )

    except Exception as e:
        # Track failure metrics
        socket_emit_failures_total.labels(event_type="pipeline_config_updated").inc()

        log.error(
            "Failed to emit pipeline_config_updated Socket.IO event",
            config_type=config_type,
            operation=operation,
            resource_id=resource_id,
            error=str(e),
            exc_info=True
        )
        # Don't raise - socket errors should not break pipeline config operations
