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
import re
import structlog
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent

from app import models, schemas
from app.repositories.login_history_repository import LoginHistoryRepository
from app.repositories.trusted_device_repository import TrustedDeviceRepository
from app.utils.exceptions import ResourceNotFoundError

log = structlog.get_logger(__name__)


# Risk score weights
RISK_WEIGHTS = {
    "new_ip": 30,
    "new_device": 40,
    "new_location": 50,
    "impossible_travel": 80,
}


# Trailing-version-suffix regex. Strips " 26.4" / " 147.0.0" / " 10" from
# display strings to recover the stable family identifier. Mirrors the
# Postgres ``regexp_replace(col, '\\s+[\\d][\\d.]*$', '')`` used by the
# sl20260524 migration backfill — keep these in lockstep.
_VERSION_SUFFIX_RE = re.compile(r"\s+[\d][\d.]*$")


def _family_from_display(s: Optional[str]) -> Optional[str]:
    """Strip the trailing version-like suffix from a display string.

    Deterministic + idempotent: ``"Mobile Safari 26.4"`` → ``"Mobile Safari"``,
    ``"iOS 18.7.1"`` → ``"iOS"``, ``"Windows 10"`` → ``"Windows"``. Empty /
    ``None`` input → ``None``.

    Used as a NULL-safe fallback in ``confirm_login`` for ``login_history``
    rows that pre-date the sl20260524 backfill (where ``browser_family`` /
    ``os_family`` columns are NULL on legacy rows).
    """
    if not s:
        return None
    stripped = _VERSION_SUFFIX_RE.sub("", s).strip()
    return stripped or None


def generate_device_fingerprint(
    browser_family: Optional[str],
    os_family: Optional[str],
    device_type: Optional[str],
    user_id: Optional[int] = None,
) -> str:
    """Generate a canonical device fingerprint (family-only inputs).

    SECURITY FIX (C1): Added user_id and server-side salt to prevent
    spoofing. Even if attacker knows browser_family/os_family/device_type,
    they cannot recreate the fingerprint without the server-side salt.

    OPTION-B FIX (sl20260524): Inputs are FAMILY identifiers (no version
    suffix) so the hash stays stable across browser/OS minor-version
    updates. Pre-PR this took the full display strings, which caused the
    user-reported bug — clicking "Là tôi" trusted a device whose hash
    drifted on the next OS update, re-flagging "thiết bị mới".

    Args:
        browser_family: Browser family ("Mobile Safari" / "Chrome" / ...).
            Caller is responsible for stripping the version suffix via
            ``_family_from_display`` or by reading ``ua.browser.family``.
        os_family: OS family ("iOS" / "Windows" / ...).
        device_type: mobile / desktop / tablet / other.
        user_id: User ID for additional entropy (different users →
            different fingerprints; protects against cross-user
            fingerprint correlation).

    Returns:
        64-character SHA256 hex digest.

    Migration parity: ``sl20260524_suspicious_login_canonical.py`` carries
    an immutable LOCAL copy (``_generate_device_fingerprint_canonical_v1``)
    that MUST produce identical output for identical inputs. Test
    ``test_canonical_helper_parity_with_service`` asserts the lockstep.
    """
    from app.config import settings

    components = [
        browser_family or "unknown",
        os_family or "unknown",
        device_type or "unknown",
        str(user_id) if user_id else "anonymous",
        settings.DEVICE_FINGERPRINT_SALT,  # Server-side secret
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
    # Phase 1: Added for merged email sending (previously in AnomalyDetector)
    email_to: Optional[str] = None,
    username: Optional[str] = None,
    # R1+R2 FIX: Added for pending notification storage
    refresh_jti: Optional[str] = None,
) -> Tuple[models.LoginHistory, Callable]:
    """
    Record a login attempt and detect anomalies.
    
    PHASE 1 MERGE: This is now the single source of truth for anomaly detection.
    - Records login history for persistent audit trail
    - Detects suspicious activity (new IP, device, location)
    - Sends email alert for suspicious logins (moved from AnomalyDetector)
    
    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    
    Phase 4: Trusted devices skip "new device" anomaly detection.
    
    Args:
        email_to: User email for sending login alert (required for email)
        username: Username for email personalization
    
    Returns:
        Tuple of (login_history, post_commit_callback)
    """
    login_repo = LoginHistoryRepository(db)
    trusted_repo = TrustedDeviceRepository(db)

    # Parse user agent → display strings (for admin UI) + family identifiers
    # (for canonical fingerprint that survives browser/OS version drift).
    device_info = _parse_user_agent(user_agent)

    # Generate canonical device fingerprint from FAMILY inputs (Option-B
    # sl20260524). Per Plan v10 Commit 2: pre-PR this hashed the full
    # display strings ("Mobile Safari 26.4"), which drifted on every minor
    # version bump → trusted_device row stopped matching → re-flag
    # "thiết bị mới" after every iOS update.
    device_fingerprint = generate_device_fingerprint(
        browser_family=device_info.get("browser_family"),
        os_family=device_info.get("os_family"),
        device_type=device_info.get("device_type"),
        user_id=user_id,
    )

    # ✅ Phase 4: Check if device is trusted (matches against canonical
    # fingerprint — sl20260524 migration re-hashed every trusted_device
    # row from display strings to family inputs, so existing trust rows
    # match post-migration).
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

    # Create login history record. Persist BOTH display strings (browser /
    # os — for admin UI) AND canonical fingerprint inputs (browser_family /
    # os_family / device_fingerprint — for fast match in
    # ``check_device_seen_before`` and for ``confirm_login`` to rebuild
    # the same hash).
    login = models.LoginHistory(
        user_id=user_id,
        login_at=datetime.now(timezone.utc),
        ip_address=ip_address,
        country=country,
        city=city,
        device_type=device_info.get("device_type"),
        browser=device_info.get("browser"),
        os=device_info.get("os"),
        browser_family=device_info.get("browser_family"),
        os_family=device_info.get("os_family"),
        device_fingerprint=device_fingerprint,
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
    
    # Post-commit callback for notifications and email alerts
    # PHASE 1 MERGE: Email sending moved here from AnomalyDetector
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
            
            # PHASE 1: Send email alert (previously in AnomalyDetector/auth.py)
            if email_to and username:
                try:
                    from app.celery_utils import send_login_alert_email_task
                    
                    # Build location string
                    location_parts = []
                    if city:
                        location_parts.append(city)
                    if country:
                        location_parts.append(country)
                    location = ", ".join(location_parts) if location_parts else None
                    
                    # Build anomalies dict for email template
                    anomalies_dict = {
                        "is_suspicious": True,
                        "new_ip": is_new_ip,
                        "new_device": is_new_device,
                        "new_location": is_new_location,
                    }
                    
                    send_login_alert_email_task.delay(
                        email_to=email_to,
                        username=username,
                        ip_address=ip_address or "Unknown",
                        user_agent=user_agent or "Unknown",
                        device_type=device_info.get("device_type") or "Unknown",
                        browser=device_info.get("browser") or "Unknown",
                        os=device_info.get("os") or "Unknown",
                        anomalies=anomalies_dict,
                        location=location,
                    )
                    log.info(
                        "Login alert email queued from login_history_service",
                        user_id=user_id,
                        email_to=email_to,
                    )
                except Exception as email_error:
                    log.error(
                        "Failed to queue login alert email",
                        user_id=user_id,
                        error=str(email_error),
                    )
            
            # R1+R2 FIX: Store pending notification in Redis for socket delivery on connect
            # This solves the race condition where socket isn't connected when notification is emitted
            if refresh_jti:
                try:
                    import json
                    from ..database import safe_redis_lpush, safe_redis_expire
                    
                    pending_key = f"pending_login_notif:{user_id}:{refresh_jti}"
                    notification_data = json.dumps({
                        "type": "SUSPICIOUS_LOGIN",
                        "login_id": login.id,
                        "login_at": login.login_at.isoformat() if login.login_at else None,
                        "ip_address": ip_address,
                        "city": city,
                        "country": country,
                        "device_type": device_info.get("device_type"),
                        "browser": device_info.get("browser"),
                        "os": device_info.get("os"),
                        "risk_score": login.risk_score,
                        "is_new_ip": is_new_ip,
                        "is_new_device": is_new_device,
                        "is_new_location": is_new_location,
                    })
                    await safe_redis_lpush(pending_key, notification_data)
                    await safe_redis_expire(pending_key, 60)  # 60 seconds TTL
                    log.info(
                        "R1+R2: Stored pending login notification in Redis",
                        user_id=user_id,
                        refresh_jti=refresh_jti[:8] + "..."
                    )
                except Exception as redis_error:
                    log.error(
                        "R1+R2: Failed to store pending notification",
                        user_id=user_id,
                        error=str(redis_error),
                    )
            # Note: Socket notification is dispatched in auth.py router (Phase 3)
    
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
    
    SECURITY FIX (C3): Added time validation - cannot confirm logins older than 7 days.
    This prevents attackers from having old suspicious logins confirmed.
    
    Phase 4: Optionally adds the device to trusted list.
    
    IMPORTANT: Router must call db.commit() and then execute the returned callback.
    
    Args:
        db: Database session
        user_id: User ID
        login_id: Login history ID to confirm
        trust_device: If True, add device to trusted list
    
    Raises:
        ResourceNotFoundError: If login not found or doesn't belong to user
        ValidationError: If login is older than 7 days (C3 fix)
    """
    from app.utils.exceptions import ValidationError
    
    # Maximum age for confirming a login (security policy)
    MAX_LOGIN_AGE_DAYS = 7
    
    login_repo = LoginHistoryRepository(db)
    trusted_repo = TrustedDeviceRepository(db)
    
    login = await login_repo.get_by_id(login_id)
    
    if not login or login.user_id != user_id:
        raise ResourceNotFoundError(f"Login {login_id} not found")
    
    # C3 FIX: Prevent confirming stale logins
    login_age = datetime.now(timezone.utc) - login.login_at
    if login_age.days > MAX_LOGIN_AGE_DAYS:
        log.warning(
            "Attempted to confirm stale login",
            user_id=user_id,
            login_id=login_id,
            login_age_days=login_age.days
        )
        raise ValidationError(
            f"Cannot confirm login older than {MAX_LOGIN_AGE_DAYS} days. "
            f"This login is {login_age.days} days old."
        )
    
    login.user_response = "confirmed"
    login.responded_at = datetime.now(timezone.utc)
    
    # ✅ Phase 4: Add device to trusted list.
    # Option-B (sl20260524): hash CANONICAL inputs (browser_family /
    # os_family / device_type) so the trusted_device row matches the next
    # login from the same device family — even after a browser/OS minor
    # version bump. Pre-PR this hashed login.browser / login.os which are
    # display strings carrying the version suffix — that's exactly the
    # bug user 16 reported.
    #
    # NULL-safe fallback via ``_family_from_display`` covers any legacy
    # ``login_history`` row that pre-dates the sl20260524 backfill (where
    # browser_family / os_family columns are NULL). Migration backfills
    # the full table on upgrade so the fallback should be hit rarely
    # post-deploy.
    trusted_device = None
    if trust_device and (login.browser_family or login.browser) and (login.os_family or login.os):
        browser_family = login.browser_family or _family_from_display(login.browser)
        os_family = login.os_family or _family_from_display(login.os)
        device_type = login.device_type

        device_fingerprint = generate_device_fingerprint(
            browser_family=browser_family,
            os_family=os_family,
            device_type=device_type,
            user_id=user_id,
        )

        # Display name is normalized to family form so the user sees a
        # stable "Mobile Safari on iOS" entry in /settings/security rather
        # than a noisy version-suffixed string that would drift on every
        # OS update.
        display_name = (
            f"{browser_family} on {os_family}"
            if browser_family and os_family
            else (login.browser or login.os or "Trusted device")
        )

        # Note: Commit 4 will extend ``trust_device`` to accept the
        # family + device_type kwargs so the trusted_device row can store
        # them. Until then the legacy signature (browser/os display +
        # IP) is sufficient — the fingerprint hash is what matters for
        # match correctness.
        trusted_device = await trusted_repo.trust_device(
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            name=display_name,
            browser=login.browser,
            os=login.os,
            ip_address=login.ip_address,
        )
    
    # ✅ FIX: Clear password_reset_required when user confirms login is legitimate
    # This handles the case where user previously clicked "Not Me" (which set the flag),
    # but now confirms a new suspicious login as legitimate.
    from app.repositories.user_repository import UserRepository
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if user and user.password_reset_required:
        user.password_reset_required = False
        log.info(
            "Cleared password_reset_required flag after user confirmed login",
            user_id=user_id,
            login_id=login_id
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
    
    SECURITY FIX (C2): Now sets password_reset_required=True to force password change.
    
    IMPORTANT: Router must call db.commit() and then execute the returned callback.
    The callback will revoke all sessions.
    
    Raises:
        ResourceNotFoundError: If login not found or doesn't belong to user
    """
    repo = LoginHistoryRepository(db)
    login = await repo.get_by_id(login_id)
    
    if not login or login.user_id != user_id:
        raise ResourceNotFoundError(f"Login {login_id} not found")
    
    login.user_response = "secured"
    login.responded_at = datetime.now(timezone.utc)
    
    # C2 FIX: Force password change on next login
    # ✅ ARCHITECTURE FIX: Use UserRepository instead of direct query
    from app.repositories.user_repository import UserRepository
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if user:
        user.password_reset_required = True
        log.info("Set password_reset_required=True for user", user_id=user_id)
    
    await db.flush()
    await db.refresh(login)
    
    async def _post_commit():
        log.warning(
            "User secured account after suspicious login",
            user_id=user_id,
            login_id=login_id,
            password_reset_required=True
        )
    
    return login, _post_commit



# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _parse_user_agent(user_agent: Optional[str]) -> Dict[str, Optional[str]]:
    """Parse User-Agent string into display + family device info.

    Returns BOTH the display strings ("Mobile Safari 26.4" / "iOS 18.7"
    — kept for admin UI / login_history.browser / login_history.os) AND
    the family identifiers ("Mobile Safari" / "iOS" — used as canonical
    fingerprint inputs that stay stable across version drift).

    Family fields come directly from ``ua.browser.family`` /
    ``ua.os.family`` (the user-agents library has already parsed them
    out), so we don't re-run the regex strip here.
    """
    if not user_agent:
        return {
            "device_type": None,
            "browser": None,
            "os": None,
            "browser_family": None,
            "os_family": None,
        }

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

        browser_family = ua.browser.family or None
        os_family = ua.os.family or None

        return {
            "device_type": device_type,
            "browser": f"{ua.browser.family} {ua.browser.version_string}",
            "os": f"{ua.os.family} {ua.os.version_string}",
            "browser_family": browser_family,
            "os_family": os_family,
        }
    except Exception:
        return {
            "device_type": None,
            "browser": None,
            "os": None,
            "browser_family": None,
            "os_family": None,
        }


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
