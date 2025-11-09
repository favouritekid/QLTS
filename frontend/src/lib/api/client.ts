// src/lib/api/client.ts
/**
 * Axios client instance with auto-refresh interceptors
 *
 * ✅ FIX-4: Implemented automatic token refresh with queueing mechanism
 * to prevent race conditions and improve UX dramatically.
 *
 * Features:
 * - Auto-refresh access token on 401 errors
 * - Queue concurrent requests during refresh
 * - Prevent infinite loops
 * - Graceful error handling
 */
import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

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
// 🔒 AUTO-REFRESH TOKEN MECHANISM (FIX-4)
// ============================================

/**
 * Queue mechanism to prevent race conditions when multiple requests
 * receive 401 simultaneously. Only ONE refresh request is made,
 * and all other requests wait for it to complete.
 */
let isRefreshing = false;
let refreshSubscribers: Array<{
  onSuccess: (token: string) => void;
  onError: (error: unknown) => void;
}> = [];

function subscribeTokenRefresh(
  onSuccess: (token: string) => void,
  onError: (error: unknown) => void
) {
  refreshSubscribers.push({ onSuccess, onError });
}

function onRefreshed(token: string) {
  refreshSubscribers.forEach((subscriber) => subscriber.onSuccess(token));
  refreshSubscribers = [];
}

function onRefreshFailed(error: unknown) {
  refreshSubscribers.forEach((subscriber) => subscriber.onError(error));
  refreshSubscribers = [];
}

// ============================================
// 📤 REQUEST INTERCEPTOR
// ============================================

// ✅ SECURITY FIX: No longer need to manually set Authorization header
// Tokens are sent automatically via httpOnly cookies by browser
// withCredentials: true ensures cookies are included in requests

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // No need to manually add Authorization header
    // Browser automatically sends access_token cookie with all requests
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
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      const currentPath =
        typeof window !== "undefined" ? window.location.pathname : "";

      // ========================================
      // STEP 2: Don't refresh on auth endpoints
      // (prevent infinite loops)
      // ========================================
      const authEndpoints = [
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/refresh",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
      ];

      if (authEndpoints.some((path) => originalRequest.url?.includes(path))) {
        console.log("[API Client] Auth endpoint failed, not retrying");
        return Promise.reject(error);
      }

      // Don't redirect if already on public pages
      const publicPages = ["/login", "/register", "/forgot-password", "/reset-password"];
      if (publicPages.includes(currentPath)) {
        return Promise.reject(error);
      }

      // ========================================
      // STEP 3: QUEUE MECHANISM
      // If refresh is already in progress, queue this request
      // ========================================
      if (isRefreshing) {
        console.log("[API Client] 🔄 Request queued (refresh in progress)");

        return new Promise((resolve, reject) => {
          subscribeTokenRefresh(
            () => {
              // ✅ SECURITY FIX: No need to set Authorization header
              // Cookie is sent automatically
              resolve(api(originalRequest));
            },
            (error: unknown) => {
              reject(error);
            }
          );
        });
      }

      // ========================================
      // STEP 4: START REFRESH PROCESS
      // ========================================
      originalRequest._retry = true;
      isRefreshing = true;

      try {
        console.log("[API Client] 🔄 Access token expired, refreshing...");

        // ✅ SECURITY FIX: Call /refresh endpoint (tokens sent/received via httpOnly cookies)
        const { data } = await axios.post<{
          access_token: string; // Kept in response for backwards compatibility
          user: {
            id: number;
            username: string;
            email: string;
            full_name: string | null;
            role: string;
          };
        }>(
          `${API_BASE_URL}/api/auth/refresh`,
          {},
          {
            withCredentials: true, // ✅ Important: Send refresh_token cookie
          }
        );

        // ✅ SECURITY FIX: No need to update localStorage
        // New access_token is already set in httpOnly cookie by backend

        console.log("[API Client] ✅ Token refreshed successfully (via httpOnly cookie)");

        // ========================================
        // STEP 5: NOTIFY QUEUED REQUESTS
        // ========================================
        isRefreshing = false;
        onRefreshed(""); // Pass empty string since we don't use token value anymore

        // ========================================
        // STEP 6: RETRY ORIGINAL REQUEST
        // ========================================
        // No need to set Authorization header - cookie is sent automatically
        return api(originalRequest);
      } catch (refreshError) {
        console.error("[API Client] ❌ Refresh failed:", refreshError);

        // ========================================
        // STEP 7: HANDLE REFRESH FAILURE
        // ========================================
        isRefreshing = false;
        onRefreshFailed(refreshError);

        // ✅ SECURITY FIX: Clear auth state (cookies are cleared by redirect/middleware)
        try {
          const { useAuthStore } = await import("@/lib/stores/auth.store");
          useAuthStore.getState().logout();
        } catch (importError) {
          console.warn("[API Client] Failed to logout:", importError);
        }

        // Redirect to login
        if (typeof window !== "undefined" && !publicPages.includes(currentPath)) {
          console.log("[API Client] 🚪 Redirecting to login...");
          window.location.href = "/login";
        }

        return Promise.reject(refreshError);
      }
    }

    // For non-401 errors, just reject
    return Promise.reject(error);
  }
);

// ============================================
// 📊 EXPORT
// ============================================

// Export as both 'api' and 'apiClient' for backward compatibility
export { api as apiClient };
export default api;
