// middleware.ts
/**
 * Next.js Edge Middleware — runs before every matched route.
 *
 * Responsibilities:
 * 1. Redirect authenticated users AWAY from auth pages (login, register, …)
 * 2. Redirect unauthenticated users TO /login when accessing protected pages
 *
 * Auth detection: checks for the `access_token` httpOnly cookie set by the
 * backend.  This is a lightweight hint — the backend still validates the
 * token on every API call.
 *
 * Edge case: after password change, the backend clears cookies in the response,
 * but if the client-side interceptor redirects to /login before that response
 * is processed, the cookie may still be present. The `force_login` query param
 * lets the interceptor bypass the "already authenticated" redirect and also
 * clears the stale cookie.
 */
import { NextRequest, NextResponse } from "next/server";

// Routes that don't require authentication
const AUTH_ROUTES = ["/login", "/register", "/forgot-password", "/reset-password", "/register-ctv"];

// Routes that are fully public (no redirect either way)
const PUBLIC_ROUTES = ["/api", "/_next", "/favicon.ico", "/health"];

function isAuthRoute(pathname: string): boolean {
  return AUTH_ROUTES.some((route) => pathname === route || pathname.startsWith(route + "/"));
}

function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some((prefix) => pathname.startsWith(prefix));
}

export function middleware(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;

  // Skip public/static routes
  if (isPublicRoute(pathname)) {
    return NextResponse.next();
  }

  const hasAccessToken = request.cookies.has("access_token");
  const forceLogin = searchParams.get("force_login") === "true";

  // --- Force login: clear stale cookies and allow login page ---
  if (forceLogin && isAuthRoute(pathname)) {
    const response = NextResponse.next();
    // Path must match backend set_cookie paths for deletion to work
    response.cookies.delete({ name: "access_token", path: "/" });
    response.cookies.delete({ name: "refresh_token", path: "/api" });
    response.cookies.delete({ name: "csrf_token", path: "/" });
    return response;
  }

  // --- Authenticated user on auth page → redirect to dashboard ---
  if (hasAccessToken && isAuthRoute(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  // --- Unauthenticated user on protected page → redirect to login ---
  if (!hasAccessToken && !isAuthRoute(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    // Preserve intended destination for post-login redirect
    if (pathname !== "/") {
      url.searchParams.set("redirect", pathname);
    }
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Match all routes except static files and api routes
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
