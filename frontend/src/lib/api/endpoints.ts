// src/lib/api/endpoints.ts
/**
 * API endpoint constants
 */
export const API_ENDPOINTS = {
  AUTH: {
    LOGIN: "/api/auth/login",
    LOGOUT: "/api/auth/logout",
    REGISTER: "/api/auth/register",
    REFRESH: "/api/auth/refresh",
    ME: "/api/users/me",
    CHANGE_PASSWORD: "/api/auth/change-password",
    FORGOT_PASSWORD: "/api/auth/forgot-password",
    RESET_PASSWORD: "/api/auth/reset-password",
    CHECK_STATUS: "/api/auth/check-status",
  },
  SESSIONS: {
    LIST: "/api/sessions",
    REVOKE: (id: number) => `/api/sessions/${id}`,
    REVOKE_ALL: "/api/sessions/revoke-all",
  },
  USERS: {
    ME: "/api/users/me",
    LIST: "/api/users",
    DETAIL: (id: number) => `/api/users/${id}`,
  },
} as const;
