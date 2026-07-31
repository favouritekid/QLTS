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

// ============================================================================
// COOLDOWN sau khi bị rate limit
// ============================================================================
// Giữ phiên khi 429 làm MẤT cái phanh cũ: trước đây một lần refresh hỏng là
// `setApiLoggedOut(true)`, và request interceptor sẽ huỷ mọi request sau đó —
// tối đa MỘT POST /auth/refresh cho một phiên chết. Nay phiên còn sống nên mọi
// query tiếp tục chạy: riêng `useNotificationDeliveries` đã có 6 query
// `refetchInterval: 30s`, cộng dashboard 60s và `refetchOnReconnect` — mỗi lần
// 401 lại đẻ một POST /auth/refresh nữa, vào đúng cái bucket 20/giờ dùng chung
// cho cả trường. Single-flight KHÔNG cứu được: nó chỉ gộp các lời gọi ĐỒNG
// THỜI, `inflight` được xoá ngay khi settle.
//
// Vì vậy sau một verdict RATE_LIMITED, chặn tại chỗ (không chạm mạng) cho tới
// khi hết cooldown.
const DEFAULT_COOLDOWN_MS = 60_000;
const MAX_COOLDOWN_MS = 5 * 60_000;

let blockedUntil = 0;

/** Đọc `Retry-After` (giây) nếu backend có gửi; hiện slowapi chưa bật header. */
function cooldownFromError(error: unknown): number {
  const headers = axios.isAxiosError(error) ? error.response?.headers : undefined;
  const retryAfter = headers?.["retry-after"] ?? headers?.["Retry-After"];
  const seconds = Number(retryAfter);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Math.min(seconds * 1000, MAX_COOLDOWN_MS);
  }
  return DEFAULT_COOLDOWN_MS;
}

function isTransientRateLimit(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  if (error.response?.status !== 429) return false;
  const errorCode = (error.response?.data as { error_code?: string } | undefined)?.error_code;
  return errorCode === TRANSIENT_RATE_LIMIT_CODE;
}

/** Còn trong cooldown do vừa bị rate limit? (dùng cho hook proactive) */
export function isRefreshRateLimited(): boolean {
  return Date.now() < blockedUntil;
}

/**
 * Cờ interceptor gắn lên lỗi khi nó CỐ Ý giữ phiên sau một refresh hỏng tạm
 * thời. Cần vì quyết định logout không chỉ nằm ở interceptor: query
 * `/users/me` trong `useAuth` cũng tự đăng xuất khi thấy 401, và nó nhận đúng
 * lỗi 401 mà interceptor vừa quyết định là "không phải phiên chết". Không có
 * cờ này thì hai nơi mâu thuẫn nhau và người dùng vẫn bị đá ra.
 */
const SESSION_KEPT_ALIVE = "__qltsSessionKeptAlive";

export function markSessionKeptAlive<T>(error: T): T {
  if (error && typeof error === "object") {
    (error as Record<string, unknown>)[SESSION_KEPT_ALIVE] = true;
  }
  return error;
}

export function isSessionKeptAliveError(error: unknown): boolean {
  return (
    !!error &&
    typeof error === "object" &&
    (error as Record<string, unknown>)[SESSION_KEPT_ALIVE] === true
  );
}

/**
 * Lỗi "đang trong cooldown" — mang hình dạng AxiosError 429 + RATE_LIMITED để
 * caller phân loại y hệt một 429 thật (giữ phiên, toast "thử lại sau"), nhưng
 * KHÔNG tốn một request nào. Tạo mới mỗi lần để nhiều caller không dùng chung
 * một object mà annotate chồng lên nhau.
 */
function rateLimitedLocally() {
  return Object.assign(new Error("Refresh đang trong cooldown do rate limit"), {
    isAxiosError: true,
    response: {
      status: 429,
      data: { error_code: TRANSIENT_RATE_LIMIT_CODE, detail: "Quá nhiều yêu cầu. Vui lòng thử lại sau." },
      headers: {},
    },
  });
}

/**
 * Refresh thất bại có nghĩa là "phiên đã chết" hay chỉ là "lỗi tạm thời"?
 *
 * Quy tắc là ĐẢO NGƯỢC của whitelist: MỌI lỗi 4xx đều coi là phiên chết, trừ
 * đúng một ngoại lệ 429 + `RATE_LIMITED`. Liệt kê xuôi (chỉ 401/403/429) để
 * sót 400/404/410/422 — vd sai `NEXT_PUBLIC_API_URL`, đổi route proxy, hay
 * một validation deny mới thêm vào endpoint — và khi đó client giữ phiên với
 * access token đã chết, lặp 401→refresh→4xx vô hạn không lối thoát.
 *
 * Logout khi:
 *  - 401/403: refresh token không còn hiệu lực.
 *  - mọi 4xx khác (400/404/410/422…): endpoint từ chối theo cách client không
 *    tự phục hồi được → đăng nhập lại là đường thoát duy nhất.
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
  if (status === undefined) return false; // mạng đứt/timeout/CORS — không biết gì về phiên
  if (status === 429) {
    const errorCode = (error.response?.data as { error_code?: string } | undefined)
      ?.error_code;
    return errorCode !== TRANSIENT_RATE_LIMIT_CODE;
  }
  return status >= 400 && status < 500;
}

/**
 * Refresh access token (rotate cookie qua POST /api/auth/refresh).
 *
 * Single-flight: các lời gọi đồng thời chia sẻ cùng promise đang bay;
 * resolve khi xong, reject khi thất bại, rồi `inflight` reset để lần sau
 * phát request mới. KHÔNG side-effect logout/redirect — caller tự quyết
 * (interceptor 401 logout, hook proactive im lặng).
 *
 * Trong cooldown sau một 429 RATE_LIMITED thì reject NGAY, không chạm mạng —
 * xem khối COOLDOWN ở đầu file.
 */
export function refreshAccessToken(): Promise<void> {
  if (inflight) return inflight;
  if (isRefreshRateLimited()) {
    return Promise.reject(rateLimitedLocally());
  }
  inflight = (async () => {
    try {
      // Tokens gửi/nhận qua httpOnly cookie.
      await axios.post(
        `${env.NEXT_PUBLIC_API_URL}${API_ENDPOINTS.AUTH.REFRESH}`,
        {},
        { withCredentials: true },
      );
    } catch (err) {
      if (isTransientRateLimit(err)) {
        blockedUntil = Date.now() + cooldownFromError(err);
      }
      throw err;
    }
    // Refresh thành công → quota còn chỗ, gỡ cooldown nếu đang treo.
    blockedUntil = 0;
    // ⚠️ DEFENSIVE: chờ browser persist cookie mới trước khi caller retry.
    await new Promise((r) => setTimeout(r, 100));
  })().finally(() => {
    inflight = null;
  });
  return inflight;
}
