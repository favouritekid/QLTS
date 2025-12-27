# app/routers/security.py
"""
✅ PATTERN A COMPLIANT - Security Router

Endpoints for login security features:
- Login history viewing
- Confirm suspicious login ("This was me")
- Secure account ("This wasn't me")
- Trusted device management
"""
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..core import deps
from ..core.rate_limits import limiter, RateLimits
from ..services import login_history_service
from ..repositories.trusted_device_repository import TrustedDeviceRepository
from ..utils.exceptions import ResourceNotFoundError

router = APIRouter(prefix="/security", tags=["Security"])
log = structlog.get_logger(__name__)


# =============================================================================
# SCHEMAS
# =============================================================================


class LoginHistoryResponse(BaseModel):
    """Response schema for login history."""
    id: int
    login_at: str
    ip_address: Optional[str]
    country: Optional[str]
    city: Optional[str]
    device_type: Optional[str]
    browser: Optional[str]
    os: Optional[str]
    is_new_ip: bool
    is_new_device: bool
    is_new_location: bool
    risk_score: int
    is_suspicious: bool
    user_response: Optional[str]
    responded_at: Optional[str]

    class Config:
        from_attributes = True


class LoginHistoryListResponse(BaseModel):
    """Paginated login history response."""
    total: int
    items: List[LoginHistoryResponse]


class ConfirmLoginRequest(BaseModel):
    """Request to confirm a suspicious login."""
    login_id: int = Field(..., description="ID of the login history record")
    trust_device: bool = Field(True, description="Add device to trusted list")


class ConfirmLoginResponse(BaseModel):
    """Response after confirming a login."""
    message: str
    device_trusted: bool


class TrustedDeviceResponse(BaseModel):
    """Response schema for trusted device."""
    id: int
    name: Optional[str]
    browser: Optional[str]
    os: Optional[str]
    first_seen_at: str
    trusted_at: str
    last_used_at: Optional[str]

    class Config:
        from_attributes = True


class TrustedDeviceListResponse(BaseModel):
    """Paginated trusted devices response."""
    total: int
    items: List[TrustedDeviceResponse]


class SecureAccountResponse(BaseModel):
    """Response after securing account."""
    message: str
    sessions_revoked: int


# =============================================================================
# LOGIN HISTORY ENDPOINTS
# =============================================================================


@router.get("/login-history", response_model=LoginHistoryListResponse)
async def get_login_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get current user's login history.
    
    Returns paginated list of all login attempts with anomaly flags.
    """
    total, items = await login_history_service.get_login_history(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )
    
    return LoginHistoryListResponse(
        total=total,
        items=[
            LoginHistoryResponse(
                id=item.id,
                login_at=item.login_at.isoformat() if item.login_at else None,
                ip_address=item.ip_address,
                country=item.country,
                city=item.city,
                device_type=item.device_type,
                browser=item.browser,
                os=item.os,
                is_new_ip=item.is_new_ip,
                is_new_device=item.is_new_device,
                is_new_location=item.is_new_location,
                risk_score=item.risk_score,
                is_suspicious=item.is_suspicious,
                user_response=item.user_response,
                responded_at=item.responded_at.isoformat() if item.responded_at else None,
            )
            for item in items
        ],
    )


@router.get("/suspicious-logins", response_model=List[LoginHistoryResponse])
async def get_suspicious_logins(
    pending_only: bool = Query(True, description="Only return logins awaiting response"),
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get suspicious logins for current user.
    
    Returns list of logins flagged as suspicious (new IP/device/location).
    """
    items = await login_history_service.get_suspicious_logins(
        db=db,
        user_id=current_user.id,
        pending_only=pending_only,
    )
    
    return [
        LoginHistoryResponse(
            id=item.id,
            login_at=item.login_at.isoformat() if item.login_at else None,
            ip_address=item.ip_address,
            country=item.country,
            city=item.city,
            device_type=item.device_type,
            browser=item.browser,
            os=item.os,
            is_new_ip=item.is_new_ip,
            is_new_device=item.is_new_device,
            is_new_location=item.is_new_location,
            risk_score=item.risk_score,
            is_suspicious=item.is_suspicious,
            user_response=item.user_response,
            responded_at=item.responded_at.isoformat() if item.responded_at else None,
        )
        for item in items
    ]


# =============================================================================
# USER RESPONSE ENDPOINTS
# =============================================================================


@router.post("/confirm-login", response_model=ConfirmLoginResponse)
@limiter.limit(RateLimits.DEFAULT)
async def confirm_login(
    request: Request,  # Required by slowapi
    request_obj: ConfirmLoginRequest,
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Confirm a suspicious login as legitimate ("This was me").
    
    Optionally adds the device to trusted list so future logins
    from this device won't trigger alerts.
    """
    try:
        login, callback = await login_history_service.confirm_login(
            db=db,
            user_id=current_user.id,
            login_id=request_obj.login_id,
            trust_device=request_obj.trust_device,
        )
        
        await db.commit()
        await callback()
        
        log.info(
            "User confirmed suspicious login",
            user_id=current_user.id,
            login_id=request_obj.login_id,
            device_trusted=request_obj.trust_device,
        )
        
        return ConfirmLoginResponse(
            message="Login confirmed successfully",
            device_trusted=request_obj.trust_device and login.browser is not None,
        )
        
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        log.error("Failed to confirm login", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to confirm login")


@router.post("/secure-account", response_model=SecureAccountResponse)
@limiter.limit(RateLimits.AUTH_PASSWORD_CHANGE)
async def secure_account(
    request: Request,  # Required by slowapi
    login_id: int = Query(..., description="ID of the suspicious login"),
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Secure account after suspicious login ("This wasn't me").
    
    This will:
    1. Mark the login as "secured"
    2. Revoke all other sessions (R7 FIX: EXCEPT current session)
    3. Remove all trusted devices
    4. Force password change on next protected endpoint
    """
    from fastapi import Cookie
    from ..services.auth_service import decode_token
    from ..repositories.session_repository import SessionRepository
    
    try:
        from ..services import session_service
        
        login, callback = await login_history_service.secure_account(
            db=db,
            user_id=current_user.id,
            login_id=login_id,
        )
        
        # R7 FIX: Get current session ID to exclude from revocation
        # This prevents user from being logged out when securing their account
        current_session_id = None
        try:
            # Get refresh_token from cookie (manual extraction since we're mid-function)
            refresh_token = request.cookies.get("refresh_token")
            if refresh_token:
                payload = decode_token(refresh_token)
                jti = payload.get("jti")  # refresh token's own JTI
                if jti:
                    session_repo = SessionRepository(db)
                    current_session = await session_repo.get_by_jti(jti)
                    if current_session and current_session.user_id == current_user.id:
                        current_session_id = current_session.id
                        log.info(
                            "R7: Will preserve current session during secure_account",
                            session_id=current_session_id,
                            user_id=current_user.id
                        )
        except Exception as e:
            # If we can't get session, continue anyway (user will be logged out - acceptable fallback)
            log.warning("R7: Could not get current session, will revoke all", error=str(e))
        
        # Revoke all sessions EXCEPT current (R7 FIX)
        sessions_revoked = await session_service.revoke_all_other_sessions(
            db=db,
            user_id=current_user.id,
            except_session_id=current_session_id  # R7: Preserve current session
        )
        
        # Remove all trusted devices
        trusted_repo = TrustedDeviceRepository(db)
        await trusted_repo.remove_all_devices(current_user.id)
        
        await db.commit()
        await callback()
        
        log.warning(
            "User secured account after suspicious login",
            user_id=current_user.id,
            login_id=login_id,
            sessions_revoked=sessions_revoked,
            current_session_preserved=current_session_id is not None,
        )
        
        # R7: Update message to reflect user stays logged in
        return SecureAccountResponse(
            message="Account secured. Please change your password.",
            sessions_revoked=sessions_revoked,
        )
        
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        log.error("Failed to secure account", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to secure account")


# =============================================================================
# TRUSTED DEVICE ENDPOINTS
# =============================================================================


@router.get("/trusted-devices", response_model=TrustedDeviceListResponse)
async def get_trusted_devices(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """Get current user's trusted devices."""
    repo = TrustedDeviceRepository(db)
    total, items = await repo.get_by_user_id(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )
    
    return TrustedDeviceListResponse(
        total=total,
        items=[
            TrustedDeviceResponse(
                id=item.id,
                name=item.name,
                browser=item.browser,
                os=item.os,
                first_seen_at=item.first_seen_at.isoformat() if item.first_seen_at else None,
                trusted_at=item.trusted_at.isoformat() if item.trusted_at else None,
                last_used_at=item.last_used_at.isoformat() if item.last_used_at else None,
            )
            for item in items
        ],
    )


@router.delete("/trusted-devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_trusted_device(
    device_id: int,
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """Remove a device from trusted list."""
    repo = TrustedDeviceRepository(db)
    removed = await repo.remove_device(
        user_id=current_user.id,
        device_id=device_id,
    )
    
    if not removed:
        raise HTTPException(status_code=404, detail="Device not found")
    
    await db.commit()
    
    log.info(
        "User removed trusted device",
        user_id=current_user.id,
        device_id=device_id,
    )


@router.delete("/trusted-devices", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(RateLimits.AUTH_PASSWORD_CHANGE)
async def remove_all_trusted_devices(
    request: Request,  # Required by slowapi
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """Remove all trusted devices for current user."""
    repo = TrustedDeviceRepository(db)
    count = await repo.remove_all_devices(current_user.id)
    
    await db.commit()
    
    log.info(
        "User removed all trusted devices",
        user_id=current_user.id,
        devices_removed=count,
    )
