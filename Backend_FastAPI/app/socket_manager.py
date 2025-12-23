# app/socket_manager.py

import socketio
import structlog
from fastapi import HTTPException

from . import models, security
from .core.constants import UserRole
from .config import settings
from .database import AsyncSessionLocal, redis_client, safe_redis_get
# NOTE: user_service import moved inside function to avoid circular import
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


# ✅ CRITICAL FIX: AsyncRedisManager for Pub/Sub across processes
# Without this, Celery tasks cannot broadcast Socket.IO events to clients
# connected to the FastAPI server (they run in separate processes)
client_manager = None
if settings.REDIS_URL:
    try:
        client_manager = socketio.AsyncRedisManager(settings.REDIS_URL)
        log.info("✅ Socket.IO Redis Manager initialized for cross-process Pub/Sub")
    except Exception as e:
        log.error("Failed to initialize Socket.IO Redis Manager", error=str(e))
        log.warning("⚠️ Celery tasks will NOT be able to broadcast Socket.IO events")

# ✅ FIX: Parse CORS origins with whitespace stripping (same as main.py CORS middleware)
# This prevents issues with spaces in .env like: "http://localhost:3000, http://127.0.0.1:3000"
cors_origins_list = [
    origin.strip() for origin in settings.CORS_ORIGINS.split(",")
] if settings.CORS_ORIGINS else []
log.info("Socket.IO CORS origins configured", origins=cors_origins_list)

sio = socketio.AsyncServer(
    async_mode="asgi",
    # ✅ FIX: Use properly parsed CORS origins (with whitespace stripped)
    cors_allowed_origins=cors_origins_list,
    # ✅ FIX: Enable credentials to allow httpOnly cookies in WebSocket handshake
    engineio_cors_credentials=True,
    # ✅ FIX: Disable internal loggers to reduce noise (we have our own structured logs)
    logger=False,
    engineio_logger=False,
    # ✅ CRITICAL: Add Redis manager for cross-process communication (Celery → API server)
    client_manager=client_manager,
)

# === ✅ CẢI TIẾN: Vấn đề #1 - Rate Limiting bằng Redis LUA Script ===
# Configuration now comes from settings (see config.py)
# Can be overridden via SOCKET_MAX_CONN_PER_MINUTE environment variable
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

    ✅ FIX: Fail-open strategy + Development bypass
    - Development: Always allow (React HMR + Strict Mode cause rapid reconnections)
    - Production: If Redis is unavailable, ALLOW connection with warning (fail-open)
    - Trade-off: Availability > Security for internal systems

    Rationale for fail-open:
    - Authentication still enforced (Redis failure doesn't bypass auth)
    - Rate limiting is defense-in-depth, not primary security
    - Internal system (not public-facing), acceptable risk
    - Monitoring should alert on Redis failures
    - Avoids service disruption from Redis hiccups
    """
    # ✅ FIX: Bypass rate limiting in development (React HMR + Strict Mode)
    if settings.APP_ENV == "development":
        log.debug("Rate limiting bypassed in development", client_ip=client_ip)
        return True

    # ✅ FIX: Fail-open strategy - allow connection if Redis unavailable
    if not redis_client or not RATE_LIMIT_SCRIPT_SHA:
        log.warning(
            "⚠️ Rate limiter skipped (Redis/Script unavailable) - allowing connection (fail-open)",
            client_ip=client_ip
        )
        return True

    key = f"socket_rate_limit:{client_ip}"
    try:
        # Chạy script bằng SHA (nhanh hơn)
        result = await redis_client.evalsha(
            RATE_LIMIT_SCRIPT_SHA, 1, key, settings.SOCKET_MAX_CONN_PER_MINUTE, 60  # TTL 60 giây
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
                RATE_LIMIT_SCRIPT_SHA, 1, key, settings.SOCKET_MAX_CONN_PER_MINUTE, 60
            )
            return bool(result)
        except Exception as e2:
            # ✅ FIX: Fail-open - allow connection if rate limit check fails
            log.warning(
                "⚠️ Rate limit check failed completely - allowing connection (fail-open)",
                error=str(e2),
                client_ip=client_ip
            )
            return True


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
            # Import here to avoid circular import
            from .services import user_service
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
        rate_limit_ok = await check_rate_limit(client_ip)

        if not rate_limit_ok:
            log.warning("Socket rate limit exceeded", client_ip=client_ip)
            socket_auth_failures_total.inc()
            raise ConnectionRefusedError("Rate limit exceeded")

        try:
            if not token:
                raise ConnectionRefusedError("Authentication failed: No token in cookie or auth")

            user = await _get_user_from_token(token)
            
            # ✅ SECURITY FIX: Extract JTI from token for session-specific room
            # We already verified the token in _get_user_from_token
            payload = security.decode_token(token)
            refresh_jti = payload.get("r_jti")

            # Save session with extended info
            await sio.save_session(sid, {
                "user_id": user.id,
                "username": user.username,
                "role": user.role,
                "unit_id": user.unit_id,
                "jti": refresh_jti  # Store JTI in socket session
            })

            # === Join rooms based on user attributes ===
            rooms_joined = []

            # 1. Personal room (always)
            room_name = f"user_room_{user.id}"
            await sio.enter_room(sid, room_name)
            rooms_joined.append(room_name)

            # 2. Session-specific room (Targeted Revocation)
            if refresh_jti:
                session_room = f"session_room_{refresh_jti}"
                await sio.enter_room(sid, session_room)
                rooms_joined.append(session_room)

            # 2. Role-based room (for role-specific broadcasts)
            if user.role:
                role_room = f"role_{user.role}"
                await sio.enter_room(sid, role_room)
                rooms_joined.append(role_room)

            # 3. Unit-based room (for unit-specific broadcasts)
            if user.unit_id:
                unit_room = f"unit_{user.unit_id}"
                await sio.enter_room(sid, unit_room)
                rooms_joined.append(unit_room)

            # 4. Admin room (for all admin users)
            if user.role == UserRole.ADMIN:
                await sio.enter_room(sid, "role_admin")
                if "role_admin" not in rooms_joined:
                    rooms_joined.append("role_admin")

            socket_connections_active.inc()

            log.info(
                "Socket client connected",
                sid=sid,
                user_id=user.id,
                username=user.username,
                rooms=rooms_joined,
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
            role = session.get("role")
            unit_id = session.get("unit_id")
            refresh_jti = session.get("jti")
            socket_connections_active.dec()  # Giảm bộ đếm

            # === Leave all rooms ===
            rooms_left = []

            # 1. Personal room
            room_name = f"user_room_{user_id}"
            await sio.leave_room(sid, room_name)
            rooms_left.append(room_name)

            # 2. Session room
            if refresh_jti:
                session_room = f"session_room_{refresh_jti}"
                await sio.leave_room(sid, session_room)
                rooms_left.append(session_room)

            # 2. Role room
            if role:
                role_room = f"role_{role}"
                await sio.leave_room(sid, role_room)
                rooms_left.append(role_room)

            # 3. Unit room
            if unit_id:
                unit_room = f"unit_{unit_id}"
                await sio.leave_room(sid, unit_room)
                rooms_left.append(unit_room)

            # 4. Admin room
            if role == UserRole.ADMIN:
                await sio.leave_room(sid, "role_admin")
                if "role_admin" not in rooms_left:
                    rooms_left.append("role_admin")

            log.info(
                "Socket client disconnected",
                sid=sid,
                user_id=user_id,
                username=session.get("username"),
                rooms=rooms_left,
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
            refresh_jti = session.get("jti")

            # Check if this specific session is still valid in Redis
            if refresh_jti:
                session_valid = await safe_redis_get(f"session:{refresh_jti}")
                if not session_valid:
                    log.warning(
                        "Revalidation failed: Session revoked",
                        sid=sid,
                        user_id=user_id,
                        jti=refresh_jti
                    )
                    await sio.disconnect(sid)
                    return {"valid": False, "reason": "Session revoked"}

            # Check user blacklist (Password changed or admin ban)
            is_blacklisted = await safe_redis_get(f"user_blacklist:{user_id}")
            if is_blacklisted:
                log.warning(
                    "Revalidation failed: User blacklisted",
                    sid=sid,
                    user_id=user_id
                )
                await sio.disconnect(sid)
                return {"valid": False, "reason": "User session invalidated"}

            # Fallback: Check if ANY active session exists in DB
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
                        "Revalidation failed: No active sessions in DB",
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
        # Track metrics
        socket_events_emitted_total.labels(event_type=event).inc()

        log.info(
            "Emitted event to all clients",
            socket_event=event,
            namespace=namespace,
            data_keys=list(data.keys())
        )
    except Exception as e:
        # Track failure metrics
        socket_emit_failures_total.labels(event_type=event).inc()

        log.error(
            "Failed to emit event to all clients",
            socket_event=event,
            error=str(e),
            exc_info=True
        )



# =====================================================================
# DEPRECATED FUNCTIONS REMOVED
# =====================================================================
# The following emit_* functions have been removed as they are now
# handled by notification_dispatcher.dispatch() which provides:
#   - Database persistence before sending
#   - Immediate Socket.IO emission
#   - Celery task queue for email delivery
#   - User preference filtering
#   - Deduplication support
#
# Removed functions:
#   - emit_lead_reassigned()
#   - emit_lead_created()
#   - emit_lead_assignment_failed()
#   - emit_lead_assigned()
#   - emit_application_created()
#   - emit_application_status_changed()
#   - emit_application_documents_updated()
#   - emit_pipeline_config_updated()
#   - emit_consultation_deleted()
#   - emit_consultation_updated()
#   - emit_consultation_created()
#   - emit_lead_updated()
# =====================================================================


# =====================================================================
# EVENT DISPATCHER HANDLERS (Architecture Refactoring)
# =====================================================================
# Services dispatch domain events → dispatcher routes to transport handlers
# This decouples service layer from Socket.IO (framework-agnostic)

from .core.events import dispatcher, TransportEvents


async def emit_force_logout(user_id: int, revoked_jtis: list, **kwargs):
    """
    Socket.IO handler for user.force_logout event.

    Args:
        user_id: User to logout
        revoked_jtis: List of revoked session JTIs. If empty, logout all sessions for user.
        **kwargs: Additional event data (ignored)
    """
    try:
        if revoked_jtis:
            # Targeted logout: Emit to specific session rooms
            for jti in revoked_jtis:
                session_room = f"session_room_{jti}"
                await sio.emit(
                    "force_logout_batch",
                    {"revoked_jtis": [jti]},
                    room=session_room
                )
            log.info("Emitted targeted force_logout_batch", user_id=user_id, count=len(revoked_jtis))
        else:
            # Broadcast logout: Emit to all user sessions
            room_name = f"user_room_{user_id}"
            await sio.emit(
                "force_logout_batch",
                {"revoked_jtis": []}, # Empty list means all
                room=room_name
            )
            log.warning("Emitted broadcast force_logout_batch (ALL)", user_id=user_id)
    except Exception as e:
        log.error("Failed to emit force_logout event", user_id=user_id, error=str(e))


async def emit_data_updated(event_data: dict, **kwargs):
    """
    Socket.IO handler for data.updated event.

    Args:
        event_data: Event payload with resource info
        **kwargs: Additional event data (ignored)
    """
    try:
        # Broadcast to all connected clients
        await sio.emit("data_updated", event_data)
        log.debug("Emitted data_updated event", resource=event_data.get("resource_type"))
    except Exception as e:
        log.error("Failed to emit data_updated event", error=str(e))


# Register handlers on module import
dispatcher.register(TransportEvents.USER_FORCE_LOGOUT, emit_force_logout)
dispatcher.register("data.updated", emit_data_updated)

log.info("✅ Event Dispatcher handlers registered", handlers=[
    f"{TransportEvents.USER_FORCE_LOGOUT} → emit_force_logout",
    "data.updated → emit_data_updated"
])
# =====================================================================
