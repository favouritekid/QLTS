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
- carrier_scan_burst: CHỈ kênh SMS (`mobile_channel=True`) — UA không phải
  trình duyệt di động VÀ cùng UA đó vừa mở link của nhiều người nhận KHÁC
  trong ít giây (xem bên dưới).
- instant_after_send: click trong vài giây ngay sau bàn giao (preview server
  fetch tức thì khi tin vừa gửi) — đo `now - recipient.handed_off_at`.

⚠ Vì sao cần `carrier_scan_burst` (bằng chứng chiến dịch #6, 13-07): 23 lượt
vào `/r/` thì 20 lượt cùng UA `Mozilla/5.0 (X11; Linux x86_64) …Chrome` trong
chùm 28 giây (10 người nhận × 2 lượt, 11 IP khác nhau) + 1 lượt
`antispam/1.0.0` — đều là máy quét của nhà mạng fetch mọi URL khi tin vừa
gửi. Cả hai lọt hết 3 dấu hiệu cũ: UA trông như trình duyệt thật (không chứa
token scanner nào), còn `instant_after_send` vô hiệu vì operator bấm "Đã bàn
giao" 10 phút SAU khi nhà mạng đã gửi → lúc quét `handed_off_at` còn NULL.
Hệ quả: báo cáo ghi 22 "người thật" trong khi chỉ ~1 người thật.

⚠ Vì sao KHÔNG chỉ dựa "UA không phải di động": iPadOS 13+ Safari gửi UA
Macintosh, Android bật "Yêu cầu trang máy tính" gửi đúng `X11; Linux x86_64`
như máy quét. Nhãn bot ghi CỨNG lúc ghi click (không tính lại được) và người
bị gắn nhãn sẽ rơi khỏi CẢ CTR lẫn danh sách "đã click" để officer gọi lại
— hỏng nghiệp vụ, không chỉ hỏng số liệu. Vân tay thật của máy quét là
**một UA mở link của NHIỀU người nhận khác nhau trong vài giây**; người thật
dùng máy tính thì lẻ tẻ nên không dính.
"""
from datetime import datetime, timedelta, timezone

from typing import Mapping, Optional, Tuple

from user_agents import parse as parse_user_agent

from app.utils.tz import ensure_aware

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

# Cửa sổ + số người nhận KHÁC tối thiểu (trong CÙNG campaign) để coi là chùm
# quét — tính cả lượt đang xét là ≥4 người trong 60 giây. Chùm thật của nhà
# mạng dày hơn nhiều (campaign #6: 10 người/28 giây) nên vẫn còn rất nhiều
# biên; ngưỡng cao giữ cho người thật dùng máy tính không bị gán nhãn oan.
BURST_WINDOW_SECONDS = 60
BURST_MIN_OTHER_RECIPIENTS = 3

# Fallback khi `user_agents` không parse được (UA rỗng/kỳ dị). Danh sách ngắn
# vì đường chính là thư viện — đừng nuôi thêm token ở đây.
_MOBILE_UA_TOKENS = (
    "mobile", "android", "iphone", "ipad", "ipod", "windows phone",
    "iemobile", "blackberry", "opera mini", "opera mobi", "silk",
)


_aware = ensure_aware  # alias tới helper tz chung (bỏ bản sao logic)


def is_mobile_ua(user_agent: Optional[str]) -> bool:
    """UA là trình duyệt di động (gồm cả tablet) hay không.

    Dùng thư viện `user-agents` (đã là dependency production, cùng thư viện
    `session_service`/`login_history_service` dùng để phân loại thiết bị) →
    một cách hiểu UA duy nhất trong hệ thống, và bắt được cả những dòng máy
    mà danh sách token tự chế bỏ sót (Symbian/Nokia, UCWEB, Fennec…).
    """
    ua = (user_agent or "").strip()
    if not ua:
        return False
    try:
        parsed = parse_user_agent(ua)
        return bool(parsed.is_mobile or parsed.is_tablet)
    except Exception:  # noqa: BLE001 — UA rác không được làm sập /r/
        lowered = ua.lower()
        return any(tok in lowered for tok in _MOBILE_UA_TOKENS)


def detect_bot(
    *,
    user_agent: Optional[str],
    headers: Optional[Mapping[str, str]] = None,
    handed_off_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    mobile_channel: bool = False,
    same_ua_recipients: int = 0,
) -> Tuple[bool, Optional[str]]:
    """Trả (is_bot, reason|None). Ưu tiên reason: UA > prefetch > chùm quét >
    instant.

    `mobile_channel=True` CHỈ cho lượt đến từ tin SMS thật (recipient) — bật
    dấu hiệu `carrier_scan_burst`. Mặc định False để link tư vấn officer /
    phiên landing KHÔNG bị đếm nhầm.
    `same_ua_recipients` = số người nhận KHÁC mà cùng UA này vừa mở link
    trong `BURST_WINDOW_SECONDS` giây (0 = không tra, coi như không có chùm).
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

    if (
        mobile_channel
        and same_ua_recipients >= BURST_MIN_OTHER_RECIPIENTS
        and not is_mobile_ua(user_agent)
    ):
        return True, "carrier_scan_burst"

    if handed_off_at is not None:
        ref = now or datetime.now(timezone.utc)
        if ref - _aware(handed_off_at) <= timedelta(seconds=_INSTANT_SECONDS):
            return True, "instant_after_send"

    return False, None
