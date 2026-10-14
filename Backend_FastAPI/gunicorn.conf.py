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


# --- Keep-Alive ---
keepalive = 5
