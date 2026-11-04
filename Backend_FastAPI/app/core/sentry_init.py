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
* chuỗi truy vấn, header ngoài :data:`TIEU_DE_GIU`, token trong đường dẫn / tên giao dịch, chữ
  của ngoại lệ — SDK không có tuỳ chọn ⇒ :func:`loc_su_kien` (``before_send`` +
  ``before_send_transaction``).

Mọi lỗi khởi tạo chỉ in TÊN lớp lỗi (không chữ lỗi — chữ có thể mang DSN).
"""
from __future__ import annotations

from typing import Any, List, Optional

from app.core.log_redaction import loai_loi_an_toan, redact_text

#: Header của request được GIỮ trong sự kiện; còn lại bỏ — ``Referer`` mang chuỗi truy vấn của
#: trang trước, header lạ do trình duyệt / client tự đặt.
TIEU_DE_GIU = frozenset(
    {"host", "user-agent", "content-type", "content-length", "accept"}
)


def _chuoi_ngoai_le(exc: Any) -> List[BaseException]:
    """Ngoại lệ gốc + chuỗi ``__cause__`` / ``__context__`` (cùng cách SDK đi chuỗi)."""
    ra: List[BaseException] = []
    da = set()
    while isinstance(exc, BaseException) and id(exc) not in da:
        da.add(id(exc))
        ra.append(exc)
        if exc.__cause__ is not None:
            exc = exc.__cause__
        elif exc.__suppress_context__:
            exc = None
        else:
            exc = exc.__context__
    return ra


def loc_su_kien(event: Any, hint: Any) -> Optional[Any]:
    """``before_send`` + ``before_send_transaction``: bỏ chuỗi truy vấn, header ngoài danh sách
    giữ; che token trong đường dẫn + tên giao dịch (bộ che của ``log_redaction``); chữ của ngoại
    lệ chỉ còn LOẠI + mã số (``loai_loi_an_toan`` — lỗi CSDL ⇒ tóm tắt thuộc tính). Thân request
    và biến cục bộ KHÔNG xử lý ở đây — SDK không thu chúng (tuỳ chọn ở :func:`khoi_tao_sentry`).
    Lỗi trong bộ lọc ⇒ BỎ sự kiện (fail-closed)."""
    try:
        req = event.get("request")
        if isinstance(req, dict):
            req.pop("query_string", None)
            tieu_de = req.get("headers")
            if isinstance(tieu_de, dict):
                req["headers"] = {
                    k: v
                    for k, v in tieu_de.items()
                    if isinstance(k, str) and k.lower() in TIEU_DE_GIU
                }
            if isinstance(req.get("url"), str):
                req["url"] = redact_text(req["url"])
        if isinstance(event.get("transaction"), str):
            event["transaction"] = redact_text(event["transaction"])
        ngoai_le = event.get("exception")
        if isinstance(ngoai_le, dict):
            exc_info = (hint or {}).get("exc_info")
            chuoi = _chuoi_ngoai_le(exc_info[1] if exc_info else None)
            for v in ngoai_le.get("values") or ():
                if isinstance(v, dict) and "value" in v:
                    doi = next(
                        (e for e in chuoi if type(e).__name__ == v.get("type")), None
                    )
                    v["value"] = loai_loi_an_toan(doi) if doi is not None else ""
        return event
    except Exception:  # noqa: BLE001 — bộ lọc hỏng ⇒ không gửi gì
        return None


def khoi_tao_sentry(
    dsn: str, moi_truong: str, ty_le_trace: float, *, transport: Any = None
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
    tuy_chon = dict(
        dsn=dsn,
        environment=moi_truong,
        traces_sample_rate=ty_le_trace,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        max_breadcrumbs=0,
        integrations=[LoggingIntegration(event_level=None)],
        before_send=loc_su_kien,
        before_send_transaction=loc_su_kien,
    )
    if transport is not None:
        tuy_chon["transport"] = transport
    try:
        sentry_sdk.init(**tuy_chon)
    except Exception as e:  # noqa: BLE001 — Sentry hỏng không được làm hỏng tiến trình
        print(
            "WARNING [sentry_init]: Failed to initialize Sentry: %s" % type(e).__name__
        )
        return False
    print(
        "INFO [sentry_init]: Sentry initialized (env=%s, sample_rate=%s)"
        % (moi_truong, ty_le_trace)
    )
    return True
