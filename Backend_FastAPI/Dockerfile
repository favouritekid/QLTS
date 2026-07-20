# =============================================================================
# QLTS Backend - Multi-stage Production Build
# =============================================================================
# Stage 1: Install Python dependencies
# Stage 2: Minimal runtime image
# =============================================================================

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.12-slim

# Runtime dependencies
# fonts-liberation + fonts-dejavu-core: chỉ là các file .ttf (~3MB) phủ đủ
# Unicode tiếng Việt cho ReportLab render "Giấy báo nhập học". KHÔNG phải thư
# viện render native (không kéo theo GTK/Cairo) — khác hẳn WeasyPrint đã bị loại
# ở P0-6.
#   - fonts-liberation → Liberation Serif, metric-tương thích Times New Roman:
#     đây là font CHÍNH của giấy báo, để bản PDF khớp mẫu Word hành chính đang
#     phát hành. ReportLab registerFont từ
#     /usr/share/fonts/truetype/liberation/LiberationSerif-*.ttf.
#   - fonts-dejavu-core → FALLBACK nếu Liberation vắng mặt (renderer tự dò).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    libmagic1 \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy installed Python packages
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create required directories and make entrypoint executable.
# /app/private_exports is the mount point cho named volume `sms_private_exports`
# (PR-4 SMS export XLSX chứa PII, để ngoài webroot). PHẢI tạo + chown appuser
# TRONG image: khi named volume rỗng mount lần đầu, Docker seed nội dung + quyền
# từ image tại mount path → volume root thuộc appuser → app (chạy appuser) tạo
# được subdir `sms`. Nếu không, mount point sinh ra root-owned → makedirs ném
# PermissionError, batch export thành `failed`.
RUN mkdir -p /app/uploads \
    /app/app/static/uploads/avatars \
    /app/geoip \
    /app/logs \
    /app/private_exports/sms \
    /app/private_exports/letters \
    && chown -R appuser:appuser /app/uploads \
    /app/app/static/uploads \
    /app/geoip \
    /app/logs \
    /app/private_exports \
    && chmod +x /app/docker-entrypoint.sh

USER appuser

ENTRYPOINT ["/app/docker-entrypoint.sh"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
