// src/lib/api/client.ts
/**
 * Axios client instance with auto-refresh interceptors
 *
 * ✅ FIX-4 ENHANCED: Mutex lock + queue + 100ms browser delay
 * Prevents race conditions and token reuse detection triggers
 *
 * ✅ CSRF Protection: Double-Submit Cookie pattern
 * Automatically sends X-CSRF-Token header for state-changing requests
 *
 * Features:
 * - Auto-refresh access token on 401 errors
 * - Mutex lock prevents duplicate refresh requests
 * - Queue concurrent requests during refresh
 * - 100ms delay for browser cookie persistence
 * - CSRF token injection for POST/PUT/DELETE/PATCH
 * - Prevent infinite loops
 * - Graceful error handling
 */
import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

import {
  getCSRFToken,
  requiresCSRFToken,
  isCSRFError,
  CSRF_HEADER_NAME,
} from "./csrf";
import { env } from "@/lib/config/env";
import { inspectVersionHeaders } from "@/lib/api/api-versioning";
import {
  markSessionKeptAlive,
  refreshAccessToken,
  shouldClearAuthCookies,
  isRefreshFailure,
} from "./refresh";
import { buildLoginRedirect } from "@/lib/auth/login-redirect";
export const API_BASE_URL = env.NEXT_PUBLIC_API_URL;

// ============================================
// 🚫 LOGOUT GUARD (window-level flag)
// ============================================
// Uses window global to survive Turbopack HMR module reloads.
// Set by logoutMutation in useAuth.ts, reset on login success.
export function isApiLoggedOut(): boolean {
  return typeof window !== "undefined" && !!(window as unknown as Record<string, unknown>).__qlts_logged_out;
}
export function setApiLoggedOut(value: boolean) {
  if (typeof window !== "undefined") {
    (window as unknown as Record<string, unknown>).__qlts_logged_out = value;
  }
}

// Create axios instance
export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // ✅ Send HttpOnly cookies (refresh_token)
  headers: {
    "Content-Type": "application/json",
  },
});

// ============================================
// 🔒 AUTO-REFRESH TOKEN MECHANISM
// ============================================
// Logic single-flight (mutex + queue + delay 100ms cookie-persist) đã được
// tách sang ./refresh (`refreshAccessToken`) để dùng chung cho: interceptor
// 401, CSRF-recovery, và hook proactive (useProactiveTokenRefresh).

// ============================================
// 📤 REQUEST INTERCEPTOR
// ============================================

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // ✅ LOGOUT GUARD: Block non-auth requests after logout.
    // After logoutMutation sets _loggedOut=true, stale React Query
    // observers may still fire requests before components unmount.
    // Rejecting them here prevents spurious 401 errors.
    if (isApiLoggedOut() && !config.url?.includes("/auth/")) {
      return Promise.reject(new axios.Cancel("Blocked: logged out"));
    }

    // ✅ CSRF Protection: Add X-CSRF-Token header for state-changing requests
    // The csrf_token cookie is set by backend on login/refresh (httpOnly=false)
    if (requiresCSRFToken(config.method)) {
      const csrfToken = getCSRFToken();
      if (csrfToken) {
        config.headers[CSRF_HEADER_NAME] = csrfToken;
      }
      // Note: If token is missing, request will proceed but backend may reject
      // This handles edge cases like first login before cookie is set
    }

    // ✅ OPTIONAL ENHANCEMENT: Auto-detect FormData
    if (config.data instanceof FormData) {
      delete config.headers["Content-Type"];
      if (process.env.NODE_ENV === "development") {
        console.log("[API Client] 📤 FormData detected - Auto-setting multipart headers");
      }
    }

    return config;
  },
  (error: AxiosError) => Promise.reject(error)
);

// ============================================
// 🔁 REFRESH FAILURE TRIAGE (dùng chung 2 nhánh)
// ============================================
type RefreshTriage =
  | { action: "logout" }
  | { action: "reject"; error: unknown };

/**
 * Refresh thất bại: phiên đã chết (logout) hay lỗi tạm thời (giữ phiên)?
 *
 * Quyết định LOGOUT đọc thẳng `outcome` đã phân loại qua `shouldClearAuthCookies`
 * — chỉ `terminal` mới được xoá cookie. Ba loại còn lại (`safe-retryable`,
 * `nonterminal-stop`, `ambiguous`) đều giữ phiên.
 *
 * Chọn lỗi để reject thì phụ thuộc CALL SITE, không suy từ status:
 *
 *  - `reject: "original"` (nhánh 401) — trả lại chính `AxiosError 401` gốc.
 *    Retry predicate ở `providers.tsx` chỉ chặn retry khi thấy một
 *    **`AxiosError` thật, 4xx, có `response`**. Trả `RefreshFailure` ở đây là
 *    trả một lỗi không phải AxiosError ⇒ React Query retry 3 lần, mỗi lần bắn
 *    thêm một `POST /auth/refresh` vào đúng quota dùng chung của cả trường.
 *
 *  - `reject: "cause"` (nhánh CSRF) — trả `RefreshFailure` để giữ NGUYÊN NHÂN
 *    thật. Lỗi gốc ở đó là 403 CSRF, mà `handleApiError` map 403 → "Bạn không
 *    có quyền thực hiện thao tác này": báo sai hoàn toàn khi nguyên nhân thật
 *    là backend 5xx. Nhánh này chạy cho mutation và `mutations: { retry: false }`
 *    nên không có nguy cơ retry storm.
 *
 * Trả kết quả có nhãn thay vì sentinel `null`: với sentinel, kiểu
 * `AxiosError | unknown | null` bị TypeScript thu về `unknown` nên guard
 * `!== null` không kiểm được gì ở compile time.
 */
function triageRefreshFailure(
  originalError: unknown,
  refreshError: unknown,
  opts: { tag: string; reject: "original" | "cause" },
): RefreshTriage {
  if (shouldClearAuthCookies(refreshError)) {
    return { action: "logout" };
  }

  const kind = isRefreshFailure(refreshError) ? refreshError.outcome.kind : "unknown";
  console.warn(
    `[API Client] ⏳ ${opts.tag}: refresh không thành công (${kind}) — giữ phiên, không logout`,
  );

  // Đánh dấu để các consumer khác (vd query /users/me trong useAuth) không tự
  // đăng xuất khi thấy 401 — quyết định "giữ phiên" đã được đưa ra ở đây.
  return {
    action: "reject",
    error: markSessionKeptAlive(
      opts.reject === "original" ? originalError : refreshError,
    ),
  };
}

/**
 * Đăng xuất cứng khi phiên đã chết: chặn request kế tiếp, XOÁ store, rồi hard
 * redirect kèm return-url.
 *
 * Dùng chung cho cả hai nhánh. Trước đây nhánh CSRF thiếu bước clear store,
 * nên sau redirect `auth.store` vẫn rehydrate `user` từ localStorage
 * (`partialize` giữ `user`, và `isAuthenticated = !!user`) → app khởi động lại
 * như đang đăng nhập trên một session đã bị thu hồi.
 */
async function performSessionExpiredLogout(pathname: string, search: string) {
  if (typeof window === "undefined") return;

  setApiLoggedOut(true);
  try {
    const { useAuthStore } = await import("@/lib/stores/auth.store");
    useAuthStore.getState().logout();
  } catch {
    // Best-effort
  }
  window.location.href = buildLoginRedirect(pathname + search, {
    forceLogin: true,
    reason: "session_expired",
  });
}

// ============================================
// 📥 RESPONSE INTERCEPTOR WITH AUTO-REFRESH
// ============================================

api.interceptors.response.use(
  // Success responses — inspect soft-cutoff headers (Wave B+30 deprecation,
  // Wave B+90 schema-version mismatch) before passing through.
  (response) => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      inspectVersionHeaders(response.headers as any)
    } catch {
      // Defensive — versioning is observability, never block the response
    }
    return response
  },

  // Error responses - handle 401 with auto-refresh
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // ========================================
    // STEP 1: Check if this is a 401 error
    // ========================================
    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      !originalRequest.url?.includes("/auth/login") &&
      !originalRequest.url?.includes("/auth/register") &&
      !originalRequest.url?.includes("/auth/refresh") &&
      !originalRequest.url?.includes("/auth/forgot-password") &&
      !originalRequest.url?.includes("/auth/reset-password") &&
      !originalRequest.url?.includes("/auth/verify-mfa")
    ) {
      // Skip refresh during logout - requests may arrive after cookies
      // are cleared but before components unmount. Just reject silently.
      if (isApiLoggedOut()) {
        return Promise.reject(error);
      }

      const currentPath = typeof window !== "undefined" ? window.location.pathname : "";
      // Capture search CÙNG LÚC (trước await refresh) — tránh trộn pathname cũ
      // với query mới nếu user điều hướng client-side trong lúc refresh.
      const currentSearch = typeof window !== "undefined" ? window.location.search : "";

      // Don't redirect if already on public pages
      const publicPages = ["/login", "/register", "/forgot-password", "/reset-password"];
      if (publicPages.includes(currentPath)) {
        return Promise.reject(error);
      }

      // ========================================
      // STEP 2: REFRESH (single-flight) + RETRY
      // refreshAccessToken() tự xử lý mutex/queue/100ms (xem ./refresh):
      // request đầu là leader gọi /auth/refresh, các request khác chờ.
      // ========================================
      originalRequest._retry = true;

      try {
        await refreshAccessToken();
        // Refresh thành công → retry request gốc với cookie mới.
        return api(originalRequest);
      } catch (refreshError) {
        // Lỗi TẠM THỜI (429 RATE_LIMITED / 5xx / mạng đứt) KHÔNG phải bằng
        // chứng phiên đã chết → giữ phiên, chỉ để request gốc thất bại. Trước
        // đây một lần 429 trên /auth/refresh là đủ đá officer về /login giữa
        // lúc nhập liệu (audit prod 2026-07-30). Phân loại TRƯỚC khi log để
        // một 429 bình thường không đổ console.error vào monitoring.
        const triage = triageRefreshFailure(error, refreshError, {
          tag: "401",
          // Trả lại chính AxiosError 401 gốc: predicate retry ở providers.tsx
          // chỉ chặn retry khi thấy AxiosError 4xx CÓ response.
          reject: "original",
        });
        if (triage.action === "reject") {
          return Promise.reject(triage.error);
        }

        console.error("[API Client] ❌ Refresh failed:", refreshError);

        // Fallback Logout: chặn API tiếp theo, clear store, rồi hard
        // redirect KÈM return-url để sau khi đăng nhập lại quay về đúng trang.
        if (typeof window !== "undefined" && !publicPages.includes(currentPath)) {
          console.log("[API Client] 🚪 Session invalid — logging out...");
          await performSessionExpiredLogout(currentPath, currentSearch);
        }

        return Promise.reject(refreshError);
      }
    }

    // ========================================
    // C2 SECURITY FIX: Handle PASSWORD_CHANGE_REQUIRED
    // ========================================
    if (
      error.response?.status === 403 &&
      typeof error.response?.data === "object" &&
      error.response.data !== null &&
      "detail" in error.response.data &&
      typeof error.response.data.detail === "object" &&
      error.response.data.detail !== null &&
      "code" in error.response.data.detail &&
      error.response.data.detail.code === "PASSWORD_CHANGE_REQUIRED"
    ) {
      console.log("[API Client] 🔐 Password change required - redirecting...");

      if (typeof window !== "undefined") {
        // Redirect to change-password page with a flag
        window.location.href = "/settings/change-password?forced=true";
      }

      return Promise.reject(error);
    }

    // ========================================
    // CSRF ERROR HANDLING — Recovery via refresh
    // ========================================
    // When csrf_token cookie expires (24h) but refresh_token (30d) is still valid,
    // CSRF middleware blocks with 403 BEFORE auth can return 401.
    // Fix: attempt /auth/refresh (CSRF-exempt) to get a new csrf_token cookie,
    // then retry the original request once.
    if (error.response?.status === 403) {
      const errorData = error.response?.data as { error_code?: string; detail?: string } | undefined;
      const errorCode = errorData?.error_code;

      if (isCSRFError(errorCode) && originalRequest && !originalRequest._retry) {
        console.warn("[API Client] 🛡️ CSRF error detected:", errorCode, "— attempting recovery via refresh");

        // Capture path/search TRƯỚC await refresh — cùng lý do với nhánh 401:
        // user có thể điều hướng client-side trong lúc refresh đang bay, và
        // return-url sẽ trộn pathname cũ với query mới.
        const csrfPath = typeof window !== "undefined" ? window.location.pathname : "";
        const csrfSearch = typeof window !== "undefined" ? window.location.search : "";

        // Skip recovery on public pages or during logout
        if (typeof window !== "undefined") {
          const publicPages = ["/login", "/register", "/forgot-password", "/reset-password"];
          if (publicPages.includes(csrfPath) || isApiLoggedOut()) {
            return Promise.reject(error);
          }
        }

        // Try refresh — /auth/refresh là CSRF-exempt và set lại csrf_token cookie.
        // Dùng chung refreshAccessToken() (single-flight) — tránh chạy song song
        // với một refresh do 401 đang diễn ra.
        originalRequest._retry = true;
        try {
          await refreshAccessToken();

          if (process.env.NODE_ENV === "development") {
            console.log("[API Client] ✅ CSRF recovery: refresh succeeded, retrying original request");
          }

          // Retry — interceptor sẽ đọc lại csrf_token mới từ document.cookie.
          return api(originalRequest);
        } catch (refreshError) {
          // Cùng một triage với nhánh 401 — hai nhánh này đã từng drift nhau
          // (xem comment "Dùng chung refreshAccessToken()" phía trên), nên
          // quyết định logout nằm ở MỘT chỗ duy nhất.
          //
          // Fallback là refreshError chứ KHÔNG phải `error`: lỗi gốc ở nhánh
          // này là 403 CSRF, mà handleApiError map 403 → "Bạn không có quyền
          // thực hiện thao tác này" — báo sai hẳn nguyên nhân khi thực chất
          // backend đang 5xx. Mutation không retry nên không sợ retry storm.
          const triage = triageRefreshFailure(error, refreshError, {
            tag: "CSRF recovery",
            // Mutation đã `retry: false`, nên giữ NGUYÊN NHÂN thật quan trọng
            // hơn — 403 CSRF gốc sẽ báo sai thành "không có quyền".
            reject: "cause",
          });
          if (triage.action === "reject") {
            return Promise.reject(triage.error);
          }

          console.warn("[API Client] ❌ CSRF recovery failed (refresh rejected) — redirecting to login");

          // Dùng chung đường logout với nhánh 401 — trước đây nhánh này quên
          // clear store nên user cũ vẫn rehydrate như đang đăng nhập.
          await performSessionExpiredLogout(csrfPath, csrfSearch);

          return Promise.reject(refreshError);
        }
      }

      // Non-CSRF 403 errors (e.g., PASSWORD_CHANGE_REQUIRED already handled above)
    }

    // For non-401 errors, just reject
    return Promise.reject(error);
  }
);

// ============================================
// 📊 EXPORT
// ============================================

export { api as apiClient };
export default api;
