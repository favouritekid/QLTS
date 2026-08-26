"""Kill-switch fail-closed cho hai thao tác kế toán chưa an toàn.

Vì sao tệp này tồn tại
======================

Hai thao tác dưới đây có chung một hình dạng rủi ro: chúng **không đảo ngược
được**, và chúng phụ thuộc vào một phần hệ thống chưa hoàn thiện. Chặn chúng ở
tầng canonical rẻ hơn nhiều so với sửa hậu quả.

⚠️ Kho này là **public**. Mô tả ở đây cố ý dừng ở mức *cơ chế* — vì sao thao tác
nguy hiểm về mặt kỹ thuật. Trạng thái vận hành cụ thể (đã chạy hay chưa, bao
nhiêu bản ghi, đo ngày nào, thiệt hại tới đâu) là hồ sơ nội bộ, giữ NGOÀI repo.

**1. Đóng kỳ kế toán — `close_period`**

``payment_date`` (ngày nghiệp vụ) và ngày ghi sổ là hai trường ĐỘC LẬP, và không
có ràng buộc nào buộc chúng cùng tháng. Đóng kỳ chốt phiếu thu theo kỳ và **kỳ
không mở lại được** — nên mọi phiếu lệch tháng bị chốt nhầm là chốt vĩnh viễn,
không một cảnh báo nào trên đường đi. Đối chiếu hai trường ấy phải xong TRƯỚC
khi đường này mở.

**2. Áp phạt hoá đơn — `apply_penalty`**

Ba callsite tính "còn nợ" **BỎ QUA** ``penalty_amount``, và cả ba đang sống:

* ``routers/fees.py``                     — số "còn nợ" trên màn hình hồ sơ
* ``services/invoice_service.py``         — số tiền trong payload nhắc nợ
* ``services/fee_calculation_service.py`` — recalc quyết định ``status = paid``

Đồng phạt đầu tiên được áp là lúc ba con số đó bắt đầu sai, và cái thứ ba sai
theo kiểu tệ nhất: đánh dấu một hoá đơn còn nợ là đã trả đủ. Hàng rào gỡ được
khi cả ba đi qua một helper chung.

Hai hàng rào này là **tạm thời**, gỡ ở cutover của ADR-003
(``Backend_FastAPI/docs/adr/ADR-003-accounting-period-and-receivable-ledger.md``).

Vì sao cờ mang nghĩa "CHO PHÉP" chứ không phải "KHOÁ"
=====================================================

Cờ tên ``*_ENABLED`` mặc định ``False``: **thiếu biến, gõ sai tên biến, tệp env
không được nạp, container tạo trước khi env đổi** — mọi ca ấy đều rơi về
**chặn**.

Cờ mang nghĩa ngược lại (``*_LOCKED = True``) hỏng đúng ở chỗ đó: gõ sai một
chữ trong tên biến thì Pydantic lấy mặc định ``False``, hàng rào **biến mất
trong im lặng**, và không có phép đo nào ở ngoài phân biệt được "khoá đã gỡ có
chủ đích" với "khoá chưa bao giờ được lắp". Đây chính là hình mẫu lỗi
``docker compose up`` tự tạo thư mục rỗng rồi exit 0.

Vì sao guard nằm ở service chứ không ở router
==============================================

``close_period`` và ``apply_penalty`` mỗi hàm hiện có **đúng một** caller là
router tương ứng (đã ``grep`` toàn ``app/`` lúc viết tệp này). Nhưng đặt guard ở
router thì mọi caller sinh sau — task Celery, script vận hành, router v2, một
lệnh bulk — đều phải **nhớ** thêm hàng rào. Đó là cách đã sót ba lần trong kho
này. Đặt ở service: đường canonical chỉ có một, và nó tự canh.
"""

from typing import Final

from app.config import settings
from app.utils.exceptions import AccountingOperationLocked

# Định danh ổn định đi ra client trong ``public_payload``. Giao diện so bằng
# hằng này, không dò chuỗi tiếng Việt trong ``detail`` — đổi lời nhắn không
# được phép làm hỏng client.
OPERATION_PERIOD_CLOSE: Final[str] = "accounting_period_close"
OPERATION_INVOICE_PENALTY: Final[str] = "invoice_apply_penalty"

# ⚠️ Thông báo đi RA CLIENT: mô tả vì sao khoá, KHÔNG kèm số liệu sổ sách. Một
# tỷ lệ đo được trên sổ thật là thông tin vận hành nội bộ; nó không giúp người
# dùng cuối làm gì, mà lại lộ quy mô và chất lượng dữ liệu tài chính cho bất kỳ
# ai gọi được endpoint.
_PERIOD_CLOSE_DETAIL: Final[str] = (
    "Chức năng Đóng kỳ kế toán đang tạm khoá. Sổ ghi nhận kỳ chưa hoàn thiện: "
    "một phần phiếu thu có ngày nghiệp vụ lệch tháng so với ngày ghi sổ, đóng "
    "kỳ bây giờ sẽ chốt chúng vào sai tháng và không mở lại được."
)

_INVOICE_PENALTY_DETAIL: Final[str] = (
    "Chức năng Áp phạt hoá đơn đang tạm khoá. Ba nơi tính số tiền còn nợ chưa "
    "cộng tiền phạt, nên đồng phạt đầu tiên được áp sẽ làm sai số công nợ và "
    "có thể đánh dấu nhầm hoá đơn là đã thanh toán đủ."
)


def is_period_close_allowed() -> bool:
    """Đóng kỳ kế toán có đang được phép không.

    Đọc ``settings`` tại **thời điểm gọi**, không chụp lại lúc import — nếu
    chụp lúc import thì test không monkeypatch được, và tệ hơn: một tệp import
    sớm sẽ giữ mãi giá trị cũ sau khi cấu hình đổi.

    Truy cập THẲNG thuộc tính, cố ý không dùng ``getattr(..., False)``: cờ đã
    khai trong ``Settings`` nên nhánh mặc định ấy **không bao giờ chạy được** —
    một hàng rào không phép thử nào chạm tới. Đã đo: đổi mặc định của
    ``getattr`` thành ``True`` mà cả 18 ca vẫn xanh, vì ``settings`` luôn có
    thuộc tính nên giá trị mặc định chưa từng được đọc.

    Nếu ngày nào đó cờ bị xoá khỏi ``Settings``, dòng này ném ``AttributeError``
    và thao tác chết ồn ào. Đó vẫn là fail-closed — thao tác KHÔNG chạy — và
    ồn ào thì tốt hơn một mặc định lặng lẽ mà không ai kiểm được.
    """
    return bool(settings.ACCOUNTING_PERIOD_CLOSE_ENABLED)


def is_invoice_penalty_allowed() -> bool:
    """Áp phạt hoá đơn có đang được phép không. Xem ``is_period_close_allowed``."""
    return bool(settings.INVOICE_PENALTY_ENABLED)


def assert_period_close_allowed() -> None:
    """Chặn đóng kỳ khi kill-switch còn bật. Ném ``AccountingOperationLocked`` (409)."""
    if not is_period_close_allowed():
        raise AccountingOperationLocked(
            operation=OPERATION_PERIOD_CLOSE,
            detail=_PERIOD_CLOSE_DETAIL,
            context={"flag": "ACCOUNTING_PERIOD_CLOSE_ENABLED"},
        )


def assert_invoice_penalty_allowed() -> None:
    """Chặn áp phạt khi kill-switch còn bật. Ném ``AccountingOperationLocked`` (409)."""
    if not is_invoice_penalty_allowed():
        raise AccountingOperationLocked(
            operation=OPERATION_INVOICE_PENALTY,
            detail=_INVOICE_PENALTY_DETAIL,
            context={"flag": "INVOICE_PENALTY_ENABLED"},
        )
