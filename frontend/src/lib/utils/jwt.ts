// lib/utils/jwt.ts
import { jwtDecode } from "jwt-decode";

// Định nghĩa cấu trúc payload của Access Token
// Phải khớp với cấu trúc trong `security.py`
interface AccessTokenPayload {
  sub: string;
  jti: string;
  r_jti: string; // ✅ Đây là JTI của Refresh Token
  type: "access";
  exp: number;
}

/**
 * Lấy JTI của Refresh Token (r_jti) từ bên trong Access Token.
 * @param token Access Token
 * @returns r_jti (Refresh Token JTI) hoặc null
 */
export const getRefreshJtiFromToken = (token: string): string | null => {
  try {
    // Giải mã token
    const payload = jwtDecode<AccessTokenPayload>(token);

    // Kiểm tra xem có đúng là Access Token và có r_jti không
    if (payload && payload.type === "access" && payload.r_jti) {
      return payload.r_jti;
    }
    console.warn("[jwt] Token is missing r_jti claim");
    return null;
  } catch (error) {
    console.error("[jwt] Failed to decode token", error);
    return null;
  }
};
