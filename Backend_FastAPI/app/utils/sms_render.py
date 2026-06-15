# app/utils/sms_render.py
"""
SMS render + preflight (PR-3): biến template, lắp TIN CUỐI ([QC]+body+optout
+link sentinel), smart-encoding, đo độ dài GSM7/UCS2 + segments, phân loại
nhà mạng theo prefix. Xem SMS_MARKETING_MODULE_DESIGN.md §7.

Đo trên TIN CUỐI (gồm [QC]+optout, sentinel link thay bằng chuỗi cùng độ dài
URL thực) — không đo body trần.
"""
import math
import re
from typing import Dict, List, Set, Tuple

from app.utils.sms_token import (
    CODE_LENGTH,
    LINK_SENTINEL,
    build_link,
    link_placeholder_length,
)

# --- Whitelist biến template (chỉ field cấp contact). Thứ tự strip:
# full_name TRƯỚC name (tránh sót). ---
ALLOWED_TEMPLATE_VARS = ("full_name", "name", "link")
_BRACE_RE = re.compile(r"\{[^{}]*\}")
# Render: chỉ thay đúng 3 token whitelist, 1 lượt (re.sub không re-scan).
_RENDER_RE = re.compile(r"\{(full_name|name|link)\}")
# Tên fallback bắt buộc (§D6) khi tên rỗng/chỉ-sentinel sau sanitize.
NAME_FALLBACK = "Quý phụ huynh/học sinh"

# --- GSM 03.38 basic + extension (ext đếm = 2). Tiếng Việt có dấu → UCS2. ---
_GSM7_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ "
    "!\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = frozenset("^{}\\[~]|€\f")

# --- Smart-encoding: ký tự "thông minh" → tương đương GSM7 (miễn phí) ---
_SMART_SUBS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "―": "-",
    "…": "...", " ": " ", " ": " ",
}


def find_unknown_vars(template: str) -> Set[str]:
    """Tập token `{...}` KHÔNG hợp lệ (rỗng = OK). FAIL-CLOSED: bắt mọi
    `{...}` lạ/dị dạng (`{foo-1}`, `{name!r}`, `{{name}}`, ngoặc lẻ) — sau
    khi gỡ 3 token whitelist, còn bất kỳ `{`/`}` nào đều bị từ chối."""
    stripped = template or ""
    for v in ALLOWED_TEMPLATE_VARS:
        stripped = stripped.replace("{" + v + "}", "")
    if "{" in stripped or "}" in stripped:
        return set(_BRACE_RE.findall(stripped)) or {"{ hoặc } lạ"}
    return set()


def has_link(template: str) -> bool:
    return "{link}" in (template or "")


def smart_encode(text: str) -> str:
    """Thay ký tự smart-quote/dash/NBSP bằng tương đương ASCII (giữ nghĩa)."""
    return "".join(_SMART_SUBS.get(c, c) for c in (text or ""))


def render_body(
    template: str, full_name: str, *, name_fallback: str = NAME_FALLBACK
) -> str:
    """Thay biến đúng 1 lượt (re.sub, KHÔNG re-scan nội dung đã thay):
    {full_name}/{name}→full_name; {link}→sentinel.

    Fail-closed: GỠ literal `__SMS_LINK__` khỏi DỮ LIỆU (template + tên)
    TRƯỚC substitution → sentinel duy nhất trong output là cái CỐ Ý đặt cho
    {link} (chống inject sentinel qua template/tên contact). Tên chứa
    '{link}'/'{name}' cũng KHÔNG bị biến thành sentinel/đệ quy. Tên rỗng
    (sau gỡ sentinel + strip) → dùng name_fallback (tránh tin tên rỗng)."""
    cleaned = (full_name or "").replace(LINK_SENTINEL, "").strip()
    name = cleaned or name_fallback
    safe_template = (template or "").replace(LINK_SENTINEL, "")

    def _repl(m: "re.Match") -> str:
        return LINK_SENTINEL if m.group(1) == "link" else name

    return _RENDER_RE.sub(_repl, safe_template)


def assemble_skeleton(
    template: str,
    full_name: str,
    *,
    optout_instruction: str,
) -> str:
    """TIN CUỐI dạng skeleton: **[QC] luôn có** (advertising NĐ91 Đ15) +
    body(render, smart-encoded) + optout. Link vẫn là sentinel (KHÔNG raw
    code). optout_instruction được build đảm bảo non-rỗng trước khi gọi."""
    body = smart_encode(render_body(template, full_name))
    parts: List[str] = ["[QC]"]
    if body:
        parts.append(body)
    if optout_instruction and optout_instruction.strip():
        # Footer cũng gỡ sentinel (org có thể vô tình đưa __SMS_LINK__ vào).
        footer = smart_encode(optout_instruction.strip()).replace(
            LINK_SENTINEL, ""
        )
        if footer:
            parts.append(footer)
    return " ".join(parts)


def measure(msg: str) -> Tuple[str, int, int, bool]:
    """Trả (encoding, length, segments, is_over_limit). §7.2."""
    msg = msg or ""
    if all((c in _GSM7_BASIC) or (c in _GSM7_EXT) for c in msg):
        encoding = "GSM7"
        n = len(msg) + sum(1 for c in msg if c in _GSM7_EXT)
        per_single, per_multi = 160, 153
    else:
        encoding = "UCS2"
        # UCS-2/UTF-16: ký tự non-BMP (emoji, ord>0xFFFF) = 2 code units.
        n = sum(2 if ord(c) > 0xFFFF else 1 for c in msg)
        per_single, per_multi = 70, 67
    segments = 1 if n <= per_single else math.ceil(n / per_multi)
    return encoding, n, segments, segments > 1


def measure_skeleton(skeleton: str) -> Tuple[str, int, int, bool]:
    """Đo skeleton: thay sentinel bằng chuỗi cùng độ dài URL link thực rồi đo.
    Link là base62 ASCII nên không đổi encoding, chỉ cộng độ dài cố định."""
    final = (skeleton or "").replace(
        LINK_SENTINEL, "X" * link_placeholder_length()
    )
    return measure(final)


def classify_carrier(
    phone_normalized: str, prefix_map: Dict[str, str]
) -> str:
    """Bucket nhà mạng theo 3 ký tự đầu (gồm số 0). Không khớp → 'unknown'.
    CHỈ để khớp format upload (MNP — xem docstring model §4.5)."""
    if not phone_normalized or len(phone_normalized) < 3:
        return "unknown"
    return prefix_map.get(phone_normalized[:3], "unknown")


def skeleton_is_broken(skeleton: str, *, has_link: bool) -> bool:
    """Tin cuối 'hỏng' → loại row (excluded_reason='missing_data', §D6
    "rendered KHÔNG còn placeholder sót"):
    (1) còn BẤT KỲ `{` hoặc `}` nào — kể cả ngoặc LẺ `{foo`/`foo}` (tên/footer
    dị dạng) lẫn `{foo}` cân bằng, hoặc biến render chưa thay; HOẶC (2) còn
    sentinel mà campaign KHÔNG có {link} (sentinel lạ → export không thay được)."""
    sk = skeleton or ""
    if "{" in sk or "}" in sk:
        return True
    if LINK_SENTINEL in sk and not has_link:
        return True
    return False


def preview_message(skeleton: str) -> str:
    """Bản XEM TRƯỚC cho admin (§D6 "5 dòng mẫu"): thay sentinel link bằng URL
    mẫu (đúng host + đúng độ dài code thực) để thấy ~tin cuối. KHÔNG phải tin
    gửi thật — code thật chỉ sinh lúc export (PR-4)."""
    sample = build_link("x" * CODE_LENGTH)
    return (skeleton or "").replace(LINK_SENTINEL, sample)
