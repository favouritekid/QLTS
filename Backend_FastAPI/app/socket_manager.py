# app/socket_manager.py

import socketio
import structlog
from fastapi import HTTPException

from . import models, security, services
from .config import settings
from .database import AsyncSessionLocal, redis_client, safe_redis_get
from .socket_metrics import track_event_latency  # ✅ Thêm latency tracker
from .socket_metrics import (
    socket_auth_failures_total,
    socket_connections_active,
    socket_events_received_total,
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
    """Kiểm tra rate limit bằng Redis LUA Script (atomic và hiệu quả)."""
    if not redis_client or not RATE_LIMIT_SCRIPT_SHA:
        log.warning("Redis or LUA script not ready, skipping rate limit (fail-open).")
        return True

    key = f"socket_rate_limit:{client_ip}"
    try:
        # Chạy script bằng SHA (nhanh hơn)
        result = await redis_client.evalsha(
            RATE_LIMIT_SCRIPT_SHA, 1, key, MAX_CONN_PER_MINUTE, 60  # TTL 60 giây
        )
        return bool(result)
    except Exception as e:
        log.error(
            "Redis LUA script (evalsha) failed, falling back to eval", error=str(e)
        )
        # Fallback: Thử load và chạy lại script (chỉ 1 lần)
        try:
            await load_rate_limit_script()  # Tải lại script
            result = await redis_client.evalsha(
                RATE_LIMIT_SCRIPT_SHA, 1, key, MAX_CONN_PER_MINUTE, 60
            )
            return bool(result)
        except Exception as e2:
            log.error("Redis rate limit check totally failed", error=str(e2))
            return True  # Fail-open


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
            user = await services.user_service.get_user_by_username(
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
        if not token:
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
