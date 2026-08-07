# app/utils/exceptions.py
"""
Custom exception hierarchy for the application.

This module defines all custom exceptions used throughout the application,
replacing direct usage of FastAPI's HTTPException in service and utility layers.

Exception Hierarchy:
    BaseAppException
    ├── ResourceNotFoundError
    │   ├── UserNotFoundError
    │   ├── LeadNotFoundError
    │   ├── OrganizationNotFoundError
    │   └── SessionNotFoundError
    ├── DuplicateResourceError
    ├── ConflictError
    ├── ValidationError
    │   ├── FileValidationError
    │   │   ├── FileSizeError
    │   │   └── FileTypeError
    │   └── DataValidationError
    ├── PermissionDeniedError
    ├── AuthenticationError
    │   ├── InvalidCredentials
    │   ├── InvalidToken
    │   └── SessionRevokedError
    └── ServiceError
        ├── CacheServiceError
        ├── SessionServiceError
        ├── EmailServiceError
        ├── UserServiceError
        └── WebSocketServiceError

Usage:
    In services, raise custom exceptions:
        raise UserNotFoundError(f"User {user_id} not found")

    In routers, catch and convert to HTTPException:
        try:
            user = await user_service.get_user(db, user_id)
        except UserNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    Or use exception handlers in main.py to auto-convert.
"""

from typing import Any, Dict, Optional
from fastapi import status


# ============================================================================
# BASE EXCEPTIONS
# ============================================================================


class BaseAppException(Exception):
    """
    Base class for all custom exceptions in the application.

    Attributes:
        status_code: HTTP status code for this exception (default 500)
        detail: Human-readable error message
        error_code: Machine-readable error code for API consumers
        context: Additional context data for debugging
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An internal server error occurred."
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        detail: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        public_payload: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize exception with custom detail message and context.

        Args:
            detail: Custom error message (overrides class default)
            context: Additional context data (e.g., {"user_id": 123})
            public_payload: Dữ liệu ĐƯỢC PHÉP đi ra tới client, tách hẳn khỏi
                ``context``. Hai thứ này phục vụ hai mục đích đối lập nhau:
                ``context`` là để người vận hành đọc log (có thể chứa id nội
                bộ, tham số truy vấn, dữ liệu nhạy cảm), còn cái này là một
                phần của hợp đồng API. Trộn chúng lại là cách rò dữ liệu debug
                ra ngoài mà không ai kịp nhận ra.
                Giá trị phải **đã serialize sẵn** (JSON thuần): handler đưa
                thẳng vào ``JSONResponse``, nên một ``Decimal`` hay
                ``datetime`` lọt vào đây sẽ biến chính thông báo lỗi thành
                lỗi 500.
        """
        if detail is not None:
            self.detail = detail
        # Khởi tạo theo TỪNG instance. Đặt mặc định ở cấp lớp (kiểu
        # `public_payload: dict = {}`) là chia sẻ MỘT dict cho mọi lần ném:
        # hai lỗi liên tiếp sẽ đắp dữ liệu của nhau, và người dùng thứ hai
        # thấy danh sách phiếu của người thứ nhất.
        self.context = context or {}
        self.public_payload: Dict[str, Any] = public_payload or {}
        super().__init__(self.detail)

    def __str__(self) -> str:
        """String representation of the exception."""
        if self.context:
            return f"{self.detail} (context: {self.context})"
        return self.detail


# ============================================================================
# RESOURCE EXCEPTIONS (404, 409)
# ============================================================================


class ResourceNotFoundError(BaseAppException):
    """Base class for resource not found errors (HTTP 404)."""

    status_code = status.HTTP_404_NOT_FOUND
    detail = "The requested resource was not found."
    error_code = "RESOURCE_NOT_FOUND"


class UserNotFoundError(ResourceNotFoundError):
    """User not found in database."""

    detail = "User not found."
    error_code = "USER_NOT_FOUND"


class LeadNotFoundError(ResourceNotFoundError):
    """Lead not found in database."""

    detail = "Lead not found."
    error_code = "LEAD_NOT_FOUND"


class OrganizationNotFoundError(ResourceNotFoundError):
    """Organization unit not found in database."""

    detail = "Organization unit not found."
    error_code = "ORGANIZATION_NOT_FOUND"


class SessionNotFoundError(ResourceNotFoundError):
    """User session not found in database."""

    detail = "Session not found."
    error_code = "SESSION_NOT_FOUND"


class DuplicateResourceError(BaseAppException):
    """Resource already exists (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    detail = "This resource already exists."
    error_code = "DUPLICATE_RESOURCE"


class ConflictError(BaseAppException):
    """
    State conflict error (HTTP 409).

    Used for:
    - Optimistic locking failures (version mismatch)
    - Concurrent operation conflicts (race conditions)
    - Business logic state conflicts

    Different from DuplicateResourceError which is for unique constraint violations.
    """

    status_code = status.HTTP_409_CONFLICT
    detail = "Request conflicts with current state."
    error_code = "CONFLICT"


class PaymentDuplicateSuspected(ConflictError):
    """Phiếu thu nghi TRÙNG với một phiếu đã có (HTTP 409).

    Không phải lỗi dữ liệu: nộp hai lần cùng số tiền là chuyện có thật, nên
    đây là hàng rào MỀM — người ghi xác nhận rồi gửi lại với
    ``confirm_duplicate=True`` là ghi được. Có mã riêng (không dùng chung
    ``CONFLICT``) vì giao diện phải phân biệt được ca này để hiện danh sách
    phiếu nghi trùng thay vì một thông báo đỏ chung chung.

    Mang theo ``duplicates`` để người ghi **nhìn thấy thứ mình đang bị so
    sánh** rồi mới quyết định — một cảnh báo không kèm bằng chứng thì chỉ còn
    là một cánh cửa để bấm qua.

    ``duplicates`` phải là JSON thuần **đã serialize sẵn** (xem
    ``schemas.finance.DuplicatePaymentInfo``); nhận thẳng ORM object hay
    ``Decimal`` ở đây là biến 409 thành 500 tại tầng handler.
    """

    detail = "Khoản thu này trùng với một phiếu đã ghi nhận gần đây."
    error_code = "PAYMENT_DUPLICATE_SUSPECTED"

    def __init__(
        self,
        detail: Optional[str] = None,
        duplicates: Optional[list] = None,
        duplicates_truncated: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            context=context,
            public_payload={
                "duplicates": duplicates or [],
                "duplicates_truncated": duplicates_truncated,
            },
        )


# ============================================================================
# GONE / CLOSED RESOURCES (410)
# ============================================================================


class GoneError(BaseAppException):
    """Resource is no longer available (HTTP 410).

    Used for hard-deadline cutoffs: round closed, archived offers, etc.
    Subclass BaseAppException directly (NOT ValidationError) so the
    global ``base_app_exception_handler`` (middleware/exception_handlers.py)
    picks up ``status_code=410`` correctly. Subclassing ValidationError
    would map to 400 via the inheritance chain.

    Strict fail-closed semantic — no implicit override. Admin extends
    a closed round via a separate explicit endpoint, NOT by bypassing
    this gate (per plan v4 locked decision 2026-05-28).
    """

    status_code = status.HTTP_410_GONE
    detail = "This resource is no longer available."
    error_code = "GONE"


class RoundClosedError(GoneError):
    """Admission round end_date has passed.

    Raised by create_profile, submit_and_evaluate, and choice CRUD
    modification endpoints (POST/PATCH; DELETE intentionally allowed
    per plan v4 — candidate retains right to withdraw a choice after
    the round closes, but cannot create/modify).
    """

    detail = "Đợt tuyển sinh đã đóng."
    error_code = "ROUND_CLOSED"


# ============================================================================
# VALIDATION EXCEPTIONS (400)
# ============================================================================


class ValidationError(BaseAppException):
    """Base class for validation errors (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Validation error."
    error_code = "VALIDATION_ERROR"


class DataValidationError(ValidationError):
    """Data validation failed."""

    detail = "Data validation failed."
    error_code = "DATA_VALIDATION_ERROR"


class FileValidationError(ValidationError):
    """File validation error base class."""

    detail = "File validation failed."
    error_code = "FILE_VALIDATION_ERROR"


class FileSizeError(FileValidationError):
    """File size exceeds limit."""

    detail = "File size exceeds maximum allowed size."
    error_code = "FILE_SIZE_ERROR"


class FileTypeError(FileValidationError):
    """File type not allowed."""

    detail = "File type not allowed."
    error_code = "FILE_TYPE_ERROR"


class BusinessRuleViolation(ValidationError):
    """
    Business rule violation (HTTP 400).
    
    Used when a business rule is violated, such as:
    - Activating a path without required configuration
    - Updating an archived record
    - Invalid state transition
    """

    detail = "Business rule violation."
    error_code = "BUSINESS_RULE_VIOLATION"


# ============================================================================
# AUTHENTICATION & AUTHORIZATION EXCEPTIONS (401, 403)
# ============================================================================


class AuthenticationError(BaseAppException):
    """Base class for authentication errors (HTTP 401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication required."
    error_code = "AUTHENTICATION_ERROR"
    headers = {"WWW-Authenticate": "Bearer"}


class InvalidCredentials(AuthenticationError):
    """Invalid username or password."""

    detail = "Incorrect username or password."
    error_code = "INVALID_CREDENTIALS"


class InvalidToken(AuthenticationError):
    """JWT token is invalid or expired."""

    detail = "Could not validate credentials (invalid or expired token)."
    error_code = "INVALID_TOKEN"


class SessionRevokedError(AuthenticationError):
    """User session has been revoked."""

    detail = "Your session has been revoked. Please login again."
    error_code = "SESSION_REVOKED"


class SessionExpiredError(AuthenticationError):
    """User session has expired."""

    detail = "Your session has expired. Please login again."
    error_code = "SESSION_EXPIRED"


class PermissionDeniedError(BaseAppException):
    """User does not have permission (HTTP 403)."""

    status_code = status.HTTP_403_FORBIDDEN
    detail = "You do not have permission to perform this action."
    error_code = "PERMISSION_DENIED"


# Alias for convenience (Level-specific IDOR checks)
ForbiddenError = PermissionDeniedError


# ============================================================================
# SERVICE LAYER EXCEPTIONS (500)
# ============================================================================


class ServiceError(BaseAppException):
    """
    Base class for service layer errors.

    These exceptions indicate that something went wrong in the service layer,
    independent of HTTP protocol. They should be caught by routers and
    converted to appropriate HTTP responses.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = "A service error occurred."
    error_code = "SERVICE_ERROR"


class CacheServiceError(ServiceError):
    """Error occurred in cache operations (Redis)."""

    detail = "Cache operation failed."
    error_code = "CACHE_ERROR"


class SessionServiceError(ServiceError):
    """Error occurred in session management."""

    detail = "Session management error."
    error_code = "SESSION_SERVICE_ERROR"


class SessionRevocationError(SessionServiceError):
    """Failed to revoke user session."""

    detail = "Failed to revoke session."
    error_code = "SESSION_REVOCATION_ERROR"


class EmailServiceError(ServiceError):
    """Error occurred in email sending."""

    detail = "Email service error."
    error_code = "EMAIL_ERROR"


class UserServiceError(ServiceError):
    """Error occurred in user service operations."""

    detail = "User service error."
    error_code = "USER_SERVICE_ERROR"


class WebSocketServiceError(ServiceError):
    """Error occurred in WebSocket operations."""

    detail = "WebSocket service error."
    error_code = "WEBSOCKET_ERROR"


# ============================================================================
# TRANSIENT/RETRYABLE EXCEPTIONS
# ============================================================================


class TransientError(ServiceError):
    """
    Base class for transient errors that should trigger retry.

    Used for temporary failures that may succeed on retry, such as:
    - Database lock contention
    - External service timeouts
    - Rate limiting

    Celery tasks can catch this and call self.retry() with appropriate parameters.
    """

    detail = "A transient error occurred. Please retry."
    error_code = "TRANSIENT_ERROR"


class LockContentionError(TransientError):
    """
    Database lock contention error.

    Raised when a database row lock cannot be obtained (e.g., FOR UPDATE SKIP LOCKED).
    The operation should be retried after a short delay.
    """

    detail = "Database lock contention. Please retry."
    error_code = "LOCK_CONTENTION"


# ============================================================================
# NOTIFICATION EXCEPTIONS
# ============================================================================


class NotificationConfigError(ServiceError):
    """
    Raised when notification rule configuration is invalid at runtime.

    Examples: resolver deserialization failure, missing required fields.
    Dispatcher catches this to log and skip (fail-closed, no fallback).
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = "Notification configuration error."
    error_code = "NOTIFICATION_CONFIG_ERROR"


class DormSyncDisabledError(ServiceError):
    """
    Raised when the dorm sync feature is called while ``DORM_SYNC_ENABLED`` is off.

    🔴 Tách RIÊNG khỏi ``DormSyncConfigError``: "chưa bật tính năng" là trạng
    thái bình thường của mọi môi trường dev/CI, còn "bật mà thiếu khoá" là cấu
    hình hỏng cần người sửa. Gộp hai ca vào một mã lỗi thì người vận hành không
    phân biệt được "chưa cấu hình" với "cấu hình sai".
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = "Tính năng đồng bộ ký túc xá chưa được bật trên máy chủ này."
    error_code = "DORM_SYNC_DISABLED"


class DormSyncGuardError(ServiceError):
    """
    Raised when a source/target identity guard refuses to proceed.

    🔴 Đây là hàng rào chặn ca tệ nhất: một backend dev trỏ nhầm, hoặc một bản
    clone của production, hạ cờ đủ-điều-kiện của cả một cohort thật. Guard hỏi
    thẳng database ``current_database()`` và ``system_identifier`` — không tin
    nhãn trong file cấu hình.

    ⚠️ Không bao giờ "bỏ qua khi gặp trở ngại". Đọc không được
    ``system_identifier`` trùng đúng với ca "đây không phải cluster ta nghĩ".
    """

    status_code = status.HTTP_409_CONFLICT
    # ⚠️ Câu này ra tới client, và lớp này nay che CẢ hai hàng rào — nguồn lẫn
    # đích. Nói riêng về "nguồn" sẽ chỉ người đọc đi kiểm sai chỗ đúng vào lúc
    # họ chỉ có mỗi dòng này để đi tiếp. Ca đích có lớp con riêng ngay dưới,
    # mang `error_code` riêng để client rẽ nhánh được mà không cần biết
    # hostname hay project ref.
    detail = "Danh tính nguồn hoặc đích không khớp khai báo; từ chối ghi."
    error_code = "DORM_SYNC_GUARD_MISMATCH"

    def __init__(self, operator_detail: str, context: Optional[Dict[str, Any]] = None):
        """
        🔴 ``detail`` CỐ Ý không nhận chuỗi chi tiết.

        ``base_app_exception_handler`` đưa ``detail`` thẳng ra HTTP. Thông điệp
        của guard chứa tên database thật và ``system_identifier`` của cluster —
        thứ mô tả hạ tầng nguồn, và không có lý do nào để một client biết.

        Chi tiết đi vào ``context`` (chỉ log) và ``operator_detail`` (để vỏ CLI
        in cho người vận hành đang ngồi trước terminal). ``__str__`` trả bản
        chi tiết nên ``print(f"✗ {exc}")`` ở CLI vẫn nói đủ.
        """
        super().__init__(
            detail=None,
            context={**(context or {}), "operator_detail": operator_detail},
        )
        self.operator_detail = operator_detail

    def __str__(self) -> str:
        return self.operator_detail


class DormSyncTargetMismatchError(DormSyncGuardError):
    """URL đích không thuộc project Supabase đã được duyệt.

    🔴 Tách khỏi lớp cha để người vận hành biết ĐI KIỂM CHỖ NÀO. Hai hàng rào
    hỏi hai câu khác nhau — "đọc từ database nào" và "gửi tới project nào" — và
    chúng hỏng vì hai lý do khác nhau: một bên là stack trỏ nhầm nguồn, bên kia
    là biến ``DORM_SUPABASE_URL`` / ``DORM_SYNC_TARGET_PROJECT_REF`` lệch nhau.
    Trả cùng một mã cho cả hai thì dòng lỗi duy nhất họ có lại chỉ sai hướng.

    ⚠️ ``detail`` vẫn KHÔNG mang hostname hay project ref — đó là mô tả hạ
    tầng. Bản chi tiết nằm ở ``operator_detail``.
    """

    detail = "Đích đồng bộ không thuộc project đã được duyệt; từ chối gửi."
    error_code = "DORM_SYNC_TARGET_MISMATCH"


class DormSyncTokenError(ServiceError):
    """Token xem trước không hợp lệ, hết hạn, hoặc không thuộc người đang gọi.

    🔴 400 chứ không 401/403: người gọi ĐÃ qua cổng quyền (endpoint là
    admin-only). Thứ hỏng là cái vé họ mang theo — hết hạn, bị sửa, hoặc của
    người khác — chứ không phải danh tính của họ. Trả 401 ở đây sẽ đẩy frontend
    đi làm mới phiên đăng nhập cho một sự cố mà cách xử đúng là bấm lại nút
    "Xem trước".

    ⚠️ ``detail`` ở cấp lớp KHÔNG nói token hỏng ở khâu nào. Phân biệt "chữ ký
    sai" với "hết hạn" cho phía ngoài là đưa cho người đang dò một tín hiệu để
    dò tiếp. Người vận hành đọc bản chi tiết ở log.
    """

    status_code = status.HTTP_409_CONFLICT
    detail = "Phiếu xem trước không dùng được. Bấm Xem trước lại rồi thử lại."
    error_code = "DORM_SYNC_TOKEN_INVALID"

    def __init__(self, operator_detail: str, context: Optional[Dict[str, Any]] = None):
        """
        🔴 ``detail`` CỐ Ý không nhận chuỗi chi tiết — cùng khuôn với
        ``DormSyncGuardError``.

        Khai một ``detail`` trung tính ở cấp lớp là chưa đủ: ``ServiceError``
        nhận chuỗi qua constructor và chuỗi đó ghi đè giá trị lớp, nên
        ``DormSyncTokenError("chữ ký sai")`` đưa thẳng lý do ra HTTP. Đã đo:
        ``detail`` trả về đúng chuỗi nội bộ.

        Mà lý do mới là thứ không được ra ngoài. Phân biệt "chữ ký sai" với
        "hết hạn" hay "sai actor" cho phía ngoài là đưa cho người đang dò một
        tín hiệu để dò tiếp: họ biết chuỗi nào bị chặn vì chưa ký đúng, chuỗi
        nào đã ký đúng mà chỉ quá giờ.

        MỌI lỗi token ra ngoài bằng cùng một ``detail`` và cùng một
        ``error_code``; bản chi tiết đi vào ``context`` (chỉ log) và
        ``operator_detail``.
        """
        super().__init__(
            detail=None,
            context={**(context or {}), "operator_detail": operator_detail},
        )
        self.operator_detail = operator_detail

    def __str__(self) -> str:
        return self.operator_detail


class DormSyncConfigError(ServiceError):
    """
    Raised when ``DORM_SYNC_ENABLED`` is on but required settings are missing.

    Fail-closed: không đoán giá trị nào cả. Một đường ghi có thể hạ cờ
    đủ-điều-kiện của cả một khoá học mà tự đoán đích đến là đường sẽ ghi nhầm
    chỗ vào một ngày nào đó.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = "Cấu hình đồng bộ ký túc xá không đầy đủ."
    error_code = "DORM_SYNC_CONFIG_ERROR"


# ============================================================================
# LEGACY SUPPORT (Deprecated)
# ============================================================================


class BadRequest(ValidationError):
    """
    DEPRECATED: Use ValidationError or specific subclasses instead.
    Kept for backward compatibility.
    """

    detail = "Bad request."
    error_code = "BAD_REQUEST"


# ============================================================================
# EXCEPTION MAPPING TABLE (for documentation)
# ============================================================================

EXCEPTION_HTTP_STATUS_MAP = {
    # 400 Bad Request
    ValidationError: 400,
    DataValidationError: 400,
    FileValidationError: 400,
    FileSizeError: 400,
    FileTypeError: 400,
    BadRequest: 400,
    # 401 Unauthorized
    AuthenticationError: 401,
    InvalidCredentials: 401,
    InvalidToken: 401,
    SessionRevokedError: 401,
    # 403 Forbidden
    PermissionDeniedError: 403,
    # 404 Not Found
    ResourceNotFoundError: 404,
    UserNotFoundError: 404,
    LeadNotFoundError: 404,
    OrganizationNotFoundError: 404,
    SessionNotFoundError: 404,
    # 409 Conflict
    DuplicateResourceError: 409,
    ConflictError: 409,
    # 410 Gone
    GoneError: 410,
    RoundClosedError: 410,
    # 500 Internal Server Error
    BaseAppException: 500,
    ServiceError: 500,
    CacheServiceError: 500,
    SessionServiceError: 500,
    SessionRevocationError: 500,
    EmailServiceError: 500,
    UserServiceError: 500,
    WebSocketServiceError: 500,
    # 503 Service Unavailable (Transient/Retryable)
    TransientError: 503,
    LockContentionError: 503,
}
