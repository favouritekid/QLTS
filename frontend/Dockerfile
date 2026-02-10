# =============================================================================
# QLTS Frontend - Multi-stage Production Build
# =============================================================================
# Stage 1: Install dependencies
# Stage 2: Build Next.js (standalone output)
# Stage 3: Minimal runtime
# =============================================================================

# --- Stage 1: Dependencies ---
FROM node:20-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# --- Stage 2: Builder ---
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

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

RUN npm run build

# --- Stage 3: Runner ---
FROM node:20-alpine AS runner

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

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
