# app/socket_metrics.py
import time
from contextlib import asynccontextmanager

from prometheus_client import Counter, Gauge, Histogram

# === Metrics (V5 - Production Ready) ===

# Đếm số lượng kết nối đang hoạt động
socket_connections_active = Gauge(
    "socket_connections_active", "Active socket connections"
)

# Đếm tổng số sự kiện đã emit (gửi đi)
socket_events_emitted_total = Counter(
    "socket_events_emitted_total",
    "Total events emitted",
    ["event_type"],  # Phân loại theo loại sự kiện
)

# Đếm tổng số sự kiện đã nhận (từ client)
socket_events_received_total = Counter(
    "socket_events_received_total", "Total events received", ["event_type"]
)

# Đếm số lần xác thực thất bại
socket_auth_failures_total = Counter(
    "socket_auth_failures_total", "Total failed socket authentication attempts"
)

# ✅ CẢI TIẾN: Theo dõi lỗi emit
socket_emit_failures_total = Counter(
    "socket_emit_failures_total", "Failed socket emit operations", ["event_type"]
)

# ✅ CẢI TIẾN: Theo dõi latency (thời gian xử lý)
socket_event_latency_seconds = Histogram(
    "socket_event_latency_seconds",
    "Time to process socket events",
    ["event_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0],  # Thêm buckets lớn hơn
)


@asynccontextmanager
async def track_event_latency(event_type: str):
    """
    Một context manager helper để theo dõi thời gian xử lý
    của một sự kiện socket.
    """
    start_time = time.monotonic()
    try:
        yield
    finally:
        latency = time.monotonic() - start_time
        socket_event_latency_seconds.labels(event_type=event_type).observe(latency)
