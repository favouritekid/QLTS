# app/core/log_redaction.py
"""
Redact raw SMS bearer code khỏi ACCESS LOG (uvicorn.access dev / gunicorn.access
prod) — §11.3 "KHÔNG log raw code". nginx `access_log off` chỉ tắt tầng nginx;
app-server vẫn ghi nguyên request line `GET /r/<code>` mỗi hit thành công →
filter này thay code bằng `<redacted>` trong record TRƯỚC khi format.

Redact ở record.msg + record.args (tuple cho uvicorn, dict-atoms cho gunicorn).
"""
import logging
import re

# Prefix bearer + phần code (tới whitespace/?/quote/&). PR-5: /r/, /lp/,
# /api/public/sms/landing/.
_BEARER_RE = re.compile(
    r"(/r/|/lp/|/api/public/sms/landing/)[^\s?\"'&]+"
)
_REDACTED = r"\1<redacted>"


def _redact(value):
    if isinstance(value, str):
        return _BEARER_RE.sub(_REDACTED, value)
    return value


class SmsBearerRedactionFilter(logging.Filter):
    """logging.Filter che bearer code trong access-log record (best-effort —
    không bao giờ làm hỏng log dù record dạng lạ)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if isinstance(args, dict):
                record.args = {k: _redact(v) for k, v in args.items()}
            elif isinstance(args, tuple):
                record.args = tuple(_redact(a) for a in args)
            if isinstance(record.msg, str):
                record.msg = _BEARER_RE.sub(_REDACTED, record.msg)
        except Exception:  # noqa: BLE001 — log filter không được phép ném
            pass
        return True


def install_sms_log_redaction() -> None:
    """Gắn filter vào các access logger (idempotent — không gắn trùng)."""
    _filter = SmsBearerRedactionFilter()
    for name in ("uvicorn.access", "gunicorn.access"):
        logger = logging.getLogger(name)
        if not any(
            isinstance(f, SmsBearerRedactionFilter) for f in logger.filters
        ):
            logger.addFilter(_filter)
