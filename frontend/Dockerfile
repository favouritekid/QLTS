# =============================================================================
# QLTS Frontend - Multi-stage Production Build
# =============================================================================
# Stage 1: Install dependencies
# Stage 2: Build Next.js (standalone output)
# Stage 3: Minimal runtime
# =============================================================================

# --- Stage 0: Source + manifest đầu vào build ---
# Băm TOÀN BỘ effective build context (đã qua `.dockerignore`) cộng với digest
# của mọi `NEXT_PUBLIC_*`. Đây là stage duy nhất `COPY . .`; `builder` lấy source
# TỪ ĐÂY, không copy context lần thứ hai — hai lần copy là hai tập tệp có thể
# khác nhau mà không ai thấy.
#
# `NEXT_PUBLIC_*` phải khai ARG ở đây thì `source-manifest.sh` mới nhìn thấy giá
# trị. Chúng bị Next.js nướng vào bundle, nên là ĐẦU VÀO BUILD đúng nghĩa: cùng
# source mà khác `NEXT_PUBLIC_API_URL` là hai ảnh khác hành vi.
FROM alpine:3.20 AS source

WORKDIR /src
COPY . .

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_SOCKET_URL
ARG NEXT_PUBLIC_FF_PERMISSION_HOOK=false
ARG NEXT_PUBLIC_FF_ERROR_HANDLER=false
ARG NEXT_PUBLIC_FF_STATUS_CONFIG=false
ARG NEXT_PUBLIC_FF_STRICT_PERMISSIONS=false
ARG NEXT_PUBLIC_SENTRY_DSN=

RUN sh scripts/source-manifest.sh /src > /qlts-source-manifest.json \
    && test -s /qlts-source-manifest.json

# --- Stage 0b: chỉ manifest ---
# Target nhẹ cho `attest-frontend-runtime.sh`: dựng được manifest của cây hiện
# tại mà KHÔNG chạy `npm ci` hay `next build`.
#   docker build --target manifest --output type=local,dest=<thư-mục> frontend/
FROM scratch AS manifest
COPY --from=source /qlts-source-manifest.json /qlts-source-manifest.json

# --- Stage 1: Dependencies ---
FROM node:26-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# --- Stage 1b: Development (for docker compose watch) ---
FROM deps AS dev

WORKDIR /app
COPY . .

# --- Stage 2: Builder ---
FROM node:26-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
# Source lấy từ stage `source` — KHÔNG `COPY . .` lần thứ hai. Manifest phải nói
# về đúng cây mà `next build` đọc; hai lần copy context là hai tập tệp có thể
# khác nhau (context đổi giữa hai layer) mà attestation không thấy.
COPY --from=source /src ./
COPY --from=source /qlts-source-manifest.json /app/.qlts-source-manifest.json

# Build-time args (NEXT_PUBLIC_* are inlined by Next.js at build time)
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_SOCKET_URL
ARG NEXT_PUBLIC_FF_PERMISSION_HOOK=false
ARG NEXT_PUBLIC_FF_ERROR_HANDLER=false
ARG NEXT_PUBLIC_FF_STATUS_CONFIG=false
ARG NEXT_PUBLIC_FF_STRICT_PERMISSIONS=false
ARG NEXT_PUBLIC_SENTRY_DSN=

# Server-side env for rewrites proxy
ENV BACKEND_URL=http://backend:8000
ENV BACKEND_INTERNAL_URL=http://backend:8000

# Use webpack for production build (Turbopack has NFT trace bug with middleware + standalone)
RUN npx next build --webpack

# --- Stage 3: Runner ---
FROM node:26-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
# Server-side env vars (runtime defaults, overridden by docker-compose)
ENV BACKEND_URL=http://backend:8000
ENV BACKEND_INTERNAL_URL=http://backend:8000

# Non-root user
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Copy standalone output
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
# Manifest đầu vào build. `attest-frontend-runtime.sh` đọc tệp này khi container
# không có `src/` (tức bản standalone) và so với manifest tính lại trên host.
COPY --from=builder /app/.qlts-source-manifest.json ./.qlts-source-manifest.json

# Truy vết, KHÔNG phải bằng chứng: nhãn chỉ nói người build KHAI là SHA nào.
# Phép so nội dung nằm ở manifest phía trên — đừng dùng nhãn thay cho nó.
ARG QLTS_GIT_SHA=
LABEL org.qlts.git-sha="${QLTS_GIT_SHA}"

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
