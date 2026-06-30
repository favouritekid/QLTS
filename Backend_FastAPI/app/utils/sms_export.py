# app/utils/sms_export.py
"""
SMS export (PR-4) helpers: sanitize tên file theo mẫu nhà mạng, render TIN
CUỐI thật (thay sentinel link bằng URL chứa raw code giải mã từ Fernet
ciphertext), và dựng workbook Excel đúng format mẫu (Sheet1, KHÔNG header,
data từ row 2, cột A = 84xxxxxxxxx text, cột B = nội dung text).

Xem SMS_MARKETING_MODULE_DESIGN.md §8.1 / §8.2.
"""
import io
import re
import unicodedata
from typing import Optional, Sequence, Tuple

from openpyxl import Workbook

from app.utils.sms_token import LINK_SENTINEL, build_link, decrypt_code

XLSX_MEDIA = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
# Ký tự không hợp lệ trong tên file (Windows + *nix) → thay '-'.
_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_FILENAME_MAX = 120


def _slug_label(text: str) -> str:
    """Bỏ dấu tiếng Việt + gọn khoảng trắng → nhãn an toàn cho hệ thống nhà
    mạng kén unicode. GIỮ chữ hoa/thường (không lowercase toàn bộ như slug-url)
    để tên file vẫn đọc được."""
    s = unicodedata.normalize("NFD", text or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    s = _BAD_FILENAME_CHARS.sub("-", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def sanitize_export_filename(
    group_label: Optional[str], campaign_name: str, carrier_label: str
) -> str:
    """`{Nhóm}-{Campaign}-{NhàMạng}.xlsx` đã sanitize + ≤120 ký tự. Cắt phần
    tên campaign (giữa) nếu quá dài — giữ nhóm (đầu) + nhà mạng (cuối) để vẫn
    phân biệt được file."""
    grp = _slug_label(group_label or "Nhom") or "Nhom"
    camp = _slug_label(campaign_name) or "Campaign"
    carrier = _slug_label(carrier_label) or "NhaMang"
    stem = f"{grp}-{camp}-{carrier}"
    if len(stem) + 5 > _FILENAME_MAX:  # +5 = ".xlsx"
        keep = _FILENAME_MAX - 5 - len(grp) - len(carrier) - 2  # 2 dấu '-'
        camp = camp[: max(keep, 1)].rstrip("-") or "Campaign"
        stem = f"{grp}-{camp}-{carrier}"
    return f"{stem}.xlsx"[:_FILENAME_MAX]


def render_export_message(
    skeleton: Optional[str],
    *,
    has_link: bool,
    token_ciphertext: Optional[str],
    token_key_version: Optional[str],
) -> Optional[str]:
    """TIN CUỐI THẬT cho file nhà mạng. Campaign có {link}: giải mã code từ
    ciphertext (Fernet) → URL thật → thay sentinel. Trả **None** nếu KHÔNG
    giải mã được (key-ring sai) hoặc tin cuối còn sót sentinel — caller fail
    cả batch thay vì ghi tin hỏng/thiếu link cho nhà mạng."""
    msg = skeleton or ""
    if has_link:
        if not (token_ciphertext and token_key_version):
            return None
        code = decrypt_code(token_ciphertext, token_key_version)
        if not code:
            return None
        msg = msg.replace(LINK_SENTINEL, build_link(code))
    # Bất biến: tin cuối KHÔNG còn sentinel nội bộ.
    if LINK_SENTINEL in msg:
        return None
    return msg


def build_carrier_workbook(rows: Sequence[Tuple[str, str]]) -> bytes:
    """Excel đúng mẫu nhà mạng: Sheet1, KHÔNG header, data từ row 2; cột A =
    84xxxxxxxxx (text), cột B = nội dung SMS (text). rows = [(phone_intl, msg)].

    Nội dung cột B GIỮ NGUYÊN tin cuối (KHÔNG escape CSV-injection): đây là văn
    bản nhà mạng GỬI thật — thêm prefix sẽ sai tin. An toàn vì mọi tin luôn bắt
    đầu bằng `[QC]` (assemble_skeleton, NĐ91) nên không thể mở đầu bằng
    `=`/`+`/`-`/`@` → Excel không diễn dịch thành formula; cột số chỉ chứa
    digit; danh bạ do admin tự nhập (không phải public untrusted)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    r = 2  # row 1 để trống theo mẫu nhà mạng
    for phone_intl, msg in rows:
        a = ws.cell(row=r, column=1, value=phone_intl)
        a.number_format = "@"
        b = ws.cell(row=r, column=2, value=msg)
        b.number_format = "@"
        r += 1
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
