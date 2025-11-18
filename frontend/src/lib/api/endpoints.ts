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
    TREE_WITH_AGGREGATION: "/api/organization-units/tree-with-aggregation",
    UNIT_TYPES: "/api/organization-unit-types",

    // === 3-TIER ARCHITECTURE (NEW) ===
    // Tier 1: MajorProgram
    LIST_MAJOR_PROGRAMS: "/api/major-programs",
    GET_MAJOR_PROGRAM: (id: number) => `/api/major-programs/${id}`,

    // Tier 2: ProgramOffering
    LIST_OFFERINGS: (programId: number) => `/api/major-programs/${programId}/offerings`,
    GET_OFFERING: (offeringId: number) => `/api/offerings/${offeringId}`,
    GET_OFFERING_CURRENT_INFO: (offeringId: number) => `/api/offerings/${offeringId}/current-info`,

    // Tier 3: OfferingAcademicInfo
    LIST_ACADEMIC_INFO: (offeringId: number) => `/api/offerings/${offeringId}/academic-info`,
    GET_ACADEMIC_INFO_BY_YEAR: (offeringId: number, year: number) => `/api/offerings/${offeringId}/academic-info/${year}`,

    // === LEGACY (DEPRECATED) ===
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

      // === 3-TIER ARCHITECTURE (NEW) ===
      // Tier 1: MajorProgram
      CREATE_MAJOR_PROGRAM: "/api/admin/programs",
      UPDATE_MAJOR_PROGRAM: (programId: number) => `/api/admin/programs/${programId}`,
      DELETE_MAJOR_PROGRAM: (programId: number) => `/api/admin/programs/${programId}`,

      // Tier 2: ProgramOffering
      CREATE_OFFERING: (programId: number) => `/api/admin/programs/${programId}/offerings`,
      UPDATE_OFFERING: (offeringId: number) => `/api/admin/offerings/${offeringId}`,
      DELETE_OFFERING: (offeringId: number) => `/api/admin/offerings/${offeringId}`,

      // Tier 3: OfferingAcademicInfo
      CREATE_ACADEMIC_INFO: (offeringId: number) => `/api/admin/offerings/${offeringId}/academic-info`,
      UPDATE_ACADEMIC_INFO: (academicInfoId: number) => `/api/admin/academic-info/${academicInfoId}`,
      DELETE_ACADEMIC_INFO: (academicInfoId: number) => `/api/admin/academic-info/${academicInfoId}`,

      // === LEGACY (DEPRECATED) ===
    },
    // System Configuration
    CONFIG: {
      // Degree Levels
      LIST_DEGREE_LEVELS: "/api/admin/config/degree-levels",
      CREATE_DEGREE_LEVEL: "/api/admin/config/degree-levels",
      UPDATE_DEGREE_LEVEL: (id: number) => `/api/admin/config/degree-levels/${id}`,
      DELETE_DEGREE_LEVEL: (id: number) => `/api/admin/config/degree-levels/${id}`,

      // Offering Types
      LIST_OFFERING_TYPES: "/api/admin/config/offering-types",
      CREATE_OFFERING_TYPE: "/api/admin/config/offering-types",
      UPDATE_OFFERING_TYPE: (id: number) => `/api/admin/config/offering-types/${id}`,
      DELETE_OFFERING_TYPE: (id: number) => `/api/admin/config/offering-types/${id}`,
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
  // Applications (Hồ sơ Tuyển sinh)
  APPLICATIONS: {
    CREATE: (leadId: number) => `/api/leads/${leadId}/applications`,
    UPDATE: (applicationId: number) => `/api/applications/${applicationId}`,
    GET: (applicationId: number) => `/api/applications/${applicationId}`,
  },
} as const;
