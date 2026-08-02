
import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  /* config options here */
  output: "standalone",

  // 🔴 BẮT BUỘC cho `src/proxy.ts` — đừng gỡ.
  //
  // Mặc định Next NORMALIZE request trước khi gọi Proxy: nó gỡ các Flight header
  // (`rsc`, `next-router-prefetch`, `next-router-segment-prefetch`,
  // `next-router-state-tree`) ra khỏi `request.headers` và cất riêng. Hệ quả:
  // `request.headers.get("next-router-prefetch")` LUÔN `null` ở production, nên
  // mọi vị từ phân loại request trong proxy im lặng trả `false` — mỗi lần người
  // dùng rê chuột qua một link lại thành một lượt cứu phiên kèm một POST
  // `/api/auth/refresh`.
  //
  // Điều này KHÔNG lộ ra ở unit test: test tự dựng `NextRequest` với header
  // nguyên vẹn, tức chạy trên một request khác với request thật. Nó chỉ lộ khi
  // smoke trên artifact production (đo 02-08-2026: 4/4 loại request nhận 307).
  skipProxyUrlNormalize: true,
  // React Compiler: enabled only in production builds for runtime performance
  // Disabled in dev to reduce compilation time by ~33% (8.4s → 6.3s measured)
  reactCompiler: !isDev,

  // ✅ PERFORMANCE: Optimize barrel imports for smaller bundles
  // These libraries use barrel exports that would otherwise import entire library
  // This enables tree-shaking at build time, reducing bundle size by 200-800KB
  experimental: {
    optimizePackageImports: [
      "lucide-react",        // Icon library - only import used icons
      "@tanstack/react-table", // Table library
      "recharts",            // Chart library (~150KB without optimization)
      "@dnd-kit/core",       // Drag-and-drop core
      "@dnd-kit/sortable",   // Drag-and-drop sortable
      "date-fns",            // Date utility functions
      "@radix-ui/react-icons", // Radix icons
      "framer-motion",         // Animation library (~150KB without optimization)
    ],
  },

  // ✅ Phase 1: Enable Partial Pre-Rendering for faster initial loads
  // Note: cacheComponents has been promoted from experimental in Next.js 16
  // WARNING:
  // cacheComponents MUST NOT be used for:
  // - auth-sensitive components
  // - role/permission-based rendering
  // - per-user dynamic data
  cacheComponents: true,

  // Allow cross-origin requests from devices on local network during development
  // (test từ điện thoại khi dev server chạy trên desktop). Next.js so khớp theo
  // HOSTNAME — KHÔNG kèm protocol/port; khai full-URL sẽ không match → dev-server
  // chặn /_next/* (403) → RSC/hydrate vỡ trên thiết bị LAN.
  allowedDevOrigins: isDev
    ? ["192.168.88.125", "192.168.0.120"]
    : [],

  // ✅ Security Headers
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // TODO: Add Content-Security-Policy (CSP) once asset & API domains are finalized
        ],
      },
    ];
  },

  // ✅ Proxy API requests to Backend
  // Supports separate Backend URL for Production vs Development
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    
    if (isDev) {
      console.log(`[Next.js] 🔀 Rewriting /api/* to ${backendUrl}/api/*`);
    }
    
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      // Also proxy /uploads for static file serving if needed
      {
        source: "/uploads/:path*",
        destination: `${backendUrl}/uploads/:path*`,
      },
    ];
  },
};

export default nextConfig;
