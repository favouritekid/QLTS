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
  PROFILE: {
    GET: "/api/profile",
    UPDATE: "/api/profile",
  },
  // Organization (Public endpoints)
  ORGANIZATION: {
    LIST_UNITS: "/api/organization-units",
    GET_UNIT: (id: number) => `/api/organization-units/${id}`,
    UNIT_TYPES: "/api/organization-unit-types",
    LIST_MAJORS: "/api/majors",
    GET_MAJOR: (id: number) => `/api/majors/${id}`,
  },
  ADMIN: {
    USERS: {
      LIST: "/api/admin/users",
      CREATE: "/api/admin/users",
      DETAIL: (id: number) => `/api/admin/users/${id}`,
      UPDATE: (id: number) => `/api/admin/users/${id}`,
      DELETE: (id: number) => `/api/admin/users/${id}`,
      SET_PASSWORD: (id: number) => `/api/admin/users/${id}/set-password`,
      BULK_ACTION: "/api/admin/users/bulk-action",
      ROLES: (id: number) => `/api/admin/users/${id}/roles`,
      EXPORT: "/api/admin/users/export",
      EXPORT_CSV_STREAM: "/api/admin/users/export-csv",
    },
    PERMISSIONS: {
      POLICIES: "/api/admin/policies",
      ASSIGN_ROLE: "/api/admin/assign-role",
      REMOVE_ROLE: "/api/admin/assign-role", // DELETE method
      ROLES: "/api/admin/roles",
      TEMPLATES: "/api/admin/policy-templates",
      BATCH: "/api/admin/policies/batch",
      VALIDATE: "/api/admin/policies/validate",
      APPLY_TEMPLATE: "/api/admin/policies/apply-template",
      STATISTICS: "/api/admin/policies/statistics",
    },
    // Organization Management (Admin Only)
    ORGANIZATION: {
      // Units
      CREATE_UNIT: "/api/admin/organization-units",
      UPDATE_UNIT: (id: number) => `/api/admin/organization-units/${id}`,
      DELETE_UNIT: (id: number) => `/api/admin/organization-units/${id}`,
      GET_UNIT: (id: number) => `/api/admin/organization-units/${id}`,
      // Majors
      CREATE_MAJOR: "/api/admin/majors",
      UPDATE_MAJOR: (id: number) => `/api/admin/majors/${id}`,
      DELETE_MAJOR: (id: number) => `/api/admin/majors/${id}`,
      GET_MAJOR: (id: number) => `/api/admin/majors/${id}`,
    },
    ACTIVITY_LOGS: "/api/admin/activity-logs",
    STATISTICS: "/api/admin/statistics",
  },
  NOTIFICATIONS: {
    LIST: "/api/notifications",
    MARK_AS_READ: "/api/notifications/mark-as-read",
    MARK_ALL_AS_READ: "/api/notifications/mark-all-as-read",
    DELETE: (id: number) => `/api/notifications/${id}`,
    PREFERENCES: "/api/notifications/preferences",
  },
} as const;
