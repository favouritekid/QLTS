
import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  /* config options here */
  output: "standalone",
  reactCompiler: true,

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
  // This enables testing from mobile devices when dev server runs on desktop
  // Note: Next.js requires both with/without port for proper matching
  allowedDevOrigins: isDev
    ? [
        // Common mobile device testing IPs
        "http://192.168.88.125", // Without port
        "http://192.168.88.125:80", // With port 80 (nginx/proxy)
        "http://192.168.88.125:3000", // With port 3000
        "http://192.168.88.125:3001", // With port 3001

        // Additional device IP from previous setup
        "http://192.168.0.120",
        "http://192.168.0.120:80",
        "http://192.168.0.120:3000",
        "http://192.168.0.120:3001",
      ]
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
