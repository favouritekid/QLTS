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
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy installed Python packages
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p /app/uploads \
    /app/app/static/uploads/avatars \
    /app/geoip \
    /app/logs \
    && chown -R appuser:appuser /app/uploads \
    /app/app/static/uploads \
    /app/geoip \
    /app/logs

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
