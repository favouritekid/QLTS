# app/utils/sms_bot.py
"""
SMS click bot heuristic (PR-5): phân loại 1 lượt /r/{code} có phải bot/link-
preview KHÔNG, để KHÔNG tính vào CTR "người thật". Best-effort, fail-OPEN cho
phía người (chỉ flag khi có dấu hiệu rõ) — CTR thà thiếu hơn thừa.

4 dấu hiệu (khớp click_event.bot_reason §4.10):
- known_scanner_ua: User-Agent của crawler/link-preview (Facebook, Zalo,
  Telegram, WhatsApp, Slack, Google, bot/crawler/spider, curl/wget/python…).
- prefetch_head: request mang header prefetch/preview (Purpose/X-Purpose) hoặc
  Sec-Purpose=prefetch.
- non_mobile_ua: CHỈ kênh SMS (`mobile_channel=True`) — UA không có dấu hiệu
  di động. Tin SMS chỉ mở được trên điện thoại, nên UA desktop = máy quét
  chống spam của nhà mạng (xem bên dưới).
- instant_after_send: click trong vài giây ngay sau bàn giao (preview server
  fetch tức thì khi tin vừa gửi) — đo `now - recipient.handed_off_at`.

⚠ Vì sao cần `non_mobile_ua` (bằng chứng chiến dịch #6, 13-07): 23 lượt vào
`/r/` thì 20 lượt cùng UA `Mozilla/5.0 (X11; Linux x86_64) …Chrome` trong
chùm 28 giây (10 người nhận × 2 lượt, 11 IP khác nhau) + 1 lượt
`antispam/1.0.0` — đều là máy quét của nhà mạng fetch mọi URL khi tin vừa
gửi. Cả hai lọt hết 3 dấu hiệu cũ: UA trông như trình duyệt thật (không chứa
token scanner nào), còn `instant_after_send` vô hiệu vì operator bấm "Đã bàn
giao" 10 phút SAU khi nhà mạng đã gửi → lúc quét `handed_off_at` còn NULL.
Hệ quả: báo cáo ghi 22 "người thật" trong khi chỉ ~1 người thật.

⚠ Đánh đổi CÓ CHỦ Ý: người thật mở link SMS trên máy tính (thường là chính
mình test) cũng bị đếm là bot. Chấp nhận được vì (a) học sinh nhận SMS gần
như luôn bấm trên điện thoại, (b) tín hiệu engagement "quan tâm ngành"
(session + dwell, cần JS) KHÔNG áp dấu hiệu này nên vẫn ghi nhận đầy đủ —
xem `mobile_channel` chỉ được bật ở nhánh recipient của `resolve_click`.
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

# Dấu hiệu trình duyệt DI ĐỘNG. Thiếu TẤT CẢ ở kênh SMS = không phải người
# nhận thật (điện thoại luôn gửi ít nhất một trong các token này).
_MOBILE_UA_TOKENS = (
    "mobile", "android", "iphone", "ipad", "ipod", "windows phone",
    "iemobile", "blackberry", "opera mini", "opera mobi", "silk",
    "kaios", "harmonyos", "webos",
)


_aware = ensure_aware  # alias tới helper tz chung (bỏ bản sao logic)


def is_mobile_ua(user_agent: Optional[str]) -> bool:
    """UA có dấu hiệu trình duyệt di động không (lower-case substring)."""
    ua = (user_agent or "").lower()
    return any(tok in ua for tok in _MOBILE_UA_TOKENS)


def detect_bot(
    *,
    user_agent: Optional[str],
    headers: Optional[Mapping[str, str]] = None,
    handed_off_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    mobile_channel: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Trả (is_bot, reason|None). Ưu tiên reason: UA > prefetch > non-mobile >
    instant.

    `mobile_channel=True` CHỈ cho lượt đến từ tin SMS thật (recipient) — bật
    dấu hiệu `non_mobile_ua`. Mặc định False để link tư vấn officer / phiên
    landing mở trên máy tính KHÔNG bị đếm nhầm là bot.
    """
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

    if mobile_channel and not is_mobile_ua(ua):
        return True, "non_mobile_ua"

    if handed_off_at is not None:
        ref = now or datetime.now(timezone.utc)
        if ref - _aware(handed_off_at) <= timedelta(seconds=_INSTANT_SECONDS):
            return True, "instant_after_send"

    return False, None
