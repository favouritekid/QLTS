// src/middleware.ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Định nghĩa các route cần bảo vệ và các route xác thực
const protectedRoutes = ["/dashboard"]; // Thêm các route khác cần bảo vệ vào đây, ví dụ: /profile, /settings
const authRoutes = ["/login", "/register"]; // Các trang đăng nhập/đăng ký

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Lấy token từ cookies (Cần điều chỉnh nếu bạn lưu token ở nơi khác khi dùng Server Components/Actions)
  // Tạm thời, chúng ta sẽ kiểm tra cookie. Logic này cần hoàn thiện sau.
  const token = request.cookies.get("auth_token")?.value;

  // Kiểm tra xem route hiện tại có phải là route cần bảo vệ không
  const isProtectedRoute = protectedRoutes.some((route) => pathname.startsWith(route));

  // Kiểm tra xem route hiện tại có phải là route xác thực không
  const isAuthRoute = authRoutes.some((route) => pathname.startsWith(route));

  // --- Logic Chuyển Hướng ---

  // 1. Nếu truy cập route cần bảo vệ MÀ KHÔNG CÓ token -> Chuyển về /login
  if (isProtectedRoute && !token) {
    const loginUrl = new URL("/login", request.url);
    // Lưu lại URL gốc để có thể redirect lại sau khi login thành công
    loginUrl.searchParams.set("redirect", pathname);
    console.log(`[Middleware] Unauthorized access to ${pathname}, redirecting to login.`);
    return NextResponse.redirect(loginUrl);
  }

  // 2. Nếu truy cập route xác thực MÀ ĐÃ CÓ token -> Chuyển về /dashboard
  if (isAuthRoute && token) {
    console.log(`[Middleware] Authenticated user accessing ${pathname}, redirecting to dashboard.`);
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Nếu không rơi vào các trường hợp trên, cho phép truy cập bình thường
  console.log(`[Middleware] Allowing access to ${pathname}.`);
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
