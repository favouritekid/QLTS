// src/lib/api/refresh.ts
/**
 * Single-flight refresh access token (tách từ client.ts interceptor).
 *
 * Dùng chung cho: interceptor 401, CSRF-recovery (client.ts), và hook
 * proactive (useProactiveTokenRefresh). Single-flight bằng SHARED-PROMISE:
 * N caller đồng thời chia sẻ CÙNG promise đang bay → chỉ 1 POST /auth/refresh
 * thật (tránh token-reuse-detection do refresh trùng). Giữ delay 100ms cho
 * browser persist cookie mới.
 *
 * Module CHỈ import axios + env + endpoints (KHÔNG import `api` từ client.ts)
 * để tránh circular import. Leader dùng bare `axios.post` — không cần
 * interceptor cho chính call refresh (đúng hành vi inline cũ).
 */
import axios from "axios";
import { env } from "@/lib/config/env";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

let inflight: Promise<void> | null = null;

/**
 * Refresh access token (rotate cookie qua POST /api/auth/refresh).
 *
 * Single-flight: các lời gọi đồng thời chia sẻ cùng promise đang bay;
 * resolve khi xong, reject khi thất bại, rồi `inflight` reset để lần sau
 * phát request mới. KHÔNG side-effect logout/redirect — caller tự quyết
 * (interceptor 401 logout, hook proactive im lặng).
 */
/**
 * Refresh thất bại có nghĩa là "phiên đã chết" hay chỉ là "lỗi tạm thời"?
 *
 * Chỉ 401/403 mới là bằng chứng refresh token không còn hiệu lực → logout.
 * Mọi trường hợp khác PHẢI giữ phiên:
 *  - 429: rate limit. Audit prod 2026-07-30 — `/api/auth/refresh` bị chặn
 *    32% (86/270 request trong 24h) vì limit 20/giờ tính THEO IP, mà cả
 *    trường ra Internet qua một IP NAT. Trước đây một lần 429 = officer bị
 *    đá về /login giữa lúc nhập liệu, mất luôn form đang mở.
 *  - 5xx: backend/proxy lỗi tạm thời.
 *  - không có `response` (mạng đứt, timeout, CORS) hoặc lỗi không phải Axios:
 *    không biết gì về phiên → không được suy ra là phiên chết.
 *
 * Dùng chung cho MỌI caller của `refreshAccessToken` (interceptor 401 và
 * CSRF-recovery) để hai nhánh không phân loại lệch nhau.
 */
export function shouldLogoutAfterRefreshFailure(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const status = error.response?.status;
  if (status === undefined) return false;
  return status === 401 || status === 403;
}

export function refreshAccessToken(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    // Tokens gửi/nhận qua httpOnly cookie.
    await axios.post(
      `${env.NEXT_PUBLIC_API_URL}${API_ENDPOINTS.AUTH.REFRESH}`,
      {},
      { withCredentials: true },
    );
    // ⚠️ DEFENSIVE: chờ browser persist cookie mới trước khi caller retry.
    await new Promise((r) => setTimeout(r, 100));
  })().finally(() => {
    inflight = null;
  });
  return inflight;
}
