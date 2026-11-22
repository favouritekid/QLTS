# app/services/thcs_school_name.py
"""MỘT nguồn chuẩn hoá tên trường THCS gõ tay (công cụ ghép — đề xuất danh mục THCS Phần B1).

Tên chuẩn hoá là KHOÁ của bảng ghép ``thcs_school_name_mapping`` và là khoá gom nhóm ở màn hình "Ghép trường THCS".
Đổi hàm này = đổi khoá ⇒ các dòng ghép cũ có thể không còn khớp. Đừng sửa mà không đo lại.

Lựa chọn (ghi rõ để owner duyệt):

* Unicode NFC (dạng dựng sẵn) ⇒ "Lê Lợi" gõ kiểu tổ hợp và kiểu dựng sẵn là MỘT tên.
* Chữ thường; dấu câu / ký hiệu (``. , - ( ) / & ' _`` …) thành khoảng trắng; gộp khoảng trắng.
* **GIỮ dấu tiếng Việt**: "Lê Lợi" ≠ "Le Loi" ≠ "Lệ Lợi". Bỏ dấu sẽ gộp nhầm hai trường khác tên (vd "Hoà" / "Hòa"
  là cùng tên nhưng "Hồ" / "Hổ" thì không); Admin gộp các cách gõ không dấu bằng cách ghép nhiều nhóm vào CÙNG một
  trường.
* Bỏ các từ KHÔNG phân biệt trường: "trường", "THCS", "trung học cơ sở" (cả dạng không dấu "truong",
  "trung hoc co so") — chỉ khi đứng thành TỪ RIÊNG.
* KHÔNG bỏ "PT", "DTNT", "PTDTNT", "bán trú", "liên cấp", "THPT", số hiệu: chúng phân biệt trường (trường dân tộc
  nội trú là trường khác, và cờ DTNT ảnh hưởng cách xét KV).
* Bỏ hết mà rỗng (tên chỉ là "Trường THCS") ⇒ dùng dạng chuẩn hoá nhẹ (chưa bỏ từ) — vẫn hiện để Admin thấy.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Final

#: Độ dài tối đa của khoá (cột ``thcs_school_name_mapping.normalized_name`` VARCHAR(255)).
NORMALIZED_NAME_MAX_LEN: Final[int] = 255

_STOP_TOKENS: Final[frozenset[str]] = frozenset({"trường", "truong", "thcs"})
_STOP_PHRASES: Final[tuple[tuple[str, ...], ...]] = (
    ("trung", "học", "cơ", "sở"),
    ("trung", "hoc", "co", "so"),
)
# Mọi ký tự KHÔNG phải chữ / số (Unicode) ⇒ khoảng trắng. ``_`` thuộc ``\w`` nên xử lý riêng.
_NON_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\w]+", re.UNICODE)


def _light(raw: str) -> list[str]:
    text = unicodedata.normalize("NFC", raw).lower().replace("_", " ")
    return _NON_WORD_RE.sub(" ", text).split()


def normalize_thcs_school_name(raw: Any) -> str:
    """Tên gõ tay ⇒ khoá chuẩn hoá. Không phải chuỗi / toàn khoảng trắng ⇒ ``""``."""
    if not isinstance(raw, str):
        return ""
    tokens = _light(raw)
    kept: list[str] = []
    i = 0
    while i < len(tokens):
        phrase = next(
            (p for p in _STOP_PHRASES if tuple(tokens[i : i + len(p)]) == p), None
        )
        if phrase is not None:
            i += len(phrase)
            continue
        if tokens[i] not in _STOP_TOKENS:
            kept.append(tokens[i])
        i += 1
    result = " ".join(kept) or " ".join(tokens)
    return result[:NORMALIZED_NAME_MAX_LEN].strip()
