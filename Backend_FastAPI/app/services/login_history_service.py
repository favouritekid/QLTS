# app/services/login_history_service.py
"""
✅ PATTERN A COMPLIANT - Login History Service

Service for managing login history and anomaly detection.
Following Architecture Guidelines:
- No HTTPException imports
- No db.commit() calls
- Uses Repository for all DB queries
- Returns Tuple[result, post_commit_callback] for write operations
"""
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent

from app import models, schemas
from app.repositories.login_history_repository import LoginHistoryRepository
from app.repositories.trusted_device_repository import TrustedDeviceRepository
from app.utils.exceptions import ResourceNotFoundError

log = logging.getLogger(__name__)


# Risk score weights
RISK_WEIGHTS = {
    "new_ip": 30,
    "new_device": 40,
    "new_location": 50,
    "impossible_travel": 80,
}


def generate_device_fingerprint(
    browser: Optional[str],
    os: Optional[str],
    device_type: Optional[str],
) -> str:
    """
    Generate a stable device fingerprint from browser/OS info.
    
    Returns:
        64-character SHA256 hash of device attributes
    """
    components = [
        browser or "unknown",
        os or "unknown",
        device_type or "unknown",
    ]
    fingerprint_string = "|".join(components)
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()


async def record_login(
    db: AsyncSession,
    user_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    oauth_provider: Optional[str] = None,
) -> Tuple[models.LoginHistory, Callable]:
    """
    Record a login attempt and detect anomalies.
    
    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    
    Phase 4: Trusted devices skip "new device" anomaly detection.
    
    Returns:
        Tuple of (login_history, post_commit_callback)
    """
    login_repo = LoginHistoryRepository(db)
    trusted_repo = TrustedDeviceRepository(db)
    
    # Parse user agent
    device_info = _parse_user_agent(user_agent)
    
    # Generate device fingerprint for trusted device check
    device_fingerprint = generate_device_fingerprint(
        browser=device_info.get("browser"),
        os=device_info.get("os"),
        device_type=device_info.get("device_type"),
    )
    
    # ✅ Phase 4: Check if device is trusted
    is_trusted_device = await trusted_repo.is_device_trusted(user_id, device_fingerprint)
    
    # Check for anomalies (skip new_device check if trusted)
    is_new_ip = not await login_repo.check_ip_seen_before(user_id, ip_address)
    is_new_device = False if is_trusted_device else not await _check_device_seen(login_repo, user_id, device_info)
    is_new_location = not await login_repo.check_country_seen_before(user_id, country)
    
    # Check for impossible travel
    last_login = await login_repo.get_last_login(user_id)
    impossible_travel = _check_impossible_travel(last_login, country)
    
    # Calculate risk score (reduced if device is trusted)
    risk_score = _calculate_risk_score(
        is_new_ip=is_new_ip,
        is_new_device=is_new_device,
        is_new_location=is_new_location,
        impossible_travel=impossible_travel,
        is_trusted_device=is_trusted_device,
    )
    
    # Create login history record
    login = models.LoginHistory(
        user_id=user_id,
        login_at=datetime.now(timezone.utc),
        ip_address=ip_address,
        country=country,
        city=city,
        device_type=device_info.get("device_type"),
        browser=device_info.get("browser"),
        os=device_info.get("os"),
        is_new_ip=is_new_ip,
        is_new_device=is_new_device,
        is_new_location=is_new_location,
        risk_score=risk_score,
        oauth_provider=oauth_provider,
    )
    
    db.add(login)
    await db.flush()
    await db.refresh(login)
    
    # Update trusted device last_used_at if applicable
    if is_trusted_device:
        await trusted_repo.update_last_used(user_id, device_fingerprint)
    
    # Post-commit callback for notifications
    async def _post_commit():
        if login.is_suspicious:
            log.warning(
                "Suspicious login detected",
                user_id=user_id,
                ip=ip_address,
                risk_score=risk_score,
                new_ip=is_new_ip,
                new_device=is_new_device,
                new_location=is_new_location,
            )
            # Note: Notification is dispatched in auth.py router (Phase 3)
    
    return login, _post_commit


async def get_login_history(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[int, List[models.LoginHistory]]:
    """
    Get paginated login history for a user.
    
    Returns:
        Tuple of (total_count, login_history_list)
    """
    repo = LoginHistoryRepository(db)
    return await repo.get_by_user_id(user_id, skip, limit)


async def get_suspicious_logins(
    db: AsyncSession,
    user_id: int,
    pending_only: bool = True,
) -> List[models.LoginHistory]:
    """
    Get suspicious logins for a user.
    
    Args:
        user_id: User ID
        pending_only: Only return logins without user response
        
    Returns:
        List of suspicious login records
    """
    repo = LoginHistoryRepository(db)
    return await repo.get_suspicious_logins(user_id, pending_only)


async def confirm_login(
    db: AsyncSession,
    user_id: int,
    login_id: int,
    trust_device: bool = True,
) -> Tuple[models.LoginHistory, Callable]:
    """
    User confirms a suspicious login as legitimate.
    
    Phase 4: Optionally adds the device to trusted list.
    
    IMPORTANT: Router must call db.commit() and then execute the returned callback.
    
    Args:
        db: Database session
        user_id: User ID
        login_id: Login history ID to confirm
        trust_device: If True, add device to trusted list
    
    Raises:
        ResourceNotFoundError: If login not found or doesn't belong to user
    """
    login_repo = LoginHistoryRepository(db)
    trusted_repo = TrustedDeviceRepository(db)
    
    login = await login_repo.get_by_id(login_id)
    
    if not login or login.user_id != user_id:
        raise ResourceNotFoundError(f"Login {login_id} not found")
    
    login.user_response = "confirmed"
    login.responded_at = datetime.now(timezone.utc)
    
    # ✅ Phase 4: Add device to trusted list
    trusted_device = None
    if trust_device and login.browser and login.os:
        device_fingerprint = generate_device_fingerprint(
            browser=login.browser,
            os=login.os,
            device_type=login.device_type,
        )
        trusted_device = await trusted_repo.trust_device(
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            name=f"{login.browser} on {login.os}",
            browser=login.browser,
            os=login.os,
            ip_address=login.ip_address,
        )
    
    await db.flush()
    await db.refresh(login)
    
    async def _post_commit():
        log.info(
            "User confirmed suspicious login",
            user_id=user_id,
            login_id=login_id,
            device_trusted=trust_device and trusted_device is not None,
        )
    
    return login, _post_commit


async def secure_account(
    db: AsyncSession,
    user_id: int,
    login_id: int,
) -> Tuple[models.LoginHistory, Callable]:
    """
    User reports suspicious login and secures account.
    
    IMPORTANT: Router must call db.commit() and then execute the returned callback.
    The callback will revoke all sessions and force password change.
    
    Raises:
        ResourceNotFoundError: If login not found or doesn't belong to user
    """
    repo = LoginHistoryRepository(db)
    login = await repo.get_by_id(login_id)
    
    if not login or login.user_id != user_id:
        raise ResourceNotFoundError(f"Login {login_id} not found")
    
    login.user_response = "secured"
    login.responded_at = datetime.now(timezone.utc)
    
    await db.flush()
    await db.refresh(login)
    
    async def _post_commit():
        log.warning("User secured account after suspicious login", user_id=user_id, login_id=login_id)
        # TODO Phase 5: Revoke all sessions, force password change
    
    return login, _post_commit


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _parse_user_agent(user_agent: Optional[str]) -> Dict[str, str]:
    """Parse User-Agent string into device info."""
    if not user_agent:
        return {"device_type": None, "browser": None, "os": None}
    
    try:
        ua = parse_user_agent(user_agent)
        
        # Determine device type
        if ua.is_mobile:
            device_type = "mobile"
        elif ua.is_tablet:
            device_type = "tablet"
        elif ua.is_pc:
            device_type = "desktop"
        else:
            device_type = "other"
        
        return {
            "device_type": device_type,
            "browser": f"{ua.browser.family} {ua.browser.version_string}",
            "os": f"{ua.os.family} {ua.os.version_string}",
        }
    except Exception:
        return {"device_type": None, "browser": None, "os": None}


async def _check_device_seen(
    repo: LoginHistoryRepository,
    user_id: int,
    device_info: Dict[str, str],
) -> bool:
    """Check if device has been seen before."""
    return await repo.check_device_seen_before(user_id, device_info)


def _check_impossible_travel(
    last_login: Optional[models.LoginHistory],
    current_country: Optional[str],
) -> bool:
    """
    Check for impossible travel (login from different country within 2 hours).
    """
    if not last_login or not current_country or not last_login.country:
        return False
    
    if last_login.country == current_country:
        return False
    
    time_diff = datetime.now(timezone.utc) - last_login.login_at
    if time_diff < timedelta(hours=2):
        return True
    
    return False


def _calculate_risk_score(
    is_new_ip: bool,
    is_new_device: bool,
    is_new_location: bool,
    impossible_travel: bool,
    is_trusted_device: bool = False,
) -> int:
    """
    Calculate risk score (0-100) based on anomaly flags.
    
    If device is trusted, a 20% reduction is applied to the final score.
    """
    score = 0
    
    if is_new_ip:
        score += RISK_WEIGHTS["new_ip"]
    if is_new_device:
        score += RISK_WEIGHTS["new_device"]
    if is_new_location:
        score += RISK_WEIGHTS["new_location"]
    if impossible_travel:
        score += RISK_WEIGHTS["impossible_travel"]
    
    # Apply reduction for trusted devices (20% off)
    if is_trusted_device and score > 0:
        score = int(score * 0.8)
    
    return min(score, 100)
