# app/socket_manager.py

import asyncio
import json
import math
import os
import threading
import uuid
from typing import NamedTuple

import redis as _redis_sync  # sync client for the heartbeat watchdog thread
import socketio
import structlog
from fastapi import HTTPException

from . import models, security
from .core.constants import UserRole
from .config import settings
from .database import (
    AsyncSessionLocal,
    RedisUnavailableError,
    redis_client,
    redis_exists_or_raise,
    redis_get_or_raise,
    safe_redis_get,
)
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


# === F103: a socket belongs to a login SESSION, named by its stable id ===
# ``UserSession.id`` is set once at login and never changes; ``refresh_jti`` of
# the same row is ROTATED by every ``/auth/refresh``. A socket used to keep the
# refresh JTI it saw at handshake, both for ``revalidate_auth`` and for its
# revocation room — so after the client's first proactive refresh (~12 min)
# the next revalidation (15 min) found ``session:{old jti}`` gone and logged
# the user out (measured on prod 26-10), and a targeted revoke emitted to the
# room of the CURRENT jti, which the socket had never joined.
def session_room(session_id: int) -> str:
    """ONE name for the room of login session ``session_id`` (``UserSession.id``).

    Joined at ``connect``, left at ``disconnect``, targeted by
    ``emit_force_logout``. Keyed by the stable row id, never by a refresh JTI.
    """
    return f"user_session_{session_id}"


class SocketAuth(NamedTuple):
    """What a socket handshake authenticated: the user and the session row."""

    user: models.User
    session_id: int


async def _get_user_from_token(token: str) -> SocketAuth:
    """
    Hàm helper xác thực token cho WebSocket (V6 - with user blacklist check).

    ✅ FIX-3: Added user blacklist check for security parity with HTTP auth.
    Now checks 3 layers: JWT validity, session validity, user blacklist.

    F103: returns the user AND the id of the live DB session row the token's
    ``r_jti`` names — the stable identity the socket is bound to.
    """
    try:
        payload = security.decode_token(token)
        username: str | None = payload.get("sub")
        refresh_jti: str | None = payload.get("r_jti")

        if not username or not refresh_jti:
            raise HTTPException(status_code=400, detail="Invalid token claims")

        # Check session validity. Lenient on purpose, unlike deps STEP 4 and
        # ``revalidate_auth``: a read Redis did not answer refuses the
        # connection here (None ⇒ 401 below; an OPEN breaker's error ⇒ the
        # ``except`` at the end), which is fail-closed and costs no logout —
        # the client retries a refused connect a few times, then stops quietly.
        # Letting the DB decide would widen what connects: connect never reads
        # ``blacklist:{access_jti}``.
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
            # Strict read, same contract as HTTP deps STEP 3: a read Redis did
            # not answer refuses the connection. The lenient GET read "no
            # answer" as "not blacklisted", and the DB fallback that ran once
            # the breaker was OPEN ("the user has SOME active session") was
            # already true after the exact-jti check above, so a revoked user
            # connected either way. Logs carry user_id and the exception
            # CLASS; never the Redis key or the exception message.
            try:
                is_user_blacklisted = await redis_exists_or_raise(
                    f"user_blacklist:{user.id}", "auth.user_blacklist"
                )
            except RedisUnavailableError:
                log.error(
                    "Socket auth deferred: user blacklist unreadable",
                    user_id=user.id,
                    action="socket.auth_state_unavailable",
                )
                raise ConnectionRefusedError("Auth state unavailable") from None
            except Exception as exc:
                log.error(
                    "Socket auth refused: user blacklist check failed",
                    user_id=user.id,
                    error_type=type(exc).__name__,
                    action="socket.user_blacklist_error",
                )
                raise ConnectionRefusedError("Auth failed") from None
            if is_user_blacklisted:
                log.warning(
                    "Socket auth rejected: User in global blacklist (password changed?)",
                    user_id=user.id
                )
                raise HTTPException(
                    status_code=401,
                    detail="User session invalidated"
                )

            return SocketAuth(user=user, session_id=db_session.id)

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

            auth_result = await _get_user_from_token(token)
            user = auth_result.user

            # Save session with extended info. F103: the socket is bound to the
            # STABLE id of its DB session row (``session_id``), NOT to the
            # refresh JTI of the handshake token — /auth/refresh rotates that
            # JTI on the same row. No ``jti`` is stored: nothing may read a
            # value that goes stale on the first refresh.
            await sio.save_session(sid, {
                "user_id": user.id,
                "username": user.username,
                "role": user.role,
                "unit_id": user.unit_id,
                "session_id": auth_result.session_id,
            })

            # === Join rooms based on user attributes ===
            rooms_joined = []

            # 1. Personal room (always)
            room_name = f"user_room_{user.id}"
            await sio.enter_room(sid, room_name)
            rooms_joined.append(room_name)

            # 2. Session-specific room (Targeted Revocation), keyed by the
            # stable session id so a revoke after any number of refreshes
            # still reaches every socket (tab) of this session.
            own_session_room = session_room(auth_result.session_id)
            await sio.enter_room(sid, own_session_room)
            rooms_joined.append(own_session_room)

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
            session_id = session.get("session_id")
            socket_connections_active.dec()  # Giảm bộ đếm

            # === Leave all rooms ===
            rooms_left = []

            # 1. Personal room
            room_name = f"user_room_{user_id}"
            await sio.leave_room(sid, room_name)
            rooms_left.append(room_name)

            # 2. Session room (stable session id, F103)
            if session_id:
                own_session_room = session_room(session_id)
                await sio.leave_room(sid, own_session_room)
                rooms_left.append(own_session_room)

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


async def _session_refusal_reason(sid, user_id: int, session_id: int) -> str | None:
    """The periodic checks of socket ``sid``, bound to DB session ``session_id``.

    Returns None when the session is still valid, else the refusal reason
    (already logged); ``revalidate_auth`` then disconnects SERVER-side. A DB
    error raises: the caller answers ``Validation error`` and disconnects
    (fail-closed), as before.

    F103: the socket names its session by the stable row id, so the refresh
    JTI is RESOLVED here on every run — the row's current one, not the one of
    the handshake token. Every check after that is the per-JTI check this
    handler always ran (Redis ``session:{jti}`` cache, strict
    ``user_blacklist``, the shared live predicate), in the same order.

    Everything runs in ONE DB transaction that holds the row ``FOR SHARE``
    (``get_refresh_jti_for_share``): an in-flight /auth/refresh (row locked,
    Redis already rotated, DB not yet committed) is waited for instead of
    half-seen, and no new rotation can start between the reads below.
    """
    from app.repositories import SessionRepository

    async with AsyncSessionLocal() as db:
        repo = SessionRepository(db)

        refresh_jti = await repo.get_refresh_jti_for_share(session_id, user_id)
        if refresh_jti is None:
            log.warning(
                "Revalidation failed: no session row of this user (session id)",
                sid=sid,
                user_id=user_id,
                session_id=session_id,
            )
            return "Session revoked"

        # Check if this specific session is still valid in Redis.
        # Three answers, as in HTTP deps STEP 4: ``session:{jti}`` is a
        # CACHE of the DB row checked below.
        # - Redis ANSWERED "no such key" ⇒ revoked, disconnect (fast path).
        # - Redis did not answer (ConnectionError/TimeoutError, OPEN
        #   breaker) ⇒ NOT "revoked". The lenient read said "revoked" for
        #   a connection/timeout error ("Validation error" for an OPEN
        #   breaker), and the frontend logs the user out on any
        #   ``valid: False`` (``frontend/src/lib/socket/client.ts``). Not a
        #   pass either: the strict ``user_blacklist`` read and the
        #   exact-jti DB check below still run, and only they reach
        #   ``valid: True``.
        try:
            cached = await redis_get_or_raise(
                f"session:{refresh_jti}", "auth.session"
            )
            session_valid = bool(cached)
        except RedisUnavailableError:
            log.warning(
                "Revalidation: session cache unreadable; the DB row decides",
                sid=sid,
                user_id=user_id,
                action="socket.session_cache_unavailable",
            )
            session_valid = None
        if session_valid is False:
            log.warning(
                "Revalidation failed: Session revoked",
                sid=sid,
                user_id=user_id,
                jti=refresh_jti
            )
            return "Session revoked"

        # Check user blacklist (Password changed or admin ban)
        # Strict read, same contract as connect: a read Redis did not
        # answer disconnects. The lenient GET read "no answer" as "not
        # blacklisted" and kept the socket serving events. Logs carry
        # user_id and the exception CLASS; never the key or the message.
        try:
            is_blacklisted = await redis_exists_or_raise(
                f"user_blacklist:{user_id}", "auth.user_blacklist"
            )
        except RedisUnavailableError:
            log.error(
                "Revalidation deferred: user blacklist unreadable",
                sid=sid,
                user_id=user_id,
                action="socket.auth_state_unavailable",
            )
            return "Auth state unavailable"
        except Exception as exc:
            log.error(
                "Revalidation refused: user blacklist check failed",
                sid=sid,
                user_id=user_id,
                error_type=type(exc).__name__,
                action="socket.user_blacklist_error",
            )
            return "Validation error"
        if is_blacklisted:
            log.warning(
                "Revalidation failed: User blacklisted",
                sid=sid,
                user_id=user_id
            )
            return "User session invalidated"

        # DB-authoritative cross-check for THIS jti (NOT "any active session"
        # of the user). The old code passed an old/revoked socket as long as
        # the user had *some* active session — so a fresh login after
        # deactivate→reactivate kept a stale socket alive. Require a
        # non-revoked, non-expired DB row matching exactly refresh_jti — the
        # jti resolved above from THIS session's row, so another live session
        # of the same user can never stand in for it.
        db_session = await repo.get_by_refresh_jti_and_user(refresh_jti, user_id)
        if db_session is None:
            log.warning(
                "Revalidation failed: session revoked/expired in DB (exact jti)",
                sid=sid,
                user_id=user_id,
                jti=refresh_jti,
            )
            return "Session revoked"

    return None


# ✅ FIX-3: Periodic revalidation event handler
@sio.event
async def revalidate_auth(sid):
    """
    Periodic re-validation của user session.
    Client gọi mỗi 15 phút (``frontend/src/lib/socket/client.ts``) để verify
    session vẫn hợp lệ.

    This catches cases where:
    - User changed password but socket didn't receive force_logout event
    - User was blacklisted by admin
    - Session was revoked by another device

    F103: the socket is bound to its DB session's stable id, so a session the
    client refreshed (refresh JTI rotated) stays valid, while a session that
    was really revoked/expired is refused and disconnected HERE, server-side,
    whatever the client does with the answer.
    """
    async with track_event_latency("revalidate_auth"):
        try:
            session = await sio.get_session(sid)
            if not session:
                log.warning("Revalidation failed: No session", sid=sid)
                await sio.disconnect(sid)
                return {"valid": False, "reason": "No session"}

            user_id = session.get("user_id")
            session_id = session.get("session_id")

            # Fail-closed: a socket session without user_id/session_id cannot
            # be tied to a DB session row, leaving it permanently trusted.
            # That includes a socket session shaped before F103 (``jti`` only):
            # refused, never validated through a JTI that may have rotated.
            if not user_id or not session_id:
                log.warning(
                    "Revalidation failed: missing user_id/session_id in socket session",
                    sid=sid,
                    user_id=user_id,
                )
                await sio.disconnect(sid)
                return {"valid": False, "reason": "Invalid session"}

            reason = await _session_refusal_reason(sid, user_id, session_id)
            if reason is not None:
                await sio.disconnect(sid)
                return {"valid": False, "reason": reason}

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


async def emit_force_logout(
    user_id: int,
    revoked_jtis: list,
    revoked_session_ids: list | None = None,
    **kwargs,
):
    """
    Socket.IO handler for user.force_logout event.

    Args:
        user_id: User to logout
        revoked_jtis: List of revoked session JTIs (the event payload). If
            empty AND ``revoked_session_ids`` is empty, logout all sessions
            for user.
        revoked_session_ids: ``UserSession.id`` of each revoked session, in
            the SAME order as ``revoked_jtis`` (F103). The rooms are keyed by
            this stable id: a socket joined its session's room at connect and
            stays in it across every /auth/refresh, while the JTI rotates.
        **kwargs: Additional event data (ignored)

    F108: a targeted revoke is ENFORCED server-side, not only announced: a
    client that ignores ``force_logout_batch`` and never calls
    ``revalidate_auth`` used to keep its socket. Runs post-commit (the
    callers' callbacks), so a socket cut here cannot reconnect: connect
    re-checks the DB row, which is already revoked.
    """
    try:
        if revoked_jtis or revoked_session_ids:
            # Targeted logout: one event per revoked session, to the room of
            # its STABLE id. The payload keeps naming the JTI (unchanged
            # client contract). A caller that cannot pair every JTI with its
            # session id is a bug: refuse loudly (caught below, logged) and
            # never widen a targeted revoke to the user room — that would log
            # out the user's OTHER, live sessions.
            jtis = list(revoked_jtis or [])
            session_ids = list(revoked_session_ids or [])
            if len(jtis) != len(session_ids):
                raise ValueError(
                    "targeted force_logout needs one session id per revoked jti "
                    f"(jtis={len(jtis)}, session_ids={len(session_ids)})"
                )
            # F108: ONE ACK-confirmed command on the force-disconnect channel;
            # every live worker tells the session's LOCAL sockets why
            # (force_logout_batch) and then disconnects them — same websocket,
            # so the reason lands before the DISCONNECT. (Sent through the
            # Socket.IO queue instead, the notice and the cut would travel on
            # two Redis channels and the cut could overtake the notice.)
            pairs = list(zip(session_ids, jtis))
            confirmed = await _enforce_session_revocation(user_id, pairs)
            if not confirmed:
                # Enforcement NOT confirmed (already logged as such): still tell
                # the sockets through the normal Socket.IO queue — advisory
                # only. The DB revoke stands and revalidate_auth refuses these
                # sessions. A worker that ACKed already cut its sockets, so they
                # miss this notice; a worker that runs the command late may
                # notify twice (harmless: the client logs out either way).
                for fallback_session_id, jti in pairs:
                    await sio.emit(
                        "force_logout_batch",
                        {"revoked_jtis": [jti]},
                        room=session_room(fallback_session_id),
                    )
            log.info(
                "Targeted force_logout_batch",
                user_id=user_id,
                count=len(pairs),
                enforced=confirmed,
            )
        else:
            # Revoke-ALL (``invalidate_all_sessions``, post-commit): the ONLY
            # path that cuts the whole user. Same contract as the targeted
            # branch: one ACK-confirmed command (each worker notifies the
            # user's local sockets, then disconnects them), and a cut nobody
            # confirmed is logged as such and only announced via the queue.
            confirmed = await _enforce_user_revocation(user_id)
            if not confirmed:
                room_name = f"user_room_{user_id}"
                await sio.emit(
                    "force_logout_batch",
                    {"revoked_jtis": []}, # Empty list means all
                    room=room_name
                )
            log.warning(
                "Emitted broadcast force_logout_batch (ALL)",
                user_id=user_id,
                enforced=confirmed,
            )
    except Exception as e:
        log.error("Failed to emit force_logout event", user_id=user_id, error=str(e))


async def _enforce_session_revocation(user_id: int, pairs: list) -> bool:
    """F108: cut every socket of the revoked sessions on every live worker.

    ``pairs`` = ``[(session_id, jti), ...]``. True ONLY when every required
    worker ACKed the session command (``force_disconnect_sessions_strict``).
    Anything else — no live worker, a worker that did not ACK, Redis error — is
    logged as NOT confirmed and returns False: never reported as done. Never
    raises: the revoke is already committed and stays the source of truth;
    ``revalidate_auth`` and connect refuse these sessions from the DB row.
    """
    session_ids = [session_id for session_id, _ in pairs]
    try:
        await force_disconnect_sessions_strict(pairs)
    except Exception as exc:
        socket_emit_failures_total.labels(event_type="force_disconnect_session").inc()
        log.error(
            "Targeted revoke: socket disconnect NOT confirmed; the DB revoke stands"
            " and revalidate_auth refuses these sessions",
            user_id=user_id,
            session_ids=session_ids,
            error_type=type(exc).__name__,
            action="socket.session_disconnect_unconfirmed",
        )
        return False
    log.info(
        "Targeted revoke: sockets disconnected on every live worker (ACK-confirmed)",
        user_id=user_id,
        session_ids=session_ids,
        action="socket.session_disconnect_confirmed",
    )
    return True


async def _enforce_user_revocation(user_id: int) -> bool:
    """Revoke-ALL (sibling of F108): cut every socket of the user on every live
    worker, each worker notifying first (``notify=True``). Same reporting
    contract as ``_enforce_session_revocation``: True only when every required
    worker ACKed; anything else is logged as NOT confirmed and returns False;
    never raises (the revoke is committed; connect and ``revalidate_auth``
    refuse via ``user_blacklist`` and the DB rows).

    Offboarding does NOT come through here: it keeps its own strict cut BEFORE
    commit, with rollback on failure (``app/routers/admin/users.py``)."""
    try:
        await force_disconnect_user_strict(user_id, notify=True)
    except Exception as exc:
        socket_emit_failures_total.labels(event_type="force_disconnect_user").inc()
        log.error(
            "Revoke-all: socket disconnect NOT confirmed; the DB revoke stands"
            " and revalidate_auth refuses this user",
            user_id=user_id,
            error_type=type(exc).__name__,
            action="socket.user_disconnect_unconfirmed",
        )
        return False
    log.info(
        "Revoke-all: every socket of the user disconnected (ACK-confirmed)",
        user_id=user_id,
        action="socket.user_disconnect_confirmed",
    )
    return True


# =====================================================================
# SERVER-SIDE FORCE-DISCONNECT (enforcement, NOT client-dependent)
# =====================================================================
# Events alone (force_logout_batch) need the client to honour them — a
# custom/malicious client can ignore them and keep receiving realtime. So
# offboarding (by user) and, since F108, targeted session revokes (by session)
# disconnect sockets server-side, across ALL Gunicorn workers,
# with confirmation. Mechanism: the request publishes a command on a Redis
# channel; every worker runs a subscriber that disconnects its LOCAL
# participants (AsyncRedisManager.get_participants is local-only) and ACKs. The
# publisher BLOCKS until every REQUIRED worker ACKs, else raises. Offboarding:
# the admin request rolls back the status change (fail-closed). Session revoke
# (F108) and revoke-all (its sibling), both post-commit: the revoke stands and
# the missing confirmation is logged as such (``_enforce_session_revocation``,
# ``_enforce_user_revocation``) — never reported as done.
#
# A command names EITHER ``user_ids`` (offboarding: the user's room) OR
# ``sessions`` (targeted revoke: ``session_room(id)`` only) — a session command
# never touches a user room.
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


async def force_disconnect_user(user_ids, *, notify: bool = False) -> int:
    """LOCAL: disconnect every SID of the given user(s) on THIS worker. Accepts a
    single id or an iterable. Snapshots participants first (disconnect mutates
    room membership). Raises on any disconnect failure → caller does NOT ACK →
    publisher times out (fail-closed).

    ``notify`` (revoke-all only, post-commit): tell the user's local sockets
    first (``force_logout_batch`` with ``revoked_jtis: []``, local emit — same
    websocket as the cut). Offboarding sends no ``notify``: it cuts BEFORE its
    commit and may still roll back, so it must not tell anyone they are out."""
    if isinstance(user_ids, int):
        user_ids = [user_ids]
    user_ids = list(user_ids)
    count = 0
    for uid in user_ids:
        room = f"user_room_{uid}"
        sids = [sid for sid, _ in sio.manager.get_participants("/", room)]
        if notify:
            try:
                await sio.emit(
                    "force_logout_batch",
                    {"revoked_jtis": []},
                    room=room,
                    ignore_queue=True,
                )
            except Exception as exc:
                log.warning(
                    "force_logout_batch (ALL) notice failed; disconnecting anyway",
                    user_id=uid,
                    error_type=type(exc).__name__,
                )
        for sid in sids:
            await sio.disconnect(sid)
            count += 1
    log.info("force_disconnect_user (local)", user_ids=user_ids, disconnected=count)
    return count


async def force_disconnect_sessions(sessions) -> int:
    """LOCAL (F108): for each revoked session ``(session_id, jti)``, tell the
    sockets of ``session_room(session_id)`` on THIS worker why
    (``force_logout_batch``, local emit) and then disconnect them. Same
    websocket, so the notice lands before the DISCONNECT. Only that session's
    room — never the user's room. The notice is advisory: its failure never
    blocks the cut. Snapshots participants first (disconnect mutates room
    membership). Raises on any disconnect failure → caller does NOT ACK →
    publisher reports the cut as unconfirmed."""
    count = 0
    for revoked_session_id, jti in sessions:
        room = session_room(revoked_session_id)
        sids = [sid for sid, _ in sio.manager.get_participants("/", room)]
        if jti:
            try:
                await sio.emit(
                    "force_logout_batch",
                    {"revoked_jtis": [jti]},
                    room=session_room(revoked_session_id),
                    ignore_queue=True,
                )
            except Exception as exc:
                log.warning(
                    "force_logout_batch notice failed; disconnecting anyway",
                    session_id=revoked_session_id,
                    error_type=type(exc).__name__,
                )
        for sid in sids:
            await sio.disconnect(sid)
            count += 1
    log.info(
        "force_disconnect_sessions (local)",
        session_ids=[session_id for session_id, _ in sessions],
        disconnected=count,
    )
    return count


async def _handle_force_disconnect(raw: str):
    """Subscriber handler: disconnect the whole batch locally, then ACK ONCE.
    No ACK if the disconnect raises (publisher fail-closes). A session command
    (``sessions``) disconnects only those sessions' rooms; a user command
    (``user_ids``) only those users' rooms."""
    data = json.loads(raw)
    command_id = data["command_id"]
    if "sessions" in data:
        await force_disconnect_sessions(data["sessions"])  # raises → no ACK below
    else:
        await force_disconnect_user(  # raises → no ACK below
            data["user_ids"], notify=bool(data.get("notify"))
        )
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
    user_ids, *, timeout: float = _ACK_TIMEOUT, notify: bool = False
) -> str:
    """ENFORCEMENT: publish ONE force-disconnect command for the whole batch and
    BLOCK until every required worker ACKs, else raise (fail-closed). Redis
    PUBLISH only reports how many subscribers RECEIVED the message — not that
    they processed it — so we require explicit per-worker ACKs. A single batched
    command bounds the admin request to ONE timeout regardless of batch size.

    ``notify=True`` only for the post-commit revoke-all
    (``_enforce_user_revocation``); offboarding keeps the command unchanged."""
    if isinstance(user_ids, int):
        user_ids = [user_ids]
    user_ids = list(user_ids)
    if not user_ids:
        return ""
    targets = {"user_ids": user_ids}
    if notify:
        targets["notify"] = True
    return await _publish_force_disconnect_strict(
        targets,
        timeout=timeout,
        label="force_disconnect_user_strict",
        log_ctx={"user_ids": user_ids},
    )


async def force_disconnect_sessions_strict(
    sessions, *, timeout: float = _ACK_TIMEOUT
) -> str:
    """ENFORCEMENT (F108): ONE command naming the revoked sessions
    ``[(session_id, jti), ...]``; every live worker notifies and disconnects the
    sockets of ``session_room(session_id)`` and ACKs. Same ACK contract as
    ``force_disconnect_user_strict``: raises unless EVERY required worker ACKs."""
    sessions = [[session_id, jti] for session_id, jti in sessions]
    if not sessions:
        return ""
    return await _publish_force_disconnect_strict(
        {"sessions": sessions},
        timeout=timeout,
        label="force_disconnect_sessions_strict",
        log_ctx={"session_ids": [session_id for session_id, _ in sessions]},
    )


async def _publish_force_disconnect_strict(
    targets: dict, *, timeout: float, label: str, log_ctx: dict
) -> str:
    """The ONE publish-and-await-every-ACK loop behind both strict commands."""
    command_id = uuid.uuid4().hex
    ack_key = _ACK_PREFIX + command_id
    # Snapshot required workers BEFORE publishing. Workers that start AFTER are
    # not required to ACK (they hold no sockets predating the command).
    required = await _required_workers()
    if not required:
        # No worker alive → cannot guarantee enforcement → fail-closed.
        raise RuntimeError("No live socket workers to enforce force-disconnect")
    payload = json.dumps({"command_id": command_id, **targets})
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
                f"{label}: ACK timeout",
                command_id=command_id,
                missing=list(missing),
                **log_ctx,
            )
            raise TimeoutError(
                f"Force-disconnect not ACKed by workers: {sorted(missing)}"
            )
        log.info(
            f"{label} OK",
            workers=len(required),
            **log_ctx,
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
