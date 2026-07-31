// src/proxy.ts
/**
 * 🔒 SERVER-SIDE AUTHENTICATION PROXY
 *
 * ✅ SECURITY FIX: Prevents Client-Side Auth Guard vulnerability
 *
 * This proxy runs on the server BEFORE any page is rendered, ensuring:
 * 1. Unauthorized users NEVER receive HTML/data from protected pages
 * 2. Authentication is verified using httpOnly cookies (not localStorage)
 * 3. Role-based access control (RBAC) is enforced server-side
 *
 * IMPORTANT: This middleware MUST run before Server Components render,
 * otherwise sensitive data could leak to unauthorized users.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { decodeJWT, isTokenExpired } from "@/lib/auth/jwt-decode";
import { hasAdminAccess, hasFinanceAccess } from "@/lib/config/roles";
import { buildLoginRedirect, isValidRedirect } from "@/lib/auth/login-redirect";

// ============================================
// 🛣️ ROUTE CONFIGURATION
// ============================================

/**
 * Public routes that don't require authentication
 */
/**
 * Tuổi thọ `refresh_token` phía backend (`REFRESH_TOKEN_EXPIRE_DAYS`, mặc định
 * 30 ngày). Middleware không đọc được cookie đó (Path=/api) nên dùng con số
 * này làm cận trên: access token hết hạn LÂU HƠN mốc này thì refresh_token
 * chắc chắn cũng đã chết, không còn gì để client cứu.
 */
const REFRESH_TOKEN_LIFETIME_MS = 30 * 24 * 60 * 60 * 1000;

/**
 * Trang bootstrap công khai: gọi `/api/auth/refresh` rồi quay lại URL cũ.
 * PHẢI nằm trong `PUBLIC_ROUTE_PREFIXES`, nếu không middleware sẽ tự đá chính
 * nó về /login và tạo vòng lặp.
 */
const SESSION_REFRESH_PATH = "/session-refresh";

const EXACT_PUBLIC_ROUTES = ["/"];

const PUBLIC_ROUTE_PREFIXES = [
  "/login",
  "/register",
  "/register-ctv",
  "/forgot-password",
  "/reset-password",
  "/tuyen-sinh",
  // Admission magic-link confirmation — applicants arrive from email
  // without being logged in. Backend exempts /api/admissions/confirm/*
  // from CSRF; frontend proxy must likewise let the page render.
  "/confirm",
  // PR-CO-2-FE / PR-3E: multi-action magic-link landing (4 actions).
  // Backend exempts /api/v2/admissions/magic-link/* from CSRF; the
  // page itself is candidate-driven and must NOT bounce to /login.
  "/magic-link",
  // SMS Marketing landing (PR-5): /lp/{code} — người nhận tới từ link SMS,
  // KHÔNG đăng nhập. Backend /api/public/sms/* CSRF-exempt; trang phải render.
  "/lp",
  // Trang bootstrap làm mới phiên. Phải công khai: người dùng tới đây CHÍNH VÌ
  // access token đã hết hạn, nếu đòi auth thì middleware đá nó về /login và
  // luồng cứu phiên không bao giờ chạy.
  "/session-refresh",
];

/**
 * Admin-only routes (requires admin or manager role)
 */
const ADMIN_ROUTES = ["/admin"];

/**
 * Finance routes (requires accountant, manager, or admin role)
 */
const FINANCE_ROUTES = ["/finance"];

/**
 * Routes to skip entirely (browser/devtool auto-requests)
 * These never need auth checks and should not be logged.
 */
const IGNORED_ROUTES = ["/.well-known"];

// ============================================
// 🔐 PROXY LOGIC
// ============================================

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // ========================================
  // STEP 1: Check if route requires auth
  // ========================================

  // Skip browser/devtool auto-requests silently (e.g. /.well-known/*)
  const isIgnored = IGNORED_ROUTES.some((route) => pathname.startsWith(route));
  if (isIgnored) {
    return NextResponse.next();
  }

  const isAuthRoute =
    pathname === "/login" ||
    pathname === "/register" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/register/");
  const isPublicRoute =
    EXACT_PUBLIC_ROUTES.includes(pathname) ||
    PUBLIC_ROUTE_PREFIXES.some((route) => pathname.startsWith(route));
  const isAdminRoute = ADMIN_ROUTES.some((route) => pathname.startsWith(route));
  const isFinanceRoute = FINANCE_ROUTES.some((route) => pathname.startsWith(route));

  // Auth routes: redirect authenticated users to dashboard, handle force_login
  if (isAuthRoute) {
    // Force login: clear stale cookies (used by logout redirect)
    const forceLogin = request.nextUrl.searchParams.get("force_login") === "true";
    if (forceLogin) {
      const response = NextResponse.next();
      response.cookies.delete({ name: "access_token", path: "/" });
      response.cookies.delete({ name: "refresh_token", path: "/api" });
      response.cookies.delete({ name: "csrf_token", path: "/" });
      return response;
    }

    const accessToken = request.cookies.get("access_token")?.value;
    if (accessToken) {
      const payload = decodeJWT(accessToken);
      if (payload && !isTokenExpired(accessToken)) {
        const defaultDashboard =
          payload.role === "officer"
            ? "/dashboard/officer"
            : payload.role === "collaborator"
              ? "/ctv"
              : "/dashboard";
        return NextResponse.redirect(new URL(defaultDashboard, request.url));
      }
    }
    // Not authenticated or token invalid — allow access to login/register
    return NextResponse.next();
  }

  // Allow other public routes without auth check
  if (isPublicRoute) {
    return NextResponse.next();
  }

  // ========================================
  // STEP 2: Get access_token from httpOnly cookie
  // ========================================

  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    // Expected for unauthenticated visitors — redirect silently, giữ cả query
    // (nhất quán với nhánh token invalid/expired bên dưới).
    return NextResponse.redirect(
      new URL(buildLoginRedirect(pathname + request.nextUrl.search), request.url),
    );
  }

  // ========================================
  // STEP 3: Decode and validate token
  // ========================================

  const payload = decodeJWT(accessToken);

  if (!payload) {
    console.warn(`[Proxy] ❌ Invalid token format for: ${pathname}`);

    // Clear invalid cookie and redirect (giữ return-url để login xong quay lại)
    const response = NextResponse.redirect(
      new URL(buildLoginRedirect(pathname + request.nextUrl.search), request.url),
    );
    response.cookies.delete("access_token");
    return response;
  }

  // Access token hết hạn KHÔNG đồng nghĩa phiên đã chết.
  //
  // `refresh_token` sống 30 ngày (REFRESH_TOKEN_EXPIRE_DAYS) và backend set nó
  // với `Path=/api` (auth.py `set_cookie`), nên trình duyệt KHÔNG gửi kèm khi
  // request tới `/admissions/...` hay `/dashboard`: middleware này không hề
  // nhìn thấy nó và do đó không có dữ liệu để kết luận "hết phiên". Trước đây
  // nó vẫn xoá `access_token` rồi đá về /login — quyết định dựa trên thông tin
  // thiếu. Access token chỉ sống 15 phút, nên chỉ cần rời máy một lúc rồi F5,
  // mở hồ sơ ở tab mới hay bấm link gây full document load là officer bị bắt
  // đăng nhập lại (và mất form đang nhập) dù phiên còn hiệu lực hàng tuần.
  //
  // Cách xử lý: đưa sang trang bootstrap công khai `/session-refresh`, nơi
  // client gọi được `/api/auth/refresh` (cookie khớp path) rồi quay lại đúng
  // URL cũ.
  //
  // ⚠️ KHÔNG `NextResponse.next()` ở đây, dù nghe có vẻ "để client tự lo":
  //  1. Server Component sẽ fetch NGAY với access token đã hết hạn (vd
  //     `admissions/[id]/page.tsx` gọi `serverApi`), backend trả 401 và
  //     `lib/api/server.ts` redirect `/login?force_login=true` — mà nhánh
  //     `force_login` phía trên xoá SẠCH cả `refresh_token`. Phiên mất hẳn
  //     trước khi client kịp hydrate: tệ hơn cả hành vi cũ.
  //  2. `next()` nằm TRƯỚC bước RBAC bên dưới, nên một token hết hạn sẽ đi
  //     thẳng vào `/admin/*` mà không qua kiểm quyền. Backend Casbin vẫn chặn
  //     dữ liệu, nhưng vỏ trang thì không nên lộ.
  if (isTokenExpired(accessToken)) {
    const expiredForMs = payload.exp ? Date.now() - payload.exp * 1000 : Infinity;
    const returnTo = pathname + request.nextUrl.search;

    if (expiredForMs < REFRESH_TOKEN_LIFETIME_MS) {
      console.warn(
        `[Proxy] ⏳ Access token hết hạn (${Math.round(expiredForMs / 1000)}s) — ` +
          `chuyển sang ${SESSION_REFRESH_PATH} để làm mới, KHÔNG xoá cookie: ${pathname}`,
      );
      const url = new URL(SESSION_REFRESH_PATH, request.url);
      if (isValidRedirect(returnTo)) url.searchParams.set("redirect", returnTo);
      // Cố ý KHÔNG xoá cookie nào: `refresh_token` là thứ sẽ cứu phiên, và
      // `access_token` hết hạn vốn vô hại (backend luôn tự kiểm hạn).
      return NextResponse.redirect(url);
    }

    console.warn(
      `[Proxy] ❌ Token hết hạn quá cửa sổ refresh (refresh_token cũng đã chết): ${pathname}`,
    );

    // Clear expired cookie and redirect (giữ return-url để login xong quay lại)
    const response = NextResponse.redirect(
      new URL(buildLoginRedirect(returnTo), request.url),
    );
    response.cookies.delete("access_token");
    return response;
  }

  // ========================================
  // STEP 4: Role-based access control (RBAC)
  // ========================================
  // NOTE: This is an early check for UX optimization (prevent flash of unauthorized content).
  // Backend Casbin performs the FINAL authorization check. Always keep roles.ts in sync with backend.

  if (isAdminRoute) {
    const userRole = payload.role;

    // ✅ DYNAMIC ROLE CHECK: Use config instead of hard-coded roles
    if (!hasAdminAccess(userRole)) {
      console.warn(
        `[Proxy] ❌ Unauthorized role '${userRole || "undefined"}' for admin route: ${pathname}`
      );

      // Redirect to dashboard (unauthorized for admin pages)
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    // Admin access granted — no log needed in production
  }

  if (isFinanceRoute) {
    const userRole = payload.role;

    if (!hasFinanceAccess(userRole)) {
      console.warn(
        `[Proxy] ❌ Unauthorized role '${userRole || "undefined"}' for finance route: ${pathname}`
      );

      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    // Finance access granted — no log needed in production
  }

  // ========================================
  // STEP 5: Role-based Dashboard Redirect
  // ========================================

  // Collaborators should use /ctv, not /dashboard
  if (pathname === "/dashboard" && payload.role === "collaborator") {
    return NextResponse.redirect(new URL("/ctv", request.url));
  }

  // Officers should use /dashboard/officer, not /dashboard
  if (pathname === "/dashboard" && payload.role === "officer") {
    // Redirect officer to their dashboard
    return NextResponse.redirect(new URL("/dashboard/officer", request.url));
  }

  // ========================================
  // STEP 6: Allow access
  // ========================================

  // Access granted — pass through
  return NextResponse.next();
}

// ============================================
// 🎯 MATCHER CONFIGURATION
// ============================================

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes - handled by backend)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico, robots.txt, sitemap.xml (public files)
     * - manifest.json (PWA manifest)
     * - public folder content (images, etc.)
     * - zalo_verifier*.html (Zalo Developer Console domain ownership proof —
     *   must be reachable without auth redirect; Zalo's verifier does not
     *   follow 307 to /login)
     */
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|manifest.json|zalo_verifier|.*\\.png|.*\\.jpg|.*\\.jpeg|.*\\.svg|.*\\.gif|.*\\.html).*)",
  ],
};
