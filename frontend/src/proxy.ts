// src/middleware.ts
/**
 * 🔒 SERVER-SIDE AUTHENTICATION MIDDLEWARE
 *
 * ✅ SECURITY FIX: Prevents Client-Side Auth Guard vulnerability
 *
 * This middleware runs on the server BEFORE any page is rendered, ensuring:
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
import { hasAdminAccess } from "@/lib/config/roles";

// ============================================
// 🛣️ ROUTE CONFIGURATION
// ============================================

/**
 * Public routes that don't require authentication
 */
const PUBLIC_ROUTES = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
];

/**
 * Admin-only routes (requires admin or manager role)
 */
const ADMIN_ROUTES = ["/admin"];

/**
 * Protected routes that require authentication
 * Note: Currently not used - all non-public routes are treated as protected by default
 * Kept for potential future use if specific route handling is needed
 */
// const PROTECTED_ROUTES = ["/dashboard", "/profile", "/settings"];

// ============================================
// 🔐 MIDDLEWARE LOGIC
// ============================================

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // ========================================
  // STEP 1: Check if route requires auth
  // ========================================

  const isPublicRoute = PUBLIC_ROUTES.some((route) => pathname.startsWith(route));
  const isAdminRoute = ADMIN_ROUTES.some((route) => pathname.startsWith(route));

  // Allow public routes without auth check
  if (isPublicRoute) {
    console.log(`[Middleware] Public route: ${pathname}`);
    return NextResponse.next();
  }

  // ========================================
  // STEP 2: Get access_token from httpOnly cookie
  // ========================================

  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    console.warn(`[Middleware] ❌ No access token for protected route: ${pathname}`);

    // Redirect to login with return URL
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // ========================================
  // STEP 3: Decode and validate token
  // ========================================

  const payload = decodeJWT(accessToken);

  if (!payload) {
    console.warn(`[Middleware] ❌ Invalid token format for: ${pathname}`);

    // Clear invalid cookie and redirect
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.delete("access_token");
    return response;
  }

  // Check if token is expired
  if (isTokenExpired(accessToken)) {
    console.warn(`[Middleware] ❌ Expired token for: ${pathname}`);

    // Clear expired cookie and redirect
    const response = NextResponse.redirect(new URL("/login", request.url));
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
        `[Middleware] ❌ Unauthorized role '${userRole || "undefined"}' for admin route: ${pathname}`
      );

      // Redirect to dashboard (unauthorized for admin pages)
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    console.log(`[Middleware] ✅ Admin access granted for role '${userRole}': ${pathname}`);
  }

  // ========================================
  // STEP 5: Redirect authenticated users from public pages
  // ========================================

  // If user is logged in and tries to access login page, redirect to dashboard
  if (pathname === "/login" || pathname === "/register") {
    console.log(`[Middleware] Redirecting authenticated user from ${pathname} to /dashboard`);
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // ========================================
  // STEP 6: Allow access
  // ========================================

  console.log(`[Middleware] ✅ Access granted: ${pathname} (user: ${payload.sub})`);
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
     * - public folder content (images, etc.)
     */
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.png|.*\\.jpg|.*\\.jpeg|.*\\.svg|.*\\.gif).*)",
  ],
};
