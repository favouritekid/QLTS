# app/utils/sms_bot.py
"""
SMS click bot heuristic (PR-5): phân loại 1 lượt /r/{code} có phải bot/link-
preview KHÔNG, để KHÔNG tính vào CTR "người thật". Best-effort, fail-OPEN cho
phía người (chỉ flag khi có dấu hiệu rõ) — CTR thà thiếu hơn thừa.

3 dấu hiệu (khớp click_event.bot_reason §4.10):
- known_scanner_ua: User-Agent của crawler/link-preview (Facebook, Zalo,
  Telegram, WhatsApp, Slack, Google, bot/crawler/spider, curl/wget/python…).
- prefetch_head: request mang header prefetch/preview (Purpose/X-Purpose) hoặc
  Sec-Purpose=prefetch.
- instant_after_send: click trong vài giây ngay sau bàn giao (preview server
  fetch tức thì khi tin vừa gửi) — đo `now - recipient.handed_off_at`.
"""
from datetime import datetime, timedelta, timezone

from app.utils.tz import ensure_aware
from typing import Mapping, Optional, Tuple

# Token UA hay gặp ở crawler/link-preview/HTTP client (so khớp lower-case).
_SCANNER_UA_TOKENS = (
    "bot", "crawler", "spider", "scanner", "preview", "fetch",
    "facebookexternalhit", "facebot", "zalo", "telegrambot", "whatsapp",
    "slackbot", "discordbot", "skypeuripreview", "twitterbot", "linkedinbot",
    "google", "bingbot", "yandex", "applebot", "pinterest", "embedly",
    "curl", "wget", "python-requests", "python-httpx", "go-http-client",
    "java/", "okhttp", "headlesschrome", "phantomjs",
)
_INSTANT_SECONDS = 8  # click ≤8s sau handoff → nghi preview server


_aware = ensure_aware  # alias tới helper tz chung (bỏ bản sao logic)


def detect_bot(
    *,
    user_agent: Optional[str],
    headers: Optional[Mapping[str, str]] = None,
    handed_off_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str]]:
    """Trả (is_bot, reason|None). Ưu tiên reason: UA > prefetch > instant."""
    ua = (user_agent or "").lower()
    if ua:
        for tok in _SCANNER_UA_TOKENS:
            if tok in ua:
                return True, "known_scanner_ua"
    if not ua:
        # Trình duyệt di động LUÔN gửi UA → thiếu UA hầu như chỉ script/preview.
        # Flag bot nhưng nhãn TRUNG THỰC (≠ known_scanner_ua) cho audit/báo cáo.
        return True, "no_user_agent"

    if headers:
        purpose = (
            headers.get("purpose")
            or headers.get("x-purpose")
            or headers.get("sec-purpose")
            or ""
        ).lower()
        if "prefetch" in purpose or "preview" in purpose:
            return True, "prefetch_head"
        if (headers.get("x-moz") or "").lower() == "prefetch":
            return True, "prefetch_head"

    if handed_off_at is not None:
        ref = now or datetime.now(timezone.utc)
        if ref - _aware(handed_off_at) <= timedelta(seconds=_INSTANT_SECONDS):
            return True, "instant_after_send"

    return False, None
