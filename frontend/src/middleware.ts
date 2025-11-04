// src/middleware.ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// ⚠️ NOTE: Middleware runs on the server and cannot access localStorage
// Auth protection is handled by client-side guards in DashboardLayout
// This middleware is kept for future cookie-based auth if needed

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // For now, we'll just allow all requests to pass through
  // Client-side auth guards will handle redirects
  console.log(
    `[Middleware] Allowing access to ${pathname} (client-side auth guard will handle protection).`
  );
  return NextResponse.next();
}

// Cấu hình Matcher: Áp dụng middleware cho các route nào
export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder content (implicitly excluded by pattern)
     */
    "/((?!api|_next/static|_next/image|favicon.ico).*)",
  ],
};
