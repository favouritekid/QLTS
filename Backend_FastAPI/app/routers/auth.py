# app/routers/auth.py
from typing import Annotated, List, Optional

import structlog
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
import jwt
from jwt.exceptions import PyJWTError as JWTError
# ✅ PHASE 2: Removed direct sqlalchemy import (Router → Service → Repository pattern)
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security
# PHASE 1: Removed send_login_alert_email_task (now in login_history_service)
from ..config import settings
from ..core import deps
from ..utils.exceptions import (  # ✅ PHASE 1: Import custom exceptions
    CacheServiceError,
    InvalidCredentials,
    UserServiceError,
)
from ..middleware.csrf import set_csrf_cookie  # ✅ CSRF Protection
from ..database import (
    KetQuaChiem,
    safe_redis_claim_once,
    safe_redis_delete,
    safe_redis_exists,
    safe_redis_get,
    safe_redis_khoa_ton_tai,
    safe_redis_pipeline,
    safe_redis_reserve_attempt,
    safe_redis_set,
)
from ..core.rate_limits import (  # ✅ MIGRATED: Use new rate limits module
    limiter,
    RateLimits,
    get_refresh_identity_key,
    refresh_limit,
)
from ..services import session_service, user_service
from ..services import login_history_service  # Security: Persistent login audit trail
from ..services.notification_dispatcher import safe_dispatch  # Security: Suspicious login alerts
# PHASE 1: Removed AnomalyDetector import (detection now in login_history_service)
from ..utils.exceptions import InvalidToken
from ..core.events import SystemEvents  # Security: Event registry

router = APIRouter(tags=["Authentication"])
log = structlog.get_logger(__name__)

# Nhãn LOẠI khoá, dùng thay cho chính khoá trên đường log của các helper Redis
# nhạy cảm. ``mfa_used:{jti}`` mang định danh của một bằng chứng MFA còn hiệu
# lực; nhánh log lại là nhánh chạy KHI REDIS SỰ CỐ, nên ghi nguyên khoá ở đó là
# đẩy JTI đầy đủ vào log đúng lúc dễ xảy ra nhất.
_NHAN_KHOA_MFA_TOKEN = "mfa.token_claim"


class RefreshAbuseLocked(HTTPException):
    """429 của cổng chống lạm dụng refresh (M4) — KHÁC 429 rate limit hạ tầng.

    Hai loại 429 rất khác nhau cùng xuất hiện trên ``POST /auth/refresh``:

    * ``RATE_LIMITED`` (slowapi, ``app/core/rate_limits.py``): quota theo IP
      hết → TẠM THỜI. Client giữ phiên và thử lại sau.
    * ``REFRESH_ABUSE_LOCKED`` (đây): ``refresh_fail:{username}`` đã chạm
      ``REFRESH_MAX_FAILURES``. Chính lần lỗi chạm ngưỡng đã gọi
      ``invalidate_all_sessions`` và trả 401; các lần refresh SAU đó rơi vào
      cổng này. Nghĩa là session đã bị thu hồi phía server → client PHẢI đăng
      xuất, không được giữ phiên.

    Vì client phân loại theo ``error_code`` (không theo chuỗi thông báo), mã
    phải nằm TOP-LEVEL trong body. ``http_exception_handler`` đọc thuộc tính
    ``error_code`` dưới đây thay cho mặc định ``HTTP_429``.

    Cố ý subclass ``HTTPException`` chứ không phải ``BaseAppException``: luồng
    ``refresh_access_token`` có nhiều tầng ``except HTTPException: raise`` để
    cho một deny hợp lệ đi thẳng ra ngoài mà KHÔNG bị đếm vào bộ đếm lạm dụng.
    Một domain exception sẽ rơi vào ``except Exception`` gần nhất và bị nuốt.
    """

    error_code = "REFRESH_ABUSE_LOCKED"

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed refresh attempts. Please login again.",
        )


def _suspicious_login_only_channels(risk_score: int) -> Optional[List[str]]:
    """Channel filter for a suspicious-login dispatch, by risk score.

    Below ``SUSPICIOUS_LOGIN_EMAIL_RISK_THRESHOLD`` (a bare new-IP login =
    30, or 24 on a trusted device — IP churn on mobile/dynamic ISPs) →
    return ``["browser"]`` so only the in-app banner fires, no email/zalo.
    At/above the threshold (new_device 40, new_location 50, impossible-travel
    80, and any combination) → return ``None`` = all channels per the rule.

    In-app banner + login_history are recorded for EVERY anomaly regardless —
    only the email/zalo fan-out is risk-gated. Pure function so the decision
    is unit-testable without a full login flow.
    """
    if risk_score >= settings.SUSPICIOUS_LOGIN_EMAIL_RISK_THRESHOLD:
        return None
    return ["browser"]


# =============================================================================
# SHARED HELPER: Complete login flow (tokens, session, history, cookies)
# Used by both /login (non-MFA) and /verify-mfa to avoid code duplication.
# =============================================================================


def _deny_if_not_active(user, *, ip_address):
    """Token-issuance gate: block any non-active account (offboarding / lock).

    Raises a generic ``InvalidCredentials`` (401) — identical to a wrong
    password, so an unauthenticated caller cannot enumerate account state.
    Do NOT record a failed lockout attempt here: this is a legitimate deny,
    not a brute-force attempt. Status is whitelisted on ``"active"`` so every
    other value (inactive/pending/banned/suspended/locked) is rejected.
    """
    if user.status != "active":
        log.warning(
            "Token issuance blocked: account not active",
            user_id=user.id,
            status=user.status,
            ip_address=ip_address,
            security_event="LOGIN_BLOCKED_INACTIVE",
        )
        raise InvalidCredentials()


async def _complete_login_flow(
    user: "models.User",
    request: Request,
    db: "AsyncSession",
) -> JSONResponse:
    """
    Complete the login flow after authentication is fully verified.

    Creates tokens, session, login history, handles suspicious login detection,
    and returns a JSONResponse with httpOnly cookies.

    Used by:
    - /login (after password auth, when MFA is NOT enabled)
    - /verify-mfa (after both password + MFA code verified)
    """
    from datetime import datetime, timedelta, timezone

    # ===== AUTHORITATIVE STATUS GATE (Tầng A) =====
    # Re-read status from the DB under a row lock immediately before minting
    # tokens. The early gates in /login and /verify-mfa read a possibly-stale
    # ORM object; this closes the deactivate↔mint race (admin sets the account
    # non-active after authentication but before tokens are issued). Runs for
    # BOTH callers (login + verify-mfa) since both mint through this helper.
    await db.refresh(user, attribute_names=["status"], with_for_update=True)
    _deny_if_not_active(
        user, ip_address=request.client.host if request.client else None
    )

    try:
        await user_service.remove_user_from_global_blacklist(user.id)
    except Exception as e:
        log.error("Failed to remove user from global blacklist", user_id=user.id, error=str(e))

    # 1. Create tokens
    refresh_token = security.create_refresh_token(data={"sub": user.username})
    refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)
    if not refresh_jti or refresh_ttl is None:
        raise HTTPException(status_code=500, detail="Could not process tokens")

    access_token = security.create_access_token(
        data={"sub": user.username, "user_id": user.id, "role": user.role},
        refresh_jti=refresh_jti,
    )
    access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
    if not access_jti:
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # 2. Store session in Redis
    try:
        await safe_redis_set(f"session:{refresh_jti}", str(user.id), ex=refresh_ttl)
    except Exception as e:
        await db.rollback()
        log.error("Failed to set session in Redis", user_id=user.id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Could not process session")

    # 3. Create DB session + login history
    post_commit_callbacks = []
    ip_address = request.client.host if request.client else None
    user_agent_string = request.headers.get("User-Agent")
    session = None

    try:
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        session, session_callback = await session_service.create_session(
            db=db,
            user_id=user.id,
            refresh_jti=refresh_jti,
            ip_address=ip_address,
            user_agent_string=user_agent_string,
            expires_at=expires_at,
        )
        if session_callback:
            post_commit_callbacks.append(session_callback)
    except Exception as session_error:
        # FAIL-CLOSED: get_current_user STEP 4 is now DB-authoritative — it
        # requires a non-revoked DB session row for this jti. Without that row an
        # issued token would be rejected (401) on the very next request. So undo
        # the Redis session key and abort the login with 500 instead of minting a
        # token that is dead on arrival.
        log.error(
            "Failed to create DB session — aborting login (fail-closed)",
            user_id=user.id,
            error=str(session_error),
            exc_info=True,
        )
        await db.rollback()
        try:
            await safe_redis_delete(f"session:{refresh_jti}")
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Could not process session")

    # 4. Record login history + suspicious login detection
    login_notification_data = None
    try:
        login_record, login_history_callback = await login_history_service.record_login(
            db=db,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent_string,
            country=session.country if session else None,
            city=session.city if session else None,
            email_to=user.email,
            username=user.username,
            refresh_jti=refresh_jti,
        )
        if login_history_callback:
            post_commit_callbacks.append(login_history_callback)

        if login_record.is_suspicious:
            log.warning(
                "Login recorded with security flags",
                user_id=user.id,
                is_new_ip=login_record.is_new_ip,
                is_new_device=login_record.is_new_device,
                is_new_location=login_record.is_new_location,
                risk_score=login_record.risk_score,
            )
            anomalies = []
            if login_record.is_new_ip:
                anomalies.append("new_ip")
            if login_record.is_new_device:
                anomalies.append("new_device")
            if login_record.is_new_location:
                anomalies.append("new_location")

            login_notification_data = {
                "type": "SUSPICIOUS_LOGIN",
                "login_id": login_record.id,
                "ip_address": ip_address or "unknown",
                "location": f"{login_record.city or ''}, {login_record.country or ''}".strip(", ") or None,
                "device": f"{login_record.browser or ''} on {login_record.os or ''}".strip() or None,
                "browser": login_record.browser,
                "os": login_record.os,
                "risk_score": login_record.risk_score,
                "anomalies": anomalies,
            }
            # Sync is_suspicious to UserSession
            if session:
                session.is_suspicious = True
                db.add(session)
            # Dispatch notification (fire-and-forget after commit).
            # Uses a SEPARATE session to avoid corrupting the login session
            # if notification dispatch fails (e.g., FK errors in test env).
            _notif_user_id = user.id
            _notif_login_id = login_record.id
            _notif_payload = {
                "user_id": _notif_user_id,
                "user_ids": [_notif_user_id],
                "login_history_id": _notif_login_id,
                "ip_address": ip_address or "unknown",
                "location": f"{login_record.city or ''}, {login_record.country or ''}".strip(", "),
                "device": f"{login_record.browser or ''} on {login_record.os or ''}".strip(),
                "risk_score": login_record.risk_score,
                "anomalies": anomalies,
                "actor_id": _notif_user_id,
            }

            # Phase 2 PR-B: risk-gate the EMAIL/zalo channels (see helper).
            # Snapshot to a plain value (not ORM) for the post-commit closure.
            _notif_only_channels = _suspicious_login_only_channels(
                login_record.risk_score
            )

            # Option-B Commit 7: DO NOT pass ``rooms_for_user`` for the
            # SUSPICIOUS_LOGIN event. The dispatcher computes the socket
            # rooms itself, gated by each user's ``browser`` notification
            # preference and explicitly omitting ``role_admin`` (this is
            # an actor-targeted event, not an admin alert). Passing
            # ``rooms_for_user`` here would short-circuit that gating and
            # broadcast the banner bump to every admin for every user's
            # suspicious login.
            async def _dispatch_suspicious_login():
                try:
                    async with database.AsyncSessionLocal() as notif_db:
                        await safe_dispatch(
                            db=notif_db,
                            event=SystemEvents.SUSPICIOUS_LOGIN,
                            payload=_notif_payload,
                            rooms=None,
                            only_channels=_notif_only_channels,
                        )
                except Exception as notif_error:
                    log.error("Failed to dispatch suspicious login notification",
                              user_id=_notif_user_id, error=str(notif_error))
            post_commit_callbacks.append(_dispatch_suspicious_login)
    except Exception as history_error:
        log.error("Failed to record login history", user_id=user.id, error=str(history_error), exc_info=True)

    # 5. Snapshot user data BEFORE callbacks (so response doesn't depend
    #    on ORM state that callbacks might corrupt)
    user_snapshot = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
        "password_reset_required": user.password_reset_required,
        "mfa_enabled": user.mfa_enabled,
    }

    # 6. Commit and execute callbacks
    try:
        await db.commit()
        for callback in post_commit_callbacks:
            try:
                await callback()
            except Exception as cb_e:
                # Callbacks use separate sessions, so errors here are
                # truly non-critical and don't affect the login session.
                log.error("Post-commit callback failed", error=str(cb_e))
    except Exception as e:
        await db.rollback()
        try:
            await safe_redis_delete(f"session:{refresh_jti}")
        except Exception:
            pass
        log.error("Failed to commit DB changes during login", user_id=user.id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Could not save session")

    # 6b. Count pending suspicious logins for the response banner
    # (Option-B Commit 5). The FE banner was hardcoded to ``1`` post-
    # login when any login_notification arrived — that hid the real
    # backlog size from the user. We do this AFTER commit (so the row
    # we just inserted is counted if it was suspicious) and tolerate
    # errors silently because it's banner UX, not auth correctness.
    suspicious_login_count = 0
    try:
        from ..repositories.login_history_repository import LoginHistoryRepository
        suspicious_login_count = await LoginHistoryRepository(db).count_pending_suspicious(user.id)
    except Exception as count_error:
        log.error(
            "Failed to count pending suspicious logins for response",
            user_id=user.id, error=str(count_error),
        )

    # 7. Build response from snapshot (not ORM objects)
    response = JSONResponse(
        content={
            "token_type": "bearer",
            "user": user_snapshot,
            "login_notification": login_notification_data,
            "suspicious_login_count": suspicious_login_count,
        },
        status_code=200,
    )
    # ⚠️ max_age = TTL của REFRESH token, KHÔNG phải của access token.
    #
    # Token vẫn hết hạn sau ACCESS_TOKEN_EXPIRE_MINUTES — backend luôn kiểm
    # ``exp`` nên một cookie quá hạn là vô hại. Nhưng nếu cookie CHẾT cùng lúc
    # với token thì trình duyệt xoá nó sau 15 phút, và request kế tiếp tới
    # middleware không còn cookie nào để phân biệt hai ca hoàn toàn khác nhau:
    # "chưa từng đăng nhập" và "phiên còn sống 30 ngày, chỉ access token cũ".
    # Middleware buộc phải đoán, và nó đoán sai theo hướng đắt nhất — đá người
    # dùng về /login giữa lúc nhập liệu. Giữ cookie sống bằng refresh token để
    # middleware còn dữ liệu mà quyết định.
    response.set_cookie(
        key="access_token", value=access_token,
        httponly=True, secure=settings.APP_ENV == "production",
        samesite="lax", max_age=int(refresh_ttl),
        path="/",
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token,
        httponly=True, secure=settings.APP_ENV == "production",
        samesite="strict", max_age=int(refresh_ttl), path="/api",
    )
    set_csrf_cookie(response)
    return response


@router.post(
    "/register", response_model=schemas.User, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RateLimits.AUTH_REGISTER)  # ✅ RATE LIMIT: 3/min - Stricter for registration (prevents enumeration)
async def register_user(
    request: Request,
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
):
    """
    User registration endpoint.

    ✅ SECURITY FIX (Phase 2): User Enumeration Prevention (CVSS 5.3 MEDIUM)
    - Returns generic error message to prevent username/email enumeration
    - Logs specific details internally for admin monitoring
    - Prevents attackers from discovering valid usernames/emails
    - Stricter rate limit (3/minute vs 5/minute for other auth endpoints)

    VULNERABILITY: User Enumeration
    - Old behavior: "Username 'john' already registered" → Attacker knows username exists
    - Attack: Enumerate all usernames/emails in database
    - Fix: Generic message "Username or email already registered" + stricter rate limit
    """
    db_user_by_username = await user_service.get_user_by_username(
        db, username=user_in.username
    )
    db_user_by_email = await user_service.get_user_by_email(
        db, email=user_in.email
    )

    # ✅ FIX: Check both conditions together and return generic message
    if db_user_by_username or db_user_by_email:
        # Log specific details for admin monitoring (internal only)
        log.warning(
            "🔒 SECURITY: Registration failed - duplicate credential",
            username=user_in.username if db_user_by_username else None,
            email=user_in.email if db_user_by_email else None,
            client_ip=request.client.host if request.client else "unknown"
        )

        # Return generic message to client (prevents enumeration)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",  # ✅ Generic message
        )

    # ✅ FIX: create_user returns Tuple[User, Callback]
    created_user, post_commit_callback = await user_service.create_user(db=db, user_in=user_in)
    
    # ✅ FIX: Commit transaction and execute callback
    await db.commit()
    await post_commit_callback()

    # ✅ FIX: Automatically add Casbin grouping policy to map user to their role
    try:
        enforcer = request.app.state.enforcer
        if enforcer:
            role_name = f"role:{created_user.role}"
            user_subject = f"user:{created_user.id}"
            await enforcer.add_grouping_policy(user_subject, role_name)
            log.info(
                "Casbin grouping policy added for new user",
                user_id=created_user.id,
                role=created_user.role,
            )
    except Exception as e:
        log.error(
            "Failed to add Casbin grouping policy for new user",
            user_id=created_user.id,
            error=str(e),
        )
        # Don't fail registration if Casbin update fails

    return created_user


@router.post("/login")
@limiter.limit(RateLimits.AUTH_LOGIN)  # ✅ RATE LIMIT: 5/min - Prevents brute force attacks
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(database.get_db),
):
    # ✅ SECURITY FIX: Check account lockout before authentication
    from ..security.account_lockout import AccountLockoutService

    is_locked, lockout_ttl = await AccountLockoutService.check_lockout(
        form_data.username
    )

    if is_locked:
        # Add delay to slow down attacker
        import asyncio
        await asyncio.sleep(2)

        remaining_minutes = max(1, (lockout_ttl + 59) // 60)  # Round up

        log.warning(
            "Login attempt blocked: Account is locked",
            username=form_data.username,
            remaining_seconds=lockout_ttl,
            ip_address=request.client.host if request.client else None,
        )

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": f"Tài khoản tạm thời bị khóa do nhập sai quá nhiều lần. "
                          f"Vui lòng thử lại sau {remaining_minutes} phút.",
            },
            headers={"Retry-After": str(lockout_ttl)},
        )

    # Attempt authentication
    try:
        user = await user_service.authenticate_user(
            db, username=form_data.username, password=form_data.password
        )
    except (InvalidCredentials, HTTPException) as auth_error:
        # ✅ SECURITY FIX: Record failed attempt
        await AccountLockoutService.record_failed_attempt(
            db=db,
            username=form_data.username,
            ip_address=request.client.host if request.client else None,
        )

        # Re-raise original error (don't reveal lockout info to attacker)
        raise auth_error

    # ===== STATUS GATE (Tầng B — early) =====
    # Block non-active accounts BEFORE the MFA branch so an inactive account
    # never receives an mfa_token. Placed OUTSIDE the authenticate try/except so
    # the raise is not recorded as a failed lockout attempt (legitimate deny).
    # Authoritative re-check happens in _complete_login_flow (Tầng A).
    _deny_if_not_active(
        user, ip_address=request.client.host if request.client else None
    )

    # ===== MFA CHECK =====
    # If user has MFA enabled, return mfa_token instead of full login.
    # CRITICAL: Do NOT reset_attempts here. Password correct ≠ auth complete.
    # Counter only resets after BOTH factors verified (in /verify-mfa).
    if getattr(user, "mfa_enabled", False):
        from ..services import mfa_service

        mfa_token = mfa_service.create_mfa_token(
            username=user.username, user_id=user.id
        )
        log.info("MFA required for login", user_id=user.id, action="mfa.challenge_issued")
        return JSONResponse(
            content={
                "mfa_required": True,
                "mfa_token": mfa_token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "mfa_enabled": True,
                },
            },
            status_code=200,
        )
    # ===== END MFA CHECK =====

    # Reset attempts counter only when auth is fully complete (no MFA)
    await AccountLockoutService.reset_attempts(form_data.username)

    # Complete login flow (shared helper: tokens, session, history, cookies)
    return await _complete_login_flow(user, request, db)


@router.post("/logout")
@limiter.limit(RateLimits.DATA_WRITE)  # ✅ RATE LIMIT: 200/hour - Normal write operation
async def logout(
    request: Request,
    response: Response,
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
    authorization: Annotated[str | None, Header()] = None,
    current_user: models.User = Depends(deps.get_current_user),
):
    # (Giữ nguyên logic)
    access_token = None
    if authorization and authorization.lower().startswith("bearer "):
        access_token = authorization.split(" ")[1]

    if access_token:
        access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
        if access_jti and access_ttl is not None and access_ttl > 0:
            try:
                await safe_redis_set(
                    f"blacklist:{access_jti}", "revoked", ex=access_ttl
                )
                log.info(
                    "Access token blacklisted on logout",
                    jti=access_jti,
                    user_id=current_user.id,
                )
            except Exception as e:
                log.error(
                    "Failed to blacklist access token on logout",
                    jti=access_jti,
                    error=str(e),
                )

    refresh_jti = None
    try:
        refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)
        if refresh_jti:
            await safe_redis_delete(f"session:{refresh_jti}")
            if refresh_ttl and refresh_ttl > 0:
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=refresh_ttl
                )
            else:
                refresh_token_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=int(refresh_token_ttl)
                )
            log.info(
                "Refresh token blacklisted on logout",
                jti=refresh_jti,
                user_id=current_user.id,
            )
    except Exception as e:
        log.error(
            "Failed to blacklist refresh token on logout",
            user_id=current_user.id,
            error=str(e),
        )

    if refresh_jti:
        # ✅ PHASE 2: Use session_service instead of direct SQL
        try:
            revoked, callback = await session_service.revoke_session_by_jti(
                db=db,
                refresh_jti=refresh_jti,
                user_id=current_user.id
            )
            if revoked:
                await db.commit()
                if callback:
                    await callback()
                log.info(
                    "Session revoked on logout",
                    user_id=current_user.id,
                )
            else:
                log.warning(
                    "Session not found for revocation on logout",
                    user_id=current_user.id,
                )
        except Exception as session_error:
            log.warning(
                "Failed to revoke session on logout",
                user_id=current_user.id,
                error=str(session_error),
            )

    # ✅ SECURITY FIX: Delete both cookies
    response.delete_cookie(
        key="access_token",
        path="/",
        samesite="lax",
    )
    response.delete_cookie(
        key="refresh_token",
        path="/api",  # ✅ FIX: Changed from "/api/auth" to "/api" to match set_cookie path
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/check-status")
@limiter.limit(RateLimits.DATA_READ)  # ✅ RATE LIMIT: 1000/hour - Normal read operation
async def check_session_status(
    request: Request,
    current_user: models.User = Depends(deps.get_current_user),
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(database.get_db),
):
    # ✅ FIX: get_current_user already validates session in Redis
    # No need to check again - if we reach here, session is valid
    
    # Get active sessions count for user info
    active_sessions = await session_service.get_active_sessions(
        db=db,
        user_id=current_user.id
    )

    return {
        "status": current_user.status,  # real account status, not hardcoded
        "user_id": current_user.id,
        "username": current_user.username,
        "session_valid": True,
        "active_sessions_count": len(active_sessions),
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RateLimits.AUTH_PASSWORD_RESET)  # ✅ RATE LIMIT: 3/hour - Prevents password reset abuse
async def request_password_reset(
    request: Request,
    forgot_data: schemas.ForgotPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    await user_service.handle_forgot_password(
        db=db, email_in=forgot_data.email
    )
    return {
        "detail": "If a user with that email exists, a password reset link will be sent."  # <--- ĐÃ SỬA
    }


@router.post("/reset-password", response_model=schemas.User)
@limiter.limit(RateLimits.AUTH_PASSWORD_RESET)  # ✅ RATE LIMIT: 3/hour - Same as forgot-password
async def perform_password_reset(
    request: Request,
    reset_data: schemas.ResetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Reset password using token from email.

    Security: Invalidates ALL sessions after password reset to prevent
    session hijacking attacks. If an attacker had access to the account,
    all their sessions will be revoked.
    """
    user, post_commit_callback = await user_service.reset_password(
        db, token=reset_data.token, new_password=reset_data.new_password
    )

    # Cache identifiers before any rollback — ORM object may expire after rollback
    user_id = user.id
    user_email = user.email

    # SECURITY: Invalidate all sessions BEFORE committing password change.
    # If revocation fails, rollback so old password stays active — fail-closed:
    # no dangling sessions with a changed password.
    try:
        await user_service.invalidate_all_sessions(db, user)
        log.warning(
            "All user sessions invalidated after password reset",
            user_id=user_id,
            email=user_email,
            security_event="PASSWORD_RESET_SESSIONS_INVALIDATED",
        )
    except (CacheServiceError, UserServiceError) as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password reset rolled back",
            user_id=user_id,
            error=e.detail,
            context=e.context,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed. Please try again later."
        )
    except Exception as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password reset rolled back",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed. Please try again later."
        )

    # Session invalidation succeeded — now commit password change
    await db.commit()
    await post_commit_callback()

    # Refresh user object — may fail if session management detached it
    try:
        await db.refresh(user)
    except Exception:
        pass  # User data is already committed; stale ORM object is acceptable

    # 📧 Send confirmation email to notify user about password reset
    # This allows user to take action if they didn't initiate the reset
    try:
        from datetime import datetime, timezone
        from ..celery_utils import send_password_reset_confirmation_email_task

        reset_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Try to get IP address from request
        ip_address = request.client.host if request.client else None

        send_password_reset_confirmation_email_task.delay(
            email_to=user.email,
            username=user.full_name or user.email,
            reset_time=reset_time,
            ip_address=ip_address,
        )
        log.info(
            "Password reset confirmation email queued",
            user_id=user.id,
            email=user.email,
        )
    except Exception as e:
        log.error(
            "Failed to queue password reset confirmation email",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        # Don't fail the request if email fails

    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(RateLimits.AUTH_PASSWORD_CHANGE)  # ✅ RATE LIMIT: 10/hour - Moderate for authenticated users
async def perform_change_password(
    request: Request,
    password_data: schemas.ChangePasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Change user password and invalidate all sessions.

    Security: This endpoint invalidates ALL sessions after password change.
    If session invalidation fails, the request will fail with 500 to prevent
    security issues with dangling sessions.
    """
    _, post_commit_callback = await user_service.change_password(
        db,
        user=current_user,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )

    # Cache identifier before any rollback — ORM object may expire after rollback
    current_user_id = current_user.id

    # C2 SECURITY FIX: Clear password_reset_required flag after password change
    if hasattr(current_user, 'password_reset_required') and current_user.password_reset_required:
        current_user.password_reset_required = False
        db.add(current_user)
        log.info("Cleared password_reset_required flag", user_id=current_user_id)

    # SECURITY: Invalidate all sessions BEFORE committing password change.
    # If revocation fails, rollback so the old password stays active —
    # fail-closed: no dangling sessions with a changed password.
    try:
        await user_service.invalidate_all_sessions(db, current_user)
        log.info(
            "All user sessions invalidated after password change",
            user_id=current_user_id,
        )
    except (CacheServiceError, UserServiceError) as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password change rolled back",
            user_id=current_user_id,
            error=e.detail,
            context=e.context,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed. Please try again later."
        )
    except Exception as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password change rolled back",
            user_id=current_user_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed. Please try again later."
        )

    # Session invalidation succeeded — now commit the password change
    await db.commit()
    await post_commit_callback()

    # Clear auth cookies — forces browser to stop sending blacklisted tokens
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key="access_token", path="/", samesite="lax")
    response.delete_cookie(key="refresh_token", path="/api", samesite="strict")
    response.delete_cookie(key="csrf_token", path="/")
    return response


@router.post("/refresh")
# Khoá theo CHỦ THỂ, không theo IP: cả trường ra Internet qua một IP NAT nên
# xô 20/giờ theo IP là quota chung cho toàn bộ nhân sự (32% request refresh bị
# chặn trong audit prod 2026-07-30). ``refresh_limit`` cấp 120/giờ khi khoá
# chứng minh được danh tính, giữ 20/giờ cho nhánh IP. Thứ tự decorator hiện tại
# là ĐÚNG — ``@limiter.limit`` nằm DƯỚI ``@router.post`` nên slowapi chặn trước
# khi thân hàm chạy, tức trước khi rotation chạm Redis/DB; đảo hai dòng này là
# biến 429 từ "chắc chắn chưa chạm rotation" thành "không biết".
@limiter.limit(refresh_limit, key_func=get_refresh_identity_key)
async def refresh_access_token(
    request: Request,
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    if not refresh_token:
        raise HTTPException(
            status_code=401, detail="Refresh token missing. Please login again."
        )

    credentials_exception = InvalidToken(detail="Invalid or expired refresh token")
    service_unavailable = HTTPException(
        status_code=503, detail="Auth service unavailable"
    )
    # PR1 Commit 2: distinct 401 for session desync — the OLD jti is valid in
    # Redis (the session:{jti} check passes) but has NO matching DB session row.
    # That only happens for sessions frozen by the historical no-commit bug, so
    # it is NOT abuse. A plain HTTPException (not the InvalidToken
    # credentials_exception) routes to the ``except HTTPException`` arm and so
    # bypasses the refresh-abuse counter / invalidate_all_sessions path below.
    session_desync_exception = HTTPException(
        status_code=401, detail="Session desynchronized. Please login again."
    )

    # ✅ M4: Per-user rate limiting for failed refresh attempts
    # We extract username from token even on failure to track abuse
    _refresh_username = None

    try:
        # (STEP 1: Decode - Giữ nguyên)
        try:
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as e:
            log.warning("JWT decode error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        old_refresh_jti: str | None = payload.get("jti")
        token_type: str | None = payload.get("type")
        _refresh_username = username  # Track for rate limiting on failure

        if not username or not old_refresh_jti or token_type != "refresh":
            log.warning("Invalid refresh token payload", sub=username, type=token_type)
            raise credentials_exception

        # ✅ M4: Check if user exceeded failed refresh attempts
        try:
            fail_key = f"refresh_fail:{username}"
            fail_count_str = await safe_redis_get(fail_key)
            fail_count = int(fail_count_str) if fail_count_str else 0
            if fail_count >= settings.REFRESH_MAX_FAILURES:
                log.warning(
                    "Refresh token rate limited - too many failures",
                    username=username,
                    fail_count=fail_count,
                    security_event="REFRESH_RATE_LIMITED",
                )
                raise RefreshAbuseLocked()
        except HTTPException:
            raise
        except Exception as e:
            log.error("Redis refresh rate limit check failed", error=str(e))

        # (STEP 2: Check Blacklist - Giữ nguyên)
        try:
            is_blacklisted = await safe_redis_exists(f"blacklist:{old_refresh_jti}")
            if is_blacklisted:
                log.warning("Refresh token is blacklisted", jti=old_refresh_jti)
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error("Blacklist check failed", error=str(e), exc_info=True)

        # ✅ FIX: Use begin_nested() (savepoint) to avoid conflict with implicit transaction
        async with db.begin_nested():
            try:
                user = await user_service.get_user_for_refresh(db, username)

                if not user:
                    log.warning("User not found during refresh", username=username)
                    raise credentials_exception

                # ===== AUTHORITATIVE STATUS GATE (Tầng A) =====
                # get_user_for_refresh already holds a FOR UPDATE row lock, so
                # this status read is authoritative. Block token rotation for a
                # non-active account. Raises InvalidCredentials (NOT InvalidToken)
                # → handled by the dedicated outer `except InvalidCredentials`
                # below: returns 401 WITHOUT incrementing the refresh-abuse
                # counter (legitimate deny, not abuse).
                _deny_if_not_active(
                    user,
                    ip_address=request.client.host if request.client else None,
                )

                # SECURITY: Check user-level blacklist (set by invalidate_all_sessions
                # on password change/reset). Without this, old refresh tokens could
                # still rotate even after all sessions were invalidated.
                try:
                    is_user_blacklisted = await safe_redis_exists(f"user_blacklist:{user.id}")
                    if is_user_blacklisted:
                        log.warning(
                            "Refresh blocked: user in global blacklist (password changed?)",
                            user_id=user.id,
                        )
                        raise credentials_exception
                except InvalidToken:
                    raise
                except Exception as e:
                    log.error("Redis user blacklist check failed during refresh", error=str(e))
                    # Fail-closed: if we can't verify, reject the refresh
                    raise credentials_exception

                # (STEP 4: Validate JTI - Giữ nguyên)
                stored_user_id = await safe_redis_get(f"session:{old_refresh_jti}")

                if not stored_user_id or int(stored_user_id) != user.id:
                    log.warning(
                        "Session not found or user mismatch in Redis",
                        user_id=user.id,
                        token_jti=old_refresh_jti,
                        stored_user_id=stored_user_id,
                    )
                    if old_refresh_jti:
                        ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
                        try:
                            await safe_redis_set(
                                f"blacklist:{old_refresh_jti}", "reuse_attempt", ex=ttl
                            )
                        except Exception as e_blacklist:
                            log.error(
                                "Failed to blacklist reuse attempt",
                                jti=old_refresh_jti,
                                error=str(e_blacklist),
                            )
                    raise credentials_exception

                # ✅ BƯỚC 2 (tt): SỬA HÀM REFRESH

                # 1. Tạo Refresh Token MỚI TRƯỚC
                new_refresh_token = security.create_refresh_token(
                    data={"sub": username}
                )
                new_refresh_jti, new_refresh_ttl = (
                    security.decode_token_for_invalidation(new_refresh_token)
                )

                if not new_refresh_jti or new_refresh_ttl is None:
                    log.error("Failed to decode new REFRESH token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # 2. Tạo Access Token MỚI, truyền new_refresh_jti vào
                # ✅ SECURITY FIX: Embed user_id and role in JWT for middleware authorization
                new_access_token = security.create_access_token(
                    data={"sub": username, "user_id": user.id, "role": user.role},
                    refresh_jti=new_refresh_jti,
                )
                new_access_jti, _ = security.decode_token_for_invalidation(
                    new_access_token
                )

                if not new_access_jti:
                    log.error("Failed to decode new ACCESS token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # (Đã xóa logic active_jti)

                # (STEP 6: Update Session) — PR1 Commit 2
                # Capture the return. ``None`` = the OLD jti has no matching DB
                # session row. The Redis ``session:{jti}`` check already passed
                # above, so a genuine reuse/forged token was already rejected;
                # None here is a DESYNC from the historical no-commit bug. FATAL:
                # force re-login instead of rotating a phantom session — this is
                # the self-heal for FROZEN sessions (their next refresh 401s →
                # clean re-login). Plain 401 so it does NOT feed the abuse
                # counter. A real DB error PROPAGATES (fail-closed: never rotate
                # Redis + return success on a half-written session).
                session = await session_service.update_session_activity(
                    db=db,
                    old_refresh_jti=old_refresh_jti,
                    new_refresh_jti=new_refresh_jti,
                    user_id=user.id,
                )
                if session is None:
                    log.warning(
                        "Refresh aborted: session desync (old jti not in DB) — "
                        "forcing re-login",
                        user_id=user.id,
                        old_jti=old_refresh_jti[:8],
                    )
                    raise session_desync_exception

                log.info(
                    "DB changes staged (savepoint, not yet committed)",
                    user_id=user.id,
                )

            except InvalidToken:
                raise credentials_exception
            except HTTPException:
                raise

        # ── Savepoint released: the new refresh_jti is staged in the OUTER
        #    transaction but NOT yet committed. Approach A ordering from here:
        #    Redis rotate FIRST, then DB commit, with best-effort compensation
        #    to OLD on either failure. Rationale: if we committed DB first and
        #    Redis then failed, DB=new while cookie/Redis=old → the next refresh
        #    would re-desync and blacklist the wrong jti. Redis-first +
        #    compensate keeps both stores consistent without a DB compensation
        #    transaction; the None-FATAL above stops the desync loop entirely.

        async def _compensate_session_to_old() -> None:
            """Best-effort: restore the OLD session to Redis (and drop the NEW
            key + un-blacklist OLD) so the client's UNCHANGED old refresh cookie
            still authenticates — no lockout. Uses the OLD token's REMAINING ttl
            (never the full window) so compensation can't silently extend the
            session."""
            try:
                _, _old_ttl = security.decode_token_for_invalidation(refresh_token)
                comp_ttl = max(60, int(_old_ttl)) if _old_ttl else 60
                async with safe_redis_pipeline(transaction=True) as pipe:
                    pipe.set(f"session:{old_refresh_jti}", str(user.id), ex=comp_ttl)
                    pipe.delete(f"session:{new_refresh_jti}")
                    pipe.delete(f"blacklist:{old_refresh_jti}")
                    await pipe.execute()
            except Exception as e_comp:  # pragma: no cover — best-effort
                log.error(
                    "Refresh compensation to OLD failed (manual review needed)",
                    user_id=getattr(user, "id", None),
                    error=str(e_comp),
                    exc_info=True,
                )

        # (STEP 7: Redis rotate — BEFORE commit)
        try:
            async with safe_redis_pipeline(transaction=True) as pipe:
                pipe.delete(f"session:{old_refresh_jti}")
                pipe.set(
                    f"session:{new_refresh_jti}",
                    str(user.id),
                    ex=new_refresh_ttl,
                )
                # Blacklist the old token for its full remaining window.
                full_refresh_ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
                safe_ttl = max(60, full_refresh_ttl)
                pipe.set(f"blacklist:{old_refresh_jti}", "rotated", ex=safe_ttl)
                await pipe.execute()
            log.info("✅ Redis update successful (session rotated)", user_id=user.id)
        except Exception as e_redis:
            # The pipeline may have applied partially → undefined Redis state.
            # Compensate to OLD, roll back the staged DB change, fail closed.
            log.error(
                "❌ Redis pipeline failed during rotate — compensating to OLD",
                user_id=user.id,
                error=str(e_redis),
                exc_info=True,
            )
            await _compensate_session_to_old()
            await db.rollback()
            raise service_unavailable

        # (STEP 8: Commit the DB refresh_jti rotation)
        try:
            await db.commit()
        except Exception as e_commit:
            # Redis already rotated to NEW; undo it so the client's still-held
            # OLD cookie keeps working (no lockout), then roll back DB.
            log.error(
                "❌ DB commit failed after Redis rotate — compensating Redis to OLD",
                user_id=user.id,
                error=str(e_commit),
                exc_info=True,
            )
            await _compensate_session_to_old()
            await db.rollback()
            raise service_unavailable

        log.info("✅ Token rotation completed successfully", user_id=user.id)

        # ✅ FIX-4/5: user info in body; tokens ONLY in httpOnly cookies.
        response = JSONResponse(
            content={
                "token_type": "bearer",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role,
                },
            },
            status_code=200,
        )

        # ✅ SECURITY FIX: Set new access_token in httpOnly cookie
        # ⚠️ max_age = TTL của REFRESH token mới (xem ghi chú ở nhánh login).
        # Cookie phải sống lâu hơn token, nếu không thì sau 15 phút middleware
        # mất luôn dữ liệu để phân biệt "chưa đăng nhập" với "phiên còn sống".
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=settings.APP_ENV == "production",
            samesite="lax",
            max_age=int(new_refresh_ttl),
            path="/",
        )
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=settings.APP_ENV == "production",
            samesite="strict",
            max_age=int(new_refresh_ttl),
            path="/api",  # cookie sent to all /api/* endpoints
        )

        # ✅ CSRF Protection: refresh CSRF token on token refresh.
        set_csrf_cookie(response)

        # ✅ M4: clear failed refresh counter on success.
        try:
            await safe_redis_delete(f"refresh_fail:{username}")
        except Exception:
            pass

        return response

    except InvalidCredentials:
        # Non-active account denied at the Tầng A gate above. Route to a clean
        # 401 via the global handler WITHOUT tripping the refresh-abuse counter
        # or revoking sessions (this is a legitimate deny, not token abuse).
        raise
    except (JWTError, InvalidToken):
        # ✅ M4: Increment failed refresh counter
        if _refresh_username:
            try:
                fail_key = f"refresh_fail:{_refresh_username}"
                window = settings.REFRESH_FAILURE_WINDOW_MINUTES * 60
                current = await safe_redis_get(fail_key)
                new_count = (int(current) if current else 0) + 1
                await safe_redis_set(fail_key, str(new_count), ex=window)

                if new_count >= settings.REFRESH_MAX_FAILURES:
                    log.warning(
                        "Refresh failure threshold reached - revoking all sessions",
                        username=_refresh_username,
                        fail_count=new_count,
                        security_event="REFRESH_ABUSE_DETECTED",
                    )
                    try:
                        user = await user_service.get_user_by_username(db, _refresh_username)
                        if user:
                            await user_service.invalidate_all_sessions(db, user)
                    except Exception as revoke_err:
                        log.error("Failed to revoke sessions after refresh abuse", error=str(revoke_err))
            except Exception as redis_err:
                log.error("Failed to track refresh failure", error=str(redis_err))

        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Unhandled exception in refresh token endpoint", error=str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


# =============================================================================
# MFA (Multi-Factor Authentication) ENDPOINTS
# =============================================================================


@router.post("/verify-mfa")
@limiter.limit(RateLimits.AUTH_LOGIN)  # 5/min - IP-based rate limit (Layer 1)
async def verify_mfa(
    request: Request,
    mfa_data: schemas.MfaVerifySchema,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Verify MFA code after successful password authentication.

    Security (defense in depth):
    - Layer 1: IP-based rate limit (5/min via slowapi)
    - Layer 2: Per-user Redis counter (5 attempts / 5 min)
    - Layer 3: AccountLockoutService (cumulative lockout)
    """
    from ..services import mfa_service
    from ..security.account_lockout import AccountLockoutService

    # 1. Decode mfa_token (verify type="mfa")
    payload = mfa_service.decode_mfa_token(mfa_data.mfa_token)
    username = payload.get("sub")
    user_id = payload.get("user_id")

    if not username or not user_id:
        raise HTTPException(status_code=401, detail="Invalid MFA token")

    # 1b. `jti` là ĐỊNH DANH của bằng chứng MFA — thiếu nó thì KHÔNG có gì để
    # đánh dấu đã dùng, nên cũng không có cách nào ngăn dùng lại.
    #
    # ⚠️ Bản trước bọc toàn bộ lớp bảo vệ trong `if mfa_jti:` — token không có
    # `jti` (token cũ, token do một bản `create_mfa_token` khác phát, hay token
    # được nặn ra) đi thẳng qua mà KHÔNG hề bị kiểm dùng-lại, và không để lại
    # dấu vết nào cho biết chuyện đó đã xảy ra. Thiếu định danh ⇒ từ chối.
    mfa_jti = payload.get("jti")
    if not isinstance(mfa_jti, str) or not mfa_jti.strip():
        log.warning(
            "mfa_token_missing_jti", username=username,
            action="mfa.token_missing_jti",
        )
        raise HTTPException(status_code=401, detail="Invalid MFA token")

    # 1c. Từ chối SỚM một token đã dùng, để không tiêu lượt thử và không tốn
    # CPU verify cho một token chắc chắn hỏng.
    #
    # ⚠️ Đây CHỈ là tối ưu, KHÔNG phải cổng có thẩm quyền: giữa `EXISTS` ở đây
    # và lúc đăng nhập hoàn tất còn cả quá trình xác minh (với backup code là
    # một phép bcrypt ~220ms), thừa sức để một request thứ hai lọt qua cùng chỗ
    # này. `safe_redis_khoa_ton_tai` cũng trả `False` khi Redis lỗi — cố ý, vì
    # một phép kiểm sớm không thẩm quyền thì không được làm hỏng request.
    # Quyết định thật nằm ở bước 5 — `SET NX` nguyên tử, TRƯỚC khi cấp phiên.
    if await safe_redis_khoa_ton_tai(f"mfa_used:{mfa_jti}", _NHAN_KHOA_MFA_TOKEN):
        raise HTTPException(
            status_code=401, detail="MFA token already used. Please login again."
        )

    # 2. RESERVATION (Layer 2) — ĐẶT CHỖ TRƯỚC CHI PHÍ CPU.
    #
    # ⚠️ Bản trước: GET đếm ở đây, rồi GET+SET tăng đếm SAU khi verify. Hai lỗi:
    #   * bộ đếm tăng sau bcrypt, nên năm request đầu đều trả giá đầy đủ —
    #     đo được 14,1s CPU mỗi mã sai. Bộ đếm không phải hàng rào chi phí.
    #   * GET rồi SET không nguyên tử: hai request đồng thời cùng đọc n, cùng
    #     ghi n+1, và cùng lọt qua kiểm tra.
    # Nay: một script Lua NGUYÊN TỬ chạy TRƯỚC khi verify, tự quyết cho qua hay
    # chặn. Vượt trần ⇒ 429 và không tốn một phép bcrypt nào.
    #
    # ⚠️ Và request đã bị chặn KHÔNG được tăng bộ đếm hay gia hạn TTL. Bản trước
    # làm cả hai, nên kẻ tấn công chỉ cần gõ một lần trước mỗi lần hết hạn là
    # giữ nạn nhân bị khoá MFA vô thời hạn (đo được: TTL 30s → 300s mỗi request
    # bị chặn). Đó là đổi một lỗ hổng CPU lấy một lỗ hổng availability.
    attempt_key = f"mfa_attempts:{username}"
    window = settings.MFA_ATTEMPT_WINDOW_MINUTES * 60
    dat_cho = await safe_redis_reserve_attempt(
        attempt_key, window, settings.MFA_MAX_ATTEMPTS
    )

    if dat_cho is None:
        # FAIL CLOSED: không CHỨNG MINH được đặt chỗ thì không tiêu CPU.
        # "Chứng minh" ở đây gồm cả TTL dương — một bộ đếm không hạn là một
        # khoá vĩnh viễn, hỏng theo chiều ngược lại nhưng vẫn là hỏng.
        # Đây là đường brute-force OTP; không có bộ đếm nghĩa là không có trần.
        # (Khác với fail-open có chủ đích của blacklist JWT trên /profile.)
        log.error(
            "mfa_reservation_unavailable", username=username,
            action="mfa.reservation_failed",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Không xác thực được lúc này. Vui lòng thử lại sau.",
            },
            headers={"Retry-After": "60"},
        )

    # TTL đọc trong CÙNG script với INCR/EXPIRE, nên nó là hạn thật.
    # Quyết định cho qua/chặn lấy THẲNG từ `allowed`: ngưỡng chỉ được diễn giải
    # ở một nơi (script), không so lại ở đây bằng một phép bất đẳng thức thứ hai.
    attempts_used = dat_cho.count

    if not dat_cho.allowed:
        retry_after = max(dat_cho.ttl, 60)
        log.warning(
            "mfa_rate_limited", user_id=user_id, username=username,
            attempts=attempts_used, retry_after=retry_after,
            action="mfa.rate_limited",
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Quá nhiều lần thử xác thực. Vui lòng thử lại sau.",
            },
            headers={"Retry-After": str(retry_after)},
        )

    # 3. Load user
    user = await user_service.get_user_by_username(db, username=username)
    if not user or user.id != user_id:
        raise HTTPException(status_code=401, detail="Invalid MFA token")

    # ===== STATUS GATE (Tầng B — early) =====
    # Block non-active accounts BEFORE spending an OTP.
    # Catches the TOCTOU window where the account is deactivated between /login
    # (mfa_token issued) and /verify-mfa. Authoritative re-check happens in
    # _complete_login_flow (Tầng A) below.
    #
    # ⚠️ Bộ đếm MFA thì ĐÃ tăng rồi, ở bước đặt chỗ phía trên — cổng này không
    # còn chạy trước nó như chú thích cũ nói. Cố ý: hàng rào chi phí phải đứng
    # trước MỌI thứ, kể cả trước khi biết user còn active hay không. Hệ quả là
    # một tài khoản đã bị vô hiệu vẫn tiêu lượt thử của chính nó, và đó là điều
    # chấp nhận được — không có OTP nào bị tiêu, không có bcrypt nào chạy.
    _deny_if_not_active(
        user, ip_address=request.client.host if request.client else None
    )

    # 4. Verify MFA code
    is_valid = await mfa_service.verify_mfa_code(db, user, mfa_data.code)

    if not is_valid:
        # Bộ đếm ĐÃ tăng ở bước 2 (reservation). Không tăng lại ở đây — nếu
        # không thì một lần thử tính hai lần và C1 (đếm đúng +1 mỗi lần sai)
        # sẽ sai.
        l2_blocked = attempts_used >= settings.MFA_MAX_ATTEMPTS

        # Feed into AccountLockoutService (Layer 3) only if L2 hasn't already blocked.
        # Avoids double-punish: L2 blocks fast OTP brute-force, L3 tracks cumulative auth failures.
        if not l2_blocked:
            await AccountLockoutService.record_failed_attempt(
                db=db,
                username=username,
                ip_address=request.client.host if request.client else None,
            )

        log.warning(
            "mfa_failed", user_id=user.id, action="mfa.verify_failed",
        )
        raise HTTPException(status_code=401, detail="Invalid verification code")

    # 5. CHIẾM bằng chứng MFA — NGUYÊN TỬ, và TRƯỚC khi cấp phiên.
    #
    # Đây là cổng có thẩm quyền của luồng này. Ba điều làm nên nó:
    #
    #   * `SET NX` thay cho `SET`: đúng MỘT trong các request đồng thời chiếm
    #     được. Bản trước ghi đè vô điều kiện, nên hai request cùng token cùng
    #     verify xong, cùng ghi dấu, và cùng được cấp phiên (đo được:
    #     `_complete_login_flow` chạy 2 lần cho MỘT mfa_token).
    #   * Đặt TRƯỚC `_complete_login_flow`: chiếm sau khi đã cấp phiên thì
    #     phiên thứ hai đã ra khỏi cửa rồi, dấu vết ghi lúc đó không thu hồi
    #     được gì.
    #   * Lỗi Redis ⇒ 503, KHÔNG đăng nhập. `try/except` cũ chỉ ghi log rồi đi
    #     tiếp — tức mọi lượt Redis trục trặc đều biến `mfa_token` thành token
    #     dùng-nhiều-lần, âm thầm.
    #
    # ⚠️ Chiếm ở ĐÂY chứ không phải ngay lúc vào: chiếm sớm sẽ đốt token sau
    # mỗi lần gõ sai mã, làm mất quyền thử lại mà `MFA_MAX_ATTEMPTS` hứa hẹn.
    # Token chỉ bị tiêu khi nó đã thực sự chứng minh được MFA.
    mfa_ttl = settings.MFA_TOKEN_EXPIRE_MINUTES * 60
    ket_qua_chiem = await safe_redis_claim_once(
        f"mfa_used:{mfa_jti}", "1", mfa_ttl, _NHAN_KHOA_MFA_TOKEN
    )

    if ket_qua_chiem is KetQuaChiem.DA_BI_CHIEM:
        # Một request khác đã hoàn tất trước với đúng token này.
        log.warning(
            "mfa_token_reuse_blocked", user_id=user.id,
            action="mfa.token_reuse_blocked",
        )
        raise HTTPException(
            status_code=401, detail="MFA token already used. Please login again."
        )

    if ket_qua_chiem is not KetQuaChiem.DA_CHIEM:
        # FAIL CLOSED: không chứng minh được token này chưa bị dùng thì không
        # cấp phiên. Thà bắt đăng nhập lại còn hơn phát hai phiên từ một bằng
        # chứng MFA.
        log.error(
            "mfa_token_claim_unavailable", user_id=user.id,
            action="mfa.token_claim_unavailable",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Không xác thực được lúc này. Vui lòng thử lại sau.",
            },
            headers={"Retry-After": "60"},
        )

    # ⚠️ Từ đây trở đi, token ĐÃ BỊ TIÊU. Nếu các bước dưới hỏng thì KHÔNG được
    # xoá dấu chiếm để "bù": một token đã chứng minh MFA xong phải coi là đã
    # dùng, kể cả khi phiên không dựng được. Người dùng đăng nhập lại — đó là
    # cái giá đúng, so với việc mở lại cửa sổ cho phát lại.

    # 6. Reset attempt counters
    try:
        await safe_redis_delete(attempt_key)
    except Exception:
        pass
    await AccountLockoutService.reset_attempts(username)

    log.info("mfa_login_complete", user_id=user.id, action="mfa.verify_success")

    # 7. Complete login flow (shared helper: tokens, session, history, cookies)
    return await _complete_login_flow(user, request, db)


@router.post("/mfa/setup", response_model=schemas.MfaSetupResponse)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_setup(
    request: Request,
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Initiate MFA setup. Returns QR code and secret.
    Secret is stored temporarily in Redis (10min TTL), NOT in DB.
    """
    from ..services import mfa_service

    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is already enabled. Disable it first to re-setup.",
        )

    setup_data, _ = await mfa_service.setup_mfa(
        user_id=current_user.id, username=current_user.username
    )

    return setup_data


@router.post("/mfa/enable", response_model=schemas.MfaBackupCodesResponse)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_enable(
    request: Request,
    enable_data: schemas.MfaEnableRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    refresh_token_cookie: str = Cookie(None, alias="refresh_token"),
):
    """
    Enable MFA after verifying TOTP code from authenticator app.
    Returns one-time backup codes. Revokes all other sessions.
    """
    from ..services import mfa_service

    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is already enabled.",
        )

    # Get current session ID to preserve it during session revocation
    current_session_id = None
    if refresh_token_cookie:
        try:
            payload = security.decode_token(refresh_token_cookie)
            current_refresh_jti = payload.get("jti")
            if current_refresh_jti:
                from ..repositories.session_repository import SessionRepository
                session_repo = SessionRepository(db)
                session_record = await session_repo.get_by_refresh_jti_and_user(
                    current_refresh_jti, current_user.id
                )
                if session_record:
                    current_session_id = session_record.id
        except Exception:
            pass  # Continue without preserving current session

    backup_codes, callback = await mfa_service.enable_mfa(
        db=db,
        user=current_user,
        code=enable_data.code,
        current_session_id=current_session_id,
    )

    await db.commit()

    if callback:
        await callback()

    return schemas.MfaBackupCodesResponse(backup_codes=backup_codes)


@router.post("/mfa/disable", status_code=status.HTTP_200_OK)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_disable(
    request: Request,
    disable_data: schemas.MfaDisableRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """Disable MFA. Requires password verification."""
    from ..services import mfa_service

    if not current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled.",
        )

    result, callback = await mfa_service.disable_mfa(
        db=db, user=current_user, password=disable_data.password
    )

    await db.commit()

    if callback:
        await callback()

    return {"message": "MFA disabled successfully."}


@router.get("/mfa/status", response_model=schemas.MfaStatusResponse)
@limiter.limit(RateLimits.DATA_READ)
async def mfa_status(
    request: Request,
    current_user: models.User = Depends(deps.get_current_user),
):
    """Get MFA status for current user."""
    return schemas.MfaStatusResponse(
        mfa_enabled=current_user.mfa_enabled,
        has_backup_codes=bool(current_user.backup_codes_hashed),
    )


@router.post("/mfa/backup-codes", response_model=schemas.MfaBackupCodesResponse)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_regenerate_backup_codes(
    request: Request,
    regen_data: schemas.MfaBackupCodesRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """Regenerate backup codes. Invalidates all old codes. Requires password."""
    from ..services import mfa_service

    new_codes, callback = await mfa_service.regenerate_backup_codes(
        db=db, user=current_user, password=regen_data.password
    )

    await db.commit()

    if callback:
        await callback()

    return schemas.MfaBackupCodesResponse(backup_codes=new_codes)
