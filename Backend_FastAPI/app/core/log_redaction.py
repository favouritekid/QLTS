# app/core/log_redaction.py
"""MỘT nguồn che dữ liệu cá nhân và token trong LOG — tầng CHỦ SỞ HỮU (V6).

Bất biến
========
Không dòng log nào rời tiến trình (web/gunicorn, celery worker, celery beat)
mang: số CCCD, token nằm trong đường dẫn, giá trị của khoá chứa ``token`` /
``password`` / ``secret``, hay giá trị của các khoá PII đã biết (``phone``,
``email``, ``full_name``, ``citizen_id``…).

Đây là thuộc tính của CỬA RA, không của từng lời gọi log: chỉ cửa ra nhìn thấy
mọi nguồn — khoá đặt tên tuỳ ý, câu lỗi ``"CCCD …"``, ``DETAIL`` của SQL,
traceback, dòng access log. Nên mẫu che chỉ khai MỘT lần ở đây, và mọi cửa ra
dùng chung nó:

1. structlog — processor :func:`redact_event_dict`, đặt SAU
   ``format_exc_info`` (traceback đã thành chuỗi khoá ``exception``).
2. ``logging`` thường — :class:`RedactingFilter` gắn vào handler GỐC (bắt mọi
   logger lan truyền lên root, gồm handler lỗi ``exception_handlers`` ghi
   ``f"{lớp}: {detail}"`` không qua structlog) và handler tệp ``LOG_FILE``.
3. access log — cũng :class:`RedactingFilter`, gắn ở MỨC LOGGER cho
   ``uvicorn.access`` / ``gunicorn.access`` (+ ``.error``) vì gunicorn dựng
   handler riêng với ``propagate=False`` — handler gốc không thấy chúng.
   ``gunicorn.conf.py::post_worker_init`` gọi lại :func:`install_log_redaction`.
4. celery worker + beat — ``app/celery_app.py`` nối tín hiệu ``setup_logging``
   ⇒ :func:`configure_logging` (worker/beat KHÔNG nạp ``app.main``).

Ngoài phạm vi (ghi rõ, không phải sót): ``print()`` và mọi thứ ghi thẳng
stdout/stderr không qua ``logging``; Sentry (nếu bật — ``send_default_pii=False``,
chưa đo); ``error_log`` của nginx (xem ``nginx/nginx.conf``).

Khoảng trống CÓ CHỦ Ý
---------------------
* KHÔNG che chuỗi số trơn 9–12 chữ số: sẽ che nhầm số tiền (≥ 100 triệu), mã
  lô, mã hồ sơ. CCCD chỉ bị che khi đứng sau NHÃN (``CCCD``, ``CMND``,
  ``citizen_id``, ``Citizen ID``) hoặc nằm trong ``Key (…citizen_id…)=(…)``.
* KHÔNG đoán email/SĐT trong câu tự do (không nhãn): chỉ che theo TÊN KHOÁ đã
  biết. Mã hồ sơ / ``profile_id``, mã lỗi / ``error_code``, số tiền được GIỮ
  nguyên để chẩn đoán.

Mọi hàm ở đây KHÔNG được ném: một bộ che hỏng không được làm hỏng request.
"""
from __future__ import annotations

import datetime as _dt
import decimal
import enum
import logging
import re
import uuid
from collections.abc import Mapping, MutableMapping
from typing import Any, Optional, Union

# ---------------------------------------------------------------------------
# MỘT NGUỒN MẪU
# ---------------------------------------------------------------------------

#: Chuỗi thay cho GIÁ TRỊ bị che bên trong một chuỗi (đường dẫn, câu lỗi…).
REDACTED = "<redacted>"
#: Chuỗi thay cho giá trị của một KHOÁ nhạy cảm (giữ như bản H3 cũ).
REDACTED_KEY = "[REDACTED]"

#: Tiền tố đường dẫn mang bí mật ngay sau nó (một đoạn đường dẫn). ``*`` = một
#: đoạn hành động (``/magic-link/<action>/<token>``). Ba tiền tố đầu là mã SMS
#: (PR-5, §11.3); hai tiền tố sau là token xác nhận nhập học / magic-link — phủ
#: cả API (``/api/admissions/confirm/…``, ``/api/v2/admissions/magic-link/…``)
#: lẫn trang FE (``/confirm/…``, ``/magic-link/…``) vì khớp ở BẤT KỲ vị trí nào.
#: ``nginx/nginx.conf`` chép tập này vào ``map`` (nginx không đọc được Python);
#: ``tests/unit/test_che_log_token_nginx.py`` khoá hai bên bằng nhau.
TOKEN_PATH_PREFIXES: tuple[str, ...] = (
    "/r/",
    "/lp/",
    "/api/public/sms/landing/",
    "/confirm/",
    "/magic-link/*/",
)
#: Tập con là route mang mã SMS — ``exception_handlers`` dùng để bỏ ``input``
#: của lỗi 422 trên các route này.
SMS_BEARER_PREFIXES: tuple[str, ...] = TOKEN_PATH_PREFIXES[:3]

#: Đoạn chuỗi trong TÊN khoá ⇒ khoá bí mật (so chuỗi con, như bản H3 cũ ở
#: ``main.py``). ``token`` phủ ``confirm_token``, ``access_token``, ``token_id``…
SECRET_KEY_SUBSTRINGS: frozenset[str] = frozenset({
    "password", "token", "secret", "payload", "authorization",
    "csrf", "access_token", "refresh_token", "mfa_token",
    "api_key", "credit_card", "ssn",
})
#: Tập con dùng cho dạng VĂN BẢN ``khoá=giá trị`` / ``"khoá": "…"``. Không gồm
#: ``payload``/``authorization``/``csrf``: ở dạng văn bản chúng hay là chữ mô tả,
#: che sẽ cắt cụt câu chẩn đoán mà không bảo vệ thêm gì.
SECRET_TEXT_KEY_SUBSTRINGS: tuple[str, ...] = ("token", "password", "secret")

#: Khoá PII — so TÊN ĐẦY ĐỦ (không phân biệt hoa thường), KHÔNG so chuỗi con:
#: ``phone_masked``, ``citizen_id_masked``, ``email_enabled``, ``send_email``,
#: ``skipped_no_phone`` không phải PII và phải giữ nguyên. Danh sách lấy từ các
#: khoá thật đang có trong mã (quét AST lời gọi log + kwarg, 11-10-2026).
PII_KEYS: frozenset[str] = frozenset({
    # CCCD / CMND
    "citizen_id", "new_citizen_id", "citizen_id_full", "cccd", "cmnd",
    "id_number",
    # Số điện thoại
    "phone", "phone_number", "phone_raw", "phone_normalized",
    "phone_international", "destination_phone",
    # Email
    "email", "to_email", "email_to", "user_email", "lead_email",
    "recipient_email", "officer_email", "admin_email", "sent_to_email",
    "destination_email",
    # Họ tên
    "full_name", "lead_full_name",
})

#: Đoạn TÊN CỘT trong ``Key (…)=(…)`` của PostgreSQL ⇒ che phần giá trị. Cột
#: khác (``profile_id``, ``lead_id``…) giữ nguyên để chẩn đoán khoá ngoại.
SQL_PII_COLUMN_STEMS: tuple[str, ...] = (
    "citizen", "cccd", "cmnd", "id_number", "phone", "email", "full_name",
) + SECRET_TEXT_KEY_SUBSTRINGS
_SQL_PII_COLUMN_RE = re.compile("|".join(SQL_PII_COLUMN_STEMS), re.IGNORECASE)

#: Dấu hiệu tham số query mang bí mật — TÊN tham số chứa ``token`` (nginx).
NGINX_QUERY_TOKEN_MARKER = r"[?&][a-z0-9_-]*token[a-z0-9_-]*="


def _slash(fragment: str) -> str:
    """Thoát regex rồi cho mỗi ``/`` khớp cả bản ujson ``\\/`` lẫn bản mã hoá
    URL ``%2F`` (vd ``?next=%2Fconfirm%2F<token>``)."""
    return re.escape(fragment).replace("/", r"(?:\\?/|%2[Ff])")


def _prefix_regex(prefix: str) -> str:
    return _slash(prefix).replace(r"\*", r"[A-Za-z_-]+")


def nginx_token_marker_alternation() -> str:
    """Tập DẤU HIỆU token viết theo cú pháp regex của ``map`` nginx (dùng với
    ``~*``): :data:`TOKEN_PATH_PREFIXES` (``/`` khớp cả ``%2f``) + tham số query
    có tên chứa ``token``. Hằng duy nhất ``nginx/nginx.conf`` phải chép nguyên
    văn; ``tests/unit/test_che_log_token_nginx.py`` so khớp."""
    duong = [
        p.replace("*", "[a-z_-]+").replace("/", "(?:/|%2f)") for p in TOKEN_PATH_PREFIXES
    ]
    return "|".join(duong + [NGINX_QUERY_TOKEN_MARKER])


# (1) token trong đường dẫn — khớp ở bất kỳ vị trí nào, cả dạng ``\/``. Đoạn
# token dừng ở ``/ ? # & " ' \`` khoảng trắng và ``<`` (nên ``<redacted>`` không
# bị che lại — idempotent, vì bản ghi có thể đi qua hai lớp che).
_TOKEN_PATH_RE = re.compile(
    "(" + "|".join(_prefix_regex(p) for p in TOKEN_PATH_PREFIXES) + ")"
    + r"[^\s/?#&\"'\\<>]+"
)

#: Hết DÒNG: xuống dòng THẬT hoặc hết chuỗi. Mọi giá trị "không xác định được
#: điểm kết thúc an toàn" bị che TỚI ĐÂY (che THỪA hơn che THIẾU — V6 vòng 3:
#: dừng ở dấu nháy đầu tiên đã để lộ đuôi giá trị có nháy). V6 vòng 4: KHÔNG
#: còn dừng ở ``\\n`` đã thoát — repr của chuỗi (asyncpg ``'GIA\\n0…'``) mang
#: ``\\n`` NGAY TRONG giá trị nên dừng ở đó để lộ phần sau. Đánh đổi: ở dòng
#: JSON đã render mà processor chưa che (hiếm — processor che giá trị thô
#: trước), lần che ở handler gốc nuốt tới cuối dòng JSON.
_HET_DONG = r"(?=\r|\n|$)"
#: Sau nháy ĐÓNG hợp lệ phải là dấu phân cách — nếu không, nháy ấy nằm TRONG giá trị.
_SAU_NHAY = r"(?=[\s,;&)}\]]|\\[nr\"]|$)"
_DA_CHE_RE = r"(?:<redacted>|\[REDACTED\])"

_TEXT_KEY_ALT = (
    "|".join(re.escape(k) for k in sorted(PII_KEYS, key=len, reverse=True))
    + "|"
    + "|".join(r"[A-Za-z0-9_]*%s[A-Za-z0-9_]*" % s for s in SECRET_TEXT_KEY_SUBSTRINGS)
)
_VALUE = (
    r"(?P<v>"
    # đã che ⇒ giữ nguyên (idempotent — bản ghi có thể qua hai lớp che; sau nó có thể
    # là nháy đóng của chuỗi JSON bao ngoài)
    r"\\?[\"']?" + _DA_CHE_RE + r"\\?[\"']?(?![^\s,;&)}\]\"'\\])"
    # nháy kép / đơn hợp lệ: hiểu ký tự thoát (``\\"``), nháy đóng phải theo sau là phân cách
    r"|\"(?:[^\"\\\r\n]|\\.)*\"" + _SAU_NHAY
    + r"|'(?:[^'\\\r\n]|\\.)*'" + _SAU_NHAY
    # nháy hỏng/lồng (``"Gia "Lap" Ten"``) hoặc đã thoát thêm một lớp (``\\"…``) ⇒ che THỪA tới hết dòng
    + r"|\\?[\"'][^\r\n]*?" + _HET_DONG
    # không nháy
    + r"|[^\s\"'&,;)}\]]+"
    r")"
)
# (2a) dạng ``khoá=giá trị`` (query string, câu log tự do).
_KV_EQ_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?P<k>%s)(?P<sep>\s*=\s*)%s" % (_TEXT_KEY_ALT, _VALUE)
)
# (2b) dạng khoá CÓ NGOẶC rồi ``:`` (JSON / repr của dict).
_KV_QUOTED_RE = re.compile(
    r"(?i)(?P<q>\\?[\"'])(?P<k>%s)(?P=q)(?P<sep>\s*:\s*)%s" % (_TEXT_KEY_ALT, _VALUE)
)
# (3) CCCD sau nhãn: "CCCD 0…", "Citizen ID 0…", "citizen_id=0…", "cccd": "0…".
_CCCD_LABEL_RE = re.compile(
    r"(?i)(?P<lbl>(?:cccd|cmnd|citizen[ _-]?id)\W{0,5}?)(?P<num>\d{9,})(?!\d)"
)
# (4) DETAIL của PostgreSQL: ``Key (citizen_id, academic_year)=(0…, 2026)`` —
# unique (``already exists``), khoá ngoại (``is not present`` / ``is still
# referenced``), tạo index (``is duplicated``) và exclusion constraint, nơi
# nhóm THỨ HAI viết thường: ``… conflicts with existing key (…)=(…)``.
#  Giá trị có thể chứa ngoặc / nháy / dấu phẩy (``(Gia (Lap) Ten, 0…)``) ⇒ nhóm giá
#  trị kết thúc ở ``)`` ngay trước một ĐUÔI PostgreSQL đã biết, hoặc ``)``/``).``
#  cuối dòng. Không thấy đuôi nào (dòng cụt) mà cột là PII ⇒ ``_SQL_KEY_CUT_RE`` che
#  tới hết dòng.
_KEY_DUOI = r" (?:already exists|is not present|is still referenced|is duplicated|conflicts with)"
_SQL_KEY_RE = re.compile(
    r"(?<![A-Za-z_])(?P<head>[Kk]ey \((?P<cols>[^=]*?)\)=\()(?P<vals>.*?)"
    r"(?P<tail>\)(?=" + _KEY_DUOI + r"|\.?(?:\\r|\\n|\r|\n|$|(?<!\\)\")))"
)
#  Chỉ khớp khi TÊN CỘT là PII — khớp cả khoá không-PII thì nó nuốt tới hết dòng
#  và che mất một ``Key (phone)=(…`` cụt đứng sau trên cùng dòng.
_SQL_KEY_CUT_RE = re.compile(
    r"(?<![A-Za-z_])(?P<head>[Kk]ey \((?P<cols>[^=)]*?(?:%s)[^=]*?)\)=\()"
    r"(?!<redacted>\))(?P<vals>[^\r\n]*?)" % "|".join(SQL_PII_COLUMN_STEMS)
    + _HET_DONG,
    re.IGNORECASE,
)
# (5) tham số bind trong câu lỗi SQLAlchemy: ``[parameters: ('Nguyen…', '0…')]``.
_SQL_PARAMS_RE = re.compile(
    r"\[parameters: .*?\](?=\\r|\\n|\r|\n|$|\s*\(Background)"
)
# (6) mật khẩu trong URL: ``redis://:pw@host``, ``postgresql://u:pw@host``.
_URL_CRED_RE = re.compile(
    r"(?P<pre>\b[A-Za-z][A-Za-z0-9+.-]*:\\?/\\?/[^:/\s@\"']*:)[^@\s]+?@"
)

# (7) Thông báo PostgreSQL 16 / asyncpg NHÚNG GIÁ TRỊ ĐẦU VÀO (bảng quyết định
# che / không che + lý do: báo cáo V6 vòng 2). Dấu nháy kép có thể ở dạng thoát
# JSON ``\"`` khi dòng đã qua renderer ⇒ ``(?P<q>\\?")`` + ``(?P=q)``.
#
# (7a) ``DETAIL: Failing row contains (…)`` — vi phạm CHECK / NOT NULL / ràng
# buộc phân vùng: PG in NGUYÊN hàng (mọi cột: CCCD, họ tên, email, SĐT…), không
# kèm tên cột ⇒ không giữ chọn lọc được ⇒ che TOÀN BỘ nhóm. Ưu tiên cắt tới
# mốc cấu trúc kế tiếp (``[SQL:`` / ``HINT:`` / ``CONTEXT:`` / ``(Background``)
# để phủ cả giá trị có xuống dòng; không có mốc thì che tới HẾT DÒNG — kể cả khi
# dòng bị cắt cụt không còn ngoặc đóng. KHÔNG dừng ở dấu nháy (V6 vòng 3: giá trị
# JSON/chuỗi có nháy từng làm lộ đuôi hàng). Đánh đổi: phần chữ sau hàng lỗi trên
# CÙNG dòng (vd " khi lưu hồ sơ") cũng bị che.
_PG_FAILING_ROW_RE = re.compile(
    r"Failing row contains \((?:"
    r"(?P<da><redacted>\)\.?)"
    r"|(?P<moc>.{0,8000}?\)\.?(?=(?:\\r|\\n|\r|\n)+(?:\[SQL:|HINT:|CONTEXT:|\(Background)))"
    # V6 vòng 4: không có mốc ⇒ che tới HẾT CHUỖI (giá trị có xuống dòng THẬT,
    # vd "Failing row contains (4242, GIA\n0…, …)." từng lộ dòng thứ hai).
    r"|(?P<dong>.*)"
    + r")",
    re.S,
)
# (7b) ``<nhãn>: "<giá trị>"`` — kiểu dữ liệu sai (``invalid input syntax for
# type integer: "…"``), enum sai, ngày giờ ngoài miền, hex sai.
_PG_NHAN_GIA_TRI_RE = re.compile(
    r"(?P<head>(?:invalid input syntax for(?: type)? [^:\r\n\"]{1,80}"
    r"|invalid input value for enum [^:\r\n\"]{1,80}"
    r"|date/time field value out of range"
    r"|invalid hexadecimal digit): )(?P<q>\\?\")(?!<redacted>(?P=q))(?P<v>[^\r\n]*?)"
    + _HET_DONG
)
# (7c) ``<từ> "<giá trị>" <đuôi>`` — ``value "…" is out of range for type …``,
# ``invalid value "…" for "…"``, ``time zone "…" not recognized``.
_PG_GIA_TRI_GIUA_RE = re.compile(
    r"(?P<head>(?:\bvalue|\binvalid value|\btime zone) )(?P<q>\\?\")(?P<v>.*?)(?P=q)"
    r"(?P<tail> (?:is out of range|for |not recognized))"
)
# (7d) asyncpg (phía client): ``invalid input for query argument $2: '…' (…)``
# — giá trị là repr của tham số bind ⇒ che TỚI HẾT DÒNG (mất cả lý do — chấp nhận;
# V6 vòng 3: repr có ``\\'`` đã thoát thêm một lớp làm lộ đuôi nếu dừng ở nháy).
_ASYNCPG_THAM_SO_RE = re.compile(
    r"(?P<head>invalid input for query argument \$\d+: )(?!<redacted>)(?P<v>[^\r\n]*?)"
    + _HET_DONG
)
# (7e) JSON đầu vào: ``DETAIL: Token "…" is invalid.`` + ``CONTEXT: JSON data,
# line N: <nội dung>`` (nội dung JSON người dùng gửi).
_PG_JSON_TOKEN_RE = re.compile(r"(?P<head>\bToken )(?P<q>\\?\")(?P<v>.*?)(?P=q)(?P<tail> is invalid)")
_PG_JSON_DONG_RE = re.compile(
    r"(?P<head>JSON data, line \d+: )(?!<redacted>)(?P<v>[^\r\n]*?)" + _HET_DONG
)
# (7f) giá trị tham số bind trong CONTEXT/DETAIL: ``unnamed portal parameter
# $1 = '…'`` (log_parameter_max_length_on_error) và ``parameters: $1 = '…'``.
_PG_THAM_SO_BIND_RE = re.compile(r"(?P<head>\$\d+ = )(?P<v>'(?:[^']|'')*')")
# (7g) ``CONTEXT: COPY bảng, line N, column c: "…"`` (hoặc cả dòng COPY).
_PG_COPY_RE = re.compile(
    r"(?P<head>COPY [^,\r\n]{1,128}, line \d+(?:, column [^:\r\n]{1,128})?: )"
    r"(?P<q>\\?\")(?!<redacted>(?P=q))(?P<v>[^\r\n]*?)" + _HET_DONG
)

_DA_CHE = (REDACTED, REDACTED_KEY)


def _thay_nhan_nhay(m: "re.Match[str]") -> str:
    """Giữ nhãn + dấu nháy (+ đuôi nếu có), thay thân giá trị."""
    tail = m.groupdict().get("tail") or ""
    return m.group("head") + m.group("q") + REDACTED + m.group("q") + tail


def _redact_postgres(s: str) -> str:
    s = _PG_FAILING_ROW_RE.sub("Failing row contains (" + REDACTED + ").", s)
    s = _PG_NHAN_GIA_TRI_RE.sub(_thay_nhan_nhay, s)
    s = _PG_GIA_TRI_GIUA_RE.sub(_thay_nhan_nhay, s)
    s = _ASYNCPG_THAM_SO_RE.sub(lambda m: m.group("head") + REDACTED, s)
    s = _PG_JSON_TOKEN_RE.sub(_thay_nhan_nhay, s)
    s = _PG_JSON_DONG_RE.sub(lambda m: m.group("head") + REDACTED, s)
    s = _PG_THAM_SO_BIND_RE.sub(lambda m: m.group("head") + "'" + REDACTED + "'", s)
    s = _PG_COPY_RE.sub(_thay_nhan_nhay, s)
    return s


def _thay_kv(m: "re.Match[str]") -> str:
    """Giữ khoá + phân cách; thay CẢ giá trị (kể cả phần bị che thừa tới hết dòng)
    bằng ``<redacted>`` trong đúng kiểu nháy mở đầu."""
    v = m.group("v")
    if v.strip("\\\"'") in _DA_CHE:
        return m.group(0)
    nhay = "\\\"" if v.startswith("\\\"") else (v[0] if v[0] in "\"'" else "")
    return m.group(0)[: m.start("v") - m.start(0)] + nhay + REDACTED + nhay


def _thay_sql_key(m: "re.Match[str]") -> str:
    if not _SQL_PII_COLUMN_RE.search(m.group("cols")):
        return m.group(0)
    return m.group("head") + REDACTED + m.group("tail")


def _thay_sql_key_cut(m: "re.Match[str]") -> str:
    """``Key (cột PII)=(`` không tìm được đuôi ⇒ che tới hết dòng."""
    if not _SQL_PII_COLUMN_RE.search(m.group("cols")):
        return m.group(0)
    return m.group("head") + REDACTED + ")"


def redact_text(text: str) -> str:
    """Áp MỌI mẫu che lên một chuỗi. Idempotent; không bao giờ ném."""
    if not isinstance(text, str) or not text:
        return text
    try:
        s = _SQL_PARAMS_RE.sub("[parameters: " + REDACTED + "]", text)
        s = _SQL_KEY_RE.sub(_thay_sql_key, s)
        s = _SQL_KEY_CUT_RE.sub(_thay_sql_key_cut, s)
        s = _redact_postgres(s)
        s = _TOKEN_PATH_RE.sub(lambda m: m.group(1) + REDACTED, s)
        s = _URL_CRED_RE.sub(lambda m: m.group("pre") + REDACTED + "@", s)
        s = _KV_QUOTED_RE.sub(_thay_kv, s)
        s = _KV_EQ_RE.sub(_thay_kv, s)
        s = _CCCD_LABEL_RE.sub(lambda m: m.group("lbl") + REDACTED, s)
        return s
    except Exception:  # noqa: BLE001 — bộ che không được làm hỏng log
        return REDACTED


def is_sensitive_key(key: Any) -> bool:
    """Khoá có phải nhạy cảm theo TÊN không (PII đầy đủ hoặc chứa đoạn bí mật)."""
    if not isinstance(key, str):
        return False
    k = key.lower()
    return k in PII_KEYS or any(s in k for s in SECRET_KEY_SUBSTRINGS)


_SCALAR_AN_TOAN = (
    bool, int, float, type(None), decimal.Decimal, uuid.UUID,
    _dt.date, _dt.datetime, _dt.time, _dt.timedelta,
)
_SAU_TOI_DA = 8


def redact_value(value: Any, _sau: int = 0, _loi_csdl: Optional[BaseException] = None) -> Any:
    """Che một giá trị bất kỳ (đệ quy dict/list/tuple/set).

    Đối tượng lạ (ngoại lệ, model…) thành chuỗi rồi che — renderer JSON vốn
    cũng ``repr()`` chúng, và chuỗi ấy có thể mang ``DETAIL`` SQL.
    ``_loi_csdl``: lỗi CSDL đang xử lý — mọi chuỗi (kể cả lồng trong dict/list)
    được thay phần nội suy từ nó trước khi che regex (V6 vòng 4).
    """
    if isinstance(value, str):
        if _loi_csdl is not None:
            return thay_loi_csdl_trong_chuoi(value, _loi_csdl)
        return redact_text(value)
    if isinstance(value, enum.Enum) or isinstance(value, _SCALAR_AN_TOAN):
        return value
    if isinstance(value, BaseException):
        return mo_ta_loi(value)
    if _sau >= _SAU_TOI_DA:
        return redact_value(repr(value), _sau, _loi_csdl)
    if isinstance(value, Mapping):
        return {
            k: (REDACTED_KEY if is_sensitive_key(k) else redact_value(v, _sau + 1, _loi_csdl))
            for k, v in value.items()
        }
    if isinstance(value, (list, set, frozenset)):
        return [redact_value(v, _sau + 1, _loi_csdl) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_value(v, _sau + 1, _loi_csdl) for v in value)
    return redact_value(repr(value), _sau, _loi_csdl)


# ---------------------------------------------------------------------------
# LỖI CSDL — NGỪNG GHI NỘI DUNG (V6 vòng 4, owner chốt 12-10-2026)
# ---------------------------------------------------------------------------
# Lỗi PostgreSQL / asyncpg / SQLAlchemy mang GIÁ TRỊ trong thông điệp (DETAIL
# hàng lỗi, khoá trùng, tham số bind, repr đầu vào, ``[parameters: …]``) dưới
# vô số dạng — regex không đuổi kịp (F30 lộ lại ở cả ba vòng trước). Nên với lỗi
# CSDL, MỌI cửa ra chỉ ghi TÓM TẮT dựng từ THUỘC TÍNH của ngoại lệ: loại lỗi,
# SQLSTATE, tên ràng buộc, schema/bảng/cột — KHÔNG thông điệp, KHÔNG DETAIL,
# KHÔNG câu SQL, KHÔNG tham số. Các regex ở trên GIỮ làm LỚP PHỤ cho chuỗi đã
# nội suy sẵn mà ta không biết là lỗi CSDL.
#
# Đánh đổi chẩn đoán: MẤT giá trị gây lỗi (hàng / khoá / tham số), câu SQL và
# chữ của thông báo PostgreSQL. CÒN: loại lỗi theo cả chuỗi (vd
# ``IntegrityError<-CheckViolationError``), SQLSTATE, tên ràng buộc, bảng/cột,
# khung traceback (tệp/dòng/hàm), và mọi trường ngữ cảnh của lời gọi log
# (``profile_id``, mã lỗi…).

#: (nhãn trong tóm tắt, các tên thuộc tính có thể mang nó — asyncpg / adapter SA)
_THUOC_TINH_CSDL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sqlstate", ("sqlstate", "pgcode")),
    ("constraint", ("constraint_name",)),
    ("schema", ("schema_name",)),
    ("table", ("table_name",)),
    ("column", ("column_name",)),
)
_DINH_DANH_AN_TOAN = re.compile(r"[^A-Za-z0-9_.$-]")
_CHUOI_TOI_DA = 16


def _la_loi_csdl_don(e: BaseException) -> bool:
    """MỘT ngoại lệ (không xét chuỗi) có phải lỗi CSDL: ``sqlalchemy.exc.
    StatementError`` (gồm ``DBAPIError`` và lớp con), mọi ngoại lệ của
    ``asyncpg`` (``PostgresError`` + lỗi phía client như ``DataError``), và lỗi
    của adapter DBAPI trong ``sqlalchemy.dialects.*``."""
    try:
        from sqlalchemy.exc import StatementError

        if isinstance(e, StatementError):
            return True
    except Exception:  # noqa: BLE001 — thiếu SQLAlchemy thì xét theo module
        pass
    mod = type(e).__module__ or ""
    return mod == "asyncpg" or mod.startswith(("asyncpg.", "sqlalchemy.dialects."))


def _chuoi_ngoai_le(exc: BaseException) -> list:
    """Mọi ngoại lệ liên quan: chính nó, ``__cause__``, ``__context__`` và
    ``.orig`` của SQLAlchemy — đệ quy, không lặp, có trần."""
    kq: list = []
    da_xet: set = set()
    hang = [exc]
    while hang and len(kq) < _CHUOI_TOI_DA:
        e = hang.pop(0)
        if not isinstance(e, BaseException) or id(e) in da_xet:
            continue
        da_xet.add(id(e))
        kq.append(e)
        for tiep in (getattr(e, "orig", None), e.__cause__, e.__context__):
            if isinstance(tiep, BaseException):
                hang.append(tiep)
    return kq


def loi_csdl_trong_chuoi(exc: Any) -> list:
    """Các lỗi CSDL nằm trong chuỗi của ``exc`` (rỗng nếu không có)."""
    if not isinstance(exc, BaseException):
        return []
    return [e for e in _chuoi_ngoai_le(exc) if _la_loi_csdl_don(e)]


def la_loi_csdl(exc: Any) -> bool:
    """``exc`` là lỗi CSDL, hoặc BỌC một lỗi CSDL ở bất kỳ đâu trong chuỗi."""
    return bool(loi_csdl_trong_chuoi(exc))


def tom_tat_loi_csdl(exc: BaseException) -> str:
    """Tóm tắt CHỈ từ THUỘC TÍNH, ví dụ
    ``DBError[IntegrityError<-CheckViolationError sqlstate=23514 constraint=ck_x table=t]``.
    Không bao giờ đọc ``str()``/``args`` của ngoại lệ."""
    dbs = loi_csdl_trong_chuoi(exc) or [exc]
    ten: list = []
    for e in dbs:
        n = type(e).__name__
        if n not in ten:
            ten.append(n)
    phan = ["<-".join(ten)]
    for nhan, cac_thuoc_tinh in _THUOC_TINH_CSDL:
        gia_tri = None
        for e in dbs:
            for a in cac_thuoc_tinh:
                v = getattr(e, a, None)
                if v:
                    gia_tri = v
                    break
            if gia_tri:
                break
        if gia_tri:
            phan.append("%s=%s" % (nhan, _DINH_DANH_AN_TOAN.sub("_", str(gia_tri))[:63]))
    return "DBError[" + " ".join(phan) + "]"


def _bien_the(s: str) -> set:
    """Chuỗi thô + dạng thoát JSON (có/không ``ensure_ascii``, có/không thoát ``/``)."""
    import json

    out = {s}
    for ascii_ in (True, False):
        try:
            j = json.dumps(s, ensure_ascii=ascii_)[1:-1]
        except Exception:  # noqa: BLE001
            continue
        out.add(j)
        out.add(j.replace("/", "\\/"))
    return out


def thay_loi_csdl_trong_chuoi(text: Any, exc: Any) -> Any:
    """Thay MỌI đoạn chữ đã nội suy từ lỗi CSDL trong chuỗi của ``exc`` (``str``/
    ``repr`` đầy đủ ⇒ tóm tắt; từng dòng ≥ 12 ký tự của thông điệp ⇒
    ``<redacted>``; cả dạng đã thoát JSON), rồi áp regex lớp phụ."""
    if not isinstance(text, str) or not text:
        return text
    dbs = loi_csdl_trong_chuoi(exc)
    if dbs:
        tom = tom_tat_loi_csdl(exc)
        cap: list = []
        for e in dbs:
            for s in (str(e), repr(e)):
                if len(s) >= 8:
                    cap += [(b, tom) for b in _bien_the(s)]
            for d in str(e).splitlines():
                d = d.strip()
                if len(d) >= 12:
                    cap += [(b, REDACTED) for b in _bien_the(d)]
        for s, thay_bang in sorted(cap, key=lambda x: -len(x[0])):
            if s and s in text:
                text = text.replace(s, thay_bang)
    return redact_text(text)


def mo_ta_loi(exc: Any) -> str:
    """Dùng THAY ``str(exc)`` khi ghi log: lỗi CSDL ⇒ tóm tắt; ngoại lệ BỌC lỗi
    CSDL ⇒ chữ của nó với phần nội suy từ lỗi CSDL đã thay; khác ⇒ che regex."""
    if not isinstance(exc, BaseException):
        return redact_text(str(exc))
    if _la_loi_csdl_don(exc):
        return tom_tat_loi_csdl(exc)
    return thay_loi_csdl_trong_chuoi(str(exc), exc)


def dinh_dang_traceback_an_toan(exc: BaseException) -> str:
    """Traceback như ``traceback.format_exception`` — giữ khung (tệp/dòng/hàm) và
    nối chuỗi cause/context — nhưng dòng thông điệp của lỗi CSDL thay bằng tóm
    tắt, của ngoại lệ khác thì đã thay phần nội suy từ lỗi CSDL + regex."""
    import traceback

    chuoi: list = []  # (ngoại lệ, câu nối với ngoại lệ ĐỨNG SAU nó trong bản in)
    da_xet: set = set()
    e, noi = exc, None
    while isinstance(e, BaseException) and id(e) not in da_xet and len(chuoi) < _CHUOI_TOI_DA:
        da_xet.add(id(e))
        chuoi.append((e, noi))
        if e.__cause__ is not None:
            e, noi = e.__cause__, (
                "\nThe above exception was the direct cause of the following exception:\n\n")
        elif e.__context__ is not None and not e.__suppress_context__:
            e, noi = e.__context__, (
                "\nDuring handling of the above exception, another exception occurred:\n\n")
        else:
            e = None
    phan: list = []
    for i in range(len(chuoi) - 1, -1, -1):
        e, noi = chuoi[i]
        if e.__traceback__ is not None:
            phan.append("Traceback (most recent call last):\n")
            phan.extend(traceback.format_list(traceback.extract_tb(e.__traceback__)))
        lop = type(e)
        ten = lop.__qualname__ if lop.__module__ in ("builtins", "__main__") else (
            "%s.%s" % (lop.__module__, lop.__qualname__))
        if _la_loi_csdl_don(e):
            phan.append("%s: %s\n" % (ten, tom_tat_loi_csdl(e)))
        else:
            phan.append("%s: %s\n" % (ten, thay_loi_csdl_trong_chuoi(str(e), exc)))
        if noi:
            phan.append(noi)
    return "".join(phan).rstrip("\n")


def _lay_ngoai_le(ei: Any) -> Optional[BaseException]:
    """Ngoại lệ từ ``exc_info`` dạng ``True`` / ngoại lệ / bộ ba."""
    import sys

    if ei is True:
        return sys.exc_info()[1]
    if isinstance(ei, BaseException):
        return ei
    if isinstance(ei, tuple) and len(ei) == 3 and isinstance(ei[1], BaseException):
        return ei[1]
    return None


def _loi_csdl_dang_xu_ly() -> Optional[BaseException]:
    """Ngoại lệ ĐANG được xử lý (lời gọi log nằm trong ``except``) nếu nó là /
    bọc lỗi CSDL — để thay ``error=str(e)`` / ``f"…{e}"`` mà không cần sửa từng
    lời gọi."""
    import sys

    e = sys.exc_info()[1]
    return e if la_loi_csdl(e) else None


# ---------------------------------------------------------------------------
# CỬA RA 1 — structlog
# ---------------------------------------------------------------------------


def tom_tat_loi_csdl_event(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Processor structlog — PHẢI đứng TRƯỚC ``format_exc_info``: ``exc_info``
    là / bọc lỗi CSDL ⇒ tự dựng ``exception`` bằng
    :func:`dinh_dang_traceback_an_toan` và bỏ ``exc_info`` (nên
    ``format_exc_info`` không in traceback thô)."""
    try:
        exc = _lay_ngoai_le(event_dict.get("exc_info"))
        if exc is not None and la_loi_csdl(exc):
            event_dict.pop("exc_info", None)
            event_dict["exception"] = dinh_dang_traceback_an_toan(exc)
    except Exception:  # noqa: BLE001
        event_dict.pop("exc_info", None)
        event_dict["exception"] = REDACTED
    return event_dict


def redact_event_dict(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Processor structlog: khoá nhạy cảm ⇒ ``[REDACTED]``; mọi giá trị khác
    (gồm ``event``, ``error``, ``exception`` do ``format_exc_info`` sinh) ⇒
    :func:`redact_value`. PHẢI đứng SAU ``format_exc_info``. Gọi trong ``except``
    lỗi CSDL thì mọi chuỗi (cả chuỗi lồng trong dict/list) còn được thay phần
    nội suy từ lỗi ấy (``error=str(e)``, ``ctx={"loi": f"{e}"}``)."""
    dang = _loi_csdl_dang_xu_ly()
    for key in list(event_dict.keys()):
        try:
            if is_sensitive_key(key):
                event_dict[key] = REDACTED_KEY
            else:
                event_dict[key] = redact_value(event_dict[key], _loi_csdl=dang)
        except Exception:  # noqa: BLE001
            event_dict[key] = REDACTED_KEY
    return event_dict


# ---------------------------------------------------------------------------
# CỬA RA 2 + 3 — logging thường + access log
# ---------------------------------------------------------------------------

_FORMATTER_MAC_DINH = logging.Formatter()


class RedactingFilter(logging.Filter):
    """``logging.Filter`` che bản ghi TRƯỚC khi handler định dạng nó.

    * Có ``args``: che từng ``args`` chuỗi của tuple (giữ nguyên dạng tuple để
      ``uvicorn.logging.AccessFormatter`` — vốn tách 5 phần tử — còn chạy), rồi
      dựng câu hoàn chỉnh và che câu ấy: ``args`` không phải chuỗi (ngoại lệ,
      đối tượng, dict-atom của gunicorn) mang PII qua ``str()``; nếu câu còn gì
      để che thì thay ``msg`` bằng câu đã che và bỏ ``args``. KHÔNG che riêng
      chuỗi định dạng ``msg`` khi có ``args`` — che lệch ``%s`` sẽ làm định dạng
      hỏng và ``logging`` in NGUYÊN ``args`` ra stderr khi báo lỗi.
    * Không ``args``: che ``msg`` (dòng structlog đã render đi lối này).
    * traceback: filter chạy TRƯỚC ``Formatter.format`` nên ``exc_text`` còn
      rỗng — dựng sẵn nó rồi che (formatter thấy ``exc_text`` có sẵn thì dùng).

    Không bao giờ chặn bản ghi (luôn trả ``True``) và không bao giờ ném.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            self._che(record)
        except Exception:  # noqa: BLE001 — log filter không được phép ném
            pass
        return True

    @staticmethod
    def _che(record: logging.LogRecord) -> None:
        # Lỗi CSDL liên quan tới bản ghi: ngoại lệ gắn kèm (exc_info) và ngoại lệ
        # ĐANG xử lý (lời gọi log nằm trong ``except``) — để thay phần chữ đã nội
        # suy từ chúng (``f"…{e}"``, ``str(e)``, câu ``%(exc)s`` của celery).
        lien_quan = [
            e for e in (_lay_ngoai_le(record.exc_info), _loi_csdl_dang_xu_ly())
            if e is not None and la_loi_csdl(e)
        ]

        def che(t: Any) -> Any:
            for e in lien_quan:
                t = thay_loi_csdl_trong_chuoi(t, e)
            return redact_text(t)

        args = record.args
        if args:
            if isinstance(args, tuple):
                record.args = tuple(
                    che(a) if isinstance(a, str)
                    else (mo_ta_loi(a) if isinstance(a, BaseException) else a)
                    for a in args
                )
            elif isinstance(args, MutableMapping):
                for k in list(args.keys()):
                    if isinstance(args[k], BaseException):
                        args[k] = mo_ta_loi(args[k])
            try:
                da_dung = record.getMessage()
            except Exception:  # noqa: BLE001 — định dạng hỏng: đừng để logging in args thô
                record.msg = che("%s %r" % (record.msg, record.args))
                record.args = None
            else:
                da_che = che(da_dung)
                if da_che != da_dung:
                    record.msg = da_che
                    record.args = None
        elif isinstance(record.msg, str):
            record.msg = che(record.msg)
        elif isinstance(record.msg, BaseException):
            record.msg = mo_ta_loi(record.msg)
        elif record.msg is not None:
            tho = str(record.msg)
            da_che = che(tho)
            if da_che != tho:
                record.msg = da_che
        if record.exc_info and not record.exc_text:
            exc = _lay_ngoai_le(record.exc_info)
            if exc is not None and la_loi_csdl(exc):
                # Lỗi CSDL: traceback giữ khung, thông điệp thay bằng tóm tắt.
                record.exc_text = dinh_dang_traceback_an_toan(exc)
            else:
                record.exc_text = _FORMATTER_MAC_DINH.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info)


#: Logger mà gunicorn/uvicorn có thể gắn handler RIÊNG (``propagate=False``).
ACCESS_LOGGERS: tuple[str, ...] = (
    "uvicorn.access", "uvicorn.error", "gunicorn.access", "gunicorn.error",
)


def install_log_redaction() -> None:
    """Gắn :class:`RedactingFilter` ở MỨC LOGGER cho các access/error logger
    của app-server (idempotent). Gọi từ :func:`configure_logging` và từ
    ``gunicorn.conf.py::post_worker_init`` (SAU khi gunicorn dựng handler)."""
    for name in ACCESS_LOGGERS:
        lg = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in lg.filters):
            lg.addFilter(RedactingFilter())


def _gan_filter(handler: logging.Handler) -> logging.Handler:
    if not any(isinstance(f, RedactingFilter) for f in handler.filters):
        handler.addFilter(RedactingFilter())
    return handler


# ---------------------------------------------------------------------------
# CẤU HÌNH CHUNG cho web + celery worker + celery beat
# ---------------------------------------------------------------------------

#: Logger ồn ào — hạ mức (chuyển nguyên từ ``main.py``).
_MUC_LOGGER: tuple[tuple[str, int], ...] = (
    ("sqlalchemy.engine", logging.WARNING),
    ("sqlalchemy.pool", logging.WARNING),
    ("uvicorn.access", logging.INFO),
    ("uvicorn.error", logging.INFO),
    ("socketio", logging.WARNING),
    ("engineio", logging.WARNING),
    ("user_agents", logging.INFO),
    ("passlib", logging.WARNING),
    ("bcrypt", logging.WARNING),
    ("multipart", logging.WARNING),
    ("python_multipart", logging.WARNING),
    ("casbin", logging.WARNING),
)


def structlog_processors(renderer: Any) -> list:
    """Chuỗi processor structlog dùng chung — bộ che đứng SAU ``format_exc_info``."""
    import structlog

    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        tom_tat_loi_csdl_event,  # V6 vòng 4: lỗi CSDL ⇒ traceback tóm tắt, TRƯỚC format_exc_info
        structlog.processors.format_exc_info,
        redact_event_dict,  # V6: che SAU khi traceback đã thành chuỗi
        renderer,
    ]


def configure_logging(
    process: str,
    loglevel: Optional[Union[int, str]] = None,
    fmt: Optional[str] = None,
) -> logging.Handler:
    """Cấu hình log cho MỘT tiến trình: structlog + handler gốc + access log.

    ``process`` chỉ để ghi nhận (``"web"``, ``"celery"``). ``fmt`` (tuỳ chọn)
    là khuôn ``logging.Formatter`` của handler gốc — celery truyền khuôn của nó
    để dòng log Celery còn giờ/mức; web để ``None`` như trước.
    Trả về handler gốc (để test chỉ được luồng ra mà không đụng gì khác).
    """
    import structlog
    import ujson

    from app.config import settings

    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.APP_ENV == "development"
        else structlog.processors.JSONRenderer(serializer=ujson.dumps)
    )
    structlog.configure(
        processors=structlog_processors(renderer),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    muc = loglevel if loglevel is not None else settings.LOG_LEVEL.upper()
    handler = logging.StreamHandler()
    if fmt:
        handler.setFormatter(logging.Formatter(fmt))
    _gan_filter(handler)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(muc)

    # L2: ghi tệp có xoay vòng khi đặt LOG_FILE — cũng phải qua bộ che.
    if settings.LOG_FILE:
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=settings.LOG_FILE_MAX_BYTES,
            backupCount=settings.LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(muc)
        if fmt:
            file_handler.setFormatter(logging.Formatter(fmt))
        root.addHandler(_gan_filter(file_handler))
        print(
            f"INFO [log_redaction.py]: ✅ File logging enabled ({process}): "
            f"{settings.LOG_FILE} (max={settings.LOG_FILE_MAX_BYTES // 1024 // 1024}MB, "
            f"backups={settings.LOG_FILE_BACKUP_COUNT})"
        )

    for ten, muc_rieng in _MUC_LOGGER:
        logging.getLogger(ten).setLevel(muc_rieng)

    # uvicorn dựng handler riêng cho hai logger này — trỏ chúng về handler gốc.
    for ten in ("uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(ten)
        lg.handlers.clear()
        lg.addHandler(handler)

    install_log_redaction()
    return handler
