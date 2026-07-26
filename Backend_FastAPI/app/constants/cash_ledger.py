"""NGUỒN SỰ THẬT DUY NHẤT cho "tiền mặt đã ghi nhận" (cash ledger).

Mọi báo cáo tiền trong hệ thống — báo cáo tuần tuyển sinh, Excel tổng hợp năm, sổ
kế toán theo kỳ — phải lấy danh sách loại giao dịch và quy ước dấu TỪ ĐÂY. Trước
khi có file này, cùng một câu hỏi ("thu được bao nhiêu?") được trả lời bằng ba đoạn
code khác nhau và cho ra ba con số:

* báo cáo tuần: tính ``payment`` + ``refund`` + ``reversal``;
* Excel: cùng ba loại nhưng ``JOIN payment`` kiểu INNER nên **rơi** những giao dịch
  không có ``payment_id`` (báo cáo tuần thì vẫn tính, xếp vào "chưa xác định ngành")
  ⇒ hai file người dùng đối chiếu lệch nhau mà không ai thấy;
* sổ kế toán theo kỳ: **bỏ hẳn** ``reversal`` ⇒ một lô thu bị huỷ 50tr vẫn nằm
  trong doanh thu của kỳ.

QUY ƯỚC DẤU (đã kiểm trong code tạo giao dịch): ``payment`` lưu số DƯƠNG;
``refund`` (``payment_service`` ~1180) và ``reversal`` (``payment_import_service``
~1648) lưu số ÂM. Nhờ vậy:

* **net** (tiền thực còn lại) = ``SUM(amount)`` trên cả ba loại — không cần trừ tay;
* **gross** (tiền đã vào) = ``SUM(amount)`` trên ``CASH_INFLOW_TYPES``;
* **tiền trả ra** = ``ABS(SUM(amount))`` trên ``CASH_OUTFLOW_TYPES``.

⚠️ THÊM MỘT LOẠI GIAO DỊCH TIỀN MỚI (vd ``adjustment`` khi bật khấu trừ khoản dư)
thì sửa Ở ĐÂY — mọi báo cáo import từ file này sẽ tự cập nhật. Đừng thêm chuỗi
literal vào SQL/service riêng: đó chính là cách ba con số trên đã drift.
``tests/unit/test_cash_ledger_single_source.py`` khoá điều này.
"""

# Ba loại giao dịch cấu thành tiền mặt đã ghi nhận.
CASH_TRANSACTION_TYPES: tuple[str, ...] = ("payment", "refund", "reversal")

# Tiền VÀO (amount dương).
CASH_INFLOW_TYPES: tuple[str, ...] = ("payment",)

# Tiền RA (amount ÂM): hoàn tiền cho thí sinh, và đảo ghi nhận khi kế toán huỷ lô
# import nhầm. Cả hai đều làm giảm net; chỉ ``refund`` là tiền thật trả ra, còn
# ``reversal`` là sửa sổ — báo cáo nào cần phân biệt thì đọc riêng từng tuple.
CASH_OUTFLOW_TYPES: tuple[str, ...] = ("refund", "reversal")

# TIỀN THẬT TRẢ LẠI THÍ SINH. Dùng cho chỉ tiêu mang nhãn "hoàn tiền" trên giao
# diện (vd ``AccountingPeriod.total_refunds`` → "Tổng hoàn" của kỳ).
# 🔴 ĐỪNG dùng ``CASH_OUTFLOW_TYPES`` cho nhãn đó: nó gồm cả ``reversal``, mà
# reversal chỉ là bút toán đảo một khoản đã ghi thu — gộp vào sẽ báo một khoản
# hoàn chưa từng trả cho ai.
CASH_REFUND_TYPES: tuple[str, ...] = ("refund",)

# Bút toán ĐẢO ghi nhận (huỷ lô import nhầm). Không phải tiền trả ra; nó rút lại
# chính khoản thu đã ghi, nên thuộc về phía TỔNG THU khi tách nhãn.
CASH_REVERSAL_TYPES: tuple[str, ...] = ("reversal",)

# Loại KHÔNG thuộc dòng tiền (giữ để người đọc biết là đã cân nhắc, không phải bỏ
# sót): ``adjustment`` — khấu trừ khoản dư sang khoản phí khác. Nó cộng
# ``fee.paid_amount`` nhưng KHÔNG phải tiền mới vào trường, nên đưa vào net sẽ
# đếm hai lần. Khi nghiệp vụ khoản dư được bật, quyết định lại tại đây.
CASH_EXCLUDED_TYPES: tuple[str, ...] = ("adjustment",)


def sql_in_list(types: tuple[str, ...]) -> str:
    """Render tuple thành literal list cho câu SQL thô: ``('payment', 'refund')``.

    Dùng cho các báo cáo viết bằng ``text()`` để chúng KHÔNG hard-code lại danh
    sách. An toàn: chỉ nhận các hằng trong module này (không có input người dùng).
    """
    return "(" + ", ".join(f"'{t}'" for t in types) + ")"
