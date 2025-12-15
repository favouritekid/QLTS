// src/middleware.ts
/**
 * Next.js Middleware for Navigation Guard
 * Layer 1 of 3-Layer Guard System
 * 
 * Intercepts all requests and enforces role-based access control
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtDecode } from "jwt-decode";

// Inline route config to avoid import issues in Edge Runtime
const routeAccessConfig: Record<string, { allowedRoles?: string[]; officerRedirect?: string; denyRedirect?: string }> = {
  "/dashboard": {
    allowedRoles: ["admin", "manager"],
    officerRedirect: "/dashboard/officer",
  },
  "/admin": {
    allowedRoles: ["admin"],
    denyRedirect: "/403",
  },
  "/settings": {
    allowedRoles: ["admin", "manager"],
    denyRedirect: "/403",
  },
};

const publicRoutes = ["/login", "/register", "/forgot-password", "/reset-password"];

interface JWTPayload {
  sub: string;
  role?: string;
  exp?: number;
}

/**
 * Parse role from JWT token
 */
function parseRoleFromToken(token: string | undefined): string | null {
  if (!token) return null;
  
  try {
    const decoded = jwtDecode<JWTPayload>(token);
    return decoded.role || null;
  } catch {
    return null;
  }
}

/**
 * Check if route matches pattern (supports prefix with *)
 */
function findRouteConfig(pathname: string) {
  // Exact match
  if (routeAccessConfig[pathname]) {
    return routeAccessConfig[pathname];
  }

  // Prefix match
  for (const pattern of Object.keys(routeAccessConfig)) {
    if (pathname.startsWith(pattern + "/") || pathname === pattern) {
      return routeAccessConfig[pattern];
    }
  }

  return null;
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip public routes
  if (publicRoutes.some((route) => pathname.startsWith(route))) {
    return NextResponse.next();
  }

  // Skip static files
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.includes(".") // Files with extensions
  ) {
    return NextResponse.next();
  }

  // Get token from cookie
  const token = request.cookies.get("access_token")?.value;

  // No token = redirect to login
  if (!token) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Parse role from token
  const userRole = parseRoleFromToken(token);

  // No role in token = continue (legacy token or error)
  if (!userRole) {
    return NextResponse.next();
  }

  // Find route config
  const config = findRouteConfig(pathname);

  // No config = allow (unprotected route)
  if (!config) {
    return NextResponse.next();
  }

  // Check access
  const allowed = config.allowedRoles?.includes(userRole) ?? true;

  if (allowed) {
    return NextResponse.next();
  }

  // Officer trying to access restricted route
  if (userRole === "officer" && config.officerRedirect) {
    return NextResponse.redirect(new URL(config.officerRedirect, request.url));
  }

  // General deny
  const redirectTo = config.denyRedirect || "/";
  return NextResponse.redirect(new URL(redirectTo, request.url));
}

/**
 * Matcher config - only run middleware on these routes
 * This improves performance by not running on every request
 */
export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    "/((?!api|_next/static|_next/image|favicon.ico).*)",
  ],
};
