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
 * `error_code` backend gửi cho 429 do rate limit HẠ TẦNG (slowapi) — xem
 * `app/core/rate_limits.py::RATE_LIMITED_ERROR_CODE`. Đây là mã DUY NHẤT
 * khiến một 429 được coi là tạm thời.
 */
const TRANSIENT_RATE_LIMIT_CODE = "RATE_LIMITED";

/**
 * Refresh thất bại có nghĩa là "phiên đã chết" hay chỉ là "lỗi tạm thời"?
 *
 * Logout khi:
 *  - 401/403: refresh token không còn hiệu lực.
 *  - 429 mà KHÔNG phải rate limit hạ tầng. `POST /auth/refresh` phát 429 cho
 *    HAI nghĩa khác nhau: quota IP của slowapi (`RATE_LIMITED`, tạm thời) và
 *    cổng chống lạm dụng M4 (`REFRESH_ABUSE_LOCKED`, `app/routers/auth.py`).
 *    Ở nhánh M4, chính lần lỗi chạm ngưỡng đã gọi `invalidate_all_sessions`
 *    và trả 401; các lần sau mới nhận 429 — nên phiên ĐÃ chết phía server,
 *    giữ phiên sẽ tạo vòng lặp 401→429→401 mà UI vẫn báo đang đăng nhập.
 *    Phân loại theo `error_code`, KHÔNG theo chuỗi thông báo (chuỗi có thể
 *    được dịch/sửa bất cứ lúc nào). Thiếu mã hoặc mã lạ → coi là phiên chết:
 *    fail-safe nghiêng về phía an toàn.
 *
 * Giữ phiên khi:
 *  - 429 có đúng `RATE_LIMITED`. Audit prod 2026-07-30 — `/api/auth/refresh`
 *    bị chặn 32% (86/270 request trong 24h) vì limit 20/giờ tính THEO IP, mà
 *    cả trường ra Internet qua một IP NAT. Trước đây một lần 429 = officer bị
 *    đá về /login giữa lúc nhập liệu, mất luôn form đang mở.
 *  - 5xx: backend/proxy lỗi tạm thời.
 *  - không có `response` (mạng đứt, timeout, CORS) hoặc lỗi không phải Axios:
 *    không biết gì về phiên → không được suy ra là phiên chết.
 *
 * Dùng chung cho hai caller quyết định logout (interceptor 401 và
 * CSRF-recovery trong `client.ts`) để chúng không phân loại lệch nhau.
 * `useProactiveTokenRefresh` KHÔNG dùng hàm này — nó nuốt mọi lỗi và để
 * request kế tiếp surface 401; xem ghi chú ở hook đó.
 */
export function shouldLogoutAfterRefreshFailure(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const status = error.response?.status;
  if (status === 401 || status === 403) return true;
  if (status === 429) {
    const errorCode = (error.response?.data as { error_code?: string } | undefined)
      ?.error_code;
    return errorCode !== TRANSIENT_RATE_LIMIT_CODE;
  }
  return false;
}

/**
 * Refresh access token (rotate cookie qua POST /api/auth/refresh).
 *
 * Single-flight: các lời gọi đồng thời chia sẻ cùng promise đang bay;
 * resolve khi xong, reject khi thất bại, rồi `inflight` reset để lần sau
 * phát request mới. KHÔNG side-effect logout/redirect — caller tự quyết
 * (interceptor 401 logout, hook proactive im lặng).
 */
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
