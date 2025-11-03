// src/app/api/auth/session/route.ts
import { NextRequest, NextResponse } from "next/server";
import { serialize } from "cookie"; // Import serialize từ thư viện cookie

const ACCESS_TOKEN_EXPIRE_MINUTES_NUM = parseInt(
  process.env.ACCESS_TOKEN_EXPIRE_MINUTES || "15",
  10
);
const ACCESS_TOKEN_MAX_AGE_SECONDS = ACCESS_TOKEN_EXPIRE_MINUTES_NUM * 60;

// POST handler: Nhận token và set cookie
export async function POST(request: NextRequest) {
  try {
    // 1. Lấy access token và refresh token từ body request
    const body = await request.json();
    const accessToken = body?.accessToken;
    const refreshToken = body?.refreshToken; // Lấy cả refresh token nếu muốn lưu vào cookie httpOnly

    if (!accessToken) {
      return NextResponse.json({ message: "Access token is required" }, { status: 400 });
    }

    // 2. Cấu hình cookie cho access token (hoặc session flag)
    // Tên cookie này sẽ được middleware kiểm tra
    const ACCESS_TOKEN_COOKIE_NAME = "auth_token"; // Đặt tên cookie
    const accessTokenCookie = serialize(ACCESS_TOKEN_COOKIE_NAME, accessToken, {
      httpOnly: true, // Quan trọng: Ngăn JavaScript client truy cập cookie
      secure: process.env.NODE_ENV === "production", // Chỉ gửi qua HTTPS ở production
      path: "/", // Cookie áp dụng cho toàn bộ trang web
      sameSite: "lax", // Giảm nguy cơ CSRF
      maxAge: ACCESS_TOKEN_MAX_AGE_SECONDS,
      // Hoặc để trống maxAge/expires để nó thành session cookie (xóa khi đóng trình duyệt)
      // Lưu ý: Nếu access token có hạn, maxAge nên khớp hoặc ngắn hơn
    });

    // 3. (Tùy chọn) Cấu hình cookie cho refresh token
    // Lưu refresh token vào httpOnly cookie an toàn hơn localStorage
    const REFRESH_TOKEN_COOKIE_NAME = "refresh_auth_token";
    let refreshTokenCookie = "";
    if (refreshToken) {
      refreshTokenCookie = serialize(REFRESH_TOKEN_COOKIE_NAME, refreshToken, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        path: "/", // Có thể giới hạn path nếu endpoint refresh khác, ví dụ: '/api/auth'
        sameSite: "strict", // Strict hơn cho refresh token
        maxAge: 60 * 60 * 24 * 30, // Thời gian sống (giây): 30 ngày, khớp với refresh token
      });
    }

    // 4. Tạo response và set cookie vào header
    const response = NextResponse.json({ message: "Session created" }, { status: 200 });
    response.headers.append("Set-Cookie", accessTokenCookie);
    if (refreshTokenCookie) {
      response.headers.append("Set-Cookie", refreshTokenCookie); // Set thêm cookie refresh token nếu có
    }

    return response;
  } catch (error) {
    console.error("[API /auth/session POST Error]:", error);
    return NextResponse.json({ message: "Failed to create session" }, { status: 500 });
  }
}

// DELETE handler: Xóa cookie khi logout
export async function DELETE(_request: NextRequest) {
  try {
    // Tên cookie cần khớp với lúc set
    const ACCESS_TOKEN_COOKIE_NAME = "auth_token";
    const REFRESH_TOKEN_COOKIE_NAME = "refresh_auth_token";

    // Tạo cookie hết hạn ngay lập tức
    const expiredAccessCookie = serialize(ACCESS_TOKEN_COOKIE_NAME, "", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      path: "/",
      sameSite: "lax",
      expires: new Date(0), // Set thời gian hết hạn trong quá khứ
    });
    const expiredRefreshCookie = serialize(REFRESH_TOKEN_COOKIE_NAME, "", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      path: "/", // Khớp path lúc set
      sameSite: "strict",
      expires: new Date(0),
    });

    // Tạo response và set cookie hết hạn
    const response = NextResponse.json({ message: "Session deleted" }, { status: 200 });
    response.headers.append("Set-Cookie", expiredAccessCookie);
    response.headers.append("Set-Cookie", expiredRefreshCookie);

    return response;
  } catch (error) {
    console.error("[API /auth/session DELETE Error]:", error);
    return NextResponse.json({ message: "Failed to delete session" }, { status: 500 });
  }
}
