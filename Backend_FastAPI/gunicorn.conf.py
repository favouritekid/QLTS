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

# --- Keep-Alive ---
keepalive = 5
