# app/services/tuition_export_service.py
"""Xuất danh sách KHOẢN PHÍ theo bộ lọc màn hình "Thu học phí".

Gọi là "khoản phí" chứ không phải "học phí": bộ lọc màn hình không mặc định
lọc loại phí nên tệp có thể gồm cả lệ phí hồ sơ, bảo hiểm…

Vì sao có service này: trước đây muốn lấy bảng "hồ sơ × học phí × đã đóng ×
còn lại" thì phải SSH vào máy chủ chạy SQL tay rồi ghép file — không audit,
không phân quyền, chỉ người giữ khoá SSH làm được.

Hai quyết định định hình toàn bộ file, đừng đổi mà không đọc lý do:

1. **Lọc ở mức hoá đơn, xuất ở mức KHOẢN PHÍ.** Bộ lọc của workspace là
   invoice-centric, nhưng ba cột tiền kế toán cần (học phí / đã đóng / còn lại)
   nằm ở mức ``Fee``. Một khoản phí nhiều đợt có nhiều hoá đơn; xuất theo hoá
   đơn là lặp lại cùng số tiền ⇒ bôi đen cột cộng ra gấp đôi mà không có dấu
   hiệu gì. Nên tập dòng = ``DISTINCT invoice.fee_id``.
   Hệ quả ANY-match (một fee lọt vào nếu ≥1 hoá đơn khớp, nhưng tiền là của cả
   khoản phí) được nói thẳng trong sheet "Thong tin xuat".

2. **Ô tiền là SỐ, không đi qua ``sanitize_csv_cell``.** Danh sách ký tự nguy
   hiểm của helper đó có cả dấu ``-``, nên số âm (hồ sơ đóng dư) sẽ bị thêm dấu
   nháy thành text và Excel không cộng được. Sanitize chỉ áp cho ô TEXT do
   người dùng nhập — xem ``_TEXT_COLUMN_INDEXES``.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.constants.fee_labels import FEE_STATUS_LABELS, FEE_TYPE_LABELS
from app.utils.exceptions import BadRequest
from app.utils.export_builder import SHEET_META, build_simple_export
from app.utils.id_helpers import format_profile_code

__all__ = ["MAX_EXPORT_ROWS", "COLUMNS", "SHEET_DATA", "SHEET_META",
           "build_tuition_export"]

log = structlog.get_logger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Trần dòng mỗi lần xuất. Prod hiện ~400 dòng nên đây là HÀNG RÀO chống truy vấn
# nuốt hết bộ nhớ, không phải chính sách nghiệp vụ.
MAX_EXPORT_ROWS = 10_000

SHEET_DATA = "Danh sach khoan phi"
# SHEET_META tái xuất từ export_builder (một nguồn tên sheet phụ).

COLUMNS: List[str] = [
    "Mã hồ sơ",                 # 0
    "Ngày nhập hồ sơ",          # 1
    "Officer phụ trách",        # 2
    "Họ và tên",                # 3
    "Số CCCD",                  # 4
    "Trình độ ngành đăng ký",   # 5
    "Ngành đăng ký",            # 6
    "Loại phí",                 # 7
    "Năm học",                  # 8
    "Học kỳ",                   # 9
    "Trạng thái khoản phí",     # 10
    "Giá trị khoản phí",        # 11
    "Tổng đã đóng",             # 12
    "Đã miễn giảm",             # 13
    "Số tiền còn lại",          # 14
    "Đơn vị",                   # 15
]

# Ô TEXT do người dùng nhập → phải sanitize (chống chèn công thức vào Excel).
# CỐ Ý không gồm cột tiền: sanitize sẽ biến số âm thành text.
_TEXT_COLUMN_INDEXES = {2, 3, 4, 5, 6, 15}

# Ô cần ép TEXT để giữ số 0 đầu / không bị Excel hiểu thành số.
_FORCE_TEXT_INDEXES = {0, 4, 8}

# Ô tiền — ghi kiểu số + number_format nghìn.
_MONEY_INDEXES = {11, 12, 13, 14}

# Cột "Loại phí" — dùng để phát hiện file trộn nhiều loại.
_FEE_TYPE_COL = 7

_COLUMN_WIDTHS = [12, 18, 22, 26, 16, 20, 30, 18, 12, 10, 22, 18, 20, 16, 18, 20]

# Cảnh báo in vào sheet phụ — người mở file sau vài tuần phải đọc được vì sao
# tổng ở đây có thể khác con số trên màn hình.
_EXPORT_NOTES = (
    (
        "Mỗi dòng là MỘT KHOẢN PHÍ",
        "Ba cột tiền là của cả khoản phí, không phải của riêng một đợt thu.",
    ),
    (
        "Bộ lọc áp ở mức hoá đơn",
        "Một khoản phí có mặt nếu ít nhất một đợt của nó khớp bộ lọc. Vì vậy "
        "tổng cột 'Số tiền còn lại' ở đây có thể KHÁC ô 'Còn phải thu' trên "
        "màn hình (ô đó cộng theo từng đợt).",
    ),
    (
        "Số tiền âm",
        "Là hồ sơ đã đóng dư, giữ nguyên dấu âm chứ không làm tròn về 0.",
    ),
)

_NOT_DECIDED = "(chưa chốt ngành)"
_NO_OFFICER = "(chưa phân công)"


def _fmt_dt(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")


def _row_for(fee: Any) -> List[Any]:
    """Một khoản phí → một dòng. Giữ nguyên kiểu dữ liệu cho ô tiền."""
    profile = fee.admission_profile
    lead = profile.lead if profile else None
    officer = getattr(lead, "assigned_officer", None) if lead else None
    unit = getattr(lead, "unit", None) if lead else None

    degree = fee.resolved_degree_level or _NOT_DECIDED
    major = fee.resolved_major.name if fee.resolved_major else _NOT_DECIDED

    remaining = fee.final_amount - fee.paid_amount - fee.waived_amount

    return [
        format_profile_code(profile.id) if profile else "",
        _fmt_dt(profile.created_at) if profile else "",
        (officer.full_name if officer else "") or _NO_OFFICER,
        (lead.full_name if lead else "") or "",
        profile.citizen_id if profile and profile.citizen_id else "",
        degree,
        major,
        FEE_TYPE_LABELS.get(fee.fee_type, fee.fee_type),
        f"{fee.academic_year}-{fee.academic_year + 1}",
        fee.semester_no if fee.semester_no is not None else "",
        FEE_STATUS_LABELS.get(fee.status, fee.status),
        fee.final_amount,
        fee.paid_amount,
        fee.waived_amount,
        remaining,
        (unit.name if unit else "") or "",
    ]


async def build_tuition_export(
    db: AsyncSession,
    *,
    fmt: str,
    unit_id: Optional[int],
    exporter_name: str,
    applied_filters: Optional[Dict[str, Any]] = None,
    **filters: Any,
) -> Tuple[bytes, str, str]:
    """Dựng file xuất → ``(content, media_type, filename)``.

    ``filters`` nhận đúng bộ tham số lọc của danh sách hoá đơn (xem
    ``InvoiceRepository.get_distinct_fee_ids_for_filter``).

    Vượt trần thì **từ chối**, không cắt bớt: một file bị cắt âm thầm trông y
    hệt một file đủ, người nhận không có cách nào biết.
    """
    invoice_repo = InvoiceRepository(db)
    fee_repo = FeeRepository(db)

    # Lấy MAX+1 trong MỘT truy vấn: đủ để biết có vượt trần không mà không cần
    # cặp count-rồi-fetch (hai câu có khe TOCTOU giữa chúng).
    fee_ids = await invoice_repo.get_distinct_fee_ids_for_filter(
        limit=MAX_EXPORT_ROWS + 1, unit_id=unit_id, **filters
    )
    if len(fee_ids) > MAX_EXPORT_ROWS:
        cap_vn = f"{MAX_EXPORT_ROWS:,}".replace(",", ".")  # 10.000 kiểu VN
        raise BadRequest(
            f"Kết quả lọc vượt quá {cap_vn} dòng cho một lần xuất. "
            "Hãy thu hẹp bộ lọc (năm học / học kỳ / đơn vị / ngành) rồi xuất lại."
        )

    fees = await fee_repo.get_many_for_export(fee_ids)
    rows = [_row_for(fee) for fee in fees]

    # Bộ lọc workspace không mặc định lọc loại phí, nên file có thể trộn học
    # phí với lệ phí xét tuyển / bảo hiểm… Cột "Loại phí" phân biệt được, nhưng
    # ai bôi đen cột tiền mà quên lọc thì cộng nhầm — nên nói thẳng ra.
    fee_type_labels = sorted({row[_FEE_TYPE_COL] for row in rows if row[_FEE_TYPE_COL]})
    notes = list(_EXPORT_NOTES)
    if len(fee_type_labels) > 1:
        notes.insert(
            0,
            (
                "⚠ File gồm NHIỀU LOẠI PHÍ",
                "Kết quả có " + ", ".join(fee_type_labels) + ". Cột tiền là giá "
                "trị của TỪNG khoản phí theo loại của nó — cộng cả cột sẽ trộn "
                "các loại với nhau. Lọc theo cột 'Loại phí' trước khi cộng.",
            ),
        )

    # Ghi cả người xuất: đây là tệp mang dữ liệu cá nhân (họ tên + CCCD của
    # hàng trăm thí sinh), nên tối thiểu phải truy được AI đã tải và tải bao
    # nhiêu dòng. (Chưa dùng audit_service — xem ghi chú ở mô tả PR.)
    log.info(
        "tuition_export_built",
        row_count=len(rows),
        fmt=fmt,
        unit_id=unit_id,
        exporter=exporter_name,
    )

    return build_simple_export(
        columns=COLUMNS,
        rows=rows,
        money_indexes=_MONEY_INDEXES,
        text_indexes=_TEXT_COLUMN_INDEXES,
        force_text_indexes=_FORCE_TEXT_INDEXES,
        fmt=fmt,
        filename_stem="danh_sach_khoan_phi",
        sheet_title=SHEET_DATA,
        exporter_name=exporter_name,
        applied_filters=applied_filters or {},
        column_widths=_COLUMN_WIDTHS,
        notes=notes,
    )
