# app/core/sentry_init.py
"""MỘT nơi khởi tạo Sentry — tầng CHỦ SỞ HỮU của cửa ra Sentry (F223, Codex lần 6).

``app/main.py`` gọi :func:`khoi_tao_sentry`; không chỗ nào khác trong ``app/`` gọi
``sentry_sdk.init`` (``tests/unit/test_sentry_khoi_tao.py`` khoá cả hai). Sentry gửi sự kiện tới
dịch vụ NGOÀI máy chủ ⇒ chặt hơn log của máy chủ: không thân request, không biến cục bộ, không chữ
tự do của người dùng hay của ngoại lệ.

Mỗi nguồn dữ liệu MỘT lớp chặn (không chồng lớp — mỗi lớp có ca kiểm và đột biến riêng). Chọn theo
nguồn sentry-sdk 2.22.0 (bản ghim ``requirements.txt``; dòng nguồn: báo cáo E4 của lượt
"Lần xét tuyển" GĐ1, ``doc-sentry-e4*.txt``):

* thân request (JSON / form) — ``max_request_body_size="never"``: SDK KHÔNG đọc thân
  (``_wsgi_common.request_body_within_bounds`` trả ``False`` ⇒ ``starlette.extract_request_info``
  chỉ ghi nhãn "quá cỡ");
* biến cục bộ của khung ngăn xếp — ``include_local_variables=False`` (``utils.serialize_frame``);
* cookie, IP, người dùng, header nhạy cảm (Authorization, Cookie …) — ``send_default_pii=False``;
* breadcrumb (log, http, redis, SQL …) — ``max_breadcrumbs=0`` (``Scope.add_breadcrumb``);
* log ⇒ sự kiện (``logentry`` + tham số + ``extra`` của bản ghi) — ``LoggingIntegration(
  event_level=None)``: log ERROR đi vào log của máy chủ (qua bộ che ``log_redaction``), không
  thành sự kiện Sentry;
* chuỗi truy vấn, header ngoài :data:`KEPT_HEADERS`, token trong đường dẫn / tên giao dịch, chữ
  của ngoại lệ — SDK không có tuỳ chọn ⇒ :func:`filter_event` (``before_send`` +
  ``before_send_transaction``);
* SPAN của giao dịch (``traces_sample_rate`` > 0): câu SQL / lệnh redis + khoá / URL gọi ra ngoài
  (``description``), ``http.query`` / ``db.*`` (``data``), ``tags`` — :func:`filter_event` chỉ giữ
  :data:`KEPT_SPAN_FIELDS` (danh sách CHO PHÉP: thời gian, định danh, ``op``, ``status``) của mọi
  span và của span gốc ``contexts.trace`` — giữ được số đo thời gian, bỏ mọi chữ.

Mọi lỗi khởi tạo chỉ in TÊN lớp lỗi (không chữ lỗi — chữ có thể mang DSN).
"""
from __future__ import annotations

from typing import Any, List, Optional

from app.core.log_redaction import loai_loi_an_toan, redact_text

#: Header của request được GIỮ trong sự kiện; còn lại bỏ — ``Referer`` mang chuỗi truy vấn của
#: trang trước, header lạ do trình duyệt / client tự đặt.
KEPT_HEADERS = frozenset(
    {"host", "user-agent", "content-type", "content-length", "accept"}
)
#: Trường GIỮ của một span (sự kiện transaction: ``spans[]`` và ``contexts.trace``) — còn lại bỏ.
KEPT_SPAN_FIELDS = frozenset(
    {
        "trace_id",
        "span_id",
        "parent_span_id",
        "op",
        "status",
        "start_timestamp",
        "timestamp",
        "same_process_as_parent",
        "origin",
        "exclusive_time",
    }
)


def _filter_span(span: Any) -> Any:
    """Một span chỉ còn :data:`KEPT_SPAN_FIELDS` (không phải dict ⇒ ``None``)."""
    if not isinstance(span, dict):
        return None
    return {k: v for k, v in span.items() if k in KEPT_SPAN_FIELDS}


def _exception_chain(exc: Any) -> List[BaseException]:
    """Ngoại lệ gốc + chuỗi ``__cause__`` / ``__context__`` (cùng cách SDK đi chuỗi)."""
    chain: List[BaseException] = []
    done = set()
    while isinstance(exc, BaseException) and id(exc) not in done:
        done.add(id(exc))
        chain.append(exc)
        if exc.__cause__ is not None:
            exc = exc.__cause__
        elif exc.__suppress_context__:
            exc = None
        else:
            exc = exc.__context__
    return chain


def filter_event(event: Any, hint: Any) -> Optional[Any]:
    """``before_send`` + ``before_send_transaction``: bỏ chuỗi truy vấn, header ngoài danh sách
    giữ; che token trong đường dẫn + tên giao dịch (bộ che của ``log_redaction``); span chỉ còn
    :data:`KEPT_SPAN_FIELDS`; chữ của ngoại
    lệ chỉ còn LOẠI + mã số (``loai_loi_an_toan`` — lỗi CSDL ⇒ tóm tắt thuộc tính). Thân request
    và biến cục bộ KHÔNG xử lý ở đây — SDK không thu chúng (tuỳ chọn ở :func:`khoi_tao_sentry`).
    Lỗi trong bộ lọc ⇒ BỎ sự kiện (fail-closed)."""
    try:
        req = event.get("request")
        if isinstance(req, dict):
            req.pop("query_string", None)
            title = req.get("headers")
            if isinstance(title, dict):
                req["headers"] = {
                    k: v
                    for k, v in title.items()
                    if isinstance(k, str) and k.lower() in KEPT_HEADERS
                }
            if isinstance(req.get("url"), str):
                req["url"] = redact_text(req["url"])
        if isinstance(event.get("transaction"), str):
            event["transaction"] = redact_text(event["transaction"])
        if isinstance(event.get("spans"), list):
            event["spans"] = [
                s for s in (_filter_span(x) for x in event["spans"]) if s is not None
            ]
        contexts = event.get("contexts")
        if isinstance(contexts, dict) and "trace" in contexts:
            contexts["trace"] = _filter_span(contexts["trace"])
        exception = event.get("exception")
        if isinstance(exception, dict):
            exc_info = (hint or {}).get("exc_info")
            chain = _exception_chain(exc_info[1] if exc_info else None)
            for v in exception.get("values") or ():
                if isinstance(v, dict) and "value" in v:
                    matched = next(
                        (e for e in chain if type(e).__name__ == v.get("type")), None
                    )
                    v["value"] = loai_loi_an_toan(matched) if matched is not None else ""
        return event
    except Exception:  # noqa: BLE001 — bộ lọc hỏng ⇒ không gửi gì
        return None


def init_sentry(
    dsn: str, environment: str, traces_sample_rate: float, *, transport: Any = None
) -> bool:
    """Khởi tạo Sentry khi có ``dsn`` (rỗng ⇒ không làm gì). Trả ``True`` khi đã khởi tạo.
    ``transport`` chỉ dùng trong test (bắt sự kiện, không mạng)."""
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        print(
            "WARNING [sentry_init]: SENTRY_DSN is set but sentry-sdk is not installed."
        )
        return False
    options = dict(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        max_breadcrumbs=0,
        integrations=[LoggingIntegration(event_level=None)],
        before_send=filter_event,
        before_send_transaction=filter_event,
    )
    if transport is not None:
        options["transport"] = transport
    try:
        sentry_sdk.init(**options)
    except Exception as e:  # noqa: BLE001 — Sentry hỏng không được làm hỏng tiến trình
        print(
            "WARNING [sentry_init]: Failed to initialize Sentry: %s" % type(e).__name__
        )
        return False
    print(
        "INFO [sentry_init]: Sentry initialized (env=%s, sample_rate=%s)"
        % (environment, traces_sample_rate)
    )
    return True
