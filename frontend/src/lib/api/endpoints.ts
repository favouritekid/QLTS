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
    VERIFY_MFA: "/api/auth/verify-mfa",
    MFA_SETUP: "/api/auth/mfa/setup",
    MFA_ENABLE: "/api/auth/mfa/enable",
    MFA_DISABLE: "/api/auth/mfa/disable",
    MFA_STATUS: "/api/auth/mfa/status",
    MFA_BACKUP_CODES: "/api/auth/mfa/backup-codes",
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
    ALL_OFFERINGS: "/api/program-offerings",
    LIST_OFFERINGS: (programId: number) => `/api/major-programs/${programId}/offerings`,
    GET_OFFERING: (offeringId: number) => `/api/offerings/${offeringId}`,
    GET_OFFERING_CURRENT_INFO: (offeringId: number) => `/api/offerings/${offeringId}/current-info`,

    // Tier 3: OfferingAcademicInfo
    LIST_ACADEMIC_INFO: (offeringId: number) => `/api/offerings/${offeringId}/academic-info`,
    GET_ACADEMIC_INFO_BY_YEAR: (offeringId: number, year: number) =>
      `/api/offerings/${offeringId}/academic-info/${year}`,

    // === LEGACY (DEPRECATED) ===
  },
  ADMIN: {
    USERS: {
      LIST: "/api/admin/users",
      CREATE: "/api/admin/users",
      DETAIL: (id: number) => `/api/admin/users/${id}`,
      UPDATE: (id: number) => `/api/admin/users/${id}`,
      DELETE: (id: number) => `/api/admin/users/${id}`,
      SET_PASSWORD: (id: number) => `/api/admin/users/${id}/password`,
      BULK_ACTION: "/api/admin/users/bulk",
      ROLES: (id: number) => `/api/admin/roles/users/${id}/roles`,
      EXPORT: "/api/admin/users/export",
      EXPORT_CSV_STREAM: "/api/admin/users/export/csv",
    },
    PERMISSIONS: {
      POLICIES: "/api/admin/roles/policies",
      ASSIGN_ROLE: "/api/admin/assign-role",
      REMOVE_ROLE: "/api/admin/assign-role", // DELETE method
      ROLES: "/api/admin/roles",
      TEMPLATES: "/api/admin/policy-templates",
      BATCH: "/api/admin/roles/policies/batch",
      VALIDATE: "/api/admin/roles/policies/validate",
      APPLY_TEMPLATE: "/api/admin/roles/policies/apply-template",
      STATISTICS: "/api/admin/roles/policies/statistics",
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
      CREATE_ACADEMIC_INFO: (offeringId: number) =>
        `/api/admin/offerings/${offeringId}/academic-info`,
      UPDATE_ACADEMIC_INFO: (academicInfoId: number) =>
        `/api/admin/academic-info/${academicInfoId}`,
      DELETE_ACADEMIC_INFO: (academicInfoId: number) =>
        `/api/admin/academic-info/${academicInfoId}`,
      RESTORE_ACADEMIC_INFO: (academicInfoId: number) =>
        `/api/admin/academic-info/${academicInfoId}/restore`,

      // === LEGACY (DEPRECATED) ===
    },
    // System Configuration
    CONFIG: {
      // Degree Levels
      LIST_DEGREE_LEVELS: "/api/admin/degree-levels",
      CREATE_DEGREE_LEVEL: "/api/admin/degree-levels",
      UPDATE_DEGREE_LEVEL: (id: number) => `/api/admin/degree-levels/${id}`,
      DELETE_DEGREE_LEVEL: (id: number) => `/api/admin/degree-levels/${id}`,

      // Offering Types
      LIST_OFFERING_TYPES: "/api/admin/offering-types",
      CREATE_OFFERING_TYPE: "/api/admin/offering-types",
      UPDATE_OFFERING_TYPE: (id: number) => `/api/admin/offering-types/${id}`,
      DELETE_OFFERING_TYPE: (id: number) => `/api/admin/offering-types/${id}`,

      // Document Types ✨ MỚI THÊM
      LIST_DOCUMENT_TYPES: "/api/admin/document-types",
      CREATE_DOCUMENT_TYPE: "/api/admin/document-types",
      UPDATE_DOCUMENT_TYPE: (id: number) => `/api/admin/document-types/${id}`,
      DELETE_DOCUMENT_TYPE: (id: number) => `/api/admin/document-types/${id}`,
    },
    // Tuition Discount Policy
    TUITION_DISCOUNT: {
      LIST: "/api/admin/tuition-discount-policies",
      CREATE: "/api/admin/tuition-discount-policies",
      GET: (id: number) => `/api/admin/tuition-discount-policies/${id}`,
      UPDATE: (id: number) => `/api/admin/tuition-discount-policies/${id}`,
      DELETE: (id: number) => `/api/admin/tuition-discount-policies/${id}`,
      CALCULATE: "/api/admin/tuition-discount-policies/calculate",
    },
    // Installment Plans
    INSTALLMENT_PLANS: {
      LIST: "/api/admin/installment-plans",
      CREATE: "/api/admin/installment-plans",
      UPDATE: (id: number) => `/api/admin/installment-plans/${id}`,
      DELETE: (id: number) => `/api/admin/installment-plans/${id}`,
    },
    ACTIVITY_LOGS: "/api/admin/activity-logs",
    STATISTICS: "/api/admin/users/statistics",
  },
  NOTIFICATIONS: {
    LIST: "/api/notifications",
    MARK_AS_READ: "/api/notifications/mark-as-read",
    MARK_ALL_AS_READ: "/api/notifications/mark-all-as-read",
    DELETE: (id: number) => `/api/notifications/${id}`,
    BULK_DELETE: "/api/notifications/bulk", // ✅ TECHNICAL DEBT FIX: Bulk delete
    PREFERENCES: "/api/notifications/preferences",
    // Event Groups (NEW - Event-Driven Architecture)
    EVENT_GROUPS: "/api/notifications/event-groups",
    EVENT_GROUPS_METADATA: "/api/notifications/event-groups/metadata",
  },
  // ✅ PHASE 2.4: Notification Rules (Admin-only)
  NOTIFICATION_RULES: {
    LIST: "/api/notification-rules",
    CREATE: "/api/notification-rules",
    DETAIL: (id: number) => `/api/notification-rules/${id}`,
    UPDATE: (id: number) => `/api/notification-rules/${id}`,
    TOGGLE: (id: number) => `/api/notification-rules/${id}/toggle`,
    DELETE: (id: number) => `/api/notification-rules/${id}`,
    METADATA: "/api/notification-rules/metadata", // ✅ NOTIFICATION 2.0: Dynamic metadata
  },
  // ✅ PHASE 3.1: Notification Templates (Admin-only)
  NOTIFICATION_TEMPLATES: {
    LIST: "/api/notification-templates",
    CREATE: "/api/notification-templates",
    DETAIL: (id: number) => `/api/notification-templates/${id}`,
    UPDATE: (id: number) => `/api/notification-templates/${id}`,
    DELETE: (id: number) => `/api/notification-templates/${id}`,
  },
  // ✅ PHASE B8: Notification Delivery Ops (Admin-only)
  NOTIFICATION_DELIVERIES: {
    LIST: "/api/notification-deliveries",
    STATS: "/api/notification-deliveries/stats",
    FAILURES: "/api/notification-deliveries/failures",
    DETAIL: (id: number) => `/api/notification-deliveries/${id}`,
    REPLAY: (id: number) => `/api/notification-deliveries/${id}/replay`,
    // D5: Mature monitoring dashboard
    TIME_SERIES: "/api/notification-deliveries/stats/time-series",
    TOP_EVENTS: "/api/notification-deliveries/stats/top-events",
    LATENCY: "/api/notification-deliveries/stats/latency",
    HEALTH: "/api/notification-deliveries/health",
    QUOTAS: "/api/notification-deliveries/quotas",
    CIRCUIT_BREAKERS: "/api/notification-deliveries/circuit-breakers",
    CIRCUIT_BREAKER_RESET: (channel: string) =>
      `/api/notification-deliveries/circuit-breakers/${channel}/reset`,
  },
  // ✅ PHASE B7: Notification Consents (Admin-only)
  NOTIFICATION_CONSENTS: {
    LIST: "/api/notification-consents",
    UPSERT: "/api/notification-consents/upsert",
    BULK_IMPORT: "/api/notification-consents/bulk-import",
  },
  // ✅ LOGIN SECURITY: Phase 5 - User Response Flow
  SECURITY: {
    LOGIN_HISTORY: "/api/security/login-history",
    SUSPICIOUS_LOGINS: "/api/security/suspicious-logins",
    CONFIRM_LOGIN: "/api/security/confirm-login",
    SECURE_ACCOUNT: "/api/security/secure-account",
    TRUSTED_DEVICES: "/api/security/trusted-devices",
    REMOVE_TRUSTED_DEVICE: (id: number) => `/api/security/trusted-devices/${id}`,
  },
  // ============================================================================
  // FINANCE MODULE (Bounded Context - Standalone)
  // ============================================================================
  FINANCE: {
    DASHBOARD: "/api/finance/dashboard",

    FEES: {
      LIST: "/api/fees",
      CALCULATE: "/api/fees/calculate",
      DETAIL: (feeId: number) => `/api/fees/${feeId}`,
      BY_PROFILE: (profileId: number) => `/api/fees/by-profile/${profileId}`,
      PROFILE_SUMMARY: (profileId: number) => `/api/fees/summary/${profileId}`,
      WAIVE: (feeId: number) => `/api/fees/${feeId}/waive`,
      CANCEL: (feeId: number) => `/api/fees/${feeId}/cancel`,
      RECALCULATE: (feeId: number) => `/api/fees/${feeId}/recalculate`,
    },

    INVOICES: {
      LIST: "/api/invoices",
      BY_FEE: (feeId: number) => `/api/invoices/by-fee/${feeId}`,
      DETAIL: (invoiceId: number) => `/api/invoices/${invoiceId}`,
      ISSUE: (invoiceId: number) => `/api/invoices/${invoiceId}/issue`,
      CANCEL: (invoiceId: number) => `/api/invoices/${invoiceId}/cancel`,
      PENALTY: (invoiceId: number) => `/api/invoices/${invoiceId}/penalty`,
    },

    PAYMENTS: {
      LIST: "/api/payments",
      CREATE: "/api/payments",
      BY_INVOICE: (invoiceId: number) => `/api/payments/by-invoice/${invoiceId}`,
      DETAIL: (paymentId: number) => `/api/payments/${paymentId}`,
      VERIFY: (paymentId: number) => `/api/payments/${paymentId}/verify`,
      REJECT: (paymentId: number) => `/api/payments/${paymentId}/reject`,
      METHODS: "/api/payments/methods",
      // Payment Intent (Online Payments)
      INTENTS: {
        CREATE: "/api/payments/intents",
        DETAIL: (intentId: number) => `/api/payments/intents/${intentId}`,
      },
    },

    // Lookup data
    INSTALLMENT_PLANS: {
      LIST: "/api/installment-plans",
      DETAIL: (id: number) => `/api/installment-plans/${id}`,
    },

    // P3 - Wait for backend router implementation
    OVERPAYMENTS: {
      LIST: "/api/overpayments",
      DETAIL: (id: number) => `/api/overpayments/${id}`,
      APPLY: (id: number) => `/api/overpayments/${id}/apply`,
      REFUND: (id: number) => `/api/overpayments/${id}/refund`,
      WRITE_OFF: (id: number) => `/api/overpayments/${id}/write-off`,
    },

    // P3 - Wait for backend router implementation
    REFUNDS: {
      LIST: "/api/refunds",
      CREATE: "/api/refunds",
      DETAIL: (id: number) => `/api/refunds/${id}`,
      APPROVE: (id: number) => `/api/refunds/${id}/approve`,
      REJECT: (id: number) => `/api/refunds/${id}/reject`,
      PROCESS: (id: number) => `/api/refunds/${id}/process`,
    },

    // P3
    ACCOUNTING: {
      PERIODS: "/api/accounting/periods",
      PERIOD_DETAIL: (id: number) => `/api/accounting/periods/${id}`,
      CLOSE_PERIOD: (id: number) => `/api/accounting/periods/${id}/close`,
    },
  },
} as const;
