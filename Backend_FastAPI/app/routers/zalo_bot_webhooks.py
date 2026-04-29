"""Zalo Bot Platform webhook receiver.

Endpoint: ``POST /api/webhooks/zalo-bot``

Auth model: shared secret in ``X-Bot-Api-Secret-Token`` header,
configured via ``settings.ZALO_BOT_WEBHOOK_SECRET``. The secret is
**required** — an empty configured secret fails closed (401) so a
mis-configured deploy can't accidentally accept anonymous traffic.

What this router does NOT do:
- Log the secret, the bot token, the link code, or the raw message
  body. Operator visibility is limited to a masked chat_id prefix and
  high-level event type.
- Return non-2xx for handled command errors. Zalo retries non-2xx
  responses, which would double-consume codes (``GETDEL`` makes the
  first attempt destructive). 401 is reserved for genuine auth
  failures; 400 for malformed JSON; everything else returns 200 with
  a status string the operator can grep.
"""
from __future__ import annotations

import hmac
import re

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import (
    get_db,
    safe_redis_expire,
    safe_redis_incr,
    safe_redis_set,
)
from app.utils.inmemory_rate_limit import fallback_incr
from app.utils.masking import mask_chat_id

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["Zalo Bot Webhooks"])


# Per-chat_id rate limit window
_WEBHOOK_RL_PREFIX = "zalo_bot:webhook_rl:"
_WEBHOOK_RL_LIMIT = 10  # commands
_WEBHOOK_RL_WINDOW = 60  # seconds

# Once-per-window flag so we send the "rate limited" reply only on the
# first hit that crosses the threshold. Without this, every subsequent
# rate-limited request still triggers a send_message (~1 reply per
# attacker request) — which on the Basic plan (3000 msg/month) burns the
# daily quota in minutes when a single chat is blasted with traffic.
_WEBHOOK_RL_NOTIFIED_PREFIX = "zalo_bot:webhook_rl_notified:"

# F-6: same once-per-window guard for the unknown-command help text.
# Without it, every stray message (or stale /lienkit typo loop) burns a
# send_message quota slot. Window matches the rate-limit window so a
# user typing legit commands after exploring isn't silenced for an hour.
_HELP_REPLY_PREFIX = "zalo_bot:help_throttle:"
_HELP_REPLY_WINDOW = 60

# 6-char uppercase alnum, exact length so attackers can't pad with spaces
_LINK_CODE_RE = re.compile(r"^[A-Z0-9]{6}$")


async def _send_reply(chat_id: str, text: str) -> None:
    """Send a reply to the chat and log if Zalo API rejects it.

    The webhook always returns 200 to Zalo so the upstream doesn't retry
    and double-consume the link code (``GETDEL`` is destructive). That
    means a silent ``send_message`` failure leaves the user with no
    confirmation and no on-host trail — the gateway only logs httpx
    exceptions, not API-level errors (``ok=false`` with ``error_code`` /
    ``description``). Surface those here so operators can spot quota
    (429), unauthorized (401), or chat-blocked failures from the log.
    """
    from app.gateways.zalo_bot import zalo_bot_gateway

    result = await zalo_bot_gateway.send_message(chat_id, text)
    if not result.success:
        log.warning(
            "zalo_bot reply send failed",
            chat_id_prefix=mask_chat_id(chat_id),
            error_code=result.error_code,
            error_message=result.error_message,
        )


async def _once_per_window(key: str, window_seconds: int) -> bool:
    """Return True iff this is the first call for ``key`` within
    ``window_seconds``. Used to throttle reply messages so spam can't
    drain ``send_message`` quota.

    Why custom: ``safe_redis_set`` re-raises on breaker open (unlike
    ``safe_redis_incr`` which returns None), so a naive call here would
    500 the webhook whenever Redis flapped. We catch the breaker
    exceptions and fall back to the per-process counter (M1 fix);
    ``count == 1`` is the in-memory equivalent of NX-set succeeding.
    """
    try:
        notified = await safe_redis_set(
            key, "1", ex=window_seconds, nx=True
        )
        return bool(notified)
    except (ConnectionError, TimeoutError):
        # Redis breaker open — degrade closed-but-bounded: use the
        # in-memory counter, send the reply only on first hit per
        # window per process. Multiple workers may each send once, but
        # that's bounded (N workers × 1 reply/window) — far better
        # than either 500ing the webhook or letting every spam message
        # trigger a reply.
        return fallback_incr(key, window_seconds) == 1


async def _rate_limit_chat(chat_id: str) -> bool:
    """Return ``True`` if the chat is over its 10/min budget.

    Atomic via INCR + EXPIRE — a GET-then-SET pattern would let two
    concurrent webhook deliveries both pass when both observe the
    pre-increment count.

    F-2: when Redis is unavailable (``safe_redis_incr`` returns None),
    fall back to a per-process in-memory counter rather than failing
    OPEN. With N workers an attacker still gets ``N × limit`` per
    window, but that's bounded — fail-open let send_message quota be
    drained whenever Redis flapped.
    """
    key = f"{_WEBHOOK_RL_PREFIX}{chat_id}"
    new_val = await safe_redis_incr(key)
    if new_val == 1:
        await safe_redis_expire(key, _WEBHOOK_RL_WINDOW)
    if new_val is None:
        new_val = fallback_incr(key, _WEBHOOK_RL_WINDOW)
    return new_val > _WEBHOOK_RL_LIMIT


@router.post("/zalo-bot")
async def zalo_bot_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.repositories.staff_zalo_bot_link_repository import (
        StaffZaloBotLinkRepository,
    )
    from app.services import zalo_bot_link_service

    # 1. Secret check (timing-safe).
    configured_secret = settings.ZALO_BOT_WEBHOOK_SECRET or ""
    if not configured_secret:
        # v5 explicit: an empty configured secret is a deploy mistake.
        # Refuse traffic so we never accept anonymous webhooks.
        log.error(
            "zalo_bot webhook rejected — ZALO_BOT_WEBHOOK_SECRET is empty",
        )
        return Response(status_code=401, content="Webhook secret not configured")

    presented_secret = request.headers.get("X-Bot-Api-Secret-Token", "") or ""
    if not hmac.compare_digest(presented_secret, configured_secret):
        return Response(status_code=401, content="Invalid secret")

    # 2. Body parse — 400 on malformed JSON (tells operator the
    #    upstream payload format changed).
    try:
        data = await request.json()
    except Exception:
        log.warning("zalo_bot webhook invalid JSON")
        return Response(status_code=400, content="Invalid JSON")

    if not isinstance(data, dict):
        log.warning("zalo_bot webhook non-object payload")
        return {"status": "ok", "mode": "non_object_payload"}

    result = data.get("result") or {}
    # Zalo Bot Platform variants observed:
    #   - top level: data["event_name"]
    #   - nested:    data["result"]["event_name"]
    # Smoke 2026-04-27 still hit ignored_event after PR #139 → real
    # payload may use a 3rd shape. Log the structure (keys only, no
    # values) when no event_name is found so we can iterate.
    event_name = (
        data.get("event_name")
        or (result.get("event_name") if isinstance(result, dict) else "")
        or ""
    )
    if event_name != "message.text.received":
        # Debug: surface the actual payload shape so future drift is
        # visible. Keys only — values may contain link codes / chat
        # IDs that are sensitive.
        log.info(
            "zalo_bot webhook ignored_event — debug shape",
            top_keys=sorted(list(data.keys())),
            result_keys=sorted(list(result.keys())) if isinstance(result, dict) else None,
            event_name_seen=event_name or "<empty>",
        )
        return {"status": "ok", "mode": "ignored_event", "event": event_name}

    message = result.get("message") or data.get("message") or {}
    chat = message.get("chat") if isinstance(message, dict) else None
    chat_id = chat.get("id", "") if isinstance(chat, dict) else ""
    text_raw = (message.get("text") or "") if isinstance(message, dict) else ""
    text = text_raw.strip()
    sender = message.get("from") if isinstance(message, dict) else None
    display_name = sender.get("display_name", "") if isinstance(sender, dict) else ""

    if not chat_id or not text:
        log.info(
            "zalo_bot webhook noop — debug shape",
            top_keys=sorted(list(data.keys())),
            result_keys=sorted(list(result.keys())) if isinstance(result, dict) else None,
            message_keys=sorted(list(message.keys())) if isinstance(message, dict) else None,
            has_chat_id=bool(chat_id),
            has_text=bool(text),
        )
        return {"status": "ok", "mode": "noop"}

    # 3. Rate limit per chat_id.
    if await _rate_limit_chat(chat_id):
        # First-hit-only reply via ``_once_per_window`` — the SET NX EX
        # plus in-memory fallback so a Redis flap doesn't 500 the webhook
        # (M1 fix; ``safe_redis_set`` re-raises on breaker open unlike
        # the rest of the safe_redis_* family).
        notified = await _once_per_window(
            f"{_WEBHOOK_RL_NOTIFIED_PREFIX}{chat_id}",
            _WEBHOOK_RL_WINDOW,
        )
        if notified:
            await _send_reply(
                chat_id, "Quá nhiều lệnh. Vui lòng thử lại sau 1 phút."
            )
        log.warning(
            "zalo_bot webhook rate_limited",
            chat_id_prefix=mask_chat_id(chat_id),
            replied=notified,
        )
        return {"status": "rate_limited"}

    # 4. Log the event class only — never the raw text (may contain code).
    #    Use ``event_kind`` not ``event`` because structlog reserves the
    #    latter as the message slot.
    log.info(
        "zalo_bot webhook event",
        chat_id_prefix=mask_chat_id(chat_id),
        event_kind="text",
    )

    text_lower = text.lower()

    # ---------------- /lienket <CODE> ----------------
    # "liên kết" without diacritics is "lien ket" (kết → ket, NOT kiet).
    # Accept legacy "/lienkiet" too in case staff cached old instruction
    # text — both route to the same handler.
    if text_lower.startswith("/lienket") or text_lower.startswith("/lienkiet"):
        prefix_len = len("/lienkiet") if text_lower.startswith("/lienkiet") else len("/lienket")
        candidate = text[prefix_len:].strip().upper()
        if not _LINK_CODE_RE.match(candidate):
            await _send_reply(
                chat_id,
                "Cú pháp sai. Gửi: /lienket <MA> (6 ký tự, chỉ chữ in hoa và số).",
            )
            return {"status": "ok", "mode": "bad_format"}

        post_commit_cb = None
        try:
            ok, reply, post_commit_cb = await zalo_bot_link_service.verify_and_link(
                db, candidate, chat_id, display_name or None
            )
            if ok:
                await db.commit()
            else:
                await db.rollback()
                post_commit_cb = None  # Don't fan out on failed verify.
        except Exception:
            await db.rollback()
            log.exception(
                "zalo_bot verify_and_link failed",
                chat_id_prefix=mask_chat_id(chat_id),
            )
            await _send_reply(chat_id, "Lỗi hệ thống. Vui lòng thử lại sau.")
            return {"status": "ok", "mode": "service_error"}

        await _send_reply(chat_id, reply)
        if post_commit_cb is not None:
            # Displacement happened — fan out the security notification
            # AFTER commit so the displaced user sees it (browser only by
            # default per ZALO_BOT_LINK_DISPLACED catalog entry).
            try:
                await post_commit_cb()
            except Exception:
                # Never fail the webhook because of a notification fan-out
                # issue — the link itself is already committed.
                log.exception(
                    "zalo_bot displacement post_commit failed",
                    chat_id_prefix=mask_chat_id(chat_id),
                )
        return {"status": "ok", "mode": "verify_and_link", "linked": ok}

    # ---------------- /huylienket ----------------
    # Same correction as /lienket above. Accept legacy "/huylienkiet" too.
    if text_lower == "/huylienket" or text_lower == "/huylienkiet":
        try:
            ok, reply, _ = await zalo_bot_link_service.unlink_by_chat_id(db, chat_id)
            if ok:
                await db.commit()
            else:
                await db.rollback()
        except Exception:
            await db.rollback()
            log.exception(
                "zalo_bot unlink_by_chat_id failed",
                chat_id_prefix=mask_chat_id(chat_id),
            )
            await _send_reply(chat_id, "Lỗi hệ thống. Vui lòng thử lại sau.")
            return {"status": "ok", "mode": "service_error"}

        await _send_reply(chat_id, reply)
        return {"status": "ok", "mode": "unlink", "found": ok}

    # ---------------- /trangthai ----------------
    if text_lower == "/trangthai":
        repo = StaffZaloBotLinkRepository(db)
        link = await repo.get_active_by_chat_id(chat_id)
        # IMPORTANT: never return the user_id (or display_name owned by
        # someone else if the chat_id has bounced) to the chat — only a
        # binary linked / not-linked answer.
        reply = "Đã liên kết." if link else "Chưa liên kết."
        await _send_reply(chat_id, reply)
        return {"status": "ok", "mode": "status", "linked": bool(link)}

    # ---------------- help / unknown ----------------
    # F-6: throttle the help reply per chat_id so an attacker spamming
    # noise can't drain send_message quota by triggering one help reply
    # per inbound text. Uses the same ``_once_per_window`` helper as the
    # rate-limited reply above so a Redis breaker open path can't 500
    # the webhook here either.
    notified = await _once_per_window(
        f"{_HELP_REPLY_PREFIX}{chat_id}", _HELP_REPLY_WINDOW
    )
    if notified:
        await _send_reply(
            chat_id,
            (
                "QLTS Bot:\n"
                "/lienket <MA> — liên kết tài khoản\n"
                "/huylienket — huỷ liên kết\n"
                "/trangthai — kiểm tra trạng thái"
            ),
        )
    return {"status": "ok", "mode": "help", "replied": notified}
