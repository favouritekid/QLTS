# tests/security/conftest.py
# -*- coding: utf-8 -*-
"""Fixture dùng chung cho tests/security/.

Chỉ chứa `test_server`: một tiến trình uvicorn thật, trong CÙNG process và CÙNG
event loop với bộ test, phục vụ ứng dụng ASGI đã bọc Socket.IO. Socket.IO qua
transport ``websocket`` không chạy được trên `ASGITransport` in-memory của httpx
nên phải có cổng TCP thật.

Fixture nằm ở conftest thay vì trong một `test_*.py` để các tệp test thôi phải
import lẫn nhau (`from .test_websocket_security import test_server`). Hàm thuần
dùng chung ở `socket_test_helpers.py`.
"""
import asyncio
import logging
import time

import pytest_asyncio
import uvicorn

log = logging.getLogger(__name__)

# Chờ `server.started`. 10s là dư cho một lần bind + startup; nó là hạn CHẾT
# để hỏng thì nổ ngay chứ không treo, không phải thời gian mong đợi.
_STARTUP_TIMEOUT = 10.0
_STARTUP_POLL = 0.05

# Tắt máy: nấc 1 lịch sự (`should_exit`), nấc 2 cưỡng chế (`force_exit`),
# nấc 3 huỷ task. Không có nấc nào được phép để lại task hay cổng.
_SHUTDOWN_GRACEFUL_TIMEOUT = 10.0
_SHUTDOWN_FORCE_TIMEOUT = 3.0


def _loi_cua_task(task: "asyncio.Task") -> BaseException | None:
    """Lấy exception của một task ĐÃ xong, không ném lại.

    `Task.exception()` tự ném CancelledError nếu task bị huỷ, nên phải bọc.
    Gọi hàm này cũng đánh dấu exception là "đã lấy" ⇒ không còn cảnh báo
    "Task exception was never retrieved" trôi ra stderr ở một ca test khác.
    """
    if not task.done():
        return None
    try:
        return task.exception()
    except asyncio.CancelledError as exc:
        return exc


async def _cho_task_ket_thuc(task: "asyncio.Task", timeout: float) -> bool:
    """Chờ task xong trong `timeout`. Trả True nếu xong, False nếu hết giờ.

    Dùng `asyncio.wait` chứ KHÔNG dùng `asyncio.wait_for`: `wait_for` HUỶ task
    khi hết giờ. Ở đây nấc sau (`force_exit`) còn phải dùng lại chính task này,
    nên nấc trước không được phép huỷ nó — nếu không, việc leo thang chỉ còn
    trên giấy.
    """
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    return bool(done)


async def _dung_server(
    server: uvicorn.Server, server_task: "asyncio.Task", port: int
) -> None:
    """Tắt máy chủ test theo ba nấc, không để sót task hay cổng."""
    server.should_exit = True
    if not await _cho_task_ket_thuc(server_task, _SHUTDOWN_GRACEFUL_TIMEOUT):
        log.warning(
            "Máy chủ test (cổng %s) không thoát trong %.1fs sau should_exit — "
            "chuyển sang force_exit.",
            port,
            _SHUTDOWN_GRACEFUL_TIMEOUT,
        )
        server.force_exit = True
        if not await _cho_task_ket_thuc(server_task, _SHUTDOWN_FORCE_TIMEOUT):
            log.error(
                "Máy chủ test (cổng %s) không thoát cả sau force_exit — huỷ task.",
                port,
            )
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)
            return

    loi = _loi_cua_task(server_task)
    if loi is not None and not isinstance(loi, asyncio.CancelledError):
        # KHÔNG raise: teardown mà ném thì che mất kết quả thật của ca test.
        # Nhưng cũng KHÔNG nuốt im: một máy chủ chết giữa chừng phải nhìn thấy được.
        log.error(
            "Máy chủ test (cổng %s) kết thúc kèm exception: %r", port, loi, exc_info=loi
        )


async def _cho_server_san_sang(
    server: uvicorn.Server, server_task: "asyncio.Task", port: int
) -> None:
    """Poll `server.started` cho tới khi True, hoặc nổ với lý do đo được.

    Bản cũ dùng `await asyncio.sleep(1.0)` rồi yield thẳng URL: máy chậm thì
    test đỏ ở chỗ khác (ConnectionError trong thân test), máy nhanh thì phí 1s
    mỗi ca. Poll `server.started` (uvicorn khởi tạo `False`, đặt `True` ở cuối
    `Server.startup()`) cho cả hai chiều: sẵn sàng thì đi ngay, hỏng thì nổ ở
    ĐÚNG chỗ hỏng.
    """
    han_chot = time.monotonic() + _STARTUP_TIMEOUT
    while not server.started:
        if server_task.done():
            # Server chết sớm (bind hỏng, import hỏng, lifespan hỏng...). Phải
            # nổ Ở ĐÂY kèm nguyên nhân thật, không được yield URL cho một cổng
            # không ai nghe rồi để test đỏ vì "Connection refused".
            loi = _loi_cua_task(server_task)
            thong_diep = (
                f"uvicorn thoát TRƯỚC khi `started=True` (cổng {port}). "
                "Máy chủ test không bao giờ nhận kết nối."
            )
            if loi is not None:
                raise RuntimeError(thong_diep) from loi
            raise RuntimeError(
                thong_diep + " Task kết thúc mà không có exception — "
                "nhiều khả năng `Server.startup()` gọi sys.exit sau lỗi bind."
            )
        if time.monotonic() >= han_chot:
            raise RuntimeError(
                f"uvicorn không đặt `started=True` trong {_STARTUP_TIMEOUT:.1f}s "
                f"(cổng {port}). Máy chủ còn sống nhưng chưa sẵn sàng."
            )
        await asyncio.sleep(_STARTUP_POLL)


@pytest_asyncio.fixture
async def test_server(client, unused_tcp_port_factory):
    """Máy chủ uvicorn thật cho các ca Socket.IO.

    Yield base URL ``http://127.0.0.1:<port>``.

    Vì sao phụ thuộc `client`:
        Fixture `client` (tests/conftest.py) đã mở lifespan của ứng dụng bằng
        ``async with lifespan(app)``. Nếu uvicorn cũng chạy lifespan thì ứng dụng
        khởi động HAI lần trong cùng process; `app/socket_manager.py` giữ
        `_worker_id` ở biến MODULE toàn cục nên lần đăng ký thứ hai ghi đè lần
        thứ nhất, và khi tắt chỉ gỡ được một ⇒ `socket:workers` để lại worker
        mồ côi làm nhiễu các ca sau. Phụ thuộc `client` còn ghim thứ tự: lifespan
        mở TRƯỚC khi uvicorn nhận request, và (do pytest tháo fixture theo chiều
        ngược) máy chủ tắt TRƯỚC khi lifespan đóng.

    Vì sao `lifespan="off"`:
        Đó là nửa còn lại của cùng một việc — chặn uvicorn phát sự kiện lifespan
        thứ hai. `uvicorn.Config` KHÔNG kiểm giá trị của tham số này: gõ sai
        chuỗi ("of", "false"...) sẽ không có lỗi nào cả, uvicorn chỉ lặng lẽ rơi
        về hành vi khác. Vì thế có `assert config.lifespan == "off"` ngay sau khi
        tạo Config — nó là phép đo, không phải trang trí.

    Vì sao `app` chứ không phải `fastapi_app`:
        ``app/main.py`` kết thúc bằng ``app = socketio.ASGIApp(sio, fastapi_app)``.
        `app` CHÍNH LÀ ứng dụng đã bọc Socket.IO; phục vụ `fastapi_app` thì
        endpoint ``/socket.io/`` không tồn tại. (Không có biến nào tên
        `app_with_sockets` — docstring cũ nói thế là sai.)
    """
    from app.main import app

    # Cổng do pytest-asyncio cấp, KHÔNG phải hằng số: hai ca chạy nối nhau trên
    # một cổng cố định sẽ đụng TIME_WAIT của ca trước, và chạy song song thì
    # đụng nhau thẳng. Factory còn nhớ những cổng đã phát trong phiên nên không
    # cấp lại. (Vẫn còn khe TOCTOU lý thuyết giữa lúc dò và lúc uvicorn bind —
    # nếu trúng, `_cho_server_san_sang` nổ kèm số cổng chứ không treo.)
    port = unused_tcp_port_factory()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
    )
    assert config.lifespan == "off", (
        "uvicorn.Config KHÔNG validate tham số `lifespan` — một chuỗi gõ sai đi "
        "qua im lặng và ứng dụng sẽ khởi động lần thứ hai (ghi đè "
        f"socket_manager._worker_id). Giá trị thực tế: {config.lifespan!r}"
    )

    server = uvicorn.Server(config)
    server_task = asyncio.create_task(
        server.serve(), name=f"uvicorn-test-server:{port}"
    )

    try:
        await _cho_server_san_sang(server, server_task, port)
    except BaseException:
        # Hỏng lúc khởi động vẫn phải dọn: không có `yield` thì pytest không gọi
        # phần teardown bên dưới, task uvicorn sẽ sống tiếp sang ca sau.
        await _dung_server(server, server_task, port)
        raise

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await _dung_server(server, server_task, port)
