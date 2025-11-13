# app/utils/file_helpers.py
import os
import uuid
from pathlib import Path  # 👈 *** THÊM IMPORT NÀY ***

import aiofiles
import magic
import structlog
from fastapi import HTTPException, UploadFile, status

from ..config import settings

log = structlog.get_logger(__name__)
# === ⭐️ SỬ DỤNG GIÁ TRỊ TỪ settings ⭐️ ===
# Chuyển thành set để check nhanh hơn
ALLOWED_EXTENSIONS = set(settings.ALLOWED_AVATAR_EXTENSIONS)
ALLOWED_MIME_TYPES = set(settings.ALLOWED_AVATAR_MIME_TYPES)
MAX_CONTENT_LENGTH = settings.MAX_AVATAR_CONTENT_LENGTH  # Đã tính toán trong config.py
UPLOAD_FOLDER = (
    settings.AVATAR_UPLOAD_FOLDER
)  # Đã tính toán và đảm bảo tồn tại trong config.py
# === KẾT THÚC SỬ DỤNG settings ===


async def save_avatar(file: UploadFile, old_avatar_url: str = None) -> str:
    """
    Lưu file avatar một cách an toàn:
    1. Kiểm tra extension.
    2. Đọc file vào bộ nhớ.
    3. Kiểm tra kích thước thật (size).
    4. Kiểm tra nội dung (magic bytes/MIME type).
    5. Tạo tên file duy nhất (UUID).
    6. Kiểm tra Path Traversal.
    7. Xóa file cũ (nếu có).
    8. Lưu file mới.

    Trả về URL tương đối của file đã lưu.
    Ném HTTPException nếu có lỗi.
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No file selected."
        )

    # 1. Kiểm tra extension (bước lọc cơ bản)
    file_extension = ""
    if "." in file.filename:
        # Lấy phần sau dấu chấm cuối cùng
        file_extension = file.filename.rsplit(".", 1)[-1].lower()

    if not file_extension or file_extension not in ALLOWED_EXTENSIONS:
        log.warning(
            "Upload rejected: Invalid file extension",
            filename=file.filename,
            ext=file_extension,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Allowed: {', '.join(sorted(list(ALLOWED_EXTENSIONS)))}.",
        )

    # 2. Đọc file theo chunks để tránh DoS (Security Fix: CVSS 7.5 HIGH)
    # OLD CODE: await file.read() - Đọc toàn bộ vào RAM trước khi check size
    # NEW CODE: Đọc từng chunk 8KB, check size mỗi lần để reject sớm
    try:
        content_chunks = []
        total_size = 0
        CHUNK_SIZE = 8192  # 8KB chunks

        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break

            total_size += len(chunk)

            # ✅ SECURITY FIX: Check size NGAY sau mỗi chunk
            # Attacker upload 2GB → Bị reject sau 5MB → Không crash server
            if total_size > MAX_CONTENT_LENGTH:
                log.warning(
                    "Upload rejected: File size exceeded limit (detected during chunked read)",
                    filename=file.filename,
                    size=total_size,
                    limit=MAX_CONTENT_LENGTH,
                )
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB.",
                )

            content_chunks.append(chunk)

        # Gộp tất cả chunks lại
        content = b''.join(content_chunks)

    except HTTPException:
        raise  # Re-raise HTTP exceptions (413, etc.)
    except Exception as e:
        log.error(
            "Failed to read uploaded file content", filename=file.filename, error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read file content.",
        )

    # 3. Kiểm tra kích thước thật của nội dung đã đọc (double-check)
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded."
        )
    if len(content) > MAX_CONTENT_LENGTH:
        log.warning(
            "Upload rejected: File size exceeded limit",
            filename=file.filename,
            size=len(content),
            limit=MAX_CONTENT_LENGTH,
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,  # <-- Thay đổi ở đây
            detail=f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB.",
        )

    # 4. Kiểm tra Magic Bytes (MIME type) - Bước bảo mật quan trọng nhất!
    try:
        mime_type = magic.from_buffer(content, mime=True)
        if mime_type not in ALLOWED_MIME_TYPES:
            log.warning(
                "Upload rejected: Invalid MIME type detected",
                filename=file.filename,
                detected_mime=mime_type,
                allowed_mimes=list(ALLOWED_MIME_TYPES),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                # Không tiết lộ MIME type chi tiết cho client
                detail=f"File content is not a valid image format. Allowed: {', '.join(sorted(list(ALLOWED_EXTENSIONS)))}.",
            )
        log.debug("MIME type validated", filename=file.filename, mime_type=mime_type)
    except HTTPException:
        raise  # Ném lại lỗi 400 từ check MIME
    except Exception as e:
        log.error(
            "Magic bytes check failed",
            filename=file.filename,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not verify file content.",
        )

    # --- Nếu tất cả kiểm tra đã qua ---

    # 5. Tạo tên file mới duy nhất (an toàn)
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)

    # 6. KIỂM TRA PATH TRAVERSAL (DEFENSE-IN-DEPTH)
    try:
        # Lấy đường dẫn tuyệt đối, chuẩn hóa (resolve) mọi '..'
        # strict=True đảm bảo thư mục upload thực sự tồn tại (đã được tạo trong config.py)
        upload_folder_abs = Path(UPLOAD_FOLDER).resolve(strict=True)
        # strict=False vì file chưa tồn tại khi resolve
        file_path_abs = Path(file_path).resolve(strict=False)

        # Kiểm tra xem đường dẫn file có nằm TRONG thư mục upload không
        # Dùng commonpath hoặc is_relative_to (Python 3.9+)
        # if not file_path_abs.is_relative_to(upload_folder_abs): # Cần Python 3.9+
        if os.path.commonpath([upload_folder_abs, file_path_abs]) != str(
            upload_folder_abs
        ):
            log.critical(
                "🚨 PATH TRAVERSAL ATTEMPT DETECTED!",
                filename=file.filename,  # Log tên file gốc để điều tra
                generated_path=file_path,
                resolved_path=str(file_path_abs),
                upload_dir=str(upload_folder_abs),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file path detected.",  # Thông báo chung chung cho client
            )
    except HTTPException:
        raise  # Ném lại lỗi 400
    except Exception as e:
        # Bắt lỗi nếu resolve path thất bại (vd: tên file chứa ký tự không hợp lệ)
        log.error(
            "Path validation/resolution failed", filename=file.filename, error=str(e)
        )
        raise HTTPException(
            status_code=400, detail="Invalid characters in filename or path."
        )

    # 7. Xóa file avatar cũ (nếu có) - An toàn hơn
    if old_avatar_url:
        try:
            # Chỉ lấy phần tên file từ URL (vd: /static/.../abc.png -> abc.png)
            old_file_name = os.path.basename(old_avatar_url)

            # Kiểm tra cơ bản tên file cũ (vẫn giữ)
            if (
                not old_file_name
                or ".." in old_file_name
                or "/" in old_file_name
                or "\\" in old_file_name
            ):
                log.warning(
                    "Invalid old avatar URL format, skipping deletion",
                    old_url=old_avatar_url,
                )
                return  # Thoát khỏi hàm try-catch

            old_file_path = os.path.join(UPLOAD_FOLDER, old_file_name)

            # Kiểm tra lại đường dẫn tuyệt đối trước khi xóa (vẫn giữ)
            old_file_path_abs = Path(old_file_path).resolve(strict=False)
            if os.path.commonpath([upload_folder_abs, old_file_path_abs]) != str(
                upload_folder_abs
            ):
                log.warning(
                    "Skipping deletion of potentially unsafe old avatar path",
                    old_url=old_avatar_url,
                    resolved_path=str(old_file_path_abs),
                )
                return  # Thoát khỏi hàm try-catch

            # ✅ SỬA LỖI: Áp dụng EAFP
            # Cứ thử xóa, nếu không tìm thấy file thì bỏ qua
            os.remove(old_file_path)
            log.info("Old avatar deleted successfully", path=old_file_path)

        except FileNotFoundError:
            # Đây là trường hợp file đã bị xóa (bởi process khác hoặc không tồn tại)
            # Đây là hành vi bình thường, không cần log error
            log.debug(
                "Old avatar file not found, nothing to delete",
                path=old_file_path_abs,  # Dùng path đã resolve
            )
        except Exception as e:
            # Bắt các lỗi khác (ví dụ: không có quyền xóa)
            log.error(
                "Failed to delete old avatar file (non-FileNotFound error)",
                url=old_avatar_url,
                error=str(e),
            )

    # 8. Lưu file mới (ghi nội dung đã đọc và validate)
    try:
        async with aiofiles.open(file_path, "wb") as buffer:
            await buffer.write(content)
        log.info("New avatar saved successfully", path=file_path, size=len(content))
    except Exception as e:
        log.error("Failed to save new avatar file", path=file_path, error=str(e))
        # Cố gắng xóa file vừa tạo nếu lưu thất bại
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save avatar file.",
        )

    # Trả về URL tương đối để lưu vào DB
    # Tính toán đường dẫn tương đối từ thư mục static gốc
    try:
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
        relative_upload_path = os.path.relpath(UPLOAD_FOLDER, static_dir)
        # Đảm bảo dùng dấu / cho URL
        url_path = (
            f"/static/{relative_upload_path.replace(os.sep, '/')}/{unique_filename}"
        )
        return url_path
    except ValueError:
        log.error(
            "Could not determine relative path for avatar URL",
            upload_folder=UPLOAD_FOLDER,
        )
        # Fallback trả về đường dẫn tuyệt đối (ít lý tưởng hơn)
        return file_path
