"""NGUỒN DUY NHẤT cho "thông tư áp dụng" của từng hồ sơ tuyển sinh.

Từ 03-11-2026, TT 76/2026/TT-BGDĐT thay TT 05/2021/TT-BLĐTBXH. Owner chốt ngày 11-10-2026:

* mỗi hồ sơ mang MỘT thông tư áp dụng, lưu ở cột riêng (``applicable_circular``), không lưu trong snapshot;
* mặc định theo ngày LỊCH GIỜ VIỆT NAM của LẦN NỘP ĐẦU (``draft → submitted`` đầu tiên), không phải lần
  gần nhất — hồ sơ đã nộp trước mốc rồi bị trả về nháp, nộp lại sau mốc, VẪN là TT 05;
* manager/admin đổi tay được, có lý do (endpoint riêng).

Ngày nộp đầu lưu ở ``first_submitted_at`` + nhãn nguồn ``first_submitted_source``. Hồ sơ đã qua bước nộp mà
lịch sử trạng thái không còn hàng nộp mang nhãn ``missing_evidence`` và để NGÀY TRỐNG — không bao giờ lấp
bằng ``updated_at``, ``applicable_circular_set_at`` hay "hôm nay".

Tầng chủ sở hữu việc đóng dấu là ``admission_state_service.transition()`` — nơi duy nhất ghi
``profile.status``. Migration ``v3circ20261011`` giữ bản chép ĐÔNG CỨNG của mốc và của tập trạng thái
(migration không import mã ứng dụng); ``tests/unit/test_admission_circular_constants.py`` khoá hai bản
bằng nhau.
"""

from datetime import date, datetime
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo

TT05_2021 = "TT05_2021"
TT76_2026 = "TT76_2026"
CIRCULARS: tuple[str, ...] = (TT05_2021, TT76_2026)

#: TT 76/2026/TT-BGDĐT Điều 2 — hiệu lực từ ngày 03-11-2026. Mốc so trên NGÀY LỊCH GIỜ VIỆT NAM và GỒM
#: chính ngày ấy: nộp lần đầu lúc 00:00 ngày 03-11 giờ VN (= 17:00Z ngày 02-11) đã là TT 76.
CIRCULAR_CUTOVER_DATE = date(2026, 11, 3)

#: Múi giờ của mốc pháp lý. CỐ Ý không đọc ``settings.TIMEZONE``: cấu hình máy chủ đổi được, ngày hiệu
#: lực của thông tư thì không.
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# --- Nguồn của ngày nộp đầu (``first_submitted_source``) ---
FIRST_SUBMITTED_SOURCE_TRANSITION = "submit_transition"
FIRST_SUBMITTED_SOURCE_HISTORY = "status_history"
FIRST_SUBMITTED_SOURCE_MISSING = "missing_evidence"
FIRST_SUBMITTED_SOURCE_MANUAL = "manual"
FIRST_SUBMITTED_SOURCES: tuple[str, ...] = (
    FIRST_SUBMITTED_SOURCE_TRANSITION,
    FIRST_SUBMITTED_SOURCE_HISTORY,
    FIRST_SUBMITTED_SOURCE_MISSING,
    FIRST_SUBMITTED_SOURCE_MANUAL,
)
#: Nguồn nào mang NGÀY. ``missing_evidence`` là nhãn "đã nộp mà không còn chứng cứ ngày" ⇒ ngày trống.
FIRST_SUBMITTED_SOURCES_WITH_DATE: tuple[str, ...] = (
    FIRST_SUBMITTED_SOURCE_TRANSITION,
    FIRST_SUBMITTED_SOURCE_HISTORY,
    FIRST_SUBMITTED_SOURCE_MANUAL,
)

# --- Nguồn của thông tư (``applicable_circular_source``) ---
CIRCULAR_SOURCE_DEFAULT = "default_first_submit"
CIRCULAR_SOURCE_BACKFILL = "backfill_first_submit"
CIRCULAR_SOURCE_BACKFILL_MISSING = "backfill_missing_evidence"
CIRCULAR_SOURCE_MANUAL = "manual"
CIRCULAR_SOURCES: tuple[str, ...] = (
    CIRCULAR_SOURCE_DEFAULT,
    CIRCULAR_SOURCE_BACKFILL,
    CIRCULAR_SOURCE_BACKFILL_MISSING,
    CIRCULAR_SOURCE_MANUAL,
)

#: Trạng thái CHỈ tới được sau khi đã qua ``submitted``. Từ ``draft`` chỉ đi tới
#: ``{submitted, withdrawn, withdrawal_pending}``, và hai trạng thái sau chỉ về ``withdrawn``/``draft`` ⇒ ba
#: trạng thái ấy là những nơi hồ sơ CHƯA TỪNG nộp có thể đứng. Test tính lại tập này từ
#: ``ALLOWED_TRANSITIONS``; thêm một cạnh như ``DRAFT → REVIEWING`` sẽ làm test đỏ.
POST_SUBMIT_STATUSES: frozenset[str] = frozenset(
    {
        "submitted",
        "resubmitted",
        "approved",
        "rejected",
        "revision_requested",
        "confirmed",
        "overridden",
        "enrolled",
        "reviewing",
        "result_published",
        "admitted",
        "waitlisted",
    }
)

# --- Trạng thái danh mục KV theo thông tư ---
KV_CATALOG_CONFIRMED = "confirmed"
KV_CATALOG_PROVISIONAL = "provisional"
#: Owner chốt 11-10-2026 (Q11 "Cả hai tạm"): danh mục KV xã đang chạy được dựng bằng script theo luật phân
#: loại mặc định rồi chỉnh KV1, chưa được trường xác nhận khớp danh sách chính thức ⇒ hồ sơ của CẢ HAI
#: thông tư hiện dải cảnh báo. Cảnh báo không đổi điểm. Đổi giá trị = sửa mã + review + deploy.
KV_CATALOG_STATUS: Mapping[str, str] = MappingProxyType(
    {
        TT05_2021: KV_CATALOG_PROVISIONAL,
        TT76_2026: KV_CATALOG_PROVISIONAL,
    }
)


def vn_calendar_date(moment: datetime) -> date:
    """Ngày lịch giờ Việt Nam của một thời điểm CÓ múi giờ.

    Thời điểm không múi giờ bị từ chối: ``astimezone()`` trên giá trị ấy ngầm hiểu là giờ máy chủ, nên
    cùng một dòng mã cho hai ngày khác nhau tuỳ máy chạy.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("vn_calendar_date cần thời điểm có múi giờ, nhận %r" % (moment,))
    return moment.astimezone(VN_TZ).date()


def default_circular_for(day: date) -> str:
    """Thông tư mặc định cho một NGÀY LỊCH GIỜ VIỆT NAM của lần nộp đầu."""
    if isinstance(day, datetime):
        # ``datetime`` là lớp con của ``date``: nhận nhầm một thời điểm UTC ở đây là đúng lỗi lệch 7 giờ
        # mà hàm này sinh ra để chặn.
        raise TypeError("default_circular_for nhận NGÀY (date), hãy qua vn_calendar_date() trước")
    return TT76_2026 if day >= CIRCULAR_CUTOVER_DATE else TT05_2021


CIRCULAR_BASIS_STORED = "stored"
CIRCULAR_BASIS_PREDICTED = "predicted"


def circular_effective(stored: "str | None", now: datetime) -> "tuple[str, str]":
    """Thông tư ĐANG ÁP cho hiển thị: ``(mã, căn_cứ)``.

    * Có giá trị lưu (đã nộp, hoặc đã đặt tay) ⇒ giá trị ấy, ``stored``. Hồ sơ đã nộp KHÔNG BAO GIỜ rơi về
      "hôm nay": ràng buộc ``ck_admission_profile_submitted_has_circular`` bảo đảm đã nộp thì có thông tư.
    * Chưa nộp, chưa đặt tay ⇒ dự kiến theo ngày lịch VN của ``now``, ``predicted`` — nộp hôm nay thì sẽ áp.
    """
    if stored is not None:
        return stored, CIRCULAR_BASIS_STORED
    return default_circular_for(vn_calendar_date(now)), CIRCULAR_BASIS_PREDICTED


KV_CATALOG_WARNING_CODE = "kv_catalog_provisional"
_TEN_THONG_TU = {TT05_2021: "TT 05/2021", TT76_2026: "TT 76/2026"}


def kv_catalog_warning(circular: str) -> "dict[str, str] | None":
    """Cảnh báo danh mục KV TẠM cho thông tư ``circular``; ``None`` khi danh mục của thông tư ấy đã xác nhận.

    Mã thông tư lạ ⇒ ``KeyError`` (không đoán "không cảnh báo").
    """
    if KV_CATALOG_STATUS[circular] != KV_CATALOG_PROVISIONAL:
        return None
    return {
        "code": KV_CATALOG_WARNING_CODE,
        "circular": circular,
        "message": (
            "Danh mục khu vực ưu tiên đang dùng cho %s là danh mục TẠM, chưa được nhà trường xác nhận khớp "
            "danh sách chính thức. Kết quả khu vực cần được kiểm lại." % _TEN_THONG_TU[circular]
        ),
    }
