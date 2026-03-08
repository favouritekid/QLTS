# Ke hoach Tich hop Zalo Business Solutions (ZBS) vao QLTS

> **Trang thai**: Draft - Can review truoc khi trien khai
> **Ngay tao**: 2026-03-06
> **Tac gia**: Claude Code (dua tren ke hoach goc + phan tich codebase)

---

## Muc luc

1. [Tong quan ZBS](#1-tong-quan-zbs)
2. [API Specifications](#2-api-specifications)
3. [Phan tich Codebase hien tai](#3-phan-tich-codebase-hien-tai)
4. [Ke hoach Implementation](#4-ke-hoach-implementation)
   - Phase 1: Config & Gateway
   - Phase 2: Database Models & Migration
   - Phase 3: Notification Channel
   - Phase 4: Preference System Extension
   - Phase 5: Celery Tasks
   - Phase 6: Webhook Receiver
   - Phase 7: Business Rules & Template Mapping
   - Phase 8: Admin Dashboard
5. [Fallback & Error Strategy](#5-fallback--error-strategy)
6. [Testing Plan](#6-testing-plan)
7. [Rui ro & Mitigation](#7-rui-ro--mitigation)
8. [Checklist Prerequisites](#8-checklist-prerequisites)

---

## 1. Tong quan ZBS

**Zalo Business Solutions (ZBS)** la he sinh thai giai phap kinh doanh tren Zalo danh cho Doanh nghiep. Tu **01/01/2026**, ZBS Template Message da thay the hoan toan ZNS, hop nhat cac loai tin nhan UID Transactional, UID Promotional, va ZNS cu thanh mot framework chuan hoa.

### 1.1. Cac nhom API chinh

| Nhom API | Muc dich | Base URL |
|----------|----------|----------|
| **ZBS Template Message** | Gui tin nhan template qua UID hoac SDT | `business.openapi.zalo.me` |
| **OA Message** | Gui tin tu van/CSKH qua OA | `openapi.zalo.me/v3.0` |
| **OAuth v4** | Xac thuc & lay Access Token | `oauth.zaloapp.com/v4` |
| **Webhook** | Nhan su kien tu Zalo | Server cua ban |
| **Template Management** | Quan ly template ZBS | `business.openapi.zalo.me` |

---

## 2. API Specifications

### 2.1. Authentication - OAuth v4

#### Lay Access Token tu Refresh Token

```
POST https://oauth.zaloapp.com/v4/oa/access_token
Content-Type: application/x-www-form-urlencoded
```

**Headers:**

| Header | Gia tri |
|--------|---------|
| `secret_key` | Secret Key cua ung dung |

**Body (form-urlencoded):**

| Tham so | Bat buoc | Mo ta |
|---------|----------|-------|
| `refresh_token` | Yes | Refresh Token hien tai |
| `app_id` | Yes | App ID cua ung dung |
| `grant_type` | Yes | Luon la `refresh_token` |

**Response:**
```json
{
  "access_token": "new_access_token_string",
  "refresh_token": "new_refresh_token_string",
  "expires_in": "90000"
}
```

**Luu y quan trong:**
- **Access Token** co thoi han **25 gio** (90,000 giay)
- **Refresh Token** co thoi han **3 thang** va la **single-use** (moi lan refresh se nhan refresh token moi)
- Phai luu tru va cap nhat ca Access Token lan Refresh Token sau moi lan refresh

### 2.2. ZBS Template Message API

#### Gui tin nhan template qua SDT (Phone)

```
POST https://business.openapi.zalo.me/message/template
Content-Type: application/json
```

**Headers:**

| Header | Gia tri |
|--------|---------|
| `access_token` | OA Access Token |

**Body:**
```json
{
  "phone": "84987654321",
  "template_id": "7895417a7d3f9461cd2e",
  "template_data": {
    "customer": "Nguyen Van A",
    "amount": "100.000d",
    "order_code": "DH-2026-001"
  },
  "tracking_id": "optional_internal_tracking_id"
}
```

**Response (Success):**
```json
{
  "error": 0,
  "message": "Success",
  "data": {
    "msg_id": "abc123...",
    "sent_time": "1709712345678",
    "quota": {
      "dailyQuota": "500",
      "remainingQuota": "499"
    }
  }
}
```

#### Gui tin nhan template qua UID (User ID tren OA)

```
POST https://openapi.zalo.me/v3.0/oa/message/template
Content-Type: application/json
```

**Body:**
```json
{
  "recipient": {
    "user_id": "user_zalo_oa_id"
  },
  "template_id": "7895417a7d3f9461cd2e",
  "template_data": {
    "customer": "Nguyen Van A",
    "amount": "100.000d"
  }
}
```

### 2.3. OA Consultation Message API

```
POST https://openapi.zalo.me/v3.0/oa/message/cs
Content-Type: application/json
```

**Headers:**

| Header | Gia tri |
|--------|---------|
| `access_token` | OA Access Token |

**Body:**
```json
{
  "recipient": {
    "user_id": "user_zalo_oa_id"
  },
  "message": {
    "text": "Xin chao, ho so cua ban da duoc tiep nhan."
  }
}
```

> Tin tu van chi gui duoc cho user da tuong tac (follow) OA trong 7 ngay gan nhat.

### 2.4. Template Management API

```
GET https://business.openapi.zalo.me/template/all?offset=0&limit=100&status=1
```

| Tham so | Mo ta |
|---------|-------|
| `offset` | Vi tri bat dau (phan trang) |
| `limit` | So luong toi da (max 100) |
| `status` | 1: Enable, 2: Pending, 3: Reject, 4: Disable |

### 2.5. Webhook

**Event Types chinh:**

| Event | Mo ta |
|-------|-------|
| `user_send_text` | User gui tin nhan text |
| `user_send_image` | User gui hinh anh |
| `user_follow_oa` | User follow OA |
| `user_unfollow_oa` | User unfollow OA |
| `oa_send_text` | Callback xac nhan tin da gui |
| `user_submit_info` | User chia se thong tin |

**Xac thuc Webhook (HMAC-SHA256):**
```python
import hmac, hashlib

signature = hmac.new(
    key=app_secret_key.encode(),
    msg=request_body.encode(),
    digestmod=hashlib.sha256
).hexdigest()
# So sanh signature voi header X-ZEvent-Signature tu Zalo
```

### 2.6. Bang ma loi quan trong

| Error Code | Mo ta | Xu ly |
|------------|-------|-------|
| `0` | Thanh cong | - |
| `-201` | Access Token khong hop le hoac het han | Refresh token, retry 1 lan |
| `-202` | App khong co quyen goi API nay | Log error, alert admin |
| `-204` | OA khong active hoac bi khoa | Log error, alert admin |
| `-210` | Quota het (ZBS Template) | Queue lai + fallback email |
| `-216` | Template ID khong ton tai | Log error, alert admin |
| `-217` | Template chua duoc duyet | Log warning, fallback email |
| `-230` | SDT khong lien ket Zalo | Fallback email |

---

## 3. Phan tich Codebase hien tai

### 3.1. Nhung gi DA san sang

| Component | File | Trang thai | Chi tiet |
|-----------|------|-----------|----------|
| `NotificationChannel.ZALO` enum | `app/services/notification_registry.py:58` | Da khai bao | `ZALO = "zalo"` trong enum |
| Channel placeholder | `app/services/notification_channels/__init__.py:12` | Comment TODO | `# from .zalo_channel import ZaloChannel` |
| `BaseChannel` interface | `app/services/notification_channels/base.py:22-74` | San sang | `send()`, `validate_config()`, `ChannelResult` |
| `EmailChannel` reference impl | `app/services/notification_channels/email_channel.py` | San sang | Pattern de follow |
| Channel Registry factory | `app/services/notification_channels/__init__.py:17-22` | San sang | `CHANNEL_REGISTRY` dict |
| Multi-channel dispatcher | `app/services/notification_dispatcher.py:402-478` | San sang | `asyncio.gather()` parallel delivery |
| Gateway pattern | `app/gateways/base.py` | San sang | `BaseGatewayAdapter` (VNPay, MoMo) |
| `User.phone_number` | `app/models/user.py` | San sang | `String(20), nullable` |
| `NotificationTemplate.template_type` | `app/models/notification.py` | San sang | Ho tro `"zalo_zns"` |
| `NotificationTemplate.supported_channels` | `app/models/notification.py` | San sang | JSONB field |
| `NotificationAction.config` | `app/models/notification.py` | San sang | JSON field cho channel-specific config |
| Notification preference system | `app/services/notification_preference_service.py` | San sang | `filter_users_by_group()` |
| Celery task pattern | `app/tasks/notification_tasks.py` | San sang | `broadcast_notification_task` |

### 3.2. Nhung gi CAN BO SUNG

| Component | Ly do |
|-----------|-------|
| `ZALO` trong `NotificationChannel` enum tai `event_groups.py:251-261` | Enum nay **KHONG** co `ZALO` - chi co BROWSER, EMAIL, SMS |
| `DEFAULT_GROUP_CHANNELS` update | Them `NotificationChannel.ZALO: False` cho tat ca 11 groups |
| Zalo gateway client | `httpx.AsyncClient` wrapper cho Zalo API |
| Token storage (Redis + DB backup) | Luu access_token/refresh_token, auto-refresh |
| `ZaloChannel` implementation | Implement `BaseChannel` interface |
| `zalo_user_mapping` table | Map QLTS user_id <-> Zalo OA user_id |
| `zalo_message_log` table | Tracking delivery status |
| Phone normalization utility | Convert `0xxx` -> `84xxx` |
| Webhook router | Nhan events tu Zalo |
| Celery task cho Zalo | Token-aware retry logic |
| Config vars | ZALO_APP_ID, ZALO_APP_SECRET, etc. |

### 3.3. Khac biet giua 2 enum NotificationChannel

Hien tai co **HAI** enum `NotificationChannel`:

1. **`app/services/notification_registry.py:53-58`** - Co `ZALO = "zalo"`
   - Dung boi: `NotificationConfig`, `NOTIFICATION_REGISTRY`
2. **`app/core/event_groups.py:251-261`** - **KHONG** co `ZALO`
   - Dung boi: `DEFAULT_GROUP_CHANNELS`, `notification_preference_service`

Ca hai can dong bo. **Recommendation**: Them `ZALO` vao `event_groups.py` va import tu do cho registry.

---

## 4. Ke hoach Implementation

### Tong quan Phases

| Phase | Noi dung | Uu tien | Phu thuoc |
|-------|----------|---------|-----------|
| **1** | Config & Gateway (token management) | P0 | - |
| **2** | Database Models & Migration | P0 | Phase 1 |
| **3** | Notification Channel Integration | P0 | Phase 1, 2 |
| **4** | Preference System Extension | P0 | Phase 3 |
| **5** | Celery Tasks (send + token refresh) | P0 | Phase 1, 3 |
| **6** | Webhook Receiver | P1 | Phase 1, 2 |
| **7** | Business Rules & Template Mapping | P1 | Phase 3 |
| **8** | Admin Dashboard (status, logs, test) | P2 | Phase 1, 2 |

```
Phase 1 (Config & Gateway)
    |
    +---> Phase 2 (DB Models)
    |         |
    |         +---> Phase 3 (Channel) ---> Phase 4 (Preferences)
    |         |         |
    |         |         +---> Phase 5 (Celery Tasks)
    |         |         |
    |         |         +---> Phase 7 (Business Rules)
    |         |
    |         +---> Phase 6 (Webhook)
    |         |
    |         +---> Phase 8 (Admin Dashboard)
```

---

### Phase 1: Config & Gateway

**Muc tieu**: Zalo API client voi token management.

#### 1.1. [MODIFY] `app/config.py`

Them Zalo settings vao class `Settings` (sau dong ~164, sau security settings):

```python
# === Zalo Business Solutions ===
ZALO_ENABLED: bool = Field(
    default=False, validation_alias="ZALO_ENABLED"
)
ZALO_APP_ID: str = Field(
    default="", validation_alias="ZALO_APP_ID"
)
ZALO_APP_SECRET: str = Field(
    default="", validation_alias="ZALO_APP_SECRET"
)
ZALO_OA_ID: str = Field(
    default="", validation_alias="ZALO_OA_ID"
)
ZALO_WEBHOOK_SECRET: str = Field(
    default="", validation_alias="ZALO_WEBHOOK_SECRET"
)
ZALO_INITIAL_REFRESH_TOKEN: str = Field(
    default="", validation_alias="ZALO_INITIAL_REFRESH_TOKEN"
)  # Bootstrap token - chi dung lan dau
```

#### 1.2. [MODIFY] `.env.example` va `Backend_FastAPI/.env`

```env
# === Zalo Business Solutions ===
ZALO_ENABLED=false
ZALO_APP_ID=
ZALO_APP_SECRET=
ZALO_OA_ID=
ZALO_WEBHOOK_SECRET=
ZALO_INITIAL_REFRESH_TOKEN=
```

#### 1.3. [NEW] `app/gateways/zalo_gateway.py`

Tao Zalo API gateway client. Follow pattern cua `BaseGatewayAdapter` nhung **KHONG** ke thua (vi day la messaging, khong phai payment).

```python
# app/gateways/zalo_gateway.py
"""
Zalo Business Solutions Gateway - HTTP client cho Zalo API.

Responsibilities:
- Token management (auto-refresh khi het han)
- ZBS Template Message sending (qua SDT hoac UID)
- OA consultation message sending
- Template listing
- Error handling & retry logic

Token Strategy:
- Primary storage: Redis (fast access, shared across workers)
- Backup storage: DB table `zalo_token` (survive Redis restart)
- Distributed lock: Redis lock khi refresh (tranh race condition)

Usage:
    from app.gateways.zalo_gateway import zalo_gateway

    result = await zalo_gateway.send_template_by_phone(
        phone="84987654321",
        template_id="abc123",
        template_data={"customer": "Nguyen Van A"},
        tracking_id="notif_456"
    )
"""
import structlog
import httpx
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.config import settings

log = structlog.get_logger(__name__)


# ---- Error classes ----

class ZaloAPIError(Exception):
    """Base exception cho Zalo API errors."""
    def __init__(self, error_code: int, message: str, raw_response: dict = None):
        super().__init__(f"Zalo API Error {error_code}: {message}")
        self.error_code = error_code
        self.raw_response = raw_response or {}


class ZaloTokenExpiredError(ZaloAPIError):
    """Access token het han (-201). Can refresh."""
    pass


class ZaloQuotaExceededError(ZaloAPIError):
    """Daily quota het (-210). Can cho hoac nang goi."""
    pass


class ZaloRecipientError(ZaloAPIError):
    """SDT khong co Zalo (-230) hoac loi recipient khac."""
    pass


# ---- Response dataclass ----

@dataclass
class ZaloSendResult:
    """Ket qua gui tin nhan Zalo."""
    success: bool
    msg_id: str = ""
    error_code: int = 0
    error_message: str = ""
    remaining_quota: int = -1
    raw_response: dict = None


# ---- Zalo Gateway ----

class ZaloGateway:
    """
    Zalo API gateway client.

    Singleton - su dung `zalo_gateway` instance o cuoi file.
    Token management:
    - Access token luu trong Redis (key: zalo:access_token, TTL 24h)
    - Refresh token luu trong Redis (key: zalo:refresh_token, TTL 85 days)
    - Backup refresh token vao DB table `zalo_token`
    - Distributed lock khi refresh (key: zalo:token_lock, TTL 30s)
    """

    # API endpoints
    OAUTH_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
    ZBS_TEMPLATE_URL = "https://business.openapi.zalo.me/message/template"
    OA_TEMPLATE_URL = "https://openapi.zalo.me/v3.0/oa/message/template"
    OA_MESSAGE_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"
    TEMPLATE_LIST_URL = "https://business.openapi.zalo.me/template/all"

    # Redis keys
    REDIS_ACCESS_TOKEN = "zalo:access_token"
    REDIS_REFRESH_TOKEN = "zalo:refresh_token"
    REDIS_TOKEN_LOCK = "zalo:token_lock"
    REDIS_QUOTA_DAILY = "zalo:quota:daily"
    REDIS_QUOTA_REMAINING = "zalo:quota:remaining"

    # TTLs
    ACCESS_TOKEN_TTL = 24 * 3600      # 24h (buffer 1h truoc 25h expiry)
    REFRESH_TOKEN_TTL = 85 * 24 * 3600  # 85 days (buffer truoc 90 days expiry)
    TOKEN_LOCK_TTL = 30                # 30s lock khi refreshing

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-init httpx client voi connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10
                )
            )
        return self._client

    async def close(self):
        """Cleanup - goi khi shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ---- Token Management ----

    async def get_access_token(self) -> str:
        """
        Lay access token tu Redis. Auto-refresh neu het han.

        Flow:
        1. Check Redis zalo:access_token
        2. Neu co -> return
        3. Neu khong -> acquire lock -> refresh -> store -> return

        Returns:
            Valid access token string

        Raises:
            ZaloAPIError: Neu khong the lay/refresh token
        """
        from app.database import get_redis
        redis = await get_redis()

        # Try get from Redis
        token = await redis.get(self.REDIS_ACCESS_TOKEN)
        if token:
            return token.decode() if isinstance(token, bytes) else token

        # Need refresh - acquire distributed lock
        lock_acquired = await redis.set(
            self.REDIS_TOKEN_LOCK, "1",
            nx=True, ex=self.TOKEN_LOCK_TTL
        )

        if not lock_acquired:
            # Another worker is refreshing, wait and retry
            import asyncio
            for _ in range(10):  # Wait max 5 seconds
                await asyncio.sleep(0.5)
                token = await redis.get(self.REDIS_ACCESS_TOKEN)
                if token:
                    return token.decode() if isinstance(token, bytes) else token
            raise ZaloAPIError(-1, "Token refresh timeout - another worker is stuck")

        try:
            return await self._refresh_token(redis)
        finally:
            await redis.delete(self.REDIS_TOKEN_LOCK)

    async def _refresh_token(self, redis) -> str:
        """
        Refresh access token tu Zalo OAuth v4.

        Flow:
        1. Lay refresh_token tu Redis (hoac DB backup, hoac initial config)
        2. Call Zalo OAuth API
        3. Store new access_token + refresh_token vao Redis
        4. Backup refresh_token vao DB
        5. Return new access_token
        """
        # Get current refresh token (Redis -> DB -> Config fallback)
        refresh_token = await redis.get(self.REDIS_REFRESH_TOKEN)
        if refresh_token:
            refresh_token = refresh_token.decode() if isinstance(refresh_token, bytes) else refresh_token

        if not refresh_token:
            refresh_token = await self._get_refresh_token_from_db()

        if not refresh_token:
            refresh_token = settings.ZALO_INITIAL_REFRESH_TOKEN

        if not refresh_token:
            raise ZaloAPIError(-1, "No refresh token available. Set ZALO_INITIAL_REFRESH_TOKEN in env.")

        # Call Zalo OAuth
        response = await self.client.post(
            self.OAUTH_URL,
            headers={"secret_key": settings.ZALO_APP_SECRET},
            data={
                "refresh_token": refresh_token,
                "app_id": settings.ZALO_APP_ID,
                "grant_type": "refresh_token"
            }
        )

        data = response.json()

        if "access_token" not in data:
            error_code = data.get("error", -1)
            error_msg = data.get("message", "Unknown OAuth error")
            log.error("Zalo token refresh failed", error_code=error_code, error_msg=error_msg)
            raise ZaloAPIError(error_code, f"Token refresh failed: {error_msg}", data)

        new_access_token = data["access_token"]
        new_refresh_token = data["refresh_token"]

        # Store in Redis
        await redis.set(self.REDIS_ACCESS_TOKEN, new_access_token, ex=self.ACCESS_TOKEN_TTL)
        await redis.set(self.REDIS_REFRESH_TOKEN, new_refresh_token, ex=self.REFRESH_TOKEN_TTL)

        # Backup refresh token to DB (non-blocking)
        try:
            await self._backup_refresh_token_to_db(new_refresh_token)
        except Exception as e:
            log.warning("Failed to backup refresh token to DB", error=str(e))

        log.info("Zalo token refreshed successfully",
                 expires_in=data.get("expires_in", "unknown"))

        return new_access_token

    async def _get_refresh_token_from_db(self) -> Optional[str]:
        """Lay refresh token tu DB backup."""
        from app.database import AsyncSessionLocal
        from sqlalchemy import select, text

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    text("SELECT refresh_token FROM zalo_token ORDER BY updated_at DESC LIMIT 1")
                )
                row = result.first()
                return row[0] if row else None
        except Exception as e:
            log.warning("Failed to get refresh token from DB", error=str(e))
            return None

    async def _backup_refresh_token_to_db(self, refresh_token: str):
        """Backup refresh token vao DB."""
        from app.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO zalo_token (refresh_token, updated_at)
                    VALUES (:token, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        refresh_token = :token,
                        updated_at = NOW()
                """),
                {"token": refresh_token}
            )
            await db.commit()

    # ---- Send Methods ----

    async def send_template_by_phone(
        self,
        phone: str,
        template_id: str,
        template_data: Dict[str, str],
        tracking_id: str = ""
    ) -> ZaloSendResult:
        """
        Gui ZBS Template Message qua SDT.

        Args:
            phone: SDT format 84xxx (se tu dong normalize)
            template_id: ZBS template ID
            template_data: Template variables
            tracking_id: Internal tracking ID

        Returns:
            ZaloSendResult

        Raises:
            ZaloTokenExpiredError: Token het han (caller should refresh + retry)
            ZaloQuotaExceededError: Quota het
            ZaloRecipientError: SDT khong co Zalo
        """
        phone = normalize_phone_for_zalo(phone)
        access_token = await self.get_access_token()

        body = {
            "phone": phone,
            "template_id": template_id,
            "template_data": template_data,
        }
        if tracking_id:
            body["tracking_id"] = tracking_id

        response = await self.client.post(
            self.ZBS_TEMPLATE_URL,
            headers={"access_token": access_token},
            json=body
        )

        return self._parse_send_response(response.json())

    async def send_template_by_uid(
        self,
        user_id: str,
        template_id: str,
        template_data: Dict[str, str]
    ) -> ZaloSendResult:
        """
        Gui ZBS Template Message qua Zalo OA User ID.

        Args:
            user_id: Zalo OA user ID (tu webhook user_follow_oa)
            template_id: ZBS template ID
            template_data: Template variables
        """
        access_token = await self.get_access_token()

        response = await self.client.post(
            self.OA_TEMPLATE_URL,
            headers={"access_token": access_token},
            json={
                "recipient": {"user_id": user_id},
                "template_id": template_id,
                "template_data": template_data
            }
        )

        return self._parse_send_response(response.json())

    async def send_consultation_message(
        self,
        user_id: str,
        text: str
    ) -> ZaloSendResult:
        """
        Gui tin tu van qua OA (chi gui duoc cho follower tuong tac trong 7 ngay).
        """
        access_token = await self.get_access_token()

        response = await self.client.post(
            self.OA_MESSAGE_URL,
            headers={"access_token": access_token},
            json={
                "recipient": {"user_id": user_id},
                "message": {"text": text}
            }
        )

        return self._parse_send_response(response.json())

    async def list_templates(
        self, offset: int = 0, limit: int = 100, status: int = 1
    ) -> Dict[str, Any]:
        """Lay danh sach ZBS templates."""
        access_token = await self.get_access_token()

        response = await self.client.get(
            self.TEMPLATE_LIST_URL,
            headers={"access_token": access_token},
            params={"offset": offset, "limit": limit, "status": status}
        )

        data = response.json()
        if data.get("error", 0) != 0:
            raise ZaloAPIError(data["error"], data.get("message", "Unknown"))
        return data

    # ---- Helpers ----

    def _parse_send_response(self, data: dict) -> ZaloSendResult:
        """Parse Zalo API send response thanh ZaloSendResult."""
        error_code = data.get("error", -1)

        if error_code == 0:
            result_data = data.get("data", {})
            quota = result_data.get("quota", {})
            return ZaloSendResult(
                success=True,
                msg_id=result_data.get("msg_id", ""),
                remaining_quota=int(quota.get("remainingQuota", -1)),
                raw_response=data
            )

        error_message = data.get("message", "Unknown error")

        # Map error codes to specific exceptions
        if error_code == -201:
            raise ZaloTokenExpiredError(error_code, error_message, data)
        elif error_code == -210:
            raise ZaloQuotaExceededError(error_code, error_message, data)
        elif error_code == -230:
            raise ZaloRecipientError(error_code, error_message, data)

        return ZaloSendResult(
            success=False,
            error_code=error_code,
            error_message=error_message,
            raw_response=data
        )


# ---- Phone Normalization Utility ----

def normalize_phone_for_zalo(phone: str) -> str:
    """
    Normalize SDT sang format Zalo (84xxx).

    Examples:
        "0987654321"   -> "84987654321"
        "+84987654321" -> "84987654321"
        "84987654321"  -> "84987654321"
        "09 8765 4321" -> "84987654321"
    """
    if not phone:
        return phone
    phone = phone.strip().replace(" ", "").replace("-", "").replace(".", "")
    if phone.startswith("+84"):
        return phone[1:]
    if phone.startswith("0"):
        return "84" + phone[1:]
    return phone


# ---- Singleton ----

zalo_gateway = ZaloGateway()
```

**Diem khac biet voi ke hoach goc:**
- **Token storage chinh la Redis** (khong phai DB) - nhanh hon, shared across Celery workers
- DB chi la backup cho refresh token (survive Redis restart)
- Distributed lock khi refresh (tranh race condition giua workers)
- Phone normalization nam ngay trong gateway (khong tao file rieng)
- Connection pooling voi `httpx.AsyncClient` singleton
- Error classes phan loai theo error code de caller xu ly dung

---

### Phase 2: Database Models & Migration

**Muc tieu**: Tao tables luu tru Zalo user mapping va message logs.

#### 2.1. [NEW] `app/models/zalo.py`

```python
# app/models/zalo.py
"""
Zalo integration models.

Tables:
- zalo_token: Backup storage cho Zalo OAuth refresh tokens
- zalo_user_mapping: Map QLTS users <-> Zalo OA followers
- zalo_message_log: Delivery tracking cho Zalo messages
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, func
)
from sqlalchemy.orm import relationship
from app.database import Base


class ZaloToken(Base):
    """
    Backup storage cho Zalo OAuth refresh tokens.

    Primary storage la Redis. DB chi la backup
    phong truong hop Redis restart.

    Chi co 1 row (singleton) - dung ON CONFLICT DO UPDATE.
    """
    __tablename__ = "zalo_token"

    id = Column(Integer, primary_key=True, default=1)
    refresh_token = Column(Text, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )


class ZaloUserMapping(Base):
    """
    Map giua QLTS user va Zalo OA follower.

    Moi QLTS user co the co 1 Zalo account lien ket.
    Lien ket duoc tao khi:
    1. User follow OA va SDT khop voi QLTS user (webhook)
    2. Admin lien ket thu cong

    Attributes:
        user_id: QLTS user ID (nullable - co the chua map)
        zalo_oa_user_id: Zalo OA follower ID (cho UID messages)
        phone_number: SDT format 84xxx (cho phone messages)
        is_follower: Hien dang follow OA?
        last_interaction_at: Lan cuoi tuong tac (cho 7-day OA message window)
    """
    __tablename__ = "zalo_user_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True
    )
    zalo_oa_user_id = Column(String(100), nullable=False, unique=True, index=True)
    phone_number = Column(String(20), nullable=True, index=True)  # Format: 84xxx
    is_follower = Column(Boolean, default=True, nullable=False)
    followed_at = Column(DateTime(timezone=True), nullable=True)
    unfollowed_at = Column(DateTime(timezone=True), nullable=True)
    last_interaction_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    user = relationship("User", backref="zalo_mapping", uselist=False)

    __table_args__ = (
        Index("ix_zalo_user_mapping_phone", "phone_number"),
    )


class ZaloMessageLog(Base):
    """
    Log gui tin nhan Zalo cho tracking va debugging.

    Moi lan gui tin nhan qua ZaloGateway -> tao 1 record.
    Dung de:
    - Monitor delivery rate
    - Debug failed messages
    - Audit trail
    - Dashboard statistics
    """
    __tablename__ = "zalo_message_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    msg_id = Column(String(100), nullable=True, index=True)  # Zalo msg_id
    notification_id = Column(
        Integer,
        ForeignKey("notification.id", ondelete="SET NULL"),
        nullable=True
    )
    template_id = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    zalo_user_id = Column(String(100), nullable=True)
    send_method = Column(String(10), nullable=False)  # "phone" | "uid"
    status = Column(String(20), nullable=False, default="pending")  # pending, sent, failed
    error_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    raw_response = Column(JSON, nullable=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_zalo_message_log_sent_at", "sent_at"),
        Index("ix_zalo_message_log_status", "status"),
    )
```

#### 2.2. [MODIFY] `app/models/__init__.py`

Them import:
```python
from .zalo import ZaloToken, ZaloUserMapping, ZaloMessageLog
```

#### 2.3. [NEW] Alembic migration

```bash
docker compose exec backend alembic revision --autogenerate -m "add zalo integration tables"
docker compose exec backend alembic upgrade head
```

**Migration se tao 3 tables**: `zalo_token`, `zalo_user_mapping`, `zalo_message_log`.

---

### Phase 3: Notification Channel Integration

**Muc tieu**: Implement `ZaloChannel` theo `BaseChannel` interface.

#### 3.1. [NEW] `app/services/notification_channels/zalo_channel.py`

```python
# app/services/notification_channels/zalo_channel.py
"""
Zalo Channel - Gui thong bao qua Zalo ZBS Template Message.

Send strategy (uu tien):
1. Neu user co zalo_oa_user_id va dang follow -> gui qua UID
2. Neu user co phone_number -> gui qua SDT
3. Neu khong co ca 2 -> skip (report as failed)

Fallback:
- Zalo failures KHONG block other channels (dispatcher goi parallel)
- Failed recipients duoc tra ve trong ChannelResult.failed_ids
"""
import asyncio
import structlog
from typing import Dict, Any, List

from .base import BaseChannel, ChannelResult

log = structlog.get_logger(__name__)

# Concurrency limit khi gui Zalo (tranh rate limit)
ZALO_SEND_CONCURRENCY = 10


class ZaloChannel(BaseChannel):
    """Zalo notification channel via ZBS Template Message."""

    channel_name = "zalo"

    async def send(
        self,
        notifications: List[Any],
        recipient_ids: List[int],
        context: Dict[str, Any]
    ) -> ChannelResult:
        """
        Gui notifications qua Zalo.

        Flow:
        1. Check feature flag ZALO_ENABLED
        2. Lay zalo_channel_config tu context (template_id, data_mapping)
        3. Bulk lookup: user phones + zalo_user_mappings
        4. Send qua UID (neu co) hoac SDT (fallback)
        5. Log moi message vao zalo_message_log
        6. Return ChannelResult
        """
        from app.config import settings

        if not settings.ZALO_ENABLED:
            log.debug("Zalo channel disabled, skipping")
            return ChannelResult(
                success=True, sent_count=0,
                failed_ids=[], error_message="Zalo disabled"
            )

        from app.gateways.zalo_gateway import (
            zalo_gateway, ZaloTokenExpiredError,
            ZaloQuotaExceededError, ZaloRecipientError,
            normalize_phone_for_zalo
        )
        from app.database import AsyncSessionLocal
        from app.models import User
        from app.models.zalo import ZaloUserMapping, ZaloMessageLog
        from sqlalchemy import select

        sent_count = 0
        failed_ids = []

        # Extract Zalo config tu context
        zalo_config = context.get("zalo_config", {})
        template_id = zalo_config.get("template_id")
        data_mapping = zalo_config.get("data_mapping", {})

        if not template_id:
            log.warning("No Zalo template_id in context, skipping")
            return ChannelResult(
                success=False, sent_count=0,
                failed_ids=recipient_ids,
                error_message="No template_id configured"
            )

        # Build template_data tu context + mapping
        template_data = {}
        for zalo_key, context_key in data_mapping.items():
            template_data[zalo_key] = str(context.get(context_key, ""))

        async with AsyncSessionLocal() as db:
            # Bulk lookup users + zalo mappings
            users_result = await db.execute(
                select(User).where(User.id.in_(recipient_ids))
            )
            users = {u.id: u for u in users_result.scalars().all()}

            mappings_result = await db.execute(
                select(ZaloUserMapping).where(
                    ZaloUserMapping.user_id.in_(recipient_ids)
                )
            )
            mappings = {m.user_id: m for m in mappings_result.scalars().all()}

            # Send with concurrency limit
            semaphore = asyncio.Semaphore(ZALO_SEND_CONCURRENCY)

            async def _send_one(user_id: int) -> bool:
                async with semaphore:
                    user = users.get(user_id)
                    if not user:
                        return False

                    mapping = mappings.get(user_id)
                    notif = next(
                        (n for n in notifications if n.user_id == user_id),
                        None
                    )

                    try:
                        result = None
                        send_method = "unknown"
                        phone = None
                        zalo_uid = None

                        # Strategy: UID first, then phone
                        if mapping and mapping.is_follower and mapping.zalo_oa_user_id:
                            zalo_uid = mapping.zalo_oa_user_id
                            send_method = "uid"
                            result = await zalo_gateway.send_template_by_uid(
                                user_id=zalo_uid,
                                template_id=template_id,
                                template_data=template_data
                            )
                        elif user.phone_number:
                            phone = normalize_phone_for_zalo(user.phone_number)
                            send_method = "phone"
                            result = await zalo_gateway.send_template_by_phone(
                                phone=phone,
                                template_id=template_id,
                                template_data=template_data,
                                tracking_id=f"notif_{notif.id}" if notif else ""
                            )
                        else:
                            log.debug("User has no Zalo contact", user_id=user_id)
                            return False

                        # Log message
                        msg_log = ZaloMessageLog(
                            msg_id=result.msg_id if result.success else None,
                            notification_id=notif.id if notif else None,
                            template_id=template_id,
                            phone=phone,
                            zalo_user_id=zalo_uid,
                            send_method=send_method,
                            status="sent" if result.success else "failed",
                            error_code=result.error_code if not result.success else None,
                            error_message=result.error_message if not result.success else None,
                            raw_response=result.raw_response
                        )
                        db.add(msg_log)

                        if result.success:
                            log.debug("Zalo sent", user_id=user_id, method=send_method)
                            return True
                        else:
                            log.warning("Zalo send failed",
                                       user_id=user_id,
                                       error_code=result.error_code)
                            return False

                    except ZaloTokenExpiredError:
                        # Token refreshed automatically by gateway
                        # Retry once
                        log.warning("Zalo token expired during send, skipping user",
                                   user_id=user_id)
                        return False
                    except ZaloQuotaExceededError:
                        log.error("Zalo quota exceeded, stopping batch")
                        return False
                    except ZaloRecipientError:
                        log.info("Zalo recipient not found", user_id=user_id)
                        return False
                    except Exception as e:
                        log.error("Zalo send error",
                                 user_id=user_id, error=str(e))
                        return False

            # Execute all sends
            results = await asyncio.gather(
                *[_send_one(uid) for uid in recipient_ids],
                return_exceptions=True
            )

            for uid, result in zip(recipient_ids, results):
                if isinstance(result, Exception) or not result:
                    failed_ids.append(uid)
                else:
                    sent_count += 1

            # Commit message logs
            try:
                await db.commit()
            except Exception as e:
                log.warning("Failed to commit Zalo message logs", error=str(e))

        return ChannelResult(
            success=sent_count > 0,
            sent_count=sent_count,
            failed_ids=failed_ids
        )

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate Zalo channel config."""
        if not config:
            return False
        return bool(config.get("template_id"))
```

#### 3.2. [MODIFY] `app/services/notification_channels/__init__.py`

```diff
 from .socket_channel import SocketChannel
 from .email_channel import EmailChannel
-# from .zalo_channel import ZaloChannel  # TODO: Phase 2
+from .zalo_channel import ZaloChannel
 # from .sms_channel import SMSChannel    # TODO: Phase 2

 CHANNEL_REGISTRY: Dict[str, Type[BaseChannel]] = {
     "browser": SocketChannel,
     "email": EmailChannel,
-    # "zalo": ZaloChannel,    # TODO
+    "zalo": ZaloChannel,
     # "sms": SMSChannel,      # TODO
 }
```

#### 3.3. [MODIFY] `app/core/event_groups.py`

Them `ZALO` vao `NotificationChannel` enum va `DEFAULT_GROUP_CHANNELS`:

```diff
 class NotificationChannel(str, Enum):
     BROWSER = "browser"
     EMAIL = "email"
     SMS = "sms"
+    ZALO = "zalo"

 DEFAULT_GROUP_CHANNELS: Dict[NotificationEventGroup, Dict[NotificationChannel, bool]] = {
     NotificationEventGroup.LEAD: {
         NotificationChannel.BROWSER: True,
         NotificationChannel.EMAIL: True,
         NotificationChannel.SMS: False,
+        NotificationChannel.ZALO: False,  # Opt-in
     },
-    # ... tuong tu cho tat ca 11 groups, them ZALO: False
+    # Them NotificationChannel.ZALO: False cho tat ca 11 groups
 }
```

**Luu y**: Default la `False` (opt-in). User phai bat Zalo notification trong preferences.

---

### Phase 4: Preference System Extension

**Muc tieu**: Cho phep user bat/tat Zalo notification theo event group.

#### 4.1. [MODIFY] `app/services/notification_preference_service.py`

Khi filter_users_by_group duoc goi voi channel="zalo":
- Check user co preference `zalo: True` cho group do
- Chi gui cho users da opt-in

**Khong can thay doi code** - he thong preference da su dung `DEFAULT_GROUP_CHANNELS` dict. Them `ZALO: False` vao dict la du.

#### 4.2. [MODIFY] Dispatcher - Zalo preference filtering

Hien tai `notification_dispatcher.py:296-303` chi filter theo `NotificationChannel.BROWSER`:

```python
# Hien tai (line 302):
channel=NotificationChannel.BROWSER.value

# Can sua thanh: filter theo TUNG channel
# Nhung vi dispatcher gui parallel tat ca channels,
# filtering can xay ra BEN TRONG moi channel
```

**Quyet dinh thiet ke**: Preference filtering cho Zalo xay ra **ben trong ZaloChannel.send()** (tuong tu EmailChannel - tu query preferences). Dispatcher chi filter cho browser channel (la default/primary channel).

#### 4.3. Frontend - Preference UI

Them toggle "Zalo" trong notification preferences UI (tuong tu Email toggle).

Files can sua:
- `frontend/src/components/notifications/NotificationPreferences.tsx`
- `frontend/src/lib/api/notifications.ts` (schema update)

---

### Phase 5: Celery Tasks

**Muc tieu**: Background tasks cho Zalo voi retry logic phu hop.

#### 5.1. [NEW] `app/tasks/zalo_tasks.py`

```python
# app/tasks/zalo_tasks.py
"""
Celery tasks cho Zalo integration.

Tasks:
- send_zalo_message_task: Gui Zalo message voi retry (token-aware)
- refresh_zalo_token_task: Periodic refresh token (Celery Beat, moi 20h)
- sync_zalo_quota_task: Periodic check quota remaining
"""
import logging
from datetime import datetime, timezone

from ..celery_app import celery_app
from ..config import settings
from .utils import task_db_session, run_async_task


@celery_app.task(
    name="send_zalo_message_task",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def send_zalo_message_task(
    self,
    phone: str,
    template_id: str,
    template_data: dict,
    notification_id: int = None,
    send_method: str = "phone",
    zalo_user_id: str = None,
):
    """
    Gui Zalo message qua Celery (async, co retry).

    Retry logic:
    - ZaloTokenExpiredError: Refresh token + retry (max 1)
    - ZaloQuotaExceededError: KHONG retry, log error
    - Other errors: Retry voi backoff (max 2)
    """
    task_name = "send_zalo_message_task"
    task_log = logging.getLogger(task_name)

    if not settings.ZALO_ENABLED:
        task_log.info("Zalo disabled, skipping task")
        return {"status": "skipped", "reason": "disabled"}

    async def _send():
        from ..gateways.zalo_gateway import (
            zalo_gateway, ZaloTokenExpiredError,
            ZaloQuotaExceededError, ZaloRecipientError
        )
        from ..models.zalo import ZaloMessageLog

        try:
            if send_method == "uid" and zalo_user_id:
                result = await zalo_gateway.send_template_by_uid(
                    user_id=zalo_user_id,
                    template_id=template_id,
                    template_data=template_data
                )
            else:
                result = await zalo_gateway.send_template_by_phone(
                    phone=phone,
                    template_id=template_id,
                    template_data=template_data,
                    tracking_id=f"notif_{notification_id}" if notification_id else ""
                )

            # Log to DB
            async with task_db_session() as db:
                log_entry = ZaloMessageLog(
                    msg_id=result.msg_id if result.success else None,
                    notification_id=notification_id,
                    template_id=template_id,
                    phone=phone if send_method == "phone" else None,
                    zalo_user_id=zalo_user_id if send_method == "uid" else None,
                    send_method=send_method,
                    status="sent" if result.success else "failed",
                    error_code=result.error_code if not result.success else None,
                    error_message=result.error_message if not result.success else None,
                    raw_response=result.raw_response
                )
                db.add(log_entry)
                await db.commit()

            return {
                "status": "sent" if result.success else "failed",
                "msg_id": result.msg_id,
                "remaining_quota": result.remaining_quota
            }

        except ZaloTokenExpiredError:
            task_log.warning("Token expired, retrying...")
            raise  # Celery will retry
        except ZaloQuotaExceededError as e:
            task_log.error(f"Quota exceeded: {e}")
            return {"status": "quota_exceeded"}
        except ZaloRecipientError as e:
            task_log.info(f"Recipient not on Zalo: {e}")
            return {"status": "recipient_not_found"}

    return run_async_task(
        async_func=_send,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["status"]
    )


@celery_app.task(name="refresh_zalo_token_task")
def refresh_zalo_token_task():
    """
    Periodic task: Proactively refresh Zalo token.

    Schedule: Moi 20 gio (buffer truoc 25h expiry).
    Chay boi Celery Beat.
    """
    task_name = "refresh_zalo_token_task"
    task_log = logging.getLogger(task_name)

    if not settings.ZALO_ENABLED:
        return {"status": "skipped"}

    async def _refresh():
        from ..gateways.zalo_gateway import zalo_gateway
        token = await zalo_gateway.get_access_token()
        return {"status": "refreshed", "token_prefix": token[:8] + "..."}

    return run_async_task(
        async_func=_refresh,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["status"]
    )
```

#### 5.2. [MODIFY] Celery Beat schedule

Them vao Celery Beat config (file cau hinh celery):

```python
# Refresh Zalo token moi 20 gio
"refresh-zalo-token": {
    "task": "refresh_zalo_token_task",
    "schedule": crontab(minute=0, hour="*/20"),
},
```

---

### Phase 6: Webhook Receiver

**Muc tieu**: Nhan events tu Zalo (follow/unfollow, tin nhan, delivery status).

#### 6.1. [NEW] `app/routers/zalo_webhook.py`

```python
# app/routers/zalo_webhook.py
"""
Zalo Webhook Receiver.

Nhan HTTP POST tu Zalo khi co events:
- user_follow_oa: User follow OA -> tao/cap nhat ZaloUserMapping
- user_unfollow_oa: User unfollow -> cap nhat is_follower=False
- user_send_text: User gui tin nhan (tuong lai: chatbot)
- oa_send_text: Delivery confirmation

Security:
- HMAC-SHA256 signature verification
- Idempotency check (msg_id in Redis, TTL 24h)
- Rate limiting
- CSRF exempt (external webhook)
"""
import hmac
import hashlib
import structlog
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException

from app.config import settings

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["zalo-webhook"])


@router.post("/zalo")
async def zalo_webhook(request: Request):
    """
    Nhan webhook events tu Zalo.

    Zalo gui POST voi body JSON va header X-ZEvent-Signature.
    """
    if not settings.ZALO_ENABLED:
        return {"status": "disabled"}

    # 1. Read body
    body = await request.body()
    body_str = body.decode("utf-8")

    # 2. Verify signature
    signature = request.headers.get("X-ZEvent-Signature", "")
    expected = hmac.new(
        key=settings.ZALO_WEBHOOK_SECRET.encode(),
        msg=body_str.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        log.warning("Zalo webhook: invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. Parse event
    import json
    try:
        data = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_name = data.get("event_name", "")

    # 4. Idempotency check
    msg_id = data.get("message", {}).get("msg_id", "")
    if msg_id:
        from app.database import get_redis
        redis = await get_redis()
        idempotency_key = f"zalo:webhook:{msg_id}"
        if await redis.get(idempotency_key):
            log.debug("Zalo webhook: duplicate event", msg_id=msg_id)
            return {"status": "duplicate"}
        await redis.set(idempotency_key, "1", ex=86400)  # 24h TTL

    # 5. Handle event
    log.info("Zalo webhook received", event_name=event_name)

    if event_name == "user_follow_oa":
        await _handle_follow(data)
    elif event_name == "user_unfollow_oa":
        await _handle_unfollow(data)
    elif event_name == "user_send_text":
        await _handle_user_message(data)
    else:
        log.debug("Zalo webhook: unhandled event", event_name=event_name)

    return {"status": "ok"}


async def _handle_follow(data: dict):
    """Xu ly user_follow_oa: Tao/cap nhat ZaloUserMapping."""
    from app.database import AsyncSessionLocal
    from app.models.zalo import ZaloUserMapping
    from app.models import User
    from sqlalchemy import select

    zalo_user_id = data.get("user_id_by_app", "")
    if not zalo_user_id:
        return

    async with AsyncSessionLocal() as db:
        # Check existing mapping
        existing = await db.execute(
            select(ZaloUserMapping).where(
                ZaloUserMapping.zalo_oa_user_id == zalo_user_id
            )
        )
        mapping = existing.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if mapping:
            mapping.is_follower = True
            mapping.followed_at = now
            mapping.unfollowed_at = None
            mapping.last_interaction_at = now
        else:
            mapping = ZaloUserMapping(
                zalo_oa_user_id=zalo_user_id,
                is_follower=True,
                followed_at=now,
                last_interaction_at=now
            )
            db.add(mapping)

        await db.commit()

    log.info("Zalo: user followed OA", zalo_user_id=zalo_user_id)


async def _handle_unfollow(data: dict):
    """Xu ly user_unfollow_oa: Danh dau is_follower=False."""
    from app.database import AsyncSessionLocal
    from app.models.zalo import ZaloUserMapping
    from sqlalchemy import select

    zalo_user_id = data.get("user_id_by_app", "")
    if not zalo_user_id:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ZaloUserMapping).where(
                ZaloUserMapping.zalo_oa_user_id == zalo_user_id
            )
        )
        mapping = result.scalar_one_or_none()

        if mapping:
            mapping.is_follower = False
            mapping.unfollowed_at = datetime.now(timezone.utc)
            await db.commit()

    log.info("Zalo: user unfollowed OA", zalo_user_id=zalo_user_id)


async def _handle_user_message(data: dict):
    """Xu ly user_send_text: Log va cap nhat last_interaction_at."""
    from app.database import AsyncSessionLocal
    from app.models.zalo import ZaloUserMapping
    from sqlalchemy import select

    zalo_user_id = data.get("user_id_by_app", "")
    if not zalo_user_id:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ZaloUserMapping).where(
                ZaloUserMapping.zalo_oa_user_id == zalo_user_id
            )
        )
        mapping = result.scalar_one_or_none()

        if mapping:
            mapping.last_interaction_at = datetime.now(timezone.utc)
            await db.commit()

    log.info("Zalo: user message received", zalo_user_id=zalo_user_id)
```

#### 6.2. [MODIFY] `app/main.py` - Register router

```python
from app.routers.zalo_webhook import router as zalo_webhook_router
app.include_router(zalo_webhook_router)
```

#### 6.3. CSRF Exempt

Webhook endpoint can CSRF exempt (tuong tu pattern CTV registration).
Them vao CSRF middleware exclude list:
```python
CSRF_EXEMPT_PATHS = [
    "/webhooks/zalo",
    # ... existing exemptions
]
```

---

### Phase 7: Business Rules & Template Mapping

**Muc tieu**: Ket noi events voi ZBS templates.

#### 7.1. Template Mapping Strategy

Su dung **database-driven approach** (qua `NotificationAction.config`):

```json
{
    "channel": "zalo",
    "config": {
        "template_id": "abc123def456",
        "data_mapping": {
            "ho_ten": "applicant_name",
            "ma_ho_so": "profile_code",
            "trang_thai": "new_status"
        }
    }
}
```

**Ly do**: template_id co the thay doi khi Zalo duyet lai template. Database-driven cho phep admin thay doi ma khong deploy code.

#### 7.2. Recommended ZBS Templates

| Use Case | Event | ZBS Template (ví dụ) | Variables |
|----------|-------|---------------------|-----------|
| Xac nhan ho so | `APPLICATION_CREATED` | "Ho so {ma_ho_so} da duoc tiep nhan" | ma_ho_so, ho_ten |
| Cap nhat trang thai | `APPLICATION_STATUS_CHANGED` | "Ho so {ma_ho_so}: {trang_thai}" | ma_ho_so, trang_thai |
| Nhac nho thanh toan | `PAYMENT_OVERDUE` | "Den han thanh toan {so_tien}" | so_tien, han_thanh_toan |
| Xac nhan thanh toan | `PAYMENT_RECEIVED` | "Thanh toan {so_tien} thanh cong" | so_tien, ma_giao_dich |
| Lich hen tu van | `CONSULTATION_REMINDER` | "Lich hen tu van ngay {ngay}" | ngay, gio, dia_diem |
| Lead assigned | `LEAD_ASSIGNED` | "Ban co lead moi: {ten_lead}" | ten_lead, sdt |

#### 7.3. [MODIFY] `NotificationConfig` - Them channel_config

Them optional field `channel_config` vao `NotificationConfig` (cho hardcoded registry):

```python
@dataclass(frozen=True)
class NotificationConfig:
    # ... existing fields ...
    channel_config: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # e.g., {"zalo": {"template_id": "abc", "data_mapping": {...}}}
```

#### 7.4. [MODIFY] Dispatcher - Pass channel_config to context

Trong `notification_dispatcher.py`, truyen `channel_config` vao context khi goi channels:

```python
# Trong _post_commit(), truoc khi goi _send_via_channel:
context_with_config = {
    **payload,
    "zalo_config": config.channel_config.get("zalo", {})
}
```

---

### Phase 8: Admin Dashboard

**Muc tieu**: UI quan ly va monitor Zalo integration.

#### 8.1. [NEW] `app/routers/admin/zalo.py`

```python
# Endpoints:
GET  /api/admin/zalo/status
# -> Token status, quota remaining, follower count

GET  /api/admin/zalo/templates
# -> Proxy list_templates() tu Zalo API

GET  /api/admin/zalo/message-logs?page=1&status=failed
# -> Paginated message logs tu zalo_message_log

POST /api/admin/zalo/test-send
# -> Test gui message (chi admin)

POST /api/admin/zalo/refresh-token
# -> Manual trigger token refresh
```

#### 8.2. Frontend Dashboard

- Widget hien thi: token status, quota remaining, last refresh time
- Message logs table voi filters (status, date range)
- Test send form (phone + template_id + template_data)
- Manual token refresh button

---

## 5. Fallback & Error Strategy

### 5.1. Error Handling Flow

```
Zalo send attempt
    |
    +-- Success (error=0) --> Log + Return success
    |
    +-- Token expired (-201) --> Auto-refresh + Retry 1 lan
    |       +-- Refresh fail --> Log + Alert admin + Fallback email
    |
    +-- Quota exceeded (-210) --> Log + Alert admin + Fallback email
    |       Note: KHONG retry, queue cho ngay hom sau
    |
    +-- Recipient not found (-230) --> Log + Fallback email
    |       Note: SDT khong co Zalo
    |
    +-- Template error (-216, -217) --> Log + Alert admin
    |       Note: Config error, can fix template
    |
    +-- OA blocked (-204) --> Log + Alert admin (critical)
    |
    +-- Network error --> Retry voi backoff (max 2)
    |
    +-- Unknown error --> Log + Retry 1 lan
```

### 5.2. Quota Management

```python
# Redis keys:
REDIS_QUOTA_DAILY = "zalo:quota:daily"       # INCR moi message
REDIS_QUOTA_REMAINING = "zalo:quota:remaining"  # SET tu API response

# Logic trong ZaloChannel.send():
# 1. Truoc khi gui: check zalo:quota:remaining
# 2. Neu < 10 messages -> log warning
# 3. Neu = 0 -> skip Zalo, fallback email
# 4. Sau khi gui: update remaining tu API response
# 5. Daily reset: TTL den midnight
```

### 5.3. Circuit Breaker (don gian)

```python
# Redis key: zalo:circuit_breaker
# Values: "closed" (normal), "open" (Zalo down), "half_open" (testing)

# Logic:
# - 5 consecutive failures trong 5 phut -> open circuit
# - Open: skip Zalo cho 5 phut, fallback email
# - After 5 phut: half_open -> thu 1 request
# - Thanh cong: closed. That bai: open lai.
```

---

## 6. Testing Plan

### 6.1. Unit Tests

| Test file | Coverage |
|-----------|----------|
| `tests/unit/test_zalo_gateway.py` | Gateway methods, token refresh, phone normalization |
| `tests/unit/test_zalo_channel.py` | ZaloChannel.send(), validate_config() |
| `tests/unit/test_zalo_webhook.py` | Webhook signature verification, event handling |

#### `test_zalo_gateway.py` - Key test cases:

```python
# Phone normalization
def test_normalize_phone_zero_prefix():
    assert normalize_phone_for_zalo("0987654321") == "84987654321"

def test_normalize_phone_plus84():
    assert normalize_phone_for_zalo("+84987654321") == "84987654321"

def test_normalize_phone_already_84():
    assert normalize_phone_for_zalo("84987654321") == "84987654321"

def test_normalize_phone_with_spaces():
    assert normalize_phone_for_zalo("09 8765 4321") == "84987654321"

# Gateway send (mock httpx)
async def test_send_template_by_phone_success(mock_httpx):
    mock_httpx.post.return_value = httpx.Response(200, json={
        "error": 0,
        "data": {"msg_id": "abc", "quota": {"remainingQuota": "499"}}
    })
    result = await zalo_gateway.send_template_by_phone(...)
    assert result.success is True
    assert result.msg_id == "abc"

async def test_send_template_token_expired_raises(mock_httpx):
    mock_httpx.post.return_value = httpx.Response(200, json={
        "error": -201, "message": "Token expired"
    })
    with pytest.raises(ZaloTokenExpiredError):
        await zalo_gateway.send_template_by_phone(...)

async def test_send_template_quota_exceeded_raises(mock_httpx):
    # error -210

async def test_send_template_recipient_not_found_raises(mock_httpx):
    # error -230

# Token management (mock Redis)
async def test_get_access_token_from_cache(mock_redis):
    mock_redis.get.return_value = b"cached_token"
    token = await zalo_gateway.get_access_token()
    assert token == "cached_token"

async def test_get_access_token_refresh_on_miss(mock_redis, mock_httpx):
    mock_redis.get.side_effect = [None, None]  # No cache, no lock
    mock_redis.set.return_value = True  # Lock acquired
    mock_httpx.post.return_value = httpx.Response(200, json={
        "access_token": "new_token",
        "refresh_token": "new_refresh",
        "expires_in": "90000"
    })
    token = await zalo_gateway.get_access_token()
    assert token == "new_token"
```

#### `test_zalo_channel.py` - Key test cases:

```python
async def test_zalo_disabled_returns_empty():
    # ZALO_ENABLED=False -> ChannelResult(success=True, sent_count=0)

async def test_no_template_id_returns_failure():
    # context khong co zalo_config -> all failed

async def test_send_via_uid_preferred_over_phone():
    # User co ca mapping va phone -> chon UID

async def test_send_via_phone_fallback():
    # User chi co phone, khong co mapping -> gui qua SDT

async def test_user_no_contact_info_skipped():
    # User khong co phone va mapping -> failed_ids

async def test_partial_failure_returns_correct_counts():
    # 3 users: 2 success, 1 fail -> sent=2, failed=[user3]
```

#### `test_zalo_webhook.py` - Key test cases:

```python
async def test_valid_signature_accepted():
async def test_invalid_signature_rejected():
async def test_duplicate_event_skipped():
async def test_follow_creates_mapping():
async def test_unfollow_updates_mapping():
async def test_user_message_updates_interaction_time():
async def test_disabled_returns_ok():
```

### 6.2. Integration Tests

```python
# tests/integration/test_zalo_token_flow.py
async def test_token_refresh_end_to_end():
    """Test full flow: Redis miss -> refresh -> store -> retry."""

async def test_token_refresh_distributed_lock():
    """Test concurrent refresh requests only trigger 1 API call."""

# tests/integration/test_zalo_notification_flow.py
async def test_dispatch_with_zalo_channel():
    """Test full dispatch: event -> resolver -> ZaloChannel.send()."""
```

### 6.3. Manual Verification

1. Gui test ZBS Template Message qua sandbox
2. Verify webhook receive (follow/unfollow)
3. Test token auto-refresh (set TTL ngan)
4. Test fallback khi Zalo khong available
5. Monitor quota qua admin dashboard

---

## 7. Rui ro & Mitigation

| Rui ro | Muc do | Mitigation |
|--------|--------|------------|
| **Mat refresh token** (single-use, Redis restart) | **Cao** | Backup DB + alert admin ngay khi refresh fail |
| **Quota gioi han** (500/ngay goi free) | Trung binh | Quota tracking Redis, priority queue, alert khi < 10% |
| **Template duyet cham** (2-3 ngay lam viec) | Trung binh | Chuan bi templates truoc, fallback email |
| **Phone format khong chuan** | Thap | `normalize_phone_for_zalo()` + validation khi nhap |
| **Webhook replay attack** | Thap | HMAC signature + timestamp check + idempotency key |
| **Zalo API downtime** | Thap | Circuit breaker + fallback email |
| **Race condition token refresh** | Thap | Redis distributed lock (nx + ttl) |
| **2 enum NotificationChannel khong dong bo** | Thap | Phase 3 fix - them ZALO vao event_groups.py |

---

## 8. Checklist Prerequisites

Truoc khi bat dau code, can hoan thanh:

- [ ] **Dang ky Zalo OA** - tao tai khoan Official Account tren oa.zalo.me
- [ ] **Tao App tren Zalo Developers** - developers.zalo.me
  - [ ] Lay `APP_ID`
  - [ ] Lay `APP_SECRET_KEY`
- [ ] **Lien ket App voi OA** - trong dashboard Zalo Developers
- [ ] **Lay Refresh Token ban dau** - qua OAuth flow tren browser
- [ ] **Dang ky & duyet Templates** - tao ZBS templates phu hop (2-3 ngay duyet)
- [ ] **Cau hinh Webhook URL** - can domain HTTPS public
- [ ] **Xac nhan goi Zalo** - free (500 msg/ngay) hay tra phi?

---

## So do Kien truc Tich hop

```
                          QLTS Backend
    +----------------------------------------------------------+
    |                                                          |
    |  SystemEvent --> Dispatcher --> Channel Registry          |
    |                     |              |     |     |         |
    |                     |           Socket  Email  Zalo      |
    |                     |                          |         |
    |                     |                    ZaloChannel     |
    |                     |                     |    |         |
    |                     |              +------+    |         |
    |                     |              |           |         |
    |                  Celery        Gateway     Preferences   |
    |                  Tasks         (httpx)     (opt-in)      |
    |                   |               |                      |
    |            +------+------+   Token Store                 |
    |            |      |      |   (Redis+DB)                  |
    |          Send   Refresh  Quota                           |
    |          Task   Task     Track                           |
    +-----|-----------|--------------------------------|-------+
          |           |                                |
    +-----|-----------|---+    +-------+    +----------|-------+
    |  Zalo Platform      |    | Redis |    | PostgreSQL      |
    |  - OAuth v4         |    | - Token|    | - zalo_token    |
    |  - ZBS Template API |    | - Lock |    | - zalo_mapping  |
    |  - OA Message API   |    | - Quota|    | - zalo_msg_log  |
    |  - Webhook Events   |    +-------+    +-----------------+
    +---------------------+
          |
    +-----|---------+
    | Webhook Router |  <-- Zalo POST events
    | /webhooks/zalo |      (HMAC verified)
    +----------------+
```

---

## Phu luc: Tham chieu Files

### Files can TAO MOI:
```
app/gateways/zalo_gateway.py          # Phase 1
app/models/zalo.py                     # Phase 2
app/services/notification_channels/zalo_channel.py  # Phase 3
app/tasks/zalo_tasks.py                # Phase 5
app/routers/zalo_webhook.py            # Phase 6
app/routers/admin/zalo.py              # Phase 8 (optional)
alembic/versions/xxx_add_zalo_tables.py  # Phase 2
tests/unit/test_zalo_gateway.py        # Phase 1
tests/unit/test_zalo_channel.py        # Phase 3
tests/unit/test_zalo_webhook.py        # Phase 6
tests/integration/test_zalo_token.py   # Phase 5
```

### Files can SUA:
```
app/config.py                          # Phase 1 (them ZALO_* settings)
app/models/__init__.py                 # Phase 2 (them imports)
app/core/event_groups.py               # Phase 3 (them ZALO enum + defaults)
app/services/notification_channels/__init__.py  # Phase 3 (register channel)
app/services/notification_registry.py  # Phase 7 (them channel_config)
app/services/notification_dispatcher.py  # Phase 7 (pass zalo_config)
app/main.py                            # Phase 6 (register webhook router)
.env.example                           # Phase 1
Backend_FastAPI/.env                   # Phase 1
```

### Files tham chieu (KHONG sua):
```
app/gateways/base.py                  # Pattern reference
app/services/notification_channels/base.py       # Interface to implement
app/services/notification_channels/email_channel.py  # Implementation reference
app/services/notification_dispatcher.py           # Integration point
app/services/notification_preference_service.py   # Preference filtering
app/tasks/notification_tasks.py                   # Celery task pattern
```
