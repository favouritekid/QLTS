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

  const isPublicRoute = PUBLIC_ROUTES.some((route) => pathname.startsWith(route));
  const isAdminRoute = ADMIN_ROUTES.some((route) => pathname.startsWith(route));
  const isFinanceRoute = FINANCE_ROUTES.some((route) => pathname.startsWith(route));

  // Allow public routes without auth check
  if (isPublicRoute) {
    return NextResponse.next();
  }

  // ========================================
  // STEP 2: Get access_token from httpOnly cookie
  // ========================================

  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    // Expected for unauthenticated visitors — redirect silently
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // ========================================
  // STEP 3: Decode and validate token
  // ========================================

  const payload = decodeJWT(accessToken);

  if (!payload) {
    console.warn(`[Proxy] ❌ Invalid token format for: ${pathname}`);

    // Clear invalid cookie and redirect
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.delete("access_token");
    return response;
  }

  // Check if token is expired
  if (isTokenExpired(accessToken)) {
    console.warn(`[Proxy] ❌ Expired token for: ${pathname}`);

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
        `[Proxy] ❌ Unauthorized role '${userRole || "undefined"}' for admin route: ${pathname}`
      );

      // Redirect to dashboard (unauthorized for admin pages)
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    console.log(`[Proxy] ✅ Admin access granted for role '${userRole}': ${pathname}`);
  }

  if (isFinanceRoute) {
    const userRole = payload.role;

    if (!hasFinanceAccess(userRole)) {
      console.warn(
        `[Proxy] ❌ Unauthorized role '${userRole || "undefined"}' for finance route: ${pathname}`
      );

      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    console.log(`[Proxy] ✅ Finance access granted for role '${userRole}': ${pathname}`);
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
    console.log(`[Proxy] 🔄 Redirecting officer to /dashboard/officer`);
    return NextResponse.redirect(new URL("/dashboard/officer", request.url));
  }

  // ========================================
  // STEP 6: Redirect authenticated users from public pages
  // ========================================

  // If user is logged in and tries to access login page, redirect to dashboard
  if (pathname === "/login" || pathname === "/register") {
    // Role-based redirect after login
    const defaultDashboard = payload.role === "officer"
      ? "/dashboard/officer"
      : payload.role === "collaborator"
        ? "/ctv"
        : "/dashboard";
    console.log(`[Proxy] Redirecting authenticated user from ${pathname} to ${defaultDashboard}`);
    return NextResponse.redirect(new URL(defaultDashboard, request.url));
  }

  // ========================================
  // STEP 7: Allow access
  // ========================================

  console.log(`[Proxy] ✅ Access granted: ${pathname} (user: ${payload.sub}, role: ${payload.role})`);
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
     */
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|manifest.json|.*\\.png|.*\\.jpg|.*\\.jpeg|.*\\.svg|.*\\.gif).*)",
  ],
};

