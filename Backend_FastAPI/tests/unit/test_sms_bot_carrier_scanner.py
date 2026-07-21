# tests/unit/test_sms_bot_carrier_scanner.py
"""
Unit test dấu hiệu `non_mobile_ua` — chặn máy quét chống spam của nhà mạng.

Bối cảnh (log prod chiến dịch #6, 13-07): 23 lượt vào /r/ thì 20 lượt cùng UA
`X11; Linux x86_64 …Chrome` trong chùm 28 giây (10 người nhận × 2 lượt, 11 IP)
+ 1 lượt `antispam/1.0.0`. Cả hai lọt hết 3 dấu hiệu cũ → báo cáo ghi 22
"người thật" trong khi chỉ ~1 người thật.

Thuần logic, không chạm DB/HTTP.
"""
from datetime import datetime, timedelta, timezone

import pytest

# UA THẬT lấy từ log prod campaign #6.
_UA_CARRIER_SCANNER = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_UA_ANTISPAM = "antispam/1.0.0"
_UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 "
    "Safari/604.1"
)
_UA_ANDROID = (
    "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
)
_UA_DESKTOP_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@pytest.mark.unit
@pytest.mark.parametrize("ua", [_UA_CARRIER_SCANNER, _UA_ANTISPAM])
def test_carrier_scanner_flagged_on_sms_channel(ua):
    """Regression sự cố CTR #6: 2 UA này lọt HẾT 3 dấu hiệu cũ."""
    from app.utils.sms_bot import detect_bot

    # Không bật kênh SMS → vẫn lọt (chứng minh dấu hiệu cũ không đủ).
    is_bot_old, _ = detect_bot(user_agent=ua)
    assert is_bot_old is False

    is_bot, reason = detect_bot(user_agent=ua, mobile_channel=True)
    assert is_bot is True
    assert reason == "non_mobile_ua"


@pytest.mark.unit
@pytest.mark.parametrize("ua", [_UA_IPHONE, _UA_ANDROID])
def test_real_mobile_click_still_human(ua):
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(user_agent=ua, mobile_channel=True)
    assert is_bot is False
    assert reason is None


@pytest.mark.unit
def test_desktop_not_flagged_outside_sms_channel():
    """Link tư vấn officer / phiên landing mở trên máy tính là HỢP LỆ —
    mobile_channel mặc định False nên không đụng tới các luồng đó."""
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(user_agent=_UA_DESKTOP_WINDOWS)
    assert is_bot is False
    assert reason is None


@pytest.mark.unit
def test_known_scanner_ua_takes_priority():
    """UA crawler quen mặt vẫn giữ nhãn cũ (không bị non_mobile_ua nuốt)."""
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(
        user_agent="facebookexternalhit/1.1", mobile_channel=True
    )
    assert is_bot is True
    assert reason == "known_scanner_ua"


@pytest.mark.unit
def test_missing_ua_keeps_own_reason():
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(user_agent=None, mobile_channel=True)
    assert is_bot is True
    assert reason == "no_user_agent"


@pytest.mark.unit
def test_prefetch_header_takes_priority_over_non_mobile():
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(
        user_agent=_UA_CARRIER_SCANNER,
        headers={"sec-purpose": "prefetch;prerender"},
        mobile_channel=True,
    )
    assert is_bot is True
    assert reason == "prefetch_head"


@pytest.mark.unit
def test_instant_after_send_still_works_for_mobile_ua():
    """Dấu hiệu cũ không bị regression: UA mobile nhưng click tức thì sau
    handoff vẫn bị nghi (preview server)."""
    from app.utils.sms_bot import detect_bot

    now = datetime(2026, 7, 13, 7, 39, tzinfo=timezone.utc)
    is_bot, reason = detect_bot(
        user_agent=_UA_IPHONE,
        handed_off_at=now - timedelta(seconds=3),
        now=now,
        mobile_channel=True,
    )
    assert is_bot is True
    assert reason == "instant_after_send"


@pytest.mark.unit
def test_is_mobile_ua_helper():
    from app.utils.sms_bot import is_mobile_ua

    assert is_mobile_ua(_UA_ANDROID) is True
    assert is_mobile_ua(_UA_CARRIER_SCANNER) is False
    assert is_mobile_ua(None) is False
