# app/services/admission_pdf_service.py
"""
ReportLab renderer for the official "Giấy báo nhập học" PDF.

Pure, side-effect-free: ``render_enrollment_letter(data)`` takes a plain dict
(the issuance ``data_snapshot``) and returns PDF ``bytes``. No DB, no ORM — so
it is trivially unit-testable and reproducible. The caller (issuance service)
gathers + validates the data, then persists the bytes.

ReportLab was chosen over WeasyPrint for repo consistency (see
``Documents/P0_GDNN_COMPLIANCE_PLAN.md`` PR P0-6) — pure Python, no GTK/Cairo.

LAYOUT — KHUNG CỐ ĐỊNH + VÙNG THẢ NỘI DUNG
------------------------------------------
Giấy báo có một BỘ KHUNG BẤT BIẾN (letterhead · khối ký · quyền lợi · lưu ý ·
footer) mà nhà trường đã chốt, và nội dung động chỉ được sống trong khoảng
trống ở giữa. Vì thế khung được vẽ ở TOẠ ĐỘ TUYỆT ĐỐI lên canvas (các hằng
``_*_MM`` đo trực tiếp từ mẫu), còn phần thân chảy trong một ``Frame`` duy
nhất bọc ``KeepInFrame(mode="shrink")``:

    9.1mm  ┌─ header banner (chiều cao SUY từ tỉ lệ ảnh, không hard-code)
           ├─ VÙNG THẢ NỘI DUNG  ← Frame + KeepInFrame
  192.9mm  ├─ HIỆU TRƯỞNG · chữ ký · họ tên
  233.4mm  ├─ QUYỀN LỢI (đỏ) + 2 gạch đầu dòng + Lưu ý
  291.1mm  └─ footer banner (neo đáy)

``mode="shrink"`` là bảo đảm AN TOÀN: nội dung dài bao nhiêu cũng KHÔNG THỂ
tràn khỏi vùng giữa, nên không có đường nào đè lên chữ ký. Cỡ chữ đặt ở
``_BASE_PT`` (12pt — cỡ công văn) và chỉ tự hạ khi hồ sơ có dữ liệu dài bất
thường.

Trình bày theo THỦ TỤC VĂN BẢN HÀNH CHÍNH VN: chữ Liberation Serif (metric
tương thích Times New Roman — không đóng gói được TNR của Microsoft vì
license), thân văn bản CĂN ĐỀU hai biên, các cặp dữ kiện gộp trên cùng một
dòng như bản Word đang phát.

Being synchronous + CPU-bound, callers in the async stack MUST invoke this via
``anyio.to_thread.run_sync`` / ``run_in_threadpool`` so it does not block the
event loop.
"""

from __future__ import annotations

import io
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Frame,
    KeepInFrame,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

import structlog

from app.constants import enrollment_letter as C
from app.utils.text_helpers import to_bank_transfer_note

log = structlog.get_logger(__name__)

# Nối tiếp hoá phần DỰNG TÀI LIỆU giữa các luồng.
#
# ReportLab giữ registry font TOÀN CỤC (``pdfmetrics``), và mỗi Canvas khi save
# sẽ subset chính TTFont singleton đó. Hai lần phát giấy đồng thời làm hỏng
# bảng glyph của nhau: đo được ~0,4% render ném ``IndexError: list index out of
# range`` (ttfonts.py makeSubset) hoặc ``KeyError`` glyph. Khoá này rẻ so với
# hậu quả: render ~120ms, còn một giấy báo hỏng là văn bản chính thức phải thu
# hồi bằng tay. Nếu sau này cần thông lượng cao hơn thì tách tiến trình render,
# đừng gỡ khoá.
_BUILD_LOCK = threading.Lock()

# --- Font -------------------------------------------------------------------
#
# MỖI stack đăng ký dưới TÊN RIÊNG. Trước đây cả hai stack dùng chung một tên
# ("LetterSerif"), mà ``pdfmetrics.registerFont`` là first-bind-wins: một khi
# tên đã trỏ Liberation thì đăng ký DejaVu lên cùng tên là no-op im lặng. Hệ
# quả là test fallback tưởng đang render DejaVu nhưng thật ra vẫn là Liberation
# thu nhỏ, và fixture không thể trả registry về trạng thái cũ. Tên riêng cho
# mỗi stack làm cả hai vấn đề biến mất — và cũng loại luôn khả năng một luồng
# ghi đè font mà luồng khác đang dùng.
#
# ``scale`` nhân vào MỌI cỡ chữ: DejaVu Serif đặt chữ rộng hơn Liberation ~10%,
# ở cỡ gốc nó đẩy nội dung vượt vùng thả. Hệ số này giữ giấy báo cân đối trên
# cả hai stack.
_FONT_STACKS = [
    {
        "id": "Liberation",
        "dirs": [
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/liberation",
            "/usr/local/share/fonts",
        ],
        "regular": "LiberationSerif-Regular.ttf",
        "bold": "LiberationSerif-Bold.ttf",
        "italic": "LiberationSerif-Italic.ttf",
        "bolditalic": "LiberationSerif-BoldItalic.ttf",
        "scale": 1.0,
    },
    {
        "id": "DejaVu",
        "dirs": [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/dejavu",
            "/usr/local/share/fonts",
        ],
        "regular": "DejaVuSerif.ttf",
        "bold": "DejaVuSerif-Bold.ttf",
        "italic": "DejaVuSerif-Italic.ttf",
        "bolditalic": "DejaVuSerif-BoldItalic.ttf",
        "scale": 0.88,
    },
]

# Stack đang dùng: {"regular","bold","italic","bolditalic","scale","id"}.
# ``_resolve_fonts()`` gán; mọi hàm layout đọc từ đây thay vì hằng toàn cục.
_active_fonts: dict[str, Any] | None = None

# Asset nằm NGOÀI webroot: app/static được mount công khai không auth
# (main.py — "stays public by design" cho avatars), nên chữ ký scan của hiệu
# trưởng + letterhead KHÔNG được đặt ở đó. app/assets không được mount.
_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "letters"
_HEADER_IMG = _ASSET_DIR / "header.png"
_FOOTER_IMG = _ASSET_DIR / "footer.png"
_SIGNATURE_IMG = _ASSET_DIR / "signature.png"

# Cache asset theo tiến trình — CHỈ chứa lần nạp thành công (xem ``_asset``).
_ASSET_CACHE: dict[str, tuple[ImageReader, float, float]] = {}

# --- Palette ----------------------------------------------------------------
# Mực đen tuyệt đối (#000) rất gắt khi in laser; #1A1A1A đọc dịu hơn mà vẫn đủ
# tương phản khi photocopy.
_INK = colors.HexColor("#1A1A1A")
_ACCENT_RED = colors.HexColor("#E62625")  # đỏ letterhead (đo từ mẫu)

# --- Khung cố định (mm tính từ ĐỈNH trang) ----------------------------------
_PAGE_W, _PAGE_H = A4
_HEADER_TOP_MM = 9.1
_HEADER_L_MM, _HEADER_R_MM = 6.2, 202.0
_SLOT_BOT_MM = 192.9  # đáy vùng thả nội dung = đỉnh khối ký
_SLOT_PAD_MM = 3.0  # đệm an toàn trên/dưới vùng thả
_SIGN_TITLE_BASE_MM = 196.4  # baseline "HIỆU TRƯỞNG"
_SIGN_IMG_TOP_MM, _SIGN_IMG_BOT_MM = 201.1, 216.9
_SIGN_NAME_BASE_MM = 224.1
_SIGN_CENTER_X_MM = 157.5
_BENEFIT_TITLE_BASE_MM = 233.4
_BENEFIT_TOP_MM, _BENEFIT_BOT_MM = 239.0, 276.3
_FOOTER_BOT_MM = 291.1
_BODY_L_MM, _BODY_R_MM = 21.0, 188.8  # lề khối văn bản
_CONTENT_W = (_BODY_R_MM - _BODY_L_MM) * mm

_BASE_PT = 12.0  # cỡ chữ thân văn bản hành chính


def _y(mm_from_top: float) -> float:
    """Đổi mm-tính-từ-đỉnh sang toạ độ ReportLab (gốc dưới-trái)."""
    return _PAGE_H - mm_from_top * mm


def _load_asset(path_str: str) -> tuple[ImageReader, float, float] | None:
    """Đọc + GIẢI MÃ SẴN một asset. Không cache (xem ``_asset``).

    ⚠️ ``getRGBData()`` Ở ĐÂY LÀ BẮT BUỘC, ĐỪNG GỠ. ImageReader giải mã LƯỜI:
    lần ``drawImage`` đầu tiên mới decode và GHI vào ``_data`` trên chính
    instance. Instance đó được cache nên DÙNG CHUNG giữa các luồng, mà
    ``render_enrollment_letter`` chạy trên threadpool (``to_thread``) — hai lần
    phát giấy đồng thời lúc cache còn "lạnh" sẽ decode chồng lên nhau.
    Đo thật (250 render đồng thời, process mới mỗi lần): decode lười → hỏng
    13,2%, trong đó có ca PDF VẪN HỢP LỆ nhưng sai 38% pixel letterhead và vẫn
    được sha256 + lưu làm bản phát hành chính thức; decode sẵn ở đây → 0,4%.
    Giải mã xong trước khi đưa vào cache thì mọi luồng sau chỉ ĐỌC.

    ⚠️ PHẠM VI của lớp bảo vệ đó: ``getRGBData()`` chỉ nạp sẵn ``_data``. Với
    ảnh CÓ KÊNH ALPHA, ``drawImage(mask="auto")`` còn dựng thêm ``_dataA`` —
    một ImageReader RIÊNG, dựng LƯỜI ở lần vẽ đầu, tức đúng cái race này quay
    lại. Hiện an toàn vì cả ba asset đều truecolor không alpha (đã đọc IHDR:
    color-type 2). Nhưng thay ``signature.png`` bằng bản nền trong suốt — việc
    rất tự nhiên với chữ ký scan — là mở lại lỗ 13,2% mà không có gì báo. Nếu
    cần alpha thì phải nạp sẵn cả ``_dataA`` ở đây (hoặc bỏ ``mask="auto"``).

    Trả None nếu file thiếu / hỏng / không đọc được — người gọi degrade sang
    nhánh "không có ảnh" thay vì 500 giữa lúc build.
    """
    try:
        if not os.path.isfile(path_str):
            log.warning("enrollment_letter.asset_missing", path=path_str)
            return None
        reader = ImageReader(path_str)
        iw, ih = reader.getSize()
        if not iw or not ih:
            log.warning("enrollment_letter.asset_empty", path=path_str)
            return None
        reader.getRGBData()  # decode NGAY — xem docstring
        return reader, float(iw), float(ih)
    except Exception:
        # Vẫn phát được giấy (thiếu letterhead còn hơn không phát được), nhưng
        # PHẢI để lại dấu vết: một văn bản chính thức thiếu letterhead + chữ ký
        # mà im lặng thì không ai biết để điều tra.
        log.exception("enrollment_letter.asset_unreadable", path=path_str)
        return None


def _asset(path_str: str) -> tuple[ImageReader, float, float] | None:
    """Asset đã giải mã, cache theo tiến trình — CHỈ ghi nhớ lần THÀNH CÔNG.

    Ba asset là file bất biến nướng vào image; không cache thì chúng bị mở +
    giải mã lại ở mọi lần render (header.png 207KB).

    Vì sao là dict tự quản chứ không phải ``lru_cache``: lru_cache ghi nhớ CẢ
    giá trị None. Một lỗi I/O thoáng qua (volume remount lúc deploy, EMFILE lúc
    tải cao) sẽ khiến MỌI giấy báo sau đó mất letterhead + chữ ký VĨNH VIỄN cho
    tới khi restart — đã tái hiện bằng cách inject OSError đúng một lần. Bản vá
    trước chữa bằng ``cache_clear()`` khi gặp None, nhưng thế là đổi bệnh: một
    asset hỏng DAI DẲNG (ca hay xảy ra nhất — quên copy file khi đổi volume)
    làm mỗi lần render thổi bay hai asset LÀNH, biến lỗi tĩnh thành decode lặp
    + log lặp trên từng tờ giấy. Chỉ-ghi-khi-thành-công thì không nhớ thất bại
    mà cũng không đụng vào entry lành.

    Không cần khoá: gán vào dict là thao tác nguyên tử dưới GIL, và hai luồng
    cùng nạp một asset chỉ tốn thêm một lần decode rồi ghi cùng giá trị.
    """
    got = _ASSET_CACHE.get(path_str)
    if got is not None:
        return got
    loaded = _load_asset(path_str)
    if loaded is not None:
        _ASSET_CACHE[path_str] = loaded
    return loaded


def _find_font(dirs: list[str], filename: str) -> str | None:
    for d in dirs:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return p
    return None


def _resolve_fonts() -> dict[str, Any]:
    """Bind stack serif đầu tiên có đủ regular + bold, trả về mô tả stack.

    Idempotent: đã bind rồi thì trả lại ngay. Raise ``RuntimeError`` với thông
    điệp hành động được nếu không stack nào có mặt, để một image thiếu font
    fail ồn ào thay vì âm thầm in tofu (□) cho mọi chữ tiếng Việt.

    ⚠️ Phần BIND chạy dưới ``_BUILD_LOCK`` — cùng khoá bảo vệ ``c.save()``, chứ
    không phải một khoá riêng. ``registered`` được chụp MỘT LẦN ở đầu, nên hai
    render đồng thời ĐẦU TIÊN của một tiến trình cùng thấy "chưa đăng ký" và
    cùng gọi ``registerFont`` vào registry TOÀN CỤC của ReportLab. Hàm đó ghi
    đè chứ không bỏ qua, nên luồng thứ hai thay TTFont singleton ngay dưới chân
    luồng thứ nhất đang subset — đúng triệu chứng hỏng font mà ``_BUILD_LOCK``
    sinh ra để diệt. Giá phải trả: một lần tuần tự hoá mỗi tiến trình (lần bind
    đầu), sau đó nhánh nhanh phía trên trả về không cần khoá.
    """
    if _active_fonts is not None:
        return _active_fonts
    with _BUILD_LOCK:
        # Kiểm lại BÊN TRONG khoá: luồng xếp hàng phía sau có thể đã bind xong.
        if _active_fonts is not None:
            return _active_fonts
        return _bind_font_stack()


def _bind_font_stack() -> dict[str, Any]:
    """Bind stack đầu tiên có đủ regular+bold. Chỉ gọi khi đang giữ
    ``_BUILD_LOCK`` (xem ``_resolve_fonts``)."""
    global _active_fonts

    registered = set(pdfmetrics.getRegisteredFontNames())
    for stack in _FONT_STACKS:
        dirs = stack["dirs"]
        regular = _find_font(dirs, stack["regular"])
        bold = _find_font(dirs, stack["bold"])
        if not (regular and bold):
            continue

        sid = stack["id"]
        names = {
            "regular": f"LetterSerif-{sid}",
            "bold": f"LetterSerif-{sid}-Bold",
            "italic": f"LetterSerif-{sid}-Italic",
            "bolditalic": f"LetterSerif-{sid}-BoldItalic",
        }
        if names["regular"] not in registered:
            pdfmetrics.registerFont(TTFont(names["regular"], regular))
        if names["bold"] not in registered:
            pdfmetrics.registerFont(TTFont(names["bold"], bold))

        # Italic là tuỳ chọn (Debian tách sang gói -extra cho DejaVu). Thiếu
        # thì trỏ về dạng đứng để markup <i> vẫn render thay vì crash.
        italic_path = _find_font(dirs, stack["italic"])
        bold_italic_path = _find_font(dirs, stack["bolditalic"])
        italic = names["regular"]
        bold_italic = names["bold"]
        if italic_path:
            if names["italic"] not in registered:
                pdfmetrics.registerFont(TTFont(names["italic"], italic_path))
            italic = names["italic"]
        if bold_italic_path:
            if names["bolditalic"] not in registered:
                pdfmetrics.registerFont(
                    TTFont(names["bolditalic"], bold_italic_path)
                )
            bold_italic = names["bolditalic"]

        pdfmetrics.registerFontFamily(
            names["regular"],
            normal=names["regular"],
            bold=names["bold"],
            italic=italic,
            boldItalic=bold_italic,
        )
        _active_fonts = {
            "id": sid,
            "regular": names["regular"],
            "bold": names["bold"],
            "italic": italic,
            "bolditalic": bold_italic,
            "scale": float(stack.get("scale", 1.0)),
        }
        return _active_fonts

    searched = sorted({d for s in _FONT_STACKS for d in s["dirs"]})
    raise RuntimeError(
        f"Không tìm thấy font serif nào để render giấy báo (đã tìm {searched}). "
        "Cài 'fonts-liberation' (ưu tiên) hoặc 'fonts-dejavu-core' — xem "
        "Dockerfile."
    )


def _esc(value: Any) -> str:
    """XML-escape a candidate-supplied string before it enters ReportLab
    Paragraph markup (A05 injection defense). None → ''."""
    return _xml_escape("" if value is None else str(value))


def _fmt_vnd(amount: Any) -> str:
    """Format a number as Vietnamese currency: 6500000 -> '6.500.000'."""
    try:
        n = int(round(float(amount)))
    except (TypeError, ValueError):
        return "0"
    return f"{n:,}".replace(",", ".")


def _fmt_date(value: Any) -> str:
    """Format a date/ISO-string as dd/mm/yyyy.

    Chuỗi không parse được sẽ được ESCAPE trước khi trả về: giá trị này đi
    thẳng vào markup Paragraph, nên một ``dob`` lạ chứa '<' sẽ làm vỡ parser
    (hồ sơ đó vĩnh viễn không phát được giấy) và một thẻ ``<img src=.../>``
    thậm chí khiến ReportLab MỞ file trên đĩa. Mọi trường khác đã qua ``_esc``;
    nhánh này từng là lỗ duy nhất.
    """
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    s = str(value)
    try:
        return datetime.fromisoformat(s).strftime("%d/%m/%Y")
    except ValueError:
        return _esc(s)


def _styles(fonts: dict[str, Any]) -> dict[str, ParagraphStyle]:
    """Thang chữ cho thân văn bản. Mọi cỡ đi qua hệ số của stack font."""
    s = fonts["scale"]

    def sz(pt: float) -> float:
        return pt * s

    base = ParagraphStyle(
        "body",
        fontName=fonts["regular"],
        fontSize=sz(_BASE_PT),
        leading=sz(_BASE_PT * 1.32),
        textColor=_INK,
        alignment=TA_JUSTIFY,  # thủ tục văn bản VN: căn đều hai biên
    )
    return {
        "body": base,
        "indent": ParagraphStyle("indent", parent=base, leftIndent=6 * mm),
        "amount": ParagraphStyle(
            "amount", parent=base, alignment=TA_RIGHT, fontName=fonts["bold"]
        ),
        "title": ParagraphStyle(
            "title",
            parent=base,
            fontName=fonts["bold"],
            fontSize=sz(16),
            leading=sz(19),
            alignment=TA_CENTER,
        ),
        "signature_line": ParagraphStyle(
            "signature_line",
            parent=base,
            fontName=fonts["bold"],
            alignment=TA_CENTER,
        ),
    }


def _two_col(left: str, right: str, st: dict, split: float = 0.60) -> Table:
    """Hai vế trên CÙNG một dòng, thẳng cột — thay cho tab của Word
    ("Thí sinh: X    Ngày sinh: Y")."""
    t = Table(
        [[Paragraph(left, st["body"]), Paragraph(right, st["body"])]],
        colWidths=[_CONTENT_W * split, _CONTENT_W * (1 - split)],
        hAlign="LEFT",
    )
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                # Khe BẮT BUỘC giữa hai vế: tên/ngành dài sẽ chạy hết cột trái
                # và dính liền vào "Ngày sinh:" / "Hệ đào tạo:" nếu thiếu.
                ("RIGHTPADDING", (0, 0), (0, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return t


def _money_rows(rows: list[tuple[str, str]], st: dict) -> Table:
    """Các dòng tiền, số căn phải thẳng cột chữ số."""
    data = [
        [Paragraph(lbl, st["body"]), Paragraph(amt, st["amount"])]
        for lbl, amt in rows
    ]
    t = Table(data, colWidths=[_CONTENT_W - 45 * mm, 45 * mm], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 6 * mm),  # thụt như gạch đầu dòng
                ("LEFTPADDING", (1, 0), (1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0.8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
            ]
        )
    )
    return t


def _officer_contact(data: dict) -> str:
    """Phần " — Cán bộ phụ trách: Tên (SĐT)" nối sau hotline chung.

    Hotline trường ĐƯỢC GIỮ (quyết định 20-07): officer nghỉ phép / chuyển việc
    thì thí sinh vẫn còn một đường dây gọi được.

    Thiếu SĐT thì chỉ in TÊN, không in ngoặc rỗng — tại thời điểm làm tính năng
    có 168/355 hồ sơ mà officer chưa khai số trong hệ thống, và một tờ giấy
    chính thức ghi "Cán bộ phụ trách: Nguyễn Văn A ()" đọc như lỗi phần mềm.
    Không officer ⇒ không in gì thêm, dòng hotline vẫn đứng vững một mình.
    """
    name = _esc((data.get("officer_name") or "").strip())
    if not name:
        return "."
    phone = _esc((data.get("officer_phone") or "").strip())
    tail = f" ({phone})" if phone else ""
    return f" — <b>Cán bộ phụ trách:</b> {name}{tail}."


def _fee_lines(data: dict, st: dict) -> list[Any]:
    """Khối học phí — in MỨC CHUẨN của bảng thu Nhà trường.

    Các con số (tổng, mức từng đợt, hạn nộp, tỉ lệ ưu đãi) đã được
    ``build_letter_data`` tra từ ``TUITION_SCHEDULE`` theo mã ngành và đối chiếu
    với Fee, nên ở đây chỉ còn việc trình bày.

    Giấy KHÔNG in phần thí sinh đã nộp trước (quyết định nghiệp vụ 19-07): mọi
    giấy của cùng một ngành in cùng một bảng thu, việc đối trừ tiền giữ chỗ diễn
    ra tại quầy khi thí sinh đến đóng.
    """
    total = max(0, int(data.get("hk1_fee_amount") or 0))
    first = max(0, int(data.get("first_installment") or 0))
    second = max(0, int(data.get("second_installment") or 0))
    discount = max(0, int(data.get("tuition_discount_percent") or 0))
    due1 = _fmt_date(data.get("first_installment_due"))
    due2 = _fmt_date(data.get("second_installment_due"))
    school_year = _esc(data.get("school_year") or C.SCHOOL_YEAR)

    flow: list[Any] = [
        Paragraph(
            f"<b>3. Học phí học kỳ I năm học {school_year}: "
            f"{_fmt_vnd(total)} đồng</b>",
            st["body"],
        )
    ]

    if discount > 0:
        # Ngành ưu đãi: nộp MỘT lần, và chính việc nộp đủ trước hạn là điều kiện
        # hưởng ưu đãi — nên câu chữ phải nói rõ điều kiện, không chỉ in số cuối.
        rows = [
            (
                f"- Ưu đãi giảm {discount}% học phí kỳ I nếu nộp đủ "
                f"đến ngày {due1}",
                f"<b>{_fmt_vnd(first)} đồng</b>",
            )
        ]
    else:
        rows = [
            (f"- Đóng đợt 1 (đến ngày {due1})", f"<b>{_fmt_vnd(first)} đồng</b>")
        ]
        if second > 0:
            rows.append(
                (
                    f"- Đóng đợt 2 (đến ngày {due2})",
                    f"<b>{_fmt_vnd(second)} đồng</b>",
                )
            )
    flow.append(_money_rows(rows, st))

    # Quà tặng nhập học sớm — đặt SAU trọn khối đợt (không chen giữa đợt 1 và
    # đợt 2, vì chen vào đó cắt đứt mạch con số). Áp dụng cho CẢ ngành thu 2 đợt
    # lẫn ngành ưu đãi: mốc xét là cùng một ngày với hạn đợt 1.
    flow.append(
        Paragraph(
            f"<b>- {C.EARLY_ENROLLMENT_BONUS_LABEL}:</b> "
            + C.EARLY_ENROLLMENT_BONUS.format(due=f"<b>{due1}</b>"),
            st["indent"],
        )
    )
    return flow


def _build_body(data: dict, st: dict) -> list[Any]:
    """Nội dung ĐỘNG thả vào vùng trống — lối văn bản hành chính: dòng chảy,
    căn đều, các cặp dữ kiện gộp trên cùng một dòng."""
    # Escape mọi chuỗi do thí sinh cung cấp trước khi vào markup Paragraph
    # (A05): một '&' / '<' / '>' thô làm vỡ parser (→ hồ sơ đó không bao giờ
    # phát được giấy) và một thẻ <img>/<font> dàn dựng có thể chèn nội dung
    # hoặc nạp tài nguyên lạ vào PDF CHÍNH THỨC. Hằng số trường/ngân hàng là
    # nguồn tin cậy.
    full_name = _esc(data.get("full_name"))
    address = _esc(data.get("permanent_address"))
    # Ngành và TRÌNH ĐỘ là hai trường riêng, phải in CẢ HAI: dữ liệu thật có
    # ngành trùng tên giữa hai trình độ (Kế toán, Công nghệ ô tô, Y sỹ đa khoa,
    # Chăn nuôi - Thú y, Công nghệ thông tin), nên chỉ ghi tên ngành là câu chưa
    # xác định — thí sinh không biết mình đỗ Cao đẳng hay Trung cấp.
    # (Comment cũ ở đây khẳng định MajorProgram.name đã gồm trình độ dạng
    # "Cao đẳng Dược" — SAI: kiểm dữ liệu 19-07, tên ngành là "Dược" trần.)
    major = _esc(data.get("major_name"))
    degree = _esc(data.get("degree_level"))
    offering = _esc(data.get("offering_type") or C.DEFAULT_OFFERING_TYPE)
    start_str = _fmt_date(data.get("enrollment_start_date"))
    end_str = _fmt_date(data.get("enrollment_end_date"))

    flow: list[Any] = [
        Paragraph("GIẤY BÁO NHẬP HỌC", st["title"]),
        Spacer(1, 3.5 * mm),
        Paragraph(
            f"{C.SCHOOL_NAME_TITLE} <b>trân trọng thông báo:</b>", st["body"]
        ),
        Spacer(1, 1.2 * mm),
        _two_col(
            f"Thí sinh: <b>{full_name}</b>",
            f"Ngày sinh: {_fmt_date(data.get('dob'))}",
            st,
        ),
        Paragraph(f"Địa chỉ thường trú: {address}", st["body"]),
        # Ngành đứng RIÊNG một dòng, trình độ + hệ gộp dòng dưới.
        #
        # Trước đây ngành dùng chung dòng với trình độ (60% bề rộng), nên tên
        # dài như "Công nghệ thông tin (ứng dụng phần mềm)" bị đẩy xuống dòng
        # thứ hai của ô trái và lệch hẳn khỏi lưới. Nới cột chỉ đẩy ngưỡng đi
        # chứ không bỏ được — tên ngành là dữ liệu, dài bao nhiêu không kiểm
        # soát được. Cho ngành nguyên một dòng thì bố cục ổn định với MỌI độ
        # dài, và TỔNG SỐ DÒNG KHÔNG ĐỔI (trước: ngành+trình độ / hệ = 2 dòng;
        # nay: ngành / trình độ+hệ = 2 dòng) nên không ăn thêm chỗ.
        Paragraph(f"Đã trúng tuyển ngành: <b>{major}</b>", st["body"]),
        _two_col(
            (f"Trình độ: <b>{degree}</b>" if degree else ""),
            f"Hệ đào tạo: {offering}",
            st,
        ),
        Spacer(1, 1.2 * mm),
        Paragraph(
            "Để hoàn tất thủ tục nhập học, đề nghị thí sinh có mặt tại trường "
            "để làm thủ tục:",
            st["body"],
        ),
        Paragraph(
            f"<b>- Thời gian:</b> Từ ngày <b>{start_str}</b> đến hết ngày "
            f"<b>{end_str}</b>.",
            st["indent"],
        ),
        # Địa chỉ chảy TIẾP dòng địa điểm, không xuống dòng riêng: <br/> +
        # thụt đầu dòng cũ tách nó thành một dòng lơ lửng không có nhãn.
        Paragraph(
            f"<b>- Địa điểm:</b> {C.SCHOOL_NAME_TITLE}, {C.LOCATION_ADDRESS}",
            st["indent"],
        ),
        Paragraph(
            f"<b>- Điện thoại hỗ trợ:</b> {C.SUPPORT_PHONE}"
            f"{_officer_contact(data)}",
            st["indent"],
        ),
        Spacer(1, 1.2 * mm),
        Paragraph("Khi đến trường thí sinh vui lòng mang theo:", st["body"]),
        Paragraph("<b>1. Giấy báo nhập học</b> (bản chính)", st["body"]),
        Paragraph(
            "<b>2. Bản sao chứng thực hợp lệ các loại giấy tờ sau:</b>",
            st["body"],
        ),
    ]
    # Danh mục hồ sơ theo TRÌNH ĐỘ. Snapshot đã ghi sẵn danh mục đã in (giấy là
    # official record, mà danh mục có thể đổi giữa các mùa); chỉ tra lại theo
    # trình độ khi render từ dữ liệu không có key đó.
    documents = data.get("required_documents") or C.documents_for_degree(
        data.get("degree_level")
    )
    for line in documents or []:
        flow.append(Paragraph(f"- {str(line).strip()}", st["indent"]))

    flow.extend(_fee_lines(data, st))
    flow.append(Spacer(1, 1.2 * mm))
    flow.append(
        Paragraph(
            "Thí sinh có thể nộp tiền trực tiếp tại trường khi làm thủ tục "
            "nhập học hoặc chuyển khoản theo thông tin sau:",
            st["body"],
        )
    )
    # Nội dung CK: ngân hàng bỏ dấu + giới hạn độ dài, nên in đúng dạng
    # ASCII/rút gọn mà thí sinh sẽ gõ, thay vì tiếng Việt có dấu. Kết quả chỉ
    # gồm [a-zA-Z0-9 ] → an toàn XML theo cấu tạo.
    # Nội dung CK mang MÃ HỒ SƠ, không phải số điện thoại: kế toán đối soát sao
    # kê cần tra ngược ra đúng hồ sơ, mà số điện thoại có thể trùng giữa các
    # thí sinh (anh em dùng chung số) và không tra được trong danh mục hồ sơ.
    # Tiền tố "HS" để con số không bị đọc nhầm thành số khác trên sao kê.
    profile_code = data.get("profile_code") or ""
    bank_note = _esc(
        to_bank_transfer_note(
            f"{data.get('full_name') or ''} {profile_code} "
            "nop hoc phi ky I",
            max_len=90,
        )
    )
    flow.append(
        Paragraph(
            f"- Số tài khoản: <b>{C.BANK_ACCOUNT_NUMBER}</b>. Đơn vị: "
            f"{C.BANK_ACCOUNT_NAME}",
            st["indent"],
        )
    )
    flow.append(Paragraph(f"- Ngân hàng: {C.BANK_NAME}", st["indent"]))
    flow.append(Paragraph(f"- Nội dung: <b>{bank_note}</b>", st["indent"]))
    return flow


def _draw_fixed_frame(c, st: dict, fonts: dict[str, Any]) -> None:
    """Vẽ MỌI thứ cố định ở toạ độ tuyệt đối: letterhead, khối ký, quyền lợi,
    lưu ý, footer. Không phụ thuộc độ dài nội dung động."""
    scale = fonts["scale"]

    # --- header: chiều cao SUY từ tỉ lệ ảnh (đổi ảnh không làm méo/đè) ---
    hdr = _asset(str(_HEADER_IMG))
    if hdr:
        reader, iw, ih = hdr
        w = (_HEADER_R_MM - _HEADER_L_MM) * mm
        h = w * ih / iw
        c.drawImage(
            reader,
            _HEADER_L_MM * mm,
            _y(_HEADER_TOP_MM) - h,
            width=w,
            height=h,
            mask="auto",
        )

    # --- chức danh ---
    c.setFont(fonts["bold"], 11 * scale)
    c.setFillColor(_INK)
    c.drawCentredString(
        _SIGN_CENTER_X_MM * mm, _y(_SIGN_TITLE_BASE_MM), C.SIGNATORY_TITLE
    )

    # --- chữ ký (căn giữa cùng trục với chức danh + họ tên) ---
    sig = _asset(str(_SIGNATURE_IMG))
    if sig:
        reader, iw, ih = sig
        h = (_SIGN_IMG_BOT_MM - _SIGN_IMG_TOP_MM) * mm
        w = h * iw / ih
        c.drawImage(
            reader,
            _SIGN_CENTER_X_MM * mm - w / 2,
            _y(_SIGN_IMG_BOT_MM),
            width=w,
            height=h,
            mask="auto",
        )

    # --- họ tên người ký ---
    c.setFont(fonts["bold"], 11 * scale)
    c.drawCentredString(
        _SIGN_CENTER_X_MM * mm, _y(_SIGN_NAME_BASE_MM), C.SIGNATORY_NAME
    )

    # --- tiêu đề quyền lợi (đỏ, căn giữa trang) ---
    c.setFont(fonts["bold"], 11 * scale)
    c.setFillColor(_ACCENT_RED)
    c.drawCentredString(
        _PAGE_W / 2, _y(_BENEFIT_TITLE_BASE_MM), C.BENEFITS_TITLE
    )
    c.setFillColor(_INK)

    # --- quyền lợi + lưu ý (frame cố định, tự co nếu sửa nội dung dài thêm) ---
    flow = [Paragraph(f"- {b}", st["body"]) for b in C.BENEFITS]
    flow.append(Paragraph(f"<b>Lưu ý:</b> {C.CLOSING_NOTE}", st["body"]))
    fw = (_BODY_R_MM - _BODY_L_MM) * mm
    fh = (_BENEFIT_BOT_MM - _BENEFIT_TOP_MM) * mm
    fr = Frame(
        _BODY_L_MM * mm,
        _y(_BENEFIT_BOT_MM),
        fw,
        fh,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        showBoundary=0,
    )
    fr.addFromList([KeepInFrame(fw, fh, flow, mode="shrink")], c)

    # --- footer: neo ĐÁY, chiều cao suy từ tỉ lệ ảnh ---
    ftr = _asset(str(_FOOTER_IMG))
    if ftr:
        reader, iw, ih = ftr
        h = _PAGE_W * ih / iw
        c.drawImage(
            reader, 0, _y(_FOOTER_BOT_MM), width=_PAGE_W, height=h, mask="auto"
        )


def render_enrollment_letter(data: dict) -> bytes:
    """Render the official admission letter to PDF bytes.

    ``data`` keys: ``full_name``, ``dob``, ``permanent_address``,
    ``major_name``, ``degree_level`` (optional), ``offering_type``,
    ``hk1_fee_amount`` (tổng), ``first_installment`` / ``second_installment`` /
    ``first_installment_due`` / ``second_installment_due`` /
    ``tuition_discount_percent`` (khối tiền, đã tra từ bảng thu ở
    ``build_letter_data``), ``school_year`` (optional → hằng fallback),
    ``enrollment_start_date``, ``enrollment_end_date``, ``phone``.
    """
    fonts = _resolve_fonts()
    st = _styles(fonts)
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    c.setTitle("Giấy báo nhập học")

    _draw_fixed_frame(c, st, fonts)

    # Vùng thả nội dung: từ ĐÁY header (suy từ tỉ lệ ảnh, không hard-code — đổi
    # letterhead cao hơn thì vùng tự lùi xuống thay vì bị banner đè) tới đỉnh
    # khối ký, trừ đệm an toàn hai đầu.
    hdr = _asset(str(_HEADER_IMG))
    if hdr:
        _, iw, ih = hdr
        header_h_mm = (_HEADER_R_MM - _HEADER_L_MM) * ih / iw
    else:
        header_h_mm = 0.0
    slot_top = _HEADER_TOP_MM + header_h_mm + _SLOT_PAD_MM
    slot_bot = _SLOT_BOT_MM - _SLOT_PAD_MM

    fw = _CONTENT_W
    fh = (slot_bot - slot_top) * mm
    frame = Frame(
        _BODY_L_MM * mm,
        _y(slot_bot),
        fw,
        fh,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        showBoundary=0,
    )
    # mode="shrink": nội dung dài bao nhiêu cũng KHÔNG THỂ tràn khỏi vùng giữa
    # → không có đường nào đè lên chữ ký.
    frame.addFromList([KeepInFrame(fw, fh, _build_body(data, st), mode="shrink")], c)

    c.showPage()
    with _BUILD_LOCK:  # xem _BUILD_LOCK: subset font là vùng dùng chung
        c.save()
    return buf.getvalue()
