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
