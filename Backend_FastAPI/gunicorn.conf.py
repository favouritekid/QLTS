"""Gunicorn configuration for production deployment."""

import os
import multiprocessing

# --- Server Socket ---
bind = "0.0.0.0:8000"

# --- Worker Processes ---
# ASGI worker class for FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Number of workers (default 2, max 4 for 4 vCPU VPS)
workers = min(int(os.getenv("GUNICORN_WORKERS", "2")), 4)

# --- CRITICAL: preload_app = False ---
# Socket.IO AsyncServer (socket_manager.py:44) needs each worker to have its own
# event loop. preload_app=True would share the socketio instance across forked
# workers, breaking asyncio.
preload_app = False

# --- Worker Lifecycle ---
# Recycle workers after N requests to prevent memory leaks
max_requests = 1000
max_requests_jitter = 50

# Graceful timeout for worker shutdown
graceful_timeout = 30
timeout = 120

# --- Proxy ---
# Trust X-Forwarded-* headers from Nginx reverse proxy
# This prevents HTTPS redirect loops (main.py HTTPSRedirectMiddleware)
forwarded_allow_ips = "*"

# --- Logging ---
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()


def post_worker_init(worker):
    """Gắn bộ che log (V6) vào access/error logger của app-server — SAU khi
    gunicorn dựng handler per-worker. Các logger ấy mang handler RIÊNG với
    ``propagate=False`` nên handler gốc (có ``RedactingFilter``) không thấy
    chúng; dòng request `GET /api/admissions/confirm/<token>`, `GET /r/<code>`
    phải được che ngay ở mức logger. Mẫu che: `app/core/log_redaction.py`."""
    from app.core.log_redaction import install_log_redaction

    install_log_redaction()


def on_starting(server):
    """F59 (21-10): nạp ``app.config`` MỘT lần trong master, TRƯỚC khi sinh worker.

    Cấu hình hỏng ⇒ mọi worker chết GẦN như cùng lúc khi boot. gunicorn 23.0.0
    ``Arbiter.reap_workers`` ném ``HaltServer`` ngay sau worker ĐẦU TIÊN gặt được, chưa
    gặt worker còn lại; nếu worker ấy đã thoát trước khi handler SIGCHLD chạy thì hai tín
    hiệu gộp làm một, không đến lần nữa ⇒ nó thành zombie mà vẫn nằm trong ``WORKERS``
    (``os.kill`` lên zombie không báo ESRCH) và ``stop()`` chờ trọn ``graceful_timeout``
    rồi mới thoát. Đo 21-10: 3/131 lượt khởi động với cấu hình giả hỏng, ~31,5 s thay vì
    ~1,5 s. Dừng ở master thì không có worker nào để đua.

    Nạp được ⇒ gỡ các module ``app`` khỏi ``sys.modules`` để worker tự nạp lại như trước
    (``preload_app = False`` giữ nguyên nghĩa). ``LoiCauHinh`` mang mô tả an toàn của
    ``app/utils/redact.py`` ⇒ in đúng một dòng ``LoiCauHinh: <mô tả>`` rồi thoát mã ≠ 0;
    lỗi khác đi nguyên đường mặc định.

    F59b: ``app/config.py`` ``print`` khi nạp. Ảnh production không đặt
    ``PYTHONUNBUFFERED`` ⇒ stdout của master là ống có bộ đệm; không xả TRƯỚC khi fork thì
    MỖI worker (cả worker tái sinh theo ``max_requests``) thừa hưởng bản sao bộ đệm và in lại
    các dòng ấy (đo khởi động thật 21-10: 4 dòng "Settings loaded" thay vì 3)."""
    import sys

    from app.utils.redact import LoiCauHinh

    try:
        import app.config  # noqa: F401
    except LoiCauHinh as loi:
        raise SystemExit("%s: %s" % (type(loi).__name__, loi)) from None
    finally:
        for ten in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[ten]
        sys.stdout.flush()
        sys.stderr.flush()


# --- Keep-Alive ---
keepalive = 5
