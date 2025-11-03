# tests/utils/test_file_helpers.py
# -*- coding: utf-8 -*-
import pytest
import pytest_asyncio
import uuid
import os
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from fastapi import UploadFile, HTTPException, status
import logging # Thêm logging

# Import các thành phần cần test và config
from app.utils import file_helpers
from app.config import settings # Dùng settings làm "constants" cho file này

log = logging.getLogger(__name__)

# === Lớp Giả lập UploadFile (Giữ nguyên như trong context) ===
class MockUploadFile:
    """Giả lập đối tượng UploadFile của FastAPI."""
    def __init__(self, filename: str, content: bytes, content_type: str = "image/png"):
        self.filename = filename
        self._content = content
        self.content_type = content_type
        self.file = MagicMock()
        self.read_called = False
        async def mock_read():
            if self.read_called: return b''
            self.read_called = True
            if self._content is None: raise IOError("Simulated file read error")
            return self._content
        self.read = AsyncMock(side_effect=mock_read)
        self.seek = MagicMock()
        self.tell = MagicMock()
    def __repr__(self):
        return f"<MockUploadFile filename={self.filename}>"

# === Fixture để Mock các Dependencies (Giữ nguyên như trong context) ===
@pytest_asyncio.fixture(autouse=True)
def mock_dependencies(mocker):
    """Mock các thư viện bên ngoài mà file_helpers sử dụng."""
    
    # 1. Mock aiofiles
    mock_aio_open = mocker.patch('aiofiles.open')
    mock_file_handle = AsyncMock()
    mock_file_handle.write = AsyncMock(return_value=None)
    async_context_manager_mock = AsyncMock()
    async_context_manager_mock.__aenter__.return_value = mock_file_handle
    async_context_manager_mock.__aexit__.return_value = None
    mock_aio_open.return_value = async_context_manager_mock

    # 2. Mock magic (mặc định là PNG hợp lệ)
    mock_magic = mocker.patch('app.utils.file_helpers.magic.from_buffer')
    mock_magic.return_value = "image/png" # Mặc định là 'image/png'

    # 3. Mock os (giả lập file cũ tồn tại và commonpath thành công)
    mock_os_path_exists = mocker.patch('app.utils.file_helpers.os.path.exists', return_value=True)
    mock_os_remove = mocker.patch('app.utils.file_helpers.os.remove')
    # Giả lập commonpath trả về đúng thư mục upload (cho trường hợp thành công)
    mock_commonpath = mocker.patch('app.utils.file_helpers.os.path.commonpath', return_value=str(settings.AVATAR_UPLOAD_FOLDER))
    # Mock relpath để trả về đường dẫn URL mong đợi
    mocker.patch('app.utils.file_helpers.os.path.relpath', return_value='uploads/avatars')

    # 4. Mock uuid
    mock_uuid4 = mocker.patch('app.utils.file_helpers.uuid.uuid4')
    mock_uuid4.return_value = uuid.UUID('12345678-1234-5678-1234-567812345678')

    # 5. Mock Path.resolve (quan trọng cho security check)
    # Cần mock cả `strict=True` (cho thư mục) và `strict=False` (cho file)
    mock_path_instance = MagicMock()
    # Giả lập resolve() trả về chính nó (đơn giản hóa) hoặc một path object an toàn
    safe_folder_path = MagicMock()
    safe_folder_path.__str__.return_value = str(settings.AVATAR_UPLOAD_FOLDER) # Đảm bảo so sánh chuỗi hoạt động
    
    safe_file_path = MagicMock()
    
    # Phân biệt resolve cho thư mục và file
    def resolve_side_effect(strict=False):
        if strict: # strict=True dùng cho UPLOAD_FOLDER
            return safe_folder_path
        return safe_file_path # strict=False dùng cho file_path

    mock_path_instance.resolve.side_effect = resolve_side_effect
    
    # Mock Path() constructor để trả về instance đã mock
    mocker.patch('app.utils.file_helpers.Path', return_value=mock_path_instance)

    return {
        "aio_open": mock_aio_open,
        "aio_handle": mock_file_handle,
        "magic": mock_magic,
        "os_path_exists": mock_os_path_exists,
        "os_remove": mock_os_remove,
        "uuid4": mock_uuid4,
        "commonpath": mock_commonpath,
        "Path": mock_path_instance
    }

# === Tests cho save_avatar (Mục 4.1) ===

@pytest.mark.asyncio
async def test_save_avatar_success(mock_dependencies):
    """Test 4.1: Lưu avatar thành công (không có file cũ)."""
    log.info("--- Running: test_save_avatar_success ---")
    file = MockUploadFile(filename="avatar.png", content=b"fake_png_bytes")

    expected_uuid = "12345678-1234-5678-1234-567812345678"
    expected_filename = f"{expected_uuid}.png"
    expected_path = os.path.join(settings.AVATAR_UPLOAD_FOLDER, expected_filename)
    expected_url = f"/static/uploads/avatars/{expected_filename}"

    # --- Action ---
    result_url = await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- Assert Response (Return Value) ---
    assert result_url == expected_url, "URL trả về không chính xác"

    # --- Assert Side Effects (Mocks) ---
    # 1. Đọc file 1 lần
    file.read.assert_awaited_once()
    # 2. Kiểm tra MIME type
    mock_dependencies["magic"].assert_called_once_with(b"fake_png_bytes", mime=True)
    # 3. Security check (Path.resolve và commonpath)
    mock_dependencies["Path"].resolve.assert_any_call(strict=True) # Kiểm tra UPLOAD_FOLDER
    mock_dependencies["Path"].resolve.assert_any_call(strict=False) # Kiểm tra file_path
    mock_dependencies["commonpath"].assert_called_once()
    # 4. Ghi file mới
    mock_dependencies["aio_open"].assert_called_once_with(expected_path, "wb")
    mock_dependencies["aio_handle"].write.assert_awaited_once_with(b"fake_png_bytes")
    # 5. Không xóa file cũ
    mock_dependencies["os_remove"].assert_not_called()
    
    # --- Assert DB/Cache/Celery ---
    # (Không áp dụng cho unit test này)
    
    log.info("save_avatar success verified.")
    log.info("--- Finished: test_save_avatar_success ---")


@pytest.mark.asyncio
async def test_save_avatar_success_with_old_file(mock_dependencies):
    """Test 4.1: Lưu avatar thành công VÀ xóa file cũ."""
    log.info("--- Running: test_save_avatar_success_with_old_file ---")
    file = MockUploadFile(filename="new_avatar.jpg", content=b"fake_jpg_bytes")
    mock_dependencies["magic"].return_value = "image/jpeg" # Giả lập file JPG

    old_url = "/static/uploads/avatars/old_file_123.jpg"
    expected_old_filename = "old_file_123.jpg"
    expected_old_path = os.path.join(settings.AVATAR_UPLOAD_FOLDER, expected_old_filename)
    
    # Cấu hình mock path.exists trả về True cho file cũ
    mock_dependencies["os_path_exists"].return_value = True

    # --- Action ---
    await file_helpers.save_avatar(file, old_avatar_url=old_url)

    # --- Assert Side Effects ---
    # 1. Kiểm tra magic (JPG)
    mock_dependencies["magic"].assert_called_once_with(b"fake_jpg_bytes", mime=True)
    # 2. Kiểm tra file cũ đã bị xóa
    # Hàm save_avatar dùng os.path.exists và os.remove
    mock_dependencies["os_path_exists"].assert_called_once_with(expected_old_path)
    mock_dependencies["os_remove"].assert_called_once_with(expected_old_path)
    log.info("Old avatar deleted successfully.")
    
    log.info("--- Finished: test_save_avatar_success_with_old_file ---")


@pytest.mark.asyncio
async def test_save_avatar_invalid_extension(mock_dependencies):
    """Test 4.1: Lỗi 400 - Đuôi file không hợp lệ (.txt)."""
    log.info("--- Running: test_save_avatar_invalid_extension ---")
    file = MockUploadFile(filename="virus.txt", content=b"i am a virus")

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    # Kiểm tra message lỗi cụ thể
    allowed_exts_str = ', '.join(sorted(list(settings.ALLOWED_AVATAR_EXTENSIONS)))
    assert exc_info.value.detail == f"Unsupported file format. Allowed: {allowed_exts_str}."
    
    # Đảm bảo không có hành động ghi file hay check magic
    mock_dependencies["magic"].assert_not_called()
    mock_dependencies["aio_open"].assert_not_called()
    log.info("Invalid extension correctly blocked (400) with specific message.")
    
    log.info("--- Finished: test_save_avatar_invalid_extension ---")


@pytest.mark.asyncio
async def test_save_avatar_file_too_large(mock_dependencies):
    """Test 4.1: Lỗi 413 - File quá lớn."""
    log.info("--- Running: test_save_avatar_file_too_large ---")
    large_content = b"a" * (settings.MAX_AVATAR_CONTENT_LENGTH + 1)
    file = MockUploadFile(filename="too_big.png", content=large_content)

    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- SỬA/THÊM ASSERTION NÀY ---
    assert exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE # <-- Đảm bảo dùng hằng số mới
    # --- KẾT THÚC SỬA ---
    assert exc_info.value.detail == f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB."

    mock_dependencies["magic"].assert_not_called()
    mock_dependencies["aio_open"].assert_not_called()
    log.info("File too large correctly blocked (413) with specific message.")

    log.info("--- Finished: test_save_avatar_file_too_large ---")


@pytest.mark.asyncio
async def test_save_avatar_invalid_mime_type(mock_dependencies):
    """Test 4.1: Lỗi 400 - Đuôi file hợp lệ (.png) nhưng nội dung là text."""
    log.info("--- Running: test_save_avatar_invalid_mime_type ---")
    file = MockUploadFile(filename="fake.png", content=b"this is actually a text file")

    # Giả lập magic phát hiện đây là text
    mock_dependencies["magic"].return_value = "text/plain"

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    allowed_exts_str = ', '.join(sorted(list(settings.ALLOWED_AVATAR_EXTENSIONS)))
    assert exc_info.value.detail == f"File content is not a valid image format. Allowed: {allowed_exts_str}."
    
    # Đảm bảo đã check magic, nhưng chưa ghi file
    mock_dependencies["magic"].assert_called_once_with(b"this is actually a text file", mime=True)
    mock_dependencies["aio_open"].assert_not_called()
    log.info("Invalid MIME type correctly blocked (400) with specific message.")

    log.info("--- Finished: test_save_avatar_invalid_mime_type ---")


@pytest.mark.asyncio
async def test_save_avatar_path_traversal_attempt(mocker): # Mock cục bộ
    """Test 4.1: Lỗi 400 - Ngăn chặn Path Traversal."""
    log.info("--- Running: test_save_avatar_path_traversal_attempt ---")
    # Mock các thư viện bên ngoài (tương tự mock_dependencies nhưng chỉ mock cái cần thiết)
    mocker.patch('aiofiles.open', new_callable=AsyncMock)
    mocker.patch('app.utils.file_helpers.magic.from_buffer', return_value="image/png")
    mocker.patch('app.utils.file_helpers.uuid.uuid4', return_value=uuid.UUID('12345678-1234-5678-1234-567812345678'))
    
    # --- Mock quan trọng cho Path Traversal ---
    # Giả lập Path('...').resolve() trả về đường dẫn nguy hiểm
    mock_path_instance = MagicMock()
    
    # Giả lập resolve() cho thư mục (strict=True)
    safe_folder_path = MagicMock()
    safe_folder_path.__str__.return_value = str(settings.AVATAR_UPLOAD_FOLDER)
    
    # Giả lập resolve() cho file (strict=False) trả về đường dẫn đã thoát ra ngoài
    unsafe_file_path = MagicMock()
    # Đường dẫn nguy hiểm (ví dụ: /etc/passwd)
    unsafe_path_str = "/etc/passwd"
    
    def resolve_side_effect(strict=False):
        if strict: return safe_folder_path
        return unsafe_file_path # Trả về path nguy hiểm

    mock_path_instance.resolve.side_effect = resolve_side_effect
    mocker.patch('app.utils.file_helpers.Path', return_value=mock_path_instance)

    # Giả lập os.path.commonpath trả về thư mục gốc "/" khi so sánh 2 đường dẫn khác nhau
    mocker.patch('app.utils.file_helpers.os.path.commonpath', return_value=os.path.sep)
    # --- Kết thúc Mock ---

    file = MockUploadFile(filename="../../etc/passwd.png", content=b"fake_bytes")

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid file path detected."
    log.info("Path Traversal attempt correctly blocked (400) with specific message.")
    
    log.info("--- Finished: test_save_avatar_path_traversal_attempt ---")


@pytest.mark.asyncio
async def test_save_avatar_empty_file(mock_dependencies):
    """Test 4.1: Lỗi 400 - File rỗng (content rỗng)."""
    log.info("--- Running: test_save_avatar_empty_file ---")
    file = MockUploadFile(filename="empty.png", content=b"") # Nội dung rỗng

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Empty file uploaded."
    
    mock_dependencies["magic"].assert_not_called() # Phải fail TRƯỚC khi check magic
    mock_dependencies["aio_open"].assert_not_called()
    log.info("Empty file upload correctly blocked (400) with specific message.")
    
    log.info("--- Finished: test_save_avatar_empty_file ---")


@pytest.mark.asyncio
async def test_save_avatar_read_error(mock_dependencies):
    """Test 4.1: Lỗi 400 - Lỗi khi đọc nội dung file (content=None)."""
    log.info("--- Running: test_save_avatar_read_error ---")
    # Sử dụng content=None để trigger lỗi đọc file trong MockUploadFile
    file = MockUploadFile(filename="read_error.png", content=None)

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Could not read file content."
    
    mock_dependencies["magic"].assert_not_called()
    mock_dependencies["aio_open"].assert_not_called()
    log.info("File read error correctly blocked (400) with specific message.")
    
    log.info("--- Finished: test_save_avatar_read_error ---")


@pytest.mark.asyncio
async def test_save_avatar_write_error(mock_dependencies):
    """Test 4.1: Lỗi 500 - Lỗi khi ghi file mới (mock aiofiles.write lỗi)."""
    log.info("--- Running: test_save_avatar_write_error ---")
    file = MockUploadFile(filename="good_file.png", content=b"fake_png_bytes")
    expected_path = os.path.join(settings.AVATAR_UPLOAD_FOLDER, "12345678-1234-5678-1234-567812345678.png")

    # Giả lập lỗi khi gọi handle.write()
    mock_dependencies["aio_handle"].write.side_effect = IOError("Disk full simulation")
    # Giả lập os.path.exists để code dọn dẹp chạy
    mock_dependencies["os_path_exists"].return_value = True 

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(file, old_avatar_url=None)

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Could not save avatar file."
    
    # --- Assert Side Effects ---
    mock_dependencies["magic"].assert_called_once() # Đã vượt qua check magic
    mock_dependencies["aio_open"].assert_called_once_with(expected_path, "wb") # Đã thử mở file
    mock_dependencies["aio_handle"].write.assert_awaited_once() # Đã thử ghi file (và fail)
    
    # Kiểm tra xem có cố gắng xóa file mới tạo (thất bại) không
    # os.path.exists được gọi 2 lần (1 cho file cũ (None), 1 cho file mới để dọn dẹp)
    assert mock_dependencies["os_path_exists"].call_count == 1 # Chỉ gọi 1 lần cho file mới
    mock_dependencies["os_path_exists"].assert_called_with(expected_path)
    # os.remove được gọi 1 lần (để dọn dẹp file mới)
    mock_dependencies["os_remove"].assert_called_once_with(expected_path)
    log.info("File write error correctly blocked (500) and cleanup attempted.")

    log.info("--- Finished: test_save_avatar_write_error ---")