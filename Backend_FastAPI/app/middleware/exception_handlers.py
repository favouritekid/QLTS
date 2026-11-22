# app/middleware/exception_handlers.py
"""
Exception handlers for converting custom exceptions to HTTP responses.

This module provides handlers that automatically convert our custom exceptions
(defined in app.utils.exceptions) to appropriate HTTP responses, eliminating
the need to manually catch and convert them in routers.

Usage:
    In main.py:
        from app.middleware import register_exception_handlers
        register_exception_handlers(app)

    In services:
        raise UserNotFoundError(f"User {user_id} not found")

    Result:
        Automatically returns HTTP 404 with proper JSON response
"""

import logging
import typing

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.log_redaction import (
    PII_BODY_ROUTE_PREFIXES,
    SMS_BEARER_PREFIXES,
    mo_ta_loi,
    redact_text,
    thay_loi_csdl_trong_chuoi,
)
from app.utils.exceptions import (
    BaseAppException,
    ResourceNotFoundError,
    UserNotFoundError,
    LeadNotFoundError,
    OrganizationNotFoundError,
    SessionNotFoundError,
    DuplicateResourceError,
    ValidationError,
    DataValidationError,
    FileValidationError,
    FileSizeError,
    FileTypeError,
    BusinessRuleViolation,
    AuthenticationError,
    InvalidCredentials,
    InvalidToken,
    SessionRevokedError,
    PermissionDeniedError,
    ServiceError,
    CacheServiceError,
    SessionServiceError,
    SessionRevocationError,
    EmailServiceError,
    UserServiceError,
    WebSocketServiceError,
)

logger = logging.getLogger(__name__)

# Đường dẫn mang bí mật (mã SMS PR-5 §11.3, token xác nhận nhập học,
# magic-link) → KHÔNG được log nguyên. Mẫu che chỉ khai MỘT lần ở
# `app/core/log_redaction.py` (V6) — đừng chép lại danh sách tiền tố ở đây.
# Ghi chú: dòng log của các handler dưới đây còn đi qua `RedactingFilter` ở
# handler gốc; `_redact_path` là lớp phụ cho trường `extra["path"]`.


def _redact_path(path: str) -> str:
    """Che phần bí mật trong path trước khi đưa vào log (giữ tiền tố route)."""
    return redact_text(path)


def _chi_tiet_an_toan(exc: BaseException) -> str:
    """``exc.detail`` để GHI LOG: nếu ngoại lệ bọc một lỗi CSDL (``raise …(f"…{e}")
    from e``) thì phần chữ đã nội suy từ lỗi CSDL được thay bằng tóm tắt (V6 vòng 4 —
    ngừng ghi nội dung lỗi PostgreSQL). Phản hồi cho client KHÔNG đổi."""
    return thay_loi_csdl_trong_chuoi(str(getattr(exc, "detail", "")), exc)


def _no_log_input_422(path: str) -> bool:
    """MỘT vị từ: route mà lỗi 422 chỉ được ghi vào log ở dạng ĐÃ CHUẨN HOÁ
    (:func:`_safe_422_error_for_log`) — không ``input`` / ``msg`` / ``ctx``, ``loc`` chỉ giữ
    phần chứng minh được an toàn.

    * Route mang bearer code SMS (path HOẶC body opt-out) — ``input`` có thể là raw code
      (§11.3).
    * Route văn bản Hội đồng (``PII_BODY_ROUTE_PREFIXES``) — thân request mang danh sách mã
      hồ sơ (CCCD); lỗi kiểu ``missing`` trả CẢ thân request trong ``input``; khoá JSON thừa
      (``extra="forbid"``) nằm trong ``loc``. Khớp theo ĐOẠN đường dẫn
      (``/api/admission-config/council-documentsX`` không khớp).
    """
    return (
        path.startswith(SMS_BEARER_PREFIXES)
        or path == "/api/public/sms/opt-out"
        or any(path == t or path.startswith(t + "/") for t in PII_BODY_ROUTE_PREFIXES)
    )


# Phần tử ĐẦU của ``loc`` do FastAPI đặt (nơi tham số nằm) — tập cố định, không do client.
_JOIN_PARAMS_422 = frozenset({"body", "query", "path", "header", "cookie"})
# Nhãn cố định thay cho mọi phần tử chuỗi của ``loc`` không chứng minh được là tên trường
# khai trong schema (khoá JSON thừa, khoá của dict, nhãn nhánh union …).
UNDECLARED_LOC_LABEL = "<khong-khai>"


def _declared_names_of_type(annotation_type, out: set, seen: set) -> None:
    """Gom tên (+ alias) mọi trường của các model Pydantic nằm trong chú thích kiểu ``kieu``
    (đệ quy qua ``Optional`` / ``List`` / ``Dict`` / ``Union`` / model lồng)."""
    if id(annotation_type) in seen:
        return
    seen.add(id(annotation_type))
    if isinstance(annotation_type, type) and issubclass(annotation_type, BaseModel):
        for field_name, f in annotation_type.model_fields.items():
            out.add(field_name)
            if isinstance(f.alias, str):
                out.add(f.alias)
            _declared_names_of_type(f.annotation, out, seen)
        return
    for arg in typing.get_args(annotation_type):
        _declared_names_of_type(arg, out, seen)


def _declared_names_of_route(route) -> frozenset:
    """Tên tham số + tên trường schema mà ROUTE đã khớp khai (body / query / path / header /
    cookie, kể cả của dependency con). Không đọc được ⇒ tập RỖNG (fail-closed: mọi chuỗi
    của ``loc`` thành nhãn cố định)."""
    out: set = set()
    try:
        stack = [getattr(route, "dependant")]
        seen: set = set()
        while stack:
            d = stack.pop()
            for group in (
                "path_params",
                "query_params",
                "header_params",
                "cookie_params",
                "body_params",
            ):
                for f in getattr(d, group, None) or ():
                    for name in (getattr(f, "name", None), getattr(f, "alias", None)):
                        if isinstance(name, str):
                            out.add(name)
                    _declared_names_of_type(
                        getattr(getattr(f, "field_info", None), "annotation", None),
                        out,
                        seen,
                    )
            stack.extend(getattr(d, "dependencies", None) or ())
    except Exception:  # noqa: BLE001 — bộ chuẩn hoá log không được làm hỏng request
        return frozenset()
    return frozenset(out)


def _safe_422_error_for_log(errors: list, route) -> list:
    """MỘT chỗ chuẩn hoá lỗi 422 trước khi ghi log cho MỌI route của
    :func:`_no_log_input_422` (F217). Chỉ giữ thứ CHỨNG MINH được an toàn:

    * ``type`` — mã lỗi do Pydantic / mã nguồn đặt, không lấy từ dữ liệu gửi lên;
    * ``loc`` đã chuẩn hoá — số nguyên (chỉ số phần tử danh sách) giữ nguyên; phần tử ĐẦU
      thuộc tập nơi tham số cố định giữ nguyên; chuỗi khác CHỈ giữ khi là tên trường / tham
      số khai trong schema của route (:func:`_declared_names_of_route`), còn lại thay
      :data:`UNDECLARED_LOC_LABEL` (khoá JSON thừa có thể chính là một CCCD).

    Bỏ hẳn ``input``, ``msg``, ``ctx``, ``url`` (``msg`` / ``ctx`` có thể nội suy giá trị)."""
    declared_names = _declared_names_of_route(route) if route is not None else frozenset()
    out = []
    for e in errors:
        loc = []
        for i, p in enumerate(e.get("loc") or ()):
            if isinstance(p, int) and not isinstance(p, bool):
                loc.append(p)
            elif isinstance(p, str) and (
                (i == 0 and p in _JOIN_PARAMS_422) or (i > 0 and p in declared_names)
            ):
                loc.append(p)
            else:
                loc.append(UNDECLARED_LOC_LABEL)
        t = e.get("type")
        out.append(
            {"type": t if isinstance(t, str) else UNDECLARED_LOC_LABEL, "loc": loc}
        )
    return out


# ============================================================================
# CUSTOM EXCEPTION HANDLERS
# ============================================================================


async def base_app_exception_handler(
    request: Request, exc: BaseAppException
) -> JSONResponse:
    """
    Generic handler for all BaseAppException subclasses.

    This handler converts any custom exception into a JSON response with:
    - status_code: from exception.status_code
    - detail: from exception.detail
    - error_code: machine-readable error code
    - context: additional debugging information (only in dev mode)

    Args:
        request: The incoming request
        exc: The custom exception

    Returns:
        JSONResponse with error details
    """
    # Log the exception with context
    logger.warning(
        f"{exc.__class__.__name__}: {_chi_tiet_an_toan(exc)}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": _redact_path(request.url.path),
            "method": request.method,
        },
    )

    # Build response payload.
    #
    # Thứ tự ở đây là một hàng rào, không phải thói quen viết code: payload
    # công khai đổ vào TRƯỚC, rồi `detail`/`error_code` chuẩn của máy chủ ghi
    # đè lên. Ngược lại thì một payload lỡ mang khoá `error_code` sẽ đổi được
    # mã lỗi mà client dùng để rẽ nhánh — và mã lỗi là thứ duy nhất client
    # được phép tin.
    #
    # `context` KHÔNG bao giờ đi ra: nó là chỗ chứa dữ liệu debug (id nội bộ,
    # tham số truy vấn). Cái đi ra là `public_payload`, một trường tách riêng
    # mà người ném lỗi phải chủ động điền — mặc định rỗng, tức fail-closed.
    response_data = dict(getattr(exc, "public_payload", None) or {})
    response_data["detail"] = exc.detail
    response_data["error_code"] = exc.error_code

    # Add headers if present (e.g., WWW-Authenticate for 401)
    headers = getattr(exc, "headers", None)

    return JSONResponse(
        status_code=exc.status_code,
        content=response_data,
        headers=headers,
    )


async def resource_not_found_handler(
    request: Request, exc: ResourceNotFoundError
) -> JSONResponse:
    """
    Handler for resource not found errors (404).

    Provides more specific logging for missing resources.
    """
    logger.info(
        f"Resource not found: {_chi_tiet_an_toan(exc)}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": _redact_path(request.url.path),
        },
    )

    # GĐ2-F1: ``public_payload`` đi ra như ở ``base_app_exception_handler`` (đổ TRƯỚC, ``detail`` / ``error_code`` ghi đè) —
    # mặc định rỗng ⇒ mọi 404 khác không đổi; chỉ người ném CHỦ ĐỘNG điền (vd dấu chỉ tiêu của năm chưa có bảng chỉ tiêu).
    content = dict(getattr(exc, "public_payload", None) or {})
    content["detail"] = exc.detail
    content["error_code"] = exc.error_code
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=content,
    )


async def validation_error_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """
    Handler for validation errors (400).

    Includes validation context when available.
    """
    logger.info(
        f"Validation error: {_chi_tiet_an_toan(exc)}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": _redact_path(request.url.path),
        },
    )

    # ``public_payload`` là hợp đồng API của lỗi (xem ``BaseAppException``): đổ vào TRƯỚC, ``detail``/``error_code``
    # ghi đè SAU — cùng hàng rào với ``base_app_exception_handler``. Trước đây handler 400 bỏ mất payload.
    response_data = dict(getattr(exc, "public_payload", None) or {})
    response_data["detail"] = exc.detail
    response_data["error_code"] = exc.error_code

    # Include validation errors if present
    if exc.context and "errors" in exc.context:
        response_data["errors"] = exc.context["errors"]

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=response_data,
    )


async def authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    """
    Handler for authentication errors (401).

    Includes WWW-Authenticate header as required by HTTP spec.
    """
    logger.warning(
        f"Authentication error: {_chi_tiet_an_toan(exc)}",
        extra={
            "error_code": exc.error_code,
            "path": _redact_path(request.url.path),
        },
    )

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "detail": exc.detail,
            "error_code": exc.error_code,
        },
        headers=exc.headers,
    )


async def service_error_handler(
    request: Request, exc: ServiceError
) -> JSONResponse:
    """
    Handler for service layer errors (500).

    Logs full error details for debugging while returning safe message to client.
    """
    logger.error(
        f"Service error: {_chi_tiet_an_toan(exc)}",
        extra={
            "error_code": exc.error_code,
            "context": exc.context,
            "path": _redact_path(request.url.path),
            "method": request.method,
        },
        exc_info=True,  # Include stack trace
    )

    # ``public_payload`` (JSON thuần, người ném chủ động điền) đi ra như ở ``base_app_exception_handler``;
    # ``context`` thì KHÔNG. ``detail``/``error_code`` ghi đè sau.
    response_data = dict(getattr(exc, "public_payload", None) or {})
    response_data["detail"] = exc.detail
    response_data["error_code"] = exc.error_code
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response_data,
    )


# ============================================================================
# PYDANTIC VALIDATION ERROR HANDLER
# ============================================================================


async def pydantic_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handler for Pydantic validation errors from request body/query params.

    Formats Pydantic errors into a consistent structure.
    """
    # Safely serialize errors - convert any non-JSON-serializable objects to strings
    def serialize_error(error: dict) -> dict:
        serialized = {}
        for key, value in error.items():
            if key == "ctx" and isinstance(value, dict):
                # Context might contain non-serializable objects like ValueError
                serialized[key] = {
                    k: str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
                    for k, v in value.items()
                }
            elif isinstance(value, Exception):
                serialized[key] = str(value)
            else:
                serialized[key] = value
        return serialized

    safe_errors = [serialize_error(e) for e in exc.errors()]

    # Route bearer (/r/, /lp/, landing, body opt-out) và route văn bản Hội đồng (thân
    # request = danh sách CCCD): 'input' / 'msg' / 'ctx' có thể mang raw bearer code / dữ
    # liệu cá nhân, khoá JSON thừa nằm trong 'loc' ⇒ LOG chỉ nhận bản đã chuẩn hoá (vẫn giữ
    # nguyên trong response cho chính người gửi). §11.3, F217.
    log_errors = safe_errors
    if _no_log_input_422(request.url.path):
        log_errors = _safe_422_error_for_log(safe_errors, request.scope.get("route"))

    logger.info(
        f"Request validation error: {len(safe_errors)} errors",
        extra={
            "path": _redact_path(request.url.path),
            "errors": log_errors,
        },
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": "Request validation failed",
            "error_code": "VALIDATION_ERROR",
            "errors": safe_errors,
        },
    )


# ============================================================================
# STARLETTE HTTP EXCEPTION HANDLER (Fallback)
# ============================================================================


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handler for Starlette HTTPException (backward compatibility).

    This handles any HTTPException raised directly (e.g., from dependencies).
    """
    logger.warning(
        f"HTTP {exc.status_code}: {_chi_tiet_an_toan(exc)}",
        extra={
            "status_code": exc.status_code,
            "path": _redact_path(request.url.path),
        },
    )

    # Một số HTTPException chuyên biệt mang sẵn ``error_code`` (vd
    # ``RefreshAbuseLocked`` ở routers/auth.py) vì client phải phân biệt được
    # nhiều nghĩa của cùng một status. Tôn trọng mã đó; mọi HTTPException
    # thường vẫn nhận mã mặc định ``HTTP_<status>`` như trước.
    error_code = getattr(exc, "error_code", None) or f"HTTP_{exc.status_code}"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error_code": error_code,
        },
        headers=getattr(exc, "headers", None),
    )


# ============================================================================
# GENERIC EXCEPTION HANDLER (Catch-all)
# ============================================================================


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Lỗi CSDL (``sqlalchemy.exc.DBAPIError``). CHỈ đổi đúng SQLSTATE của trigger khoá cấu hình K-2
    (``app.models.council_config_lock_ddl``) thành 409 câu dễ hiểu — trigger là tầng chủ sở hữu bất biến, bắt mọi
    đường ghi (sửa / xoá dòng học vụ, đường xét, xoá dây chuyền). Mọi lỗi CSDL khác: NÉM LẠI nguyên trạng ⇒ đi đúng
    đường cũ (``ServerErrorMiddleware`` → ``generic_exception_handler`` 500 + ném tiếp như trước — test client có
    ``raise_app_exceptions`` vẫn thấy ngoại lệ). Đọc SQLSTATE bằng thuộc tính (``db_error_codes``), không đọc chữ."""
    from app.models.council_config_lock_ddl import (
        SQLSTATE_CONFIG_IN_USE,
        MESSAGE_CONFIG_IN_USE,
    )
    from app.repositories.council_decision_repository import db_error_codes

    if db_error_codes(exc)[0] == SQLSTATE_CONFIG_IN_USE:
        logger.warning(
            "config_row_locked_by_signed_decision",
            extra={"path": _redact_path(request.url.path), "method": request.method},
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": MESSAGE_CONFIG_IN_USE, "error_code": "CAU_HINH_DA_DUOC_QUYET_DINH_DUNG"},
        )
    # GĐ2-A: trigger "bảng chỉ tiêu năm đã khoá" (``app.models.admission_quota_ddl``) — bắt mọi đường sửa chỉ tiêu ngành
    # / nhóm / trần (kể cả API sửa học vụ có sẵn) ⇒ 409 câu dễ hiểu, cùng cách như K-2.
    from app.models.admission_quota_ddl import MESSAGE_QUOTA_TABLE_LOCKED, SQLSTATE_QUOTA_TABLE_LOCKED

    if db_error_codes(exc)[0] == SQLSTATE_QUOTA_TABLE_LOCKED:
        logger.warning(
            "quota_table_locked_write_blocked",
            extra={"path": _redact_path(request.url.path), "method": request.method},
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": MESSAGE_QUOTA_TABLE_LOCKED, "error_code": "QUOTA_TABLE_LOCKED"},
        )
    # GĐ2-B: trigger "lần xét không còn nháp" (``app.models.admission_review_ddl`` — ghi điểm sàn khi lần xét không ``draft``,
    # sửa lần xét đã huỷ; bắt cả SQL tay) ⇒ 409 CÙNG ``error_code`` / ``reason_code`` / ``detail`` với lỗi kiểm trước ở dịch vụ
    # (``admission_review_errors.review_session_not_draft`` — MỘT nguồn), KHÔNG có ``status`` (hợp đồng API GĐ2-B bản 4 §1.3).
    # SQLSTATE ``QLC04`` (huỷ lần xét ở mức cô lập khác ``read committed``): xem nhánh riêng dưới — 500 có mã riêng.
    # SQLSTATE ``QLC03`` (dữ liệu lần xét bất biến: xoá lần xét, đổi năm, huỷ khi còn sàn, lượt / dòng đã xong) CỐ Ý KHÔNG đổi ở
    # đây: không route nào của GĐ2-B làm những việc ấy ⇒ gặp là lỗi lập trình ⇒ rơi xuống ``raise exc`` dưới (500
    # ``INTERNAL_ERROR`` — hợp đồng §5 "lỗi không lường; không ghi gì"), như mọi lỗi CSDL khác.
    from app.models.admission_review_ddl import SQLSTATE_REVIEW_SESSION_NOT_DRAFT

    if db_error_codes(exc)[0] == SQLSTATE_REVIEW_SESSION_NOT_DRAFT:
        from app.services.admission_review_errors import review_session_not_draft

        loi = review_session_not_draft()
        logger.warning(
            "review_session_not_draft_write_blocked",
            extra={"path": _redact_path(request.url.path), "method": request.method},
        )
        content = dict(loi.public_payload)
        content["detail"] = loi.detail
        content["error_code"] = loi.error_code
        return JSONResponse(status_code=loi.status_code, content=content)
    # GĐ2-B (Codex 22-11 lượt 2, E5): ``QLC04`` = dịch vụ huỷ chạy sai mức cô lập — lỗi lập trình ⇒ GIỮ 500 (không 409 / 503: người
    # dùng không làm gì được), nhưng thân CỐ ĐỊNH có mã riêng + log mức lỗi kèm SQLSTATE (không câu SQL, không tham số).
    from app.models.admission_review_ddl import SQLSTATE_REVIEW_ISOLATION_UNSUPPORTED

    if db_error_codes(exc)[0] == SQLSTATE_REVIEW_ISOLATION_UNSUPPORTED:
        from app.services.admission_review_errors import (
            ERROR_CODE_REVIEW_ISOLATION_UNSUPPORTED,
            MESSAGE_REVIEW_ISOLATION_UNSUPPORTED,
        )

        logger.error(
            "review_session_cancel_isolation_unsupported",
            extra={
                "path": _redact_path(request.url.path),
                "method": request.method,
                "sqlstate": SQLSTATE_REVIEW_ISOLATION_UNSUPPORTED,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": MESSAGE_REVIEW_ISOLATION_UNSUPPORTED,
                "error_code": ERROR_CODE_REVIEW_ISOLATION_UNSUPPORTED,
            },
        )
    raise exc


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unexpected exceptions.

    Logs the full error and returns a generic 500 response to avoid
    leaking implementation details.
    """
    logger.error(
        # V6 vòng 4: KHÔNG str(exc) — lỗi CSDL mang giá trị (DETAIL, tham số) ⇒ tóm tắt.
        f"Unhandled exception: {type(exc).__name__}: {mo_ta_loi(exc)}",
        extra={
            "path": _redact_path(request.url.path),
            "method": request.method,
        },
        exc_info=True,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected error occurred. Please try again later.",
            "error_code": "INTERNAL_ERROR",
        },
    )


# ============================================================================
# REGISTRATION FUNCTION
# ============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI application.

    Handlers are registered in order of specificity (most specific first).
    This ensures that subclass exceptions are caught before parent classes.

    Args:
        app: The FastAPI application instance

    Example:
        from fastapi import FastAPI
        from app.middleware import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)
    """
    # Register custom exception handlers (most specific first)

    # Service errors (500)
    app.add_exception_handler(CacheServiceError, service_error_handler)
    app.add_exception_handler(SessionServiceError, service_error_handler)
    app.add_exception_handler(SessionRevocationError, service_error_handler)
    app.add_exception_handler(EmailServiceError, service_error_handler)
    app.add_exception_handler(UserServiceError, service_error_handler)
    app.add_exception_handler(WebSocketServiceError, service_error_handler)
    app.add_exception_handler(ServiceError, service_error_handler)

    # Authentication errors (401)
    app.add_exception_handler(InvalidCredentials, authentication_error_handler)
    app.add_exception_handler(InvalidToken, authentication_error_handler)
    app.add_exception_handler(SessionRevokedError, authentication_error_handler)
    app.add_exception_handler(AuthenticationError, authentication_error_handler)

    # Authorization errors (403)
    app.add_exception_handler(PermissionDeniedError, base_app_exception_handler)

    # Resource not found errors (404)
    app.add_exception_handler(UserNotFoundError, resource_not_found_handler)
    app.add_exception_handler(LeadNotFoundError, resource_not_found_handler)
    app.add_exception_handler(OrganizationNotFoundError, resource_not_found_handler)
    app.add_exception_handler(SessionNotFoundError, resource_not_found_handler)
    app.add_exception_handler(ResourceNotFoundError, resource_not_found_handler)

    # Validation errors (400)
    app.add_exception_handler(FileSizeError, validation_error_handler)
    app.add_exception_handler(FileTypeError, validation_error_handler)
    app.add_exception_handler(FileValidationError, validation_error_handler)
    app.add_exception_handler(DataValidationError, validation_error_handler)
    app.add_exception_handler(BusinessRuleViolation, validation_error_handler)
    app.add_exception_handler(ValidationError, validation_error_handler)

    # Duplicate resource (409)
    app.add_exception_handler(DuplicateResourceError, base_app_exception_handler)

    # Base exception handler (catch-all for custom exceptions)
    app.add_exception_handler(BaseAppException, base_app_exception_handler)

    # Pydantic validation errors (422)
    app.add_exception_handler(
        RequestValidationError, pydantic_validation_error_handler
    )

    # Starlette HTTPException (backward compatibility)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Lỗi CSDL: chỉ SQLSTATE trigger K-2 ⇒ 409; còn lại như generic (500)
    from sqlalchemy.exc import DBAPIError

    app.add_exception_handler(DBAPIError, database_error_handler)

    # Generic exception handler (last resort)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("✅ Exception handlers registered successfully")
