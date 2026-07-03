"""BIN (Napas) → tên ngân hàng đầy đủ, để hiển thị kèm mã VietQR.

Nguồn DUY NHẤT cho tên ngân hàng (thin-client): FE chỉ render giá trị BE trả,
không tự map BIN→tên. Trường thường dùng 1 ngân hàng cố định nên chỉ cần phủ
các ngân hàng phổ biến; BIN lạ rơi về nhãn "Ngân hàng (BIN xxxxxx)".
"""

BANK_NAMES = {
    "970436": "Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)",
    "970418": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam (BIDV)",
    "970405": "Ngân hàng Nông nghiệp và PTNT Việt Nam (Agribank)",
    "970415": "Ngân hàng TMCP Công thương Việt Nam (VietinBank)",
    "970422": "Ngân hàng TMCP Quân đội (MB)",
    "970407": "Ngân hàng TMCP Kỹ thương Việt Nam (Techcombank)",
    "970416": "Ngân hàng TMCP Á Châu (ACB)",
    "970432": "Ngân hàng TMCP Việt Nam Thịnh Vượng (VPBank)",
    "970423": "Ngân hàng TMCP Tiên Phong (TPBank)",
    "970403": "Ngân hàng TMCP Sài Gòn Thương Tín (Sacombank)",
    "970443": "Ngân hàng TMCP Sài Gòn - Hà Nội (SHB)",
    "970431": "Ngân hàng TMCP Xuất Nhập khẩu Việt Nam (Eximbank)",
    "970426": "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)",
    "970441": "Ngân hàng TMCP Quốc tế Việt Nam (VIB)",
    "970448": "Ngân hàng TMCP Phương Đông (OCB)",
    "970437": "Ngân hàng TMCP Phát triển TP.HCM (HDBank)",
    "970429": "Ngân hàng TMCP Sài Gòn (SCB)",
    "970409": "Ngân hàng TMCP Bắc Á (BacABank)",
    "970425": "Ngân hàng TMCP An Bình (ABBANK)",
    "970412": "Ngân hàng TMCP Đại Chúng Việt Nam (PVcomBank)",
    "970440": "Ngân hàng TMCP Đông Nam Á (SeABank)",
    "970419": "Ngân hàng TMCP Quốc Dân (NCB)",
    "970433": "Ngân hàng TMCP Việt Nam Thương Tín (VietBank)",
    "970438": "Ngân hàng TMCP Bảo Việt (BaoVietBank)",
    "970406": "Ngân hàng TMCP Đông Á (DongABank)",
    "970424": "Ngân hàng Shinhan Việt Nam (Shinhan Bank)",
    "970430": "Ngân hàng TMCP Xăng dầu Petrolimex (PGBank)",
    "970452": "Ngân hàng TMCP Kiên Long (KienLongBank)",
    "970457": "Ngân hàng Woori Việt Nam (Woori Bank)",
    "970454": "Ngân hàng TMCP Bản Việt (BVBank)",
}


def bank_name_from_bin(bin_code: str) -> str:
    """Tên ngân hàng đầy đủ theo BIN; BIN lạ → nhãn fallback."""
    return BANK_NAMES.get(bin_code, f"Ngân hàng (BIN {bin_code})")
