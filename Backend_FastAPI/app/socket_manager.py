# app/socket_manager.py

import asyncio
import json
import math
import os
import threading
import uuid

import redis as _redis_sync  # sync client for the heartbeat watchdog thread
import socketio
import structlog
from fastapi import HTTPException

from . import models, security
from .core.constants import UserRole
from .config import settings
from .database import AsyncSessionLocal, redis_client, safe_redis_get
from .utils.token_logging import token_fingerprint
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
# PR-5 (2026-05-28): token[:8] leaked partial entropy into logs. Now use
# SHA-256 fingerprint (one-way, stable for log correlation).
# token_fingerprint is imported at the module top (relative import) —
# token_logging only depends on hashlib so there is no circular-import risk.
def sanitize_token(token: str) -> str:
    return token_fingerprint(token) if token else "None"


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

            # DB-authoritative session cross-check (parity with HTTP deps STEP 4).
            # The Redis session:{jti} hit above can be stale (cleanup miss) or a
            # phantom (Redis-only, no DB row). Require a non-revoked, non-expired
            # DB session row for THIS jti, else reject — closes token resurrection
            # after reactivate + login clears user_blacklist.
            from app.repositories import SessionRepository
            db_session = await SessionRepository(db).get_by_refresh_jti_and_user(
                refresh_jti, user.id
            )
            if db_session is None:
                log.warning(
                    "Socket auth rejected: no non-revoked DB session (stale/phantom)",
                    user_id=user.id,
                    jti=refresh_jti,
                )
                raise HTTPException(
                    status_code=401, detail="Session revoked or expired"
                )

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
            
            # R1+R2: Pending login notifications are now handled via Client-Pull model
            # Client emits "get_pending_login_notifications" after registering listeners
            # See: @sio.event get_pending_login_notifications() handler below

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


# R1+R2: get_pending_login_notifications handler REMOVED
# Login notification is now included directly in the login API response
# See: auth.py login_for_access_token() - login_notification_data field


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

            # Fail-closed: a session without user_id/jti cannot be validated
            # against the DB (the exact-jti check below would be skipped),
            # leaving it permanently trusted. Disconnect immediately.
            if not user_id or not refresh_jti:
                log.warning(
                    "Revalidation failed: missing user_id/jti in socket session",
                    sid=sid,
                    user_id=user_id,
                )
                await sio.disconnect(sid)
                return {"valid": False, "reason": "Invalid session"}

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

            # DB-authoritative cross-check for THIS jti (NOT "any active session"
            # of the user). The old code passed an old/revoked socket as long as
            # the user had *some* active session — so a fresh login after
            # deactivate→reactivate kept a stale socket alive. Require a
            # non-revoked, non-expired DB row matching exactly refresh_jti.
            if refresh_jti:
                async with AsyncSessionLocal() as db:
                    from app.repositories import SessionRepository

                    db_session = await SessionRepository(
                        db
                    ).get_by_refresh_jti_and_user(refresh_jti, user_id)
                if db_session is None:
                    log.warning(
                        "Revalidation failed: session revoked/expired in DB (exact jti)",
                        sid=sid,
                        user_id=user_id,
                        jti=refresh_jti,
                    )
                    await sio.disconnect(sid)
                    return {"valid": False, "reason": "Session revoked"}

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


# =====================================================================
# SERVER-SIDE FORCE-DISCONNECT (enforcement, NOT client-dependent)
# =====================================================================
# emit_force_logout() above only EMITS an event the client must honour — a
# custom/malicious client can ignore it and keep receiving realtime. For real
# offboarding we disconnect sockets server-side, across ALL Gunicorn workers,
# with confirmation. Mechanism: the offboarding request publishes a command on a
# Redis channel; every worker runs a subscriber that disconnects its LOCAL
# participants (AsyncRedisManager.get_participants is local-only) and ACKs. The
# publisher BLOCKS until every REQUIRED worker ACKs, else raises → the admin
# request rolls back the status change (fail-closed).
#
# A "required" worker is any registered worker whose heartbeat key still exists.
# The heartbeat is refreshed by a DEDICATED THREAD (not a coroutine) so it keeps
# proving "process alive" even when the event loop stalls — a stalled worker then
# stays in the required set but cannot ACK → fail-closed. A worker that cannot
# refresh its heartbeat (Redis unreachable) or whose process dies stops the
# thread, so a missing heartbeat key (past the TTL grace) provably means the
# process exited and its sockets are closed. A worker with a live heartbeat that
# fails to ACK makes offboarding fail-closed (NOT pruned).
FORCE_DISCONNECT_CHANNEL = "socket:force_disconnect"
_WORKERS_SET = "socket:workers"
_WORKER_HB_PREFIX = "socket:worker_hb:"
_ACK_PREFIX = "socket:dc_ack:"
# TTL must exceed the max tolerated event-loop stall; a worker that stops
# refreshing self-terminates, so key-gone (past this grace) == process gone.
_WORKER_HB_TTL = 30        # heartbeat key lifetime / death grace (s)
_WORKER_HB_REFRESH = 5     # heartbeat refresh interval (s)
_ACK_TTL = 30             # ack-set cleanup backstop (s)
_ACK_TIMEOUT = 3.0        # publisher waits for all required workers (s)
_ACK_POLL = 0.1          # ack poll interval (s)

# Unique id for THIS worker process (set by register_socket_worker at startup).
_worker_id = None

_HB_MAX_FAILS = 3        # consecutive heartbeat-thread refresh failures → os._exit
_hb_thread = None        # heartbeat watchdog thread (independent of event loop)
_hb_stop = None          # threading.Event used to stop the heartbeat thread


async def register_socket_worker():
    """Register this worker: write heartbeat FIRST, then add to the set (so a
    worker is never in the set without a live heartbeat). Called once at startup
    AFTER the subscriber is listening; caller treats failure as fatal."""
    global _worker_id
    _worker_id = uuid.uuid4().hex
    await redis_client.set(_WORKER_HB_PREFIX + _worker_id, "1", ex=_WORKER_HB_TTL)
    await redis_client.sadd(_WORKERS_SET, _worker_id)
    log.info("Socket worker registered", worker_id=_worker_id)
    return _worker_id


async def deregister_socket_worker():
    """Remove this worker from the set + drop its heartbeat (graceful exit)."""
    if not _worker_id:
        return
    try:
        await redis_client.srem(_WORKERS_SET, _worker_id)
        await redis_client.delete(_WORKER_HB_PREFIX + _worker_id)
    except Exception as e:
        log.error("Socket worker deregister failed", worker_id=_worker_id, error=str(e))


def _heartbeat_thread_run(worker_id, stop_event):
    """Runs in a DEDICATED THREAD, independent of the asyncio event loop, so the
    heartbeat keeps proving 'process alive' even if the event loop STALLS. If the
    loop hangs, this worker stays in the required ACK set (heartbeat still alive)
    but cannot ACK → the offboarding request times out and rolls back
    (fail-closed). A coroutine heartbeat could NOT do this: a stalled loop never
    runs it, the key expires, and the worker would be wrongly pruned while its
    sockets are still alive. If Redis is unreachable for too long, terminate the
    process so its sockets close (heartbeat-gone then provably == process-gone).
    Gunicorn's worker `timeout` (120s) > TTL (30s), so without this thread a
    31–119s stall would silently drop a live worker."""
    # Finite socket timeouts are REQUIRED: with the default (infinite) timeout a
    # network blackhole makes client.set() hang past the TTL, the key expires and
    # the worker is pruned while its process/sockets are still alive. With a 2s
    # timeout, 3 consecutive failures trip os._exit well before the 30s TTL
    # (~3×(2+5)s ≈ 21s), so heartbeat-gone still implies process-gone.
    client = _redis_sync.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=False,
    )
    fails = 0
    try:
        while not stop_event.is_set():
            try:
                client.set(_WORKER_HB_PREFIX + worker_id, "1", ex=_WORKER_HB_TTL)
                fails = 0
            except Exception as e:
                fails += 1
                log.error(
                    "Heartbeat thread refresh failed",
                    worker_id=worker_id,
                    attempt=fails,
                    error=str(e),
                )
                if fails >= _HB_MAX_FAILS:
                    log.critical(
                        "Heartbeat unrecoverable — exiting worker (Gunicorn restart)",
                        worker_id=worker_id,
                    )
                    os._exit(1)
            stop_event.wait(_WORKER_HB_REFRESH)
    finally:
        try:
            client.close()
        except Exception:
            pass


def start_heartbeat_thread():
    """Start the heartbeat watchdog thread (call AFTER register_socket_worker)."""
    global _hb_thread, _hb_stop
    _hb_stop = threading.Event()
    _hb_thread = threading.Thread(
        target=_heartbeat_thread_run,
        args=(_worker_id, _hb_stop),
        name="socket-heartbeat",
        daemon=True,
    )
    _hb_thread.start()
    log.info("Socket heartbeat thread started", worker_id=_worker_id)


def stop_heartbeat_thread():
    """Signal the heartbeat thread to stop and join it (graceful shutdown)."""
    if _hb_stop is not None:
        _hb_stop.set()
    if _hb_thread is not None:
        _hb_thread.join(timeout=5)


async def _required_workers():
    """Workers that MUST ACK a force-disconnect: every registered worker whose
    heartbeat key still EXISTS. Entries whose key is gone (past the TTL grace)
    are pruned — a worker that stopped refreshing self-terminated (os._exit), so
    its process is gone and sockets closed. We do NOT prune a worker that merely
    fails to ACK while its heartbeat is live: that path stays fail-closed."""
    members = await redis_client.smembers(_WORKERS_SET)  # decode_responses → str
    required, dead = set(), set()
    for wid in members:
        if await redis_client.exists(_WORKER_HB_PREFIX + wid):
            required.add(wid)
        else:
            dead.add(wid)  # heartbeat gone past grace → process exited
    if dead:
        await redis_client.srem(_WORKERS_SET, *dead)
    return required


async def force_disconnect_user(user_ids) -> int:
    """LOCAL: disconnect every SID of the given user(s) on THIS worker. Accepts a
    single id or an iterable. Snapshots participants first (disconnect mutates
    room membership). Raises on any disconnect failure → caller does NOT ACK →
    publisher times out (fail-closed)."""
    if isinstance(user_ids, int):
        user_ids = [user_ids]
    user_ids = list(user_ids)
    count = 0
    for uid in user_ids:
        room = f"user_room_{uid}"
        sids = [sid for sid, _ in sio.manager.get_participants("/", room)]
        for sid in sids:
            await sio.disconnect(sid)
            count += 1
    log.info("force_disconnect_user (local)", user_ids=user_ids, disconnected=count)
    return count


async def _handle_force_disconnect(raw: str):
    """Subscriber handler: disconnect the whole batch locally, then ACK ONCE.
    No ACK if the disconnect raises (publisher fail-closes)."""
    data = json.loads(raw)
    command_id = data["command_id"]
    await force_disconnect_user(data["user_ids"])  # raises → no ACK below
    ack_key = _ACK_PREFIX + command_id
    await redis_client.sadd(ack_key, _worker_id)
    await redis_client.expire(ack_key, _ACK_TTL)


async def subscribe_force_disconnect():
    """Create the pubsub and AWAIT the SUBSCRIBE before returning, so the caller
    registers this worker as live only AFTER it is actually listening."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(FORCE_DISCONNECT_CHANNEL)
    return pubsub


async def consume_force_disconnect(pubsub):
    """Background consumer loop. Raises/returns on fatal pubsub error → the
    lifespan supervisor terminates the worker so Gunicorn restarts it."""
    log.info("Force-disconnect subscriber listening", worker_id=_worker_id)
    try:
        async for message in pubsub.listen():
            if not message or message.get("type") != "message":
                continue
            try:
                await _handle_force_disconnect(message["data"])
            except Exception as e:
                # Handler failure → deliberately do NOT ACK so the publisher
                # times out and fail-closes. Keep consuming other commands.
                log.error("Force-disconnect handler failed (no ACK)", error=str(e))
    finally:
        try:
            await pubsub.unsubscribe(FORCE_DISCONNECT_CHANNEL)
            await pubsub.aclose()
        except Exception:
            pass


async def force_disconnect_user_strict(
    user_ids, *, timeout: float = _ACK_TIMEOUT
) -> str:
    """ENFORCEMENT: publish ONE force-disconnect command for the whole batch and
    BLOCK until every required worker ACKs, else raise (fail-closed). Redis
    PUBLISH only reports how many subscribers RECEIVED the message — not that
    they processed it — so we require explicit per-worker ACKs. A single batched
    command bounds the admin request to ONE timeout regardless of batch size."""
    if isinstance(user_ids, int):
        user_ids = [user_ids]
    user_ids = list(user_ids)
    if not user_ids:
        return ""
    command_id = uuid.uuid4().hex
    ack_key = _ACK_PREFIX + command_id
    # Snapshot required workers BEFORE publishing. Workers that start AFTER are
    # not required to ACK (they hold no sockets predating the command).
    required = await _required_workers()
    if not required:
        # No worker alive → cannot guarantee enforcement → fail-closed.
        raise RuntimeError("No live socket workers to enforce force-disconnect")
    payload = json.dumps({"command_id": command_id, "user_ids": user_ids})
    await redis_client.publish(FORCE_DISCONNECT_CHANNEL, payload)
    try:
        max_polls = max(1, int(math.ceil(timeout / _ACK_POLL)))
        acked = set()
        for _ in range(max_polls):
            acked = set(await redis_client.smembers(ack_key))
            if required <= acked:
                break
            await asyncio.sleep(_ACK_POLL)
        missing = required - acked
        if missing:
            log.error(
                "force_disconnect_user_strict: ACK timeout",
                user_ids=user_ids,
                command_id=command_id,
                missing=list(missing),
            )
            raise TimeoutError(
                f"Force-disconnect not ACKed by workers: {sorted(missing)}"
            )
        log.info(
            "force_disconnect_user_strict OK",
            user_ids=user_ids,
            workers=len(required),
        )
        return command_id
    finally:
        try:
            await redis_client.delete(ack_key)
        except Exception:
            pass


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
