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


async def _get_user_from_token(token: str) -> models.User:
    """Hàm helper xác thực token (sử dụng V3)."""
    try:
        payload = security.decode_token(token)
        username: str | None = payload.get("sub")
        refresh_jti: str | None = payload.get("r_jti")

        if not username or not refresh_jti:
            raise HTTPException(status_code=400, detail="Invalid token claims")

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
            return user

    except Exception as e:
        # Log lỗi mà không log token
        log.warning("Socket auth failed", error=str(e))
        raise ConnectionRefusedError("Auth failed")


@sio.event
async def connect(sid, environ, auth):
    """Sự kiện connect (V5) - Tích hợp Rate Limiting Redis LUA."""
    async with track_event_latency("connect"):  # ✅ Theo dõi latency
        client_ip = environ.get("REMOTE_ADDR") or "unknown_ip"
        token = auth.get("token")

        # === ✅ CẢI TIẾN: Rate Limiting bằng Redis LUA ===
        if not await check_rate_limit(client_ip):
            log.warning("Socket rate limit exceeded", client_ip=client_ip)
            socket_auth_failures_total.inc()
            raise ConnectionRefusedError("Rate limit exceeded")

        try:
            if not token:
                raise ConnectionRefusedError("Authentication failed: No token")

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
