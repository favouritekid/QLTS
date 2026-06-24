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
import { refreshAccessToken } from "./refresh";
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
        console.error("[API Client] ❌ Refresh failed:", refreshError);

        // Fallback Logout: chặn API tiếp theo, clear store, rồi hard
        // redirect KÈM return-url để sau khi đăng nhập lại quay về đúng trang.
        if (typeof window !== "undefined" && !publicPages.includes(currentPath)) {
          console.log("[API Client] 🚪 Session invalid — logging out...");
          setApiLoggedOut(true);

          // Clear Zustand auth store
          try {
            const { useAuthStore } = await import("@/lib/stores/auth.store");
            useAuthStore.getState().logout();
          } catch {
            // Best-effort
          }

          // force_login → middleware xoá cookie cũ mà JS không xoá được.
          window.location.href = buildLoginRedirect(currentPath + currentSearch, {
            forceLogin: true,
          });
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

        // Skip recovery on public pages or during logout
        if (typeof window !== "undefined") {
          const currentPath = window.location.pathname;
          const publicPages = ["/login", "/register", "/forgot-password", "/reset-password"];
          if (publicPages.includes(currentPath) || isApiLoggedOut()) {
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
          console.warn("[API Client] ❌ CSRF recovery failed (refresh rejected) — redirecting to login");

          if (typeof window !== "undefined") {
            setApiLoggedOut(true);
            // forceLogin → middleware xoá httpOnly cookie chết (giống nhánh 401);
            // CSRF-recovery fail nghĩa session đã hết hiệu lực.
            window.location.href = buildLoginRedirect(
              window.location.pathname + window.location.search,
              { forceLogin: true, reason: "session_expired" },
            );
          }

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
