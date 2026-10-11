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
from collections.abc import Mapping
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

#: Cột trong ``DETAIL: Key (…)=(…)`` của PostgreSQL ⇒ che phần giá trị. Cột
#: khác (``profile_id``, ``lead_id``…) giữ nguyên để chẩn đoán khoá ngoại.
_SQL_PII_COLUMN_RE = re.compile(
    r"citizen|cccd|cmnd|id_number|phone|email|full_name", re.IGNORECASE
)


def _slash(fragment: str) -> str:
    """Thoát regex rồi cho mỗi ``/`` khớp cả bản ujson thoát thành ``\\/``."""
    return re.escape(fragment).replace("/", r"\\?/")


def _prefix_regex(prefix: str) -> str:
    return _slash(prefix).replace(r"\*", r"[A-Za-z_-]+")


def nginx_token_path_alternation() -> str:
    """Tập :data:`TOKEN_PATH_PREFIXES` viết theo cú pháp regex của ``map`` nginx.

    Hằng duy nhất mà ``nginx/nginx.conf`` phải chép nguyên văn; test so khớp.
    """
    return "|".join(p.replace("*", "[A-Za-z_-]+") for p in TOKEN_PATH_PREFIXES)


# (1) token trong đường dẫn — khớp ở bất kỳ vị trí nào, cả dạng ``\/``. Đoạn
# token dừng ở ``/ ? # & " ' \`` khoảng trắng và ``<`` (nên ``<redacted>`` không
# bị che lại — idempotent, vì bản ghi có thể đi qua hai lớp che).
_TOKEN_PATH_RE = re.compile(
    "(" + "|".join(_prefix_regex(p) for p in TOKEN_PATH_PREFIXES) + ")"
    + r"[^\s/?#&\"'\\<>]+"
)

_TEXT_KEY_ALT = (
    "|".join(re.escape(k) for k in sorted(PII_KEYS, key=len, reverse=True))
    + "|"
    + "|".join(r"[A-Za-z0-9_]*%s[A-Za-z0-9_]*" % s for s in SECRET_TEXT_KEY_SUBSTRINGS)
)
_VALUE = r"(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<bare>[^\s\"'&,;)}\]]+))"
# (2a) dạng ``khoá=giá trị`` (query string, câu log tự do).
_KV_EQ_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?P<k>%s)(?P<sep>\s*=\s*)%s" % (_TEXT_KEY_ALT, _VALUE)
)
# (2b) dạng khoá CÓ NGOẶC rồi ``:`` (JSON / repr của dict).
_KV_QUOTED_RE = re.compile(
    r"(?i)(?P<q>[\"'])(?P<k>%s)(?P=q)(?P<sep>\s*:\s*)%s" % (_TEXT_KEY_ALT, _VALUE)
)
# (3) CCCD sau nhãn: "CCCD 0…", "Citizen ID 0…", "citizen_id=0…", "cccd": "0…".
_CCCD_LABEL_RE = re.compile(
    r"(?i)(?P<lbl>(?:cccd|cmnd|citizen[ _-]?id)\W{0,5}?)(?P<num>\d{9,})(?!\d)"
)
# (4) DETAIL của PostgreSQL: ``Key (citizen_id, academic_year)=(0…, 2026)``.
_SQL_KEY_RE = re.compile(
    r"(?P<head>Key \((?P<cols>[^=]*?)\)=\()(?P<vals>.*?)(?P<tail>\)(?=[\s.,;\"'\\]|$))"
)
# (5) tham số bind trong câu lỗi SQLAlchemy: ``[parameters: ('Nguyen…', '0…')]``.
_SQL_PARAMS_RE = re.compile(
    r"\[parameters: .*?\](?=\\r|\\n|\r|\n|$|\s*\(Background)"
)
# (6) mật khẩu trong URL: ``redis://:pw@host``, ``postgresql://u:pw@host``.
_URL_CRED_RE = re.compile(
    r"(?P<pre>\b[A-Za-z][A-Za-z0-9+.-]*:\\?/\\?/[^:/\s@\"']*:)[^@\s\"']+?@"
)

_DA_CHE = (REDACTED, REDACTED_KEY)


def _thay_kv(m: "re.Match[str]") -> str:
    giu = m.group("dq") if m.group("dq") is not None else (
        m.group("sq") if m.group("sq") is not None else m.group("bare")
    )
    if giu in _DA_CHE:
        return m.group(0)
    full = m.group(0)
    # Giữ nguyên khoá + dấu phân cách + ngoặc; chỉ thay thân giá trị.
    start = m.start("dq") if m.group("dq") is not None else (
        m.start("sq") if m.group("sq") is not None else m.start("bare")
    )
    end = start + len(giu)
    off = m.start(0)
    return full[: start - off] + REDACTED + full[end - off:]


def _thay_sql_key(m: "re.Match[str]") -> str:
    if not _SQL_PII_COLUMN_RE.search(m.group("cols")):
        return m.group(0)
    return m.group("head") + REDACTED + m.group("tail")


def redact_text(text: str) -> str:
    """Áp MỌI mẫu che lên một chuỗi. Idempotent; không bao giờ ném."""
    if not isinstance(text, str) or not text:
        return text
    try:
        s = _SQL_PARAMS_RE.sub("[parameters: " + REDACTED + "]", text)
        s = _SQL_KEY_RE.sub(_thay_sql_key, s)
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


def redact_value(value: Any, _sau: int = 0) -> Any:
    """Che một giá trị bất kỳ (đệ quy dict/list/tuple/set).

    Đối tượng lạ (ngoại lệ, model…) thành chuỗi rồi che — renderer JSON vốn
    cũng ``repr()`` chúng, và chuỗi ấy có thể mang ``DETAIL`` SQL.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, enum.Enum) or isinstance(value, _SCALAR_AN_TOAN):
        return value
    if _sau >= _SAU_TOI_DA:
        return redact_text(repr(value))
    if isinstance(value, Mapping):
        return {
            k: (REDACTED_KEY if is_sensitive_key(k) else redact_value(v, _sau + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(v, _sau + 1) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_value(v, _sau + 1) for v in value)
    if isinstance(value, (set, frozenset)):
        return [redact_value(v, _sau + 1) for v in value]
    if isinstance(value, BaseException):
        return redact_text(str(value))
    return redact_text(repr(value))


# ---------------------------------------------------------------------------
# CỬA RA 1 — structlog
# ---------------------------------------------------------------------------


def redact_event_dict(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Processor structlog: khoá nhạy cảm ⇒ ``[REDACTED]``; mọi giá trị khác
    (gồm ``event``, ``error``, ``exception`` do ``format_exc_info`` sinh) ⇒
    :func:`redact_value`. PHẢI đứng SAU ``format_exc_info``."""
    for key in list(event_dict.keys()):
        try:
            if is_sensitive_key(key):
                event_dict[key] = REDACTED_KEY
            else:
                event_dict[key] = redact_value(event_dict[key])
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
        args = record.args
        if args:
            if isinstance(args, tuple):
                record.args = tuple(redact_text(a) if isinstance(a, str) else a for a in args)
            try:
                da_dung = record.getMessage()
            except Exception:  # noqa: BLE001 — định dạng hỏng: đừng để logging in args thô
                record.msg = redact_text("%s %r" % (record.msg, record.args))
                record.args = None
            else:
                da_che = redact_text(da_dung)
                if da_che != da_dung:
                    record.msg = da_che
                    record.args = None
        elif isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        elif record.msg is not None:
            tho = str(record.msg)
            da_che = redact_text(tho)
            if da_che != tho:
                record.msg = da_che
        if record.exc_info and not record.exc_text:
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
