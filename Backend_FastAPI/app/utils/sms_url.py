# app/utils/sms_url.py
"""
SMS redirect allowlist (PR-5): kiểm host của landing_url/CTA external có thuộc
`SMS_ALLOWED_REDIRECT_DOMAINS` không — chống open-redirect ở `/r/` và landing
(§6.2). Cùng logic `_host_allowed` của campaign validate (PR-3) nhưng tách util
để dùng ở public surface mà không import service.
"""
import re
from urllib.parse import urlparse

from app.config import settings

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
# Host hợp lệ chỉ gồm chữ/số/'.'/'-'. CHẶN backslash, '@', '/', '%', space…
# (urlparse('https://evil.com\\.allowed.com') giữ '\\.' trong host → endswith
# '.allowed.com' lọt allowlist; trình duyệt đổi '\\'→'/' → tới evil.com).
_HOST_RE = re.compile(r"^[a-z0-9.-]+$")


def host_in_allowlist(url: str) -> bool:
    """https + host ∈ allowlist (exact/subdomain); chặn `@`/`\\`, IP literal,
    scheme ≠ https, userinfo, host ký tự lạ. URL rỗng/sai → False (fail-closed)."""
    raw = (url or "").strip()
    if not raw or "@" in raw or "\\" in raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower()
    # Charset host nghiêm ngặt: chặn parser-differential (backslash, IDN raw…).
    if not host or _IP_RE.match(host) or not _HOST_RE.match(host):
        return False
    allowed = [
        d.strip().lower()
        for d in settings.SMS_ALLOWED_REDIRECT_DOMAINS.split(",")
        if d.strip()
    ]
    return any(host == d or host.endswith("." + d) for d in allowed)
