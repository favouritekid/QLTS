"""Mã tham chiếu phiếu chi hoàn phí.

**1 NGUỒN** cho hai đường vốn dễ trôi dạt khỏi nhau:
  * ``suggested_reference`` mà API trả về để màn Hoàn phí điền sẵn vào ô nhập;
  * giá trị backend tự điền khi kế toán bỏ trống ô đó lúc bấm "Chi tiền".

Hai đường phải sinh ra CÙNG một chuỗi, nếu không thì cái kế toán nhìn thấy trước
khi bấm sẽ khác cái được ghi vào sổ — đúng loại lệch mà người dùng không bao giờ
tự phát hiện ra (ref chỉ lộ ra khi đối soát với ngân hàng, hàng tuần sau).

Dạng: ``HT-<id phiếu hoàn>-<ngày chi YYYYMMDD>`` → ``HT-9-20260729``.
  * ``HT`` = hoàn tiền, phân biệt với ``PT`` (phiếu thu) đang dùng ở
    ``payment.reference_code``;
  * id phiếu hoàn để tra ngược đúng một bản ghi (không trùng, không cần sequence);
  * ngày chi để đối chiếu sao kê theo ngày mà không phải mở lại hệ thống.

Không đặt UNIQUE ở DB: kế toán vẫn được gõ đè mã của ngân hàng/UNC, và một phiếu
chi làm hai lần (hiếm, sau khi đảo) có thể chính đáng dùng lại mã cũ.
"""
from datetime import date, datetime, timezone
from typing import Optional

REFUND_REFERENCE_PREFIX = "HT"


def build_refund_reference(refund_id: int, on: Optional[date] = None) -> str:
    """Sinh mã tham chiếu cho phiếu chi hoàn phí ``refund_id``.

    Args:
        refund_id: id phiếu hoàn.
        on: ngày chi; mặc định hôm nay (UTC — khớp cách toàn hệ thống đóng dấu
            thời gian, xem ``refunded_at``).
    """
    day = on or datetime.now(timezone.utc).date()
    return f"{REFUND_REFERENCE_PREFIX}-{refund_id}-{day:%Y%m%d}"
