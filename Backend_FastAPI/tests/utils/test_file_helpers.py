# tests/utils/test_file_helpers.py
# -*- coding: utf-8 -*-
import logging  # Thêm logging
import os
import uuid
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import aiofiles
import magic
import pytest
import pytest_asyncio
from fastapi import HTTPException, status

from app.config import settings  # Dùng settings làm "constants" cho file này

# Import các thành phần cần test và config
from app.utils import file_helpers

log = logging.getLogger(__name__)

# Chụp bản THẬT của các object module dùng chung, ngay lúc import — trước khi
# bất kỳ fixture nào chạy. ``test_khong_ro_ri_stdlib`` so identity với bản này.
_MODULE_DUNG_CHUNG_THAT = {
    "os.path.commonpath": os.path.commonpath,
    "os.path.exists": os.path.exists,
    "os.path.relpath": os.path.relpath,
    "os.remove": os.remove,
    "uuid.uuid4": uuid.uuid4,
    "aiofiles.open": aiofiles.open,
    "magic.from_buffer": magic.from_buffer,
}


# === Fixture để Mock các Dependencies (Giữ nguyên như trong context) ===
@pytest_asyncio.fixture(autouse=True)
def mock_dependencies(mocker):
    """Mock các thư viện bên ngoài mà file_helpers sử dụng."""

    # ⚠️ KHÔNG dùng ``mocker.patch("app.utils.file_helpers.os.path.exists")``.
    # ``file_helpers`` khai ``import os``, nên ``file_helpers.os`` CHÍNH LÀ module
    # ``os`` toàn tiến trình: vá thuộc tính trên nó là vá ``posixpath`` cho mọi
    # thứ đang chạy, kể cả pytest. Hậu quả đo được: pytest gọi
    # ``os.path.commonpath`` khi dựng traceback (``_makepath`` → ``bestrelpath``),
    # nhận đường avatar giả, rồi ``relative_to`` ném ``ValueError`` và
    # ``wrap_session`` chết bằng INTERNALERROR — nuốt trọn kết quả của cả lát.
    # Đúng cơ chế đã giết shard-06 của nightly 32513696715.
    #
    # Cách đúng: thay chính BINDING trong module ``file_helpers`` bằng một
    # namespace giả. Module thật không bị chạm; các hàm ``file_helpers`` cần mà
    # không cần giả (``join``/``basename``/``dirname``/``sep``) trỏ thẳng về bản
    # thật. ``test_khong_ro_ri_stdlib`` khoá bất biến này.

    # 1. aiofiles
    mock_aio_open = MagicMock()
    mock_file_handle = AsyncMock()
    mock_file_handle.write = AsyncMock(return_value=None)
    async_context_manager_mock = AsyncMock()
    async_context_manager_mock.__aenter__.return_value = mock_file_handle
    async_context_manager_mock.__aexit__.return_value = None
    mock_aio_open.return_value = async_context_manager_mock
    mocker.patch.object(
        file_helpers, "aiofiles", SimpleNamespace(open=mock_aio_open)
    )

    # 2. magic (mặc định là PNG hợp lệ)
    mock_magic = MagicMock(return_value="image/png")
    mocker.patch.object(
        file_helpers, "magic", SimpleNamespace(from_buffer=mock_magic)
    )

    # 3. os — giả lập file cũ tồn tại và commonpath thành công
    mock_os_path_exists = MagicMock(return_value=True)
    mock_os_remove = MagicMock()
    mock_commonpath = MagicMock(return_value=str(settings.AVATAR_UPLOAD_FOLDER))
    mock_relpath = MagicMock(return_value="uploads/avatars")
    mocker.patch.object(
        file_helpers,
        "os",
        SimpleNamespace(
            path=SimpleNamespace(
                exists=mock_os_path_exists,
                commonpath=mock_commonpath,
                relpath=mock_relpath,
                basename=os.path.basename,
                dirname=os.path.dirname,
                join=os.path.join,
            ),
            remove=mock_os_remove,
            sep=os.sep,
        ),
    )

    # 4. uuid
    mock_uuid4 = MagicMock(
        return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")
    )
    mocker.patch.object(file_helpers, "uuid", SimpleNamespace(uuid4=mock_uuid4))

    # 5. Mock Path.resolve (quan trọng cho security check)
    # Cần mock cả `strict=True` (cho thư mục) và `strict=False` (cho file)
    mock_path_instance = MagicMock()
    # Giả lập resolve() trả về chính nó (đơn giản hóa) hoặc một path object an toàn
    safe_folder_path = MagicMock()
    safe_folder_path.__str__.return_value = str(
        settings.AVATAR_UPLOAD_FOLDER
    )  # Đảm bảo so sánh chuỗi hoạt động

    safe_file_path = MagicMock()

    # Phân biệt resolve cho thư mục và file
    def resolve_side_effect(strict=False):
        if strict:  # strict=True dùng cho UPLOAD_FOLDER
            return safe_folder_path
        return safe_file_path  # strict=False dùng cho file_path

    mock_path_instance.resolve.side_effect = resolve_side_effect

    # Mock Path() constructor để trả về instance đã mock
    mocker.patch.object(file_helpers, "Path", return_value=mock_path_instance)

    return {
        "aio_open": mock_aio_open,
        "aio_handle": mock_file_handle,
        "magic": mock_magic,
        "os_path_exists": mock_os_path_exists,
        "os_remove": mock_os_remove,
        "uuid4": mock_uuid4,
        "commonpath": mock_commonpath,
        "Path": mock_path_instance,
    }


# === Tests cho save_avatar (Mục 4.1) ===


@pytest.mark.asyncio
async def test_save_avatar_success(mock_dependencies):
    """Test 4.1: Lưu avatar thành công (không có file cũ)."""
    log.info("--- Running: test_save_avatar_success ---")
    avatar_filename = "avatar.png"
    avatar_content = b"fake_png_bytes"

    expected_uuid = "12345678-1234-5678-1234-567812345678"
    expected_filename = f"{expected_uuid}.png"
    expected_path = os.path.join(settings.AVATAR_UPLOAD_FOLDER, expected_filename)
    expected_url = f"/static/uploads/avatars/{expected_filename}"

    # --- Action ---
    result_url = await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=None
        )

    # --- Assert Response (Return Value) ---
    assert result_url == expected_url, "URL trả về không chính xác"

    # --- Assert Side Effects (Mocks) ---
    # KHÔNG còn khẳng định "helper đọc file 1 lần": sau refactor Service Layer
    # Purity, `save_avatar` NHẬN bytes chứ không đọc — việc đọc `UploadFile` là
    # của tầng gọi. Giữ lại `file.read.assert_awaited_once()` là đòi hàm làm
    # đúng thứ vừa được gỡ khỏi nó.
    # 1. Kiểm tra MIME type
    mock_dependencies["magic"].assert_called_once_with(b"fake_png_bytes", mime=True)
    # 3. Security check (Path.resolve và commonpath)
    mock_dependencies["Path"].resolve.assert_any_call(
        strict=True
    )  # Kiểm tra UPLOAD_FOLDER
    mock_dependencies["Path"].resolve.assert_any_call(
        strict=False
    )  # Kiểm tra file_path
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
    avatar_filename = "new_avatar.jpg"
    avatar_content = b"fake_jpg_bytes"
    mock_dependencies["magic"].return_value = "image/jpeg"  # Giả lập file JPG

    old_url = "/static/uploads/avatars/old_file_123.jpg"
    expected_old_filename = "old_file_123.jpg"
    expected_old_path = os.path.join(
        settings.AVATAR_UPLOAD_FOLDER, expected_old_filename
    )

    # Cấu hình mock path.exists trả về True cho file cũ
    mock_dependencies["os_path_exists"].return_value = True

    # --- Action ---
    await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=old_url
        )

    # --- Assert Side Effects ---
    # 1. Kiểm tra magic (JPG)
    mock_dependencies["magic"].assert_called_once_with(b"fake_jpg_bytes", mime=True)
    # 2. Kiểm tra file cũ đã bị xóa
    # KHÔNG khẳng định `os.path.exists` nữa: phần xoá đã chuyển từ LBYL sang
    # EAFP — `os.remove` được gọi thẳng và `FileNotFoundError` bị bắt (chú thích
    # "✅ SỬA LỖI: Áp dụng EAFP" trong `file_helpers`). Đổi ấy đóng một khe
    # TOCTOU; khẳng định `exists` là khoá vào CÁCH LÀM chứ không phải kết quả.
    mock_dependencies["os_remove"].assert_called_once_with(expected_old_path)
    log.info("Old avatar deleted successfully.")

    log.info("--- Finished: test_save_avatar_success_with_old_file ---")


@pytest.mark.asyncio
async def test_save_avatar_invalid_extension(mock_dependencies):
    """Test 4.1: Lỗi 400 - Đuôi file không hợp lệ (.txt)."""
    log.info("--- Running: test_save_avatar_invalid_extension ---")
    avatar_filename = "virus.txt"
    avatar_content = b"i am a virus"

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=None
        )

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    # Kiểm tra message lỗi cụ thể
    allowed_exts_str = ", ".join(sorted(list(settings.ALLOWED_AVATAR_EXTENSIONS)))
    assert (
        exc_info.value.detail
        == f"Unsupported file format. Allowed: {allowed_exts_str}."
    )

    # Đảm bảo không có hành động ghi file hay check magic
    mock_dependencies["magic"].assert_not_called()
    mock_dependencies["aio_open"].assert_not_called()
    log.info("Invalid extension correctly blocked (400) with specific message.")

    log.info("--- Finished: test_save_avatar_invalid_extension ---")


@pytest.mark.asyncio
async def test_save_avatar_file_too_large(mock_dependencies):
    """Test 4.1: Lỗi 413 - File quá lớn."""
    log.info("--- Running: test_save_avatar_file_too_large ---")
    avatar_filename = "too_big.png"
    avatar_content = b"a" * (settings.MAX_AVATAR_CONTENT_LENGTH + 1)

    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=None
        )

    # --- SỬA/THÊM ASSERTION NÀY ---
    assert (
        exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    )  # <-- Đảm bảo dùng hằng số mới
    # --- KẾT THÚC SỬA ---
    assert (
        exc_info.value.detail
        == f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB."
    )

    mock_dependencies["magic"].assert_not_called()
    mock_dependencies["aio_open"].assert_not_called()
    log.info("File too large correctly blocked (413) with specific message.")

    log.info("--- Finished: test_save_avatar_file_too_large ---")


@pytest.mark.asyncio
async def test_save_avatar_invalid_mime_type(mock_dependencies):
    """Test 4.1: Lỗi 400 - Đuôi file hợp lệ (.png) nhưng nội dung là text."""
    log.info("--- Running: test_save_avatar_invalid_mime_type ---")
    avatar_filename = "fake.png"
    avatar_content = b"this is actually a text file"

    # Giả lập magic phát hiện đây là text
    mock_dependencies["magic"].return_value = "text/plain"

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=None
        )

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    allowed_exts_str = ", ".join(sorted(list(settings.ALLOWED_AVATAR_EXTENSIONS)))
    assert (
        exc_info.value.detail
        == f"File content is not a valid image format. Allowed: {allowed_exts_str}."
    )

    # Đảm bảo đã check magic, nhưng chưa ghi file
    mock_dependencies["magic"].assert_called_once_with(
        b"this is actually a text file", mime=True
    )
    mock_dependencies["aio_open"].assert_not_called()
    log.info("Invalid MIME type correctly blocked (400) with specific message.")

    log.info("--- Finished: test_save_avatar_invalid_mime_type ---")


@pytest.mark.asyncio
async def test_save_avatar_path_traversal_attempt(mocker, mock_dependencies):
    """Test 4.1: Lỗi 400 - Ngăn chặn Path Traversal."""
    log.info("--- Running: test_save_avatar_path_traversal_attempt ---")
    # Mock các thư viện bên ngoài (tương tự mock_dependencies nhưng chỉ mock cái cần thiết)
    # aiofiles / magic / uuid đã do fixture autouse ``mock_dependencies`` cung
    # cấp dưới dạng namespace giả. KHÔNG vá lại ở đây: mỗi lần vá lại là một cơ
    # hội để bản vá toàn cục quay về, mà Tier 5 chỉ chạy sentinel nên thân hàm
    # này không hề chạy trên PR gate.

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
        if strict:
            return safe_folder_path
        return unsafe_file_path  # Trả về path nguy hiểm

    mock_path_instance.resolve.side_effect = resolve_side_effect
    mocker.patch.object(file_helpers, "Path", return_value=mock_path_instance)

    # commonpath trả "/" ⇒ hai đường dẫn không cùng gốc ⇒ coi là traversal.
    # Chỉnh ``return_value`` của chính mock do fixture tạo, KHÔNG vá thêm lần
    # nào: một biểu thức như ``patch.object(file_helpers.os.path, …)`` tuy đúng
    # lúc chạy (vì ``file_helpers.os`` đã là namespace giả) nhưng đọc TĨNH thì
    # không phân biệt được với việc chọc thẳng vào ``os.path`` thật.
    mock_dependencies["commonpath"].return_value = os.path.sep
    # --- Kết thúc Mock ---

    avatar_filename = "../../etc/passwd.png"
    avatar_content = b"fake_bytes"

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=None
        )

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid file path detected."
    log.info("Path Traversal attempt correctly blocked (400) with specific message.")

    log.info("--- Finished: test_save_avatar_path_traversal_attempt ---")


@pytest.mark.asyncio
async def test_save_avatar_empty_file(mock_dependencies):
    """Test 4.1: Lỗi 400 - File rỗng (content rỗng)."""
    log.info("--- Running: test_save_avatar_empty_file ---")
    avatar_filename = "empty.png"
    avatar_content = b""  # Nội dung rỗng

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=None
        )

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Empty file uploaded."

    mock_dependencies["magic"].assert_not_called()  # Phải fail TRƯỚC khi check magic
    mock_dependencies["aio_open"].assert_not_called()
    log.info("Empty file upload correctly blocked (400) with specific message.")

    log.info("--- Finished: test_save_avatar_empty_file ---")


@pytest.mark.asyncio
async def test_save_avatar_content_none_tra_400_khong_phai_500(mock_dependencies):
    """``content=None`` phải cho 400 sạch, KHÔNG phải TypeError 500.

    Trước lượt refactor "Service Layer Purity", ``content`` được dựng ngay trong
    hàm (``b''.join(chunks)``) nên không bao giờ là None, và ca này kiểm nhánh
    "đọc file thất bại" -> 400 "Could not read file content.".

    Sau refactor, việc đọc chuyển ra ngoài và ``content`` thành THAM SỐ. Nhánh
    kiểm cỡ vẫn là ``len(content)``, nên một caller truyền None làm hàm ném
    ``TypeError: object of type 'NoneType' has no len()`` — 500, trong khi mọi
    đầu vào hỏng khác đều được trả 400 sạch.

    Ca này khoá lại hàng rào ấy. ``None`` là đầu vào KHÁC với ``b""`` (caller
    đọc hụt vs tệp rỗng thật) nên vẫn giữ riêng, cạnh
    ``test_save_avatar_empty_file``.
    """
    log.info("--- Running: test_save_avatar_content_none ---")

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(None, "read_error.png", old_avatar_url=None)

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Empty file uploaded."

    mock_dependencies["magic"].assert_not_called()
    mock_dependencies["aio_open"].assert_not_called()
    log.info("File read error correctly blocked (400) with specific message.")

    log.info("--- Finished: test_save_avatar_read_error ---")


@pytest.mark.asyncio
async def test_save_avatar_write_error(mock_dependencies):
    """Test 4.1: Lỗi 500 - Lỗi khi ghi file mới (mock aiofiles.write lỗi)."""
    log.info("--- Running: test_save_avatar_write_error ---")
    avatar_filename = "good_file.png"
    avatar_content = b"fake_png_bytes"
    expected_path = os.path.join(
        settings.AVATAR_UPLOAD_FOLDER, "12345678-1234-5678-1234-567812345678.png"
    )

    # Giả lập lỗi khi gọi handle.write()
    mock_dependencies["aio_handle"].write.side_effect = IOError("Disk full simulation")
    # Giả lập os.path.exists để code dọn dẹp chạy
    mock_dependencies["os_path_exists"].return_value = True

    # --- Action & Assert Exception ---
    with pytest.raises(HTTPException) as exc_info:
        await file_helpers.save_avatar(
            avatar_content, avatar_filename, old_avatar_url=None
        )

    # --- Assert Error Message ---
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Could not save avatar file."

    # --- Assert Side Effects ---
    mock_dependencies["magic"].assert_called_once()  # Đã vượt qua check magic
    mock_dependencies["aio_open"].assert_called_once_with(
        expected_path, "wb"
    )  # Đã thử mở file
    mock_dependencies[
        "aio_handle"
    ].write.assert_awaited_once()  # Đã thử ghi file (và fail)

    # Kiểm tra xem có cố gắng xóa file mới tạo (thất bại) không
    # os.path.exists được gọi 2 lần (1 cho file cũ (None), 1 cho file mới để dọn dẹp)
    assert (
        mock_dependencies["os_path_exists"].call_count == 1
    )  # Chỉ gọi 1 lần cho file mới
    mock_dependencies["os_path_exists"].assert_called_with(expected_path)
    # os.remove được gọi 1 lần (để dọn dẹp file mới)
    mock_dependencies["os_remove"].assert_called_once_with(expected_path)
    log.info("File write error correctly blocked (500) and cleanup attempted.")

    log.info("--- Finished: test_save_avatar_write_error ---")


# === Cổng chống rò stdlib =====================================================
# Cổng LÚC CHẠY. Nó chỉ thấy thứ fixture autouse thật sự làm, nên KHÔNG đủ một
# mình: Tier 5 chạy đúng nodeid này, còn thân các test khác không chạy ở đó.
# Ba cổng còn lại nằm ở ``test_file_helpers_guard.py`` — tệp ấy cố ý KHÔNG import
# mã ứng dụng nên nó chạy được chính tệp này trong tiến trình con mà không có
# hai bản app cùng nằm trong trần 1G.
#
# Sentinel đặt cuối tệp có chủ đích, nhưng tính chất "sống qua 9 traceback" CHỈ
# đúng khi chạy CẢ TỆP (chín ca trên đang đỏ vì lý do khác — test double lỗi
# thời, ngoài phạm vi PR này). Việc chạy cả tệp do guard đảm nhận.


def test_khong_ro_ri_stdlib(mock_dependencies):
    """Fixture autouse KHÔNG được đổi object stdlib dùng chung toàn tiến trình.

    ``file_helpers`` khai ``import os`` / ``import uuid``, nên
    ``file_helpers.os`` và ``file_helpers.uuid`` CHÍNH LÀ module toàn cục. Vá
    thuộc tính trên chúng (``mocker.patch("app.utils.file_helpers.os.path.…")``)
    là vá ``posixpath``/``uuid`` cho mọi thứ trong tiến trình, kể cả pytest.

    Đo được trên ``main@0c3031d7``: chạy MỘT ca của tệp này với ``--tb=short``
    cho INTERNALERROR và exit 3::

        _pytest/_code/code.py:1092 repr_traceback_entry → _makepath → bestrelpath
        ValueError: '/app' is not in the subpath of '/app/app/static/uploads/avatars'

    Trên nightly 32513696715 nó giết shard-06 giữa phiên: 7 test không bao giờ
    chạy, mà cổng độ phủ vẫn xanh vì node đã được PHÂN LÁT.
    """
    # (a) Fixture thật sự có tác dụng. Thiếu vế này thì (b) xanh mà không chứng
    #     minh được gì — một fixture không chạy cũng cho identity nguyên vẹn.
    assert file_helpers.os is not os, "fixture khong thay binding file_helpers.os"
    assert file_helpers.uuid is not uuid, "fixture khong thay binding file_helpers.uuid"
    assert file_helpers.aiofiles is not aiofiles, "fixture khong thay binding aiofiles"
    assert file_helpers.magic is not magic, "fixture khong thay binding magic"
    assert file_helpers.os.path.exists is not os.path.exists

    # (b) …mà module thật vẫn nguyên vẹn.
    hien = {
        "os.path.commonpath": os.path.commonpath,
        "os.path.exists": os.path.exists,
        "os.path.relpath": os.path.relpath,
        "os.remove": os.remove,
        "uuid.uuid4": uuid.uuid4,
        "aiofiles.open": aiofiles.open,
        "magic.from_buffer": magic.from_buffer,
    }
    lech = sorted(
        t for t, that in _MODULE_DUNG_CHUNG_THAT.items() if hien[t] is not that
    )
    assert not lech, (
        "Fixture da doi object stdlib TOAN CUC: %s. Dung "
        "mocker.patch.object(file_helpers, '<ten>', SimpleNamespace(...)) de "
        "thay BINDING trong module, thay vi va thuoc tinh tren module that." % lech
    )

    # (c) …và vẫn hành xử như hàm thật, không phải mock trả hằng số.
    assert os.path.commonpath(["/a/b", "/a/c"]) == "/a"
    assert os.path.relpath("/a/b/c", "/a") == "b/c"
