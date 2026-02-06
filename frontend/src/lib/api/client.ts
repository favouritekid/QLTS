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

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

// Create axios instance
export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // ✅ Send HttpOnly cookies (refresh_token)
  headers: {
    "Content-Type": "application/json",
  },
});

// ============================================
// 🔒 AUTO-REFRESH TOKEN MECHANISM (FIX-4 ENHANCED)
// ============================================

/**
 * Mutex lock + Queue mechanism to prevent race conditions
 *
 * When multiple requests receive 401 simultaneously:
 * - Only ONE refresh request is made (Leader)
 * - Other requests wait in queue (Followers)
 * - After refresh success, all queued requests retry
 *
 * This prevents "Token Reuse Detection" false positives
 * caused by duplicate refresh requests hitting backend.
 */
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value?: unknown) => void;
  reject: (reason?: unknown) => void;
}> = [];

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

// ============================================
// 📤 REQUEST INTERCEPTOR
// ============================================

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // ✅ SECURITY FIX: No longer need to manually set Authorization header
    // Tokens are sent automatically via httpOnly cookies by browser
    // withCredentials: true ensures cookies are included in requests

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
      console.log("[API Client] 📤 FormData detected - Auto-setting multipart headers");
    }

    return config;
  },
  (error: AxiosError) => Promise.reject(error)
);

// ============================================
// 📥 RESPONSE INTERCEPTOR WITH AUTO-REFRESH
// ============================================

api.interceptors.response.use(
  // Success responses - pass through
  (response) => response,

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
      !originalRequest.url?.includes("/auth/reset-password")
    ) {
      const currentPath = typeof window !== "undefined" ? window.location.pathname : "";

      // Don't redirect if already on public pages
      const publicPages = ["/login", "/register", "/forgot-password", "/reset-password"];
      if (publicPages.includes(currentPath)) {
        return Promise.reject(error);
      }

      // ========================================
      // STEP 2: QUEUE MECHANISM (Follower)
      // If refresh is already in progress, queue this request
      // ========================================
      if (isRefreshing) {
        console.log("[API Client] 🔄 Request queued (refresh in progress)");

        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(() => {
            // When queue is processed, retry original request
            return api(originalRequest);
          })
          .catch((err) => {
            return Promise.reject(err);
          });
      }

      // ========================================
      // STEP 3: START REFRESH PROCESS (Leader)
      // ========================================
      originalRequest._retry = true;
      isRefreshing = true;

      try {
        console.log("[API Client] 🔄 Access token expired, refreshing...");

        // Call /refresh endpoint (tokens sent/received via httpOnly cookies)
        await axios.post(
          `${API_BASE_URL}/api/auth/refresh`,
          {},
          {
            withCredentials: true, // ✅ Important: Send refresh_token cookie
          }
        );

        // ⚠️ DEFENSIVE FIX: Wait for browser to persist new cookie
        // This prevents race condition at browser storage level
        // Some browsers (especially mobile) need 50-150ms to persist cookies
        await new Promise((resolve) => setTimeout(resolve, 100));

        console.log("[API Client] ✅ Token refreshed successfully (via httpOnly cookie)");

        // ========================================
        // STEP 4: NOTIFY QUEUED REQUESTS
        // ========================================
        processQueue(null, "success");

        // ========================================
        // STEP 5: RETRY ORIGINAL REQUEST
        // ========================================
        return api(originalRequest);
      } catch (refreshError) {
        console.error("[API Client] ❌ Refresh failed:", refreshError);

        // ========================================
        // STEP 6: HANDLE REFRESH FAILURE
        // ========================================
        processQueue(refreshError, null);

        // Fallback Logout: Hard redirect to clear all state
        // Using window.location.href is more reliable than dynamic imports
        if (typeof window !== "undefined" && !publicPages.includes(currentPath)) {
          console.log("[API Client] 🚪 Redirecting to login...");
          window.location.href = "/login";
        }

        return Promise.reject(refreshError);
      } finally {
        // Always unlock mutex
        isRefreshing = false;
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
    // CSRF ERROR HANDLING
    // ========================================
    // Handle CSRF token errors (403 with CSRF error codes)
    // This can happen if:
    // 1. User's session expired and cookie was cleared
    // 2. Cookie was deleted manually
    // 3. Cross-site request attempt (attack scenario)
    if (error.response?.status === 403) {
      const errorData = error.response?.data as { error_code?: string; detail?: string } | undefined;
      const errorCode = errorData?.error_code;

      if (isCSRFError(errorCode)) {
        console.warn("[API Client] 🛡️ CSRF error detected:", errorCode);

        // For CSRF errors, the user likely needs to re-authenticate
        // because the csrf_token cookie is tied to their session
        if (typeof window !== "undefined") {
          const currentPath = window.location.pathname;
          const publicPages = ["/login", "/register", "/forgot-password", "/reset-password"];

          if (!publicPages.includes(currentPath)) {
            console.log("[API Client] 🚪 CSRF token invalid - redirecting to login...");
            window.location.href = "/login?reason=session_expired";
          }
        }

        return Promise.reject(error);
      }
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
