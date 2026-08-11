# app/services/duplicate_review_token.py
"""Phiếu xác nhận nghi trùng do MÁY CHỦ cấp — quyền xác nhận duy nhất.

Trước đây quyền ấy nằm rải khắp nơi: một cờ boolean ở thân yêu cầu, một danh
sách mã phiếu, một con số tổng, một dấu vân do giao diện ghép lại từ hai nguồn
(kết quả xem trước và thân lỗi 409). Mỗi lần vá là thêm một trường và thêm một
chỗ hai bên có thể nói khác nhau — bốn vòng liền, mỗi vòng lộ đúng một khe
kiểu đó.

Ở đây chỉ còn MỘT thứ: một chuỗi mờ có chữ ký. Giao diện không đọc được nó,
không dựng được nó, không ghép nó từ mảnh nào — nó chỉ nhận và gửi trả. Mọi
câu hỏi "xác nhận này có còn đúng không" đều trở thành một phép so chữ ký cộng
một phép so số version, cả hai đều ở máy chủ, cả hai đều dưới khoá.

Ràng buộc nằm TRONG chữ ký, nên một phiếu cấp cho hoàn cảnh này không dùng
được cho hoàn cảnh khác:

  * ``flow``      — ghi tay hay nhập lô (một phiếu của luồng này không mở được
                    cửa cho luồng kia);
  * ``user_id``   — người khác không mượn được;
  * ``unit_id``   — và không mang sang đơn vị khác được;
  * ``fee_id``, ``invoice_id``;
  * ``amount``, ``payment_date`` đã chuẩn hoá — đổi số tiền là đổi hoàn cảnh;
  * ``batch_id``, ``row_no`` khi là nhập lô;
  * ``guard_version`` — ảnh chụp của ``fee.duplicate_guard_version`` lúc cảnh
    báo. Đây là vế chống chen ngang: bất kỳ thứ gì làm đổi tập ứng viên đều
    làm số này tăng (trigger ở tầng cơ sở dữ liệu), nên một phiếu cấp trước đó
    tự hết hiệu lực;
  * ``exp``       — hạn ngắn, vì một xác nhận để quên vài giờ không còn nói
                    được gì về hiện tại;
  * ``jti``       — để lần theo trong log mà không phải in cả phiếu ra.

Khoá ký DẪN XUẤT riêng, không dùng thẳng ``SECRET_KEY`` và tuyệt đối không
dùng khoá của JWT đăng nhập: hai loại chứng từ khác nhau về ý nghĩa và vòng
đời không được ký bằng cùng một khoá — lẫn khoá là mở đường cho một chứng từ
loại này được nhận nhầm ở chỗ chờ loại kia.

Mọi lỗi đều trả về cùng một kết quả "không hợp lệ": chữ ký sai, hết hạn, sai
người, sai khoản phí, thân méo — không phân biệt trong thông báo. Nói rõ "chữ
ký đúng nhưng version cũ" là chỉ đường cho người dò.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app.config import settings
from app.utils.datetime_helpers import vn_calendar_date

#: Hạn của một phiếu. Đủ dài để đọc cảnh báo, soát lại sổ, rồi bấm gửi; đủ
#: ngắn để một tab bỏ quên từ sáng không còn xác nhận được cho buổi chiều.
#: Không phải hàng rào chính (``guard_version`` mới là) — đây là lớp bọc ngoài
#: cho trường hợp tập ứng viên tình cờ không đổi suốt thời gian đó.
TTL_GIAY = 15 * 60

_NHAN_KHOA = b"qlts/duplicate-review-token/v1"


def _khoa_ky() -> bytes:
    """Dẫn xuất khoá riêng từ ``SECRET_KEY``.

    HKDF thu gọn (một vòng HMAC là đủ cho một nhãn cố định): khoá ra khác hẳn
    khoá gốc, nên rò rỉ chữ ký ở đây không nói gì về ``SECRET_KEY``, và một
    chứng từ ký bằng khoá gốc không bao giờ hợp lệ ở đây.
    """
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), _NHAN_KHOA, hashlib.sha256
    ).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _un_b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass(frozen=True)
class RangBuoc:
    """Hoàn cảnh mà một phiếu xác nhận nói về.

    Dùng chung cho cả lúc cấp lẫn lúc soát, nên không có đường nào ký một tập
    trường rồi lại kiểm một tập khác.
    """

    flow: str  # "manual" | "import"
    user_id: int
    unit_id: Optional[int]
    fee_id: int
    invoice_id: Optional[int]
    amount: Decimal
    payment_date: datetime
    guard_version: int
    batch_id: Optional[int] = None
    row_no: Optional[int] = None

    def _than(self) -> dict:
        return {
            "flow": self.flow,
            "uid": self.user_id,
            # `unit_id=None` (admin toàn hệ) và `unit_id=0` phải khác nhau khi
            # so, nên giữ nguyên None chứ không quy về 0.
            "unit": self.unit_id,
            "fee": self.fee_id,
            "inv": self.invoice_id,
            # Chuỗi, không phải số thực: `2000000.00` và `2000000` là cùng một
            # số tiền và phải cho ra cùng một chữ ký, còn JSON float thì vừa
            # mất chính xác vừa phụ thuộc cách máy in số.
            "amt": str(self.amount.quantize(Decimal("0.01"))),
            # NGÀY LỊCH Việt Nam, không phải mốc thời gian chính xác. Đây là
            # đúng hạt mà luật dò trùng dùng (cửa sổ ±N ngày lịch VN), nên nó
            # cũng là hạt đúng để ràng buộc phiếu.
            #
            # Không phải chuyện làm tròn cho tiện: khi giao diện KHÔNG gửi ngày
            # thu, máy chủ lấy `now()`. Ràng buộc theo mốc chính xác thì lần gửi
            # lại có một `now()` khác vài mili giây, phiếu không bao giờ khớp,
            # và người ghi mắc kẹt trong một vòng 409 vô tận. Đã vấp thật: 11 ca
            # dựng dữ liệu chết ở đúng chỗ này.
            #
            # Nới ra tới mức ngày KHÔNG làm hàng rào lỏng đi: hai lần gửi trong
            # cùng một ngày là hai lần mà luật dò trùng vốn coi như nhau, còn
            # vế chống chen ngang nằm ở `gv`.
            "when": vn_calendar_date(self.payment_date).isoformat(),
            "gv": self.guard_version,
            "batch": self.batch_id,
            "row": self.row_no,
        }


def cap_phieu(rang_buoc: RangBuoc, *, now: Optional[datetime] = None) -> str:
    """Cấp một phiếu cho đúng hoàn cảnh ``rang_buoc``."""
    bay_gio = now or datetime.now(timezone.utc)
    than = rang_buoc._than()
    than["exp"] = int(bay_gio.timestamp()) + TTL_GIAY
    than["jti"] = secrets.token_urlsafe(9)

    # `sort_keys` + `separators`: hai lần ký cùng một hoàn cảnh phải cho cùng
    # chuỗi byte, nếu không thì chữ ký phụ thuộc thứ tự khoá của dict.
    raw = json.dumps(than, sort_keys=True, separators=(",", ":")).encode("utf-8")
    chu_ky = hmac.new(_khoa_ky(), raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(chu_ky)}"


def soat_phieu(
    phieu: str,
    rang_buoc: RangBuoc,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Phiếu này có nói đúng về hoàn cảnh ``rang_buoc`` không?

    Fail-closed ở mọi nhánh: thân méo, thiếu khoá, sai kiểu, quá hạn, lệch một
    trường — tất cả đều là ``False``. Không có nhánh nào "gần đúng thì cho qua".
    """
    if not phieu or not isinstance(phieu, str) or phieu.count(".") != 1:
        return False
    phan_than, phan_ky = phieu.split(".")
    try:
        raw = _un_b64(phan_than)
        ky_nhan = _un_b64(phan_ky)
    except Exception:  # noqa: BLE001 — mọi lỗi giải mã đều là "không hợp lệ"
        return False

    ky_dung = hmac.new(_khoa_ky(), raw, hashlib.sha256).digest()
    # `compare_digest`: so từng byte theo thời gian hằng định. Phép so `==`
    # thoát sớm ở byte lệch đầu tiên, và thời gian thoát đó đo được — đủ để dò
    # dần ra một chữ ký hợp lệ.
    if not hmac.compare_digest(ky_nhan, ky_dung):
        return False

    try:
        than = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(than, dict):
        return False

    han = than.get("exp")
    if not isinstance(han, int):
        return False
    bay_gio = now or datetime.now(timezone.utc)
    if int(bay_gio.timestamp()) > han:
        return False

    mong_doi = rang_buoc._than()
    # So TOÀN BỘ tập khoá ràng buộc, không so từng cái một: thêm một trường vào
    # `_than()` mà quên thêm vào phép so là mở lại đúng lớp lỗi mà cả đợt này
    # sinh ra để đóng.
    return all(than.get(k) == v for k, v in mong_doi.items())
