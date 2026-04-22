# app/gateways/zalo.py
"""
Zalo Business Solutions (ZBS) Gateway — token management + API client.

Phase C1: Handles OAuth v4 token lifecycle and ZBS Template Message API.

Token strategy:
  - Redis primary: fast reads, TTL-based expiry
  - DB backup: crash recovery via zalo_token_store table
  - Distributed lock: prevents concurrent refreshes

API flows:
  - send_template_message(phone, template_id, template_data) → ZaloSendResult
  - verify_webhook_signature(body, signature) → bool
"""
import hashlib
import hmac
import structlog
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from app.config import settings

log = structlog.get_logger(__name__)

# Redis keys for token storage
ZALO_ACCESS_TOKEN_KEY = "zalo:access_token"
ZALO_REFRESH_TOKEN_KEY = "zalo:refresh_token"
ZALO_ACCESS_TOKEN_TTL = 86400  # 24 hours (access token valid 25h, refresh early)

# Zalo API endpoints
ZALO_OAUTH_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
ZALO_TEMPLATE_MSG_URL = "https://business.openapi.zalo.me/message/template"


@dataclass
class ZaloSendResult:
    """Result of a Zalo template message send."""
    success: bool
    msg_id: Optional[str] = None
    error_code: int = 0
    error_message: str = ""
    quota_remaining: Optional[int] = None


class ZaloGateway:
    """
    Zalo Business Solutions gateway with token management.

    Usage:
        gateway = ZaloGateway()
        result = await gateway.send_template_message(
            phone="84901234567",
            template_id="abc123",
            template_data={"customer": "Nguyen Van A"},
        )
    """

    async def get_access_token(self) -> str:
        """
        Get a valid Zalo access token.

        Checks Redis cache first, falls back to DB, then refreshes if needed.

        Returns:
            Valid access token string

        Raises:
            RuntimeError: If unable to obtain a token
        """
        from app.database import safe_redis_get, safe_redis_set

        # 1. Try Redis cache
        cached = await safe_redis_get(ZALO_ACCESS_TOKEN_KEY)
        if cached:
            return cached

        # 2. Try DB backup
        token_data = await self._load_from_db()
        if token_data and token_data.access_token_expires_at > datetime.now(timezone.utc):
            # Cache back to Redis
            ttl = int((token_data.access_token_expires_at - datetime.now(timezone.utc)).total_seconds())
            await safe_redis_set(ZALO_ACCESS_TOKEN_KEY, token_data.access_token, ex=max(ttl, 60))
            await safe_redis_set(ZALO_REFRESH_TOKEN_KEY, token_data.refresh_token)
            return token_data.access_token

        # 3. Refresh token
        access_token, _ = await self.refresh_access_token()
        return access_token

    async def refresh_access_token(self) -> tuple[str, str]:
        """
        Refresh Zalo OAuth access token.

        Uses distributed lock to prevent concurrent refreshes.
        Stores new tokens in both Redis and DB.

        Returns:
            Tuple of (access_token, refresh_token)

        Raises:
            RuntimeError: If refresh fails
        """
        from app.utils.redis_lock import acquire_redis_lock
        from app.database import safe_redis_get, safe_redis_set

        async with acquire_redis_lock("zalo_token_refresh", timeout=30) as acquired:
            if not acquired:
                # Another worker is refreshing — wait and re-read from Redis
                cached = await safe_redis_get(ZALO_ACCESS_TOKEN_KEY)
                if cached:
                    refresh = await safe_redis_get(ZALO_REFRESH_TOKEN_KEY) or ""
                    return cached, refresh
                raise RuntimeError("Failed to acquire Zalo token refresh lock")

            # Re-check Redis (another worker may have just refreshed)
            cached = await safe_redis_get(ZALO_ACCESS_TOKEN_KEY)
            if cached:
                refresh = await safe_redis_get(ZALO_REFRESH_TOKEN_KEY) or ""
                return cached, refresh

            # Get current refresh token
            current_refresh = await safe_redis_get(ZALO_REFRESH_TOKEN_KEY)
            if not current_refresh:
                # Try DB
                token_data = await self._load_from_db()
                if token_data:
                    current_refresh = token_data.refresh_token
                else:
                    # Bootstrap from env
                    current_refresh = settings.ZALO_REFRESH_TOKEN

            if not current_refresh:
                raise RuntimeError(
                    "No Zalo refresh token available. "
                    "Set ZALO_REFRESH_TOKEN in environment or seed via admin panel."
                )

            # Call Zalo OAuth v4
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    ZALO_OAUTH_URL,
                    headers={"secret_key": settings.ZALO_APP_SECRET},
                    data={
                        "refresh_token": current_refresh,
                        "app_id": settings.ZALO_APP_ID,
                        "grant_type": "refresh_token",
                    },
                )

            data = response.json()

            if "access_token" not in data:
                error_msg = data.get("error_description", data.get("message", str(data)))
                log.error("Zalo token refresh failed", response=data)
                raise RuntimeError(f"Zalo token refresh failed: {error_msg}")

            new_access = data["access_token"]
            new_refresh = data["refresh_token"]
            expires_in = int(data.get("expires_in", 90000))

            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Store in Redis
            await safe_redis_set(
                ZALO_ACCESS_TOKEN_KEY, new_access,
                ex=min(expires_in - 3600, ZALO_ACCESS_TOKEN_TTL),  # Refresh 1h early
            )
            await safe_redis_set(ZALO_REFRESH_TOKEN_KEY, new_refresh)

            # Store in DB backup
            await self._save_to_db(new_access, new_refresh, expires_at)

            log.info(
                "Zalo token refreshed",
                expires_at=expires_at.isoformat(),
                oa_id=settings.ZALO_OA_ID,
            )

            return new_access, new_refresh

    async def send_template_message(
        self,
        phone: str,
        template_id: str,
        template_data: Dict[str, Any],
        tracking_id: Optional[str] = None,
    ) -> ZaloSendResult:
        """
        Send a ZBS Template Message to a phone number.

        Auto-retries once on -201 (expired token) by refreshing.

        Args:
            phone: Normalized phone (84xxx format)
            template_id: Approved ZBS template ID
            template_data: Template variables
            tracking_id: Optional internal tracking ID

        Returns:
            ZaloSendResult with success status and msg_id
        """
        access_token = await self.get_access_token()

        result = await self._call_template_api(
            access_token, phone, template_id, template_data, tracking_id
        )

        # Auto-retry on expired token (-201)
        if result.error_code == -201:
            log.info("Zalo token expired, refreshing and retrying")
            access_token, _ = await self.refresh_access_token()
            result = await self._call_template_api(
                access_token, phone, template_id, template_data, tracking_id
            )

        return result

    async def _call_template_api(
        self,
        access_token: str,
        phone: str,
        template_id: str,
        template_data: Dict[str, Any],
        tracking_id: Optional[str] = None,
    ) -> ZaloSendResult:
        """Call Zalo ZBS Template Message API."""
        body: Dict[str, Any] = {
            "phone": phone,
            "template_id": template_id,
            "template_data": template_data,
        }
        if tracking_id:
            body["tracking_id"] = tracking_id

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    ZALO_TEMPLATE_MSG_URL,
                    headers={"access_token": access_token},
                    json=body,
                )

            data = response.json()
            error_code = data.get("error", -1)

            if error_code == 0:
                msg_data = data.get("data", {})
                quota = msg_data.get("quota", {})
                return ZaloSendResult(
                    success=True,
                    msg_id=msg_data.get("msg_id"),
                    error_code=0,
                    quota_remaining=int(quota.get("remainingQuota", 0)) if quota else None,
                )
            else:
                return ZaloSendResult(
                    success=False,
                    error_code=error_code,
                    error_message=data.get("message", str(data)),
                )

        except httpx.TimeoutException:
            return ZaloSendResult(
                success=False,
                error_code=-999,
                error_message="Zalo API timeout",
            )
        except Exception as e:
            log.error("Zalo API call failed", error=str(e))
            return ZaloSendResult(
                success=False,
                error_code=-998,
                error_message=f"Zalo API error: {str(e)}",
            )

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """
        Verify Zalo webhook signature per official spec.

        Spec (verified across docs pages — chat user_send_text, ZBS quota,
        ZBS user_received_message): the X-ZEvent-Signature header value is
        ``sha256(appId + data + timeStamp + OAsecretKey)`` where ``data``
        is the raw JSON request body and ``appId`` / ``timeStamp`` are
        echoed as fields inside that body. NOT HMAC — plain SHA-256 of a
        concatenated string.

        ``OAsecretKey`` comes from the webhook page in
        ``developers.zalo.me/app/<id>/webhook`` (NOT the App Secret used
        for OAuth). It is set in ``ZALO_WEBHOOK_SECRET``.

        Args:
            body: Raw request body bytes
            signature: X-ZEvent-Signature header value

        Returns:
            True if signature is valid
        """
        secret = settings.ZALO_WEBHOOK_SECRET
        if not secret:
            log.warning(
                "ZALO_WEBHOOK_SECRET not configured, rejecting webhook signature"
            )
            return False

        # Zalo wraps the hex digest with a literal ``mac=`` prefix in the
        # X-ZEvent-Signature header (the docs render the formula as
        # ``mac = sha256(...)``, and the literal string ``mac=`` is part
        # of the wire value). Strip it before constant-time compare.
        if signature.startswith("mac="):
            signature = signature[4:]

        try:
            data_str = body.decode("utf-8")
        except UnicodeDecodeError:
            log.warning("Webhook body is not valid UTF-8, signature verify aborted")
            return False

        # Extract appId / timestamp from the JSON body. Use string parsing
        # rather than json.loads so the exact serialization is preserved
        # for the SHA-256 input (the spec hashes the body verbatim).
        import json
        try:
            payload = json.loads(data_str)
        except (json.JSONDecodeError, ValueError):
            log.warning("Webhook body is not valid JSON, signature verify aborted")
            return False

        app_id = str(payload.get("app_id", ""))
        timestamp = str(payload.get("timestamp", ""))

        if not app_id or not timestamp:
            log.warning(
                "Webhook body missing app_id or timestamp for signature input",
                has_app_id=bool(app_id),
                has_timestamp=bool(timestamp),
            )
            return False

        mac_input = f"{app_id}{data_str}{timestamp}{secret}"
        expected = hashlib.sha256(mac_input.encode("utf-8")).hexdigest()

        return hmac.compare_digest(expected, signature)

    # =========================================================================
    # DB backup helpers
    # =========================================================================

    async def _load_from_db(self):
        """Load token from DB backup."""
        try:
            from app.database import AsyncSessionLocal
            from app.models.zalo_token_store import ZaloTokenStore
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ZaloTokenStore)
                    .where(ZaloTokenStore.oa_id == settings.ZALO_OA_ID)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            log.warning("Failed to load Zalo token from DB", error=str(e))
            return None

    async def _save_to_db(
        self, access_token: str, refresh_token: str, expires_at: datetime
    ):
        """Save token to DB backup (upsert)."""
        try:
            from app.database import AsyncSessionLocal
            from app.models.zalo_token_store import ZaloTokenStore
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ZaloTokenStore)
                    .where(ZaloTokenStore.oa_id == settings.ZALO_OA_ID)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.access_token = access_token
                    existing.refresh_token = refresh_token
                    existing.access_token_expires_at = expires_at
                    existing.refresh_token_expires_at = (
                        datetime.now(timezone.utc) + timedelta(days=90)
                    )
                else:
                    token = ZaloTokenStore(
                        oa_id=settings.ZALO_OA_ID,
                        access_token=access_token,
                        refresh_token=refresh_token,
                        access_token_expires_at=expires_at,
                        refresh_token_expires_at=(
                            datetime.now(timezone.utc) + timedelta(days=90)
                        ),
                    )
                    session.add(token)

                await session.commit()

        except Exception as e:
            log.error("Failed to save Zalo token to DB", error=str(e))


# Singleton instance
zalo_gateway = ZaloGateway()
