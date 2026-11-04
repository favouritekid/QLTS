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


def _khong_log_input_422(path: str) -> bool:
    """MỘT vị từ: route mà lỗi 422 chỉ được ghi vào log ở dạng ĐÃ CHUẨN HOÁ
    (:func:`_loi_422_an_toan_de_log`) — không ``input`` / ``msg`` / ``ctx``, ``loc`` chỉ giữ
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
_NOI_THAM_SO_422 = frozenset({"body", "query", "path", "header", "cookie"})
# Nhãn cố định thay cho mọi phần tử chuỗi của ``loc`` không chứng minh được là tên trường
# khai trong schema (khoá JSON thừa, khoá của dict, nhãn nhánh union …).
NHAN_LOC_KHONG_KHAI = "<khong-khai>"


def _ten_khai_cua_kieu(kieu, ra: set, da_xem: set) -> None:
    """Gom tên (+ alias) mọi trường của các model Pydantic nằm trong chú thích kiểu ``kieu``
    (đệ quy qua ``Optional`` / ``List`` / ``Dict`` / ``Union`` / model lồng)."""
    if id(kieu) in da_xem:
        return
    da_xem.add(id(kieu))
    if isinstance(kieu, type) and issubclass(kieu, BaseModel):
        for ten, f in kieu.model_fields.items():
            ra.add(ten)
            if isinstance(f.alias, str):
                ra.add(f.alias)
            _ten_khai_cua_kieu(f.annotation, ra, da_xem)
        return
    for con in typing.get_args(kieu):
        _ten_khai_cua_kieu(con, ra, da_xem)


def _ten_khai_cua_route(route) -> frozenset:
    """Tên tham số + tên trường schema mà ROUTE đã khớp khai (body / query / path / header /
    cookie, kể cả của dependency con). Không đọc được ⇒ tập RỖNG (fail-closed: mọi chuỗi
    của ``loc`` thành nhãn cố định)."""
    ra: set = set()
    try:
        con = [getattr(route, "dependant")]
        da_xem: set = set()
        while con:
            d = con.pop()
            for nhom in (
                "path_params",
                "query_params",
                "header_params",
                "cookie_params",
                "body_params",
            ):
                for f in getattr(d, nhom, None) or ():
                    for ten in (getattr(f, "name", None), getattr(f, "alias", None)):
                        if isinstance(ten, str):
                            ra.add(ten)
                    _ten_khai_cua_kieu(
                        getattr(getattr(f, "field_info", None), "annotation", None),
                        ra,
                        da_xem,
                    )
            con.extend(getattr(d, "dependencies", None) or ())
    except Exception:  # noqa: BLE001 — bộ chuẩn hoá log không được làm hỏng request
        return frozenset()
    return frozenset(ra)


def _loi_422_an_toan_de_log(errors: list, route) -> list:
    """MỘT chỗ chuẩn hoá lỗi 422 trước khi ghi log cho MỌI route của
    :func:`_khong_log_input_422` (F217). Chỉ giữ thứ CHỨNG MINH được an toàn:

    * ``type`` — mã lỗi do Pydantic / mã nguồn đặt, không lấy từ dữ liệu gửi lên;
    * ``loc`` đã chuẩn hoá — số nguyên (chỉ số phần tử danh sách) giữ nguyên; phần tử ĐẦU
      thuộc tập nơi tham số cố định giữ nguyên; chuỗi khác CHỈ giữ khi là tên trường / tham
      số khai trong schema của route (:func:`_ten_khai_cua_route`), còn lại thay
      :data:`NHAN_LOC_KHONG_KHAI` (khoá JSON thừa có thể chính là một CCCD).

    Bỏ hẳn ``input``, ``msg``, ``ctx``, ``url`` (``msg`` / ``ctx`` có thể nội suy giá trị)."""
    ten_khai = _ten_khai_cua_route(route) if route is not None else frozenset()
    ra = []
    for e in errors:
        loc = []
        for i, p in enumerate(e.get("loc") or ()):
            if isinstance(p, int) and not isinstance(p, bool):
                loc.append(p)
            elif isinstance(p, str) and (
                (i == 0 and p in _NOI_THAM_SO_422) or (i > 0 and p in ten_khai)
            ):
                loc.append(p)
            else:
                loc.append(NHAN_LOC_KHONG_KHAI)
        t = e.get("type")
        ra.append(
            {"type": t if isinstance(t, str) else NHAN_LOC_KHONG_KHAI, "loc": loc}
        )
    return ra


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

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": exc.detail,
            "error_code": exc.error_code,
        },
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
    if _khong_log_input_422(request.url.path):
        log_errors = _loi_422_an_toan_de_log(safe_errors, request.scope.get("route"))

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

    # Generic exception handler (last resort)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("✅ Exception handlers registered successfully")
