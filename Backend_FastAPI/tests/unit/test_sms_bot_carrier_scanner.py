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
def test_carrier_scanner_flagged_when_burst(ua):
    """Regression sự cố CTR #6: 2 UA này lọt HẾT 3 dấu hiệu cũ; chỉ lộ ra khi
    nhìn thấy cùng UA quét link của nhiều người nhận khác trong ít giây."""
    from app.utils.sms_bot import detect_bot

    # Dấu hiệu cũ (không có ngữ cảnh chùm) → vẫn lọt.
    assert detect_bot(user_agent=ua)[0] is False

    is_bot, reason = detect_bot(
        user_agent=ua, mobile_channel=True, same_ua_recipients=9
    )
    assert is_bot is True
    assert reason == "carrier_scan_burst"


@pytest.mark.unit
@pytest.mark.parametrize("ua", [_UA_IPHONE, _UA_ANDROID])
def test_real_mobile_click_still_human(ua):
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(
        user_agent=ua, mobile_channel=True, same_ua_recipients=9
    )
    assert is_bot is False
    assert reason is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "ua",
    [
        _UA_DESKTOP_WINDOWS,
        # iPadOS 13+ Safari tự giới thiệu là Macintosh; Android bật "Yêu cầu
        # trang máy tính" gửi đúng X11/Linux như máy quét. Người thật dùng máy
        # tính KHÔNG được biến thành bot chỉ vì UA — họ sẽ rơi khỏi cả CTR lẫn
        # danh sách officer gọi lại.
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Safari/605.1.15"
        ),
        _UA_CARRIER_SCANNER,
    ],
)
def test_lone_desktop_click_is_not_a_bot(ua):
    """Không có chùm → không gắn nhãn, dù UA là desktop.

    Ngưỡng đếm theo NGƯỜI NHẬN KHÁC trong CÙNG campaign: vài người thật dùng
    Windows (chuỗi UA Chrome desktop đã đóng băng từ bản 120 nên giống hệt
    nhau) bấm trong cùng phút vẫn phải là người thật.
    """
    from app.utils.sms_bot import detect_bot

    for peers in (0, 1, 2):
        is_bot, reason = detect_bot(
            user_agent=ua, mobile_channel=True, same_ua_recipients=peers
        )
        assert is_bot is False, f"{peers} người khác chưa phải chùm"
        assert reason is None


@pytest.mark.unit
def test_burst_ignored_outside_sms_channel():
    """Link tư vấn officer không bật `mobile_channel` → chùm không áp dụng."""
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(
        user_agent=_UA_CARRIER_SCANNER, same_ua_recipients=9
    )
    assert is_bot is False
    assert reason is None


@pytest.mark.unit
def test_known_scanner_ua_takes_priority():
    """UA crawler quen mặt vẫn giữ nhãn cũ (không bị nhãn chùm nuốt)."""
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(
        user_agent="facebookexternalhit/1.1",
        mobile_channel=True,
        same_ua_recipients=9,
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
def test_prefetch_header_takes_priority_over_burst():
    from app.utils.sms_bot import detect_bot

    is_bot, reason = detect_bot(
        user_agent=_UA_CARRIER_SCANNER,
        headers={"sec-purpose": "prefetch;prerender"},
        mobile_channel=True,
        same_ua_recipients=9,
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
def test_burst_threshold_boundary():
    """Ngưỡng = số người nhận KHÁC; 1 người khác vẫn chưa đủ thành chùm."""
    from app.utils.sms_bot import BURST_MIN_OTHER_RECIPIENTS, detect_bot

    assert BURST_MIN_OTHER_RECIPIENTS == 3
    below = detect_bot(
        user_agent=_UA_CARRIER_SCANNER,
        mobile_channel=True,
        same_ua_recipients=BURST_MIN_OTHER_RECIPIENTS - 1,
    )
    at = detect_bot(
        user_agent=_UA_CARRIER_SCANNER,
        mobile_channel=True,
        same_ua_recipients=BURST_MIN_OTHER_RECIPIENTS,
    )
    assert below == (False, None)
    assert at == (True, "carrier_scan_burst")


@pytest.mark.unit
def test_is_mobile_ua_uses_shared_library():
    """Dùng `user-agents` (thư viện đã dùng ở session/login_history) nên bắt
    được cả những dòng máy mà danh sách token tự chế bỏ sót."""
    from app.utils.sms_bot import is_mobile_ua

    assert is_mobile_ua(_UA_ANDROID) is True
    assert is_mobile_ua(_UA_IPHONE) is True
    assert is_mobile_ua(_UA_CARRIER_SCANNER) is False
    assert is_mobile_ua(None) is False
    # Máy cũ / trình duyệt hiếm — token list trước đây bỏ sót.
    assert is_mobile_ua(
        "Mozilla/5.0 (SymbianOS/9.4; Series60/5.0 NokiaN97-1/12.0.024) "
        "AppleWebKit/525 (KHTML, like Gecko) BrowserNG/7.1.12344"
    ) is True
    # Tablet cũng là người thật mở tin.
    assert is_mobile_ua(
        "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    ) is True
