# app/utils/exceptions.py
from fastapi import status  # Bỏ HTTPException và JSONResponse khỏi đây

# === Định nghĩa lại các lớp Exception tùy chỉnh ===


class BaseAppException(Exception):
    """Lớp cơ sở cho các exception tùy chỉnh trong ứng dụng."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An internal server error occurred."

    def __init__(self, detail: str = None):
        if detail is not None:
            self.detail = detail


class ResourceNotFoundError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_404_NOT_FOUND
    detail = "The requested resource was not found."


class DuplicateResourceError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_409_CONFLICT
    detail = "This resource already exists."


class PermissionDeniedError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_403_FORBIDDEN
    detail = "You do not have permission to perform this action."


class AuthenticationError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication required."
    headers = {"WWW-Authenticate": "Bearer"}  # Giữ lại headers nếu cần


class InvalidCredentials(AuthenticationError):  # Kế thừa từ AuthenticationError
    detail = "Incorrect username or password."


class InvalidToken(AuthenticationError):  # Kế thừa từ AuthenticationError
    detail = "Could not validate credentials (invalid or expired token)."


class BadRequest(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Bad request."


# === KẾT THÚC ĐỊNH NGHĨA LẠI ===

# Các global handler đã được định nghĩa trong main.py, không cần ở đây nữa.
