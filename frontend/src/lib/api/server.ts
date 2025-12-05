/**
 * Server-Side API Client
 *
 * ✅ PHASE 1 - WEEK 1: Server Components Data Fetching
 *
 * This module provides server-side data fetching utilities for Next.js Server Components.
 *
 * Features:
 * - Cookie forwarding from incoming requests to backend API
 * - Type-safe API functions
 * - Error handling with proper status codes
 * - No client-side dependencies (React Query, axios interceptors)
 *
 * Usage:
 * ```tsx
 * // In Server Component
 * import { serverApi } from '@/lib/api/server';
 *
 * export default async function Page() {
 *   const data = await serverApi.leads.getLeads({ page: 1 });
 *   return <ClientComponent initialData={data} />;
 * }
 * ```
 *
 * Security:
 * - Automatically forwards authentication cookies
 * - Validates responses
 * - Handles 401/403 gracefully
 */

import { cookies } from 'next/headers';
import type {
  Lead,
  LeadsPage,
  LeadListParams,
  TimelineItem,
  LeadInsights,
} from '@/types/lead.types';
import type {
  FullPipeline,
} from '@/types/pipeline.types';
import type {
  User,
  UsersPage,
  UserStatistics,
  ConsultationStatus,
  PipelineStage,
  OrganizationUnit,
  OrganizationTreeWithAggregation,
  MajorProgram,
  ProgramOffering,
  NotificationTemplatesPage,
  NotificationRulesPage,
  EventGroup,
  NotificationPreferences,
  NotificationsPage,
  DistributionRule,
  DistributionStats,
  DegreeLevel,
  OfferingType,
  DocumentType,
  TuitionDiscountPoliciesPage,
  PermissionStatistics,
  EventGroupPreferencesResponse,
  UserSessionListResponse,
} from '@/types/api.types';

// ============================================
// CONFIGURATION
// ============================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

/**
 * Get backend API URL (internal docker network in production)
 * In production, use internal container name instead of external domain
 */
function getBackendUrl(): string {
  // In production (Docker), use internal container network
  if (process.env.NODE_ENV === 'production' && process.env.BACKEND_INTERNAL_URL) {
    return process.env.BACKEND_INTERNAL_URL;
  }

  // Development: use public API URL
  return API_BASE_URL;
}

// ============================================
// SERVER-SIDE FETCH WRAPPER
// ============================================

interface FetchOptions extends RequestInit {
  params?: Record<string, unknown>; // Generic query parameters - type varies by endpoint
}

/**
 * Server-side fetch wrapper with cookie forwarding
 *
 * Automatically includes authentication cookies from incoming request.
 * Handles query parameters and JSON serialization.
 *
 * @throws {Error} On network errors or invalid responses
 */
async function serverFetch<T>(
  endpoint: string,
  options: FetchOptions = {}
): Promise<T> {
  const { params, ...fetchOptions } = options;

  // Build URL with query parameters
  const url = new URL(endpoint, getBackendUrl());
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        url.searchParams.append(key, String(value));
      }
    });
  }

  // Get cookies from incoming request
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();

  // Prepare headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(fetchOptions.headers as Record<string, string>),
  };

  // Forward authentication cookies
  if (cookieHeader) {
    headers['Cookie'] = cookieHeader;
  }

  // Execute fetch
  const response = await fetch(url.toString(), {
    ...fetchOptions,
    headers,
    credentials: 'include', // Include cookies
    cache: fetchOptions.cache || 'no-store', // Default: no cache for fresh data
  });

  // Handle non-OK responses
  if (!response.ok) {
    const errorText = await response.text();
    let errorMessage: string;

    try {
      const errorJson = JSON.parse(errorText);
      errorMessage = errorJson.detail || errorJson.message || 'API request failed';
    } catch {
      errorMessage = errorText || `HTTP ${response.status}`;
    }

    throw new Error(`API Error (${response.status}): ${errorMessage}`);
  }

  // Parse JSON response
  const data = await response.json();
  return data as T;
}

// ============================================
// LEADS API (SERVER-SIDE)
// ============================================

const leads = {
  /**
   * Get paginated leads list (Server-Side)
   *
   * @example
   * ```ts
   * const leadsPage = await serverApi.leads.getLeads({
   *   page: 1,
   *   page_size: 20,
   *   status: 'new',
   * });
   * ```
   */
  async getLeads(params?: LeadListParams): Promise<LeadsPage> {
    return serverFetch<LeadsPage>('/api/leads', { params: params as Record<string, unknown> });
  },

  /**
   * Get single lead by ID (Server-Side)
   *
   * @throws {Error} 404 if lead not found, 403 if no permission
   */
  async getLead(leadId: number): Promise<Lead> {
    return serverFetch<Lead>(`/api/leads/${leadId}`);
  },

  /**
   * Get lead timeline (Server-Side)
   */
  async getLeadTimeline(leadId: number): Promise<TimelineItem[]> {
    return serverFetch<TimelineItem[]>(`/api/leads/${leadId}/timeline`);
  },

  /**
   * Get lead insights (Server-Side)
   */
  async getLeadInsights(leadId: number): Promise<LeadInsights> {
    return serverFetch<LeadInsights>(`/api/leads/${leadId}/insights`);
  },
};

// ============================================
// USERS API (SERVER-SIDE)
// ============================================

const users = {
  /**
   * Get current user profile (Server-Side)
   */  async getCurrentUser(): Promise<User> {
    return serverFetch<User>('/api/users/me');
  },
};

// ============================================
// ADMIN API (SERVER-SIDE)
// ============================================

const admin = {
  /**
   * Admin Users Management
   */
  users: {
    /**
     * Get paginated admin users list
     */
    async getUsers(params?: {
      page?: number;
      page_size?: number;
      search?: string;
      role?: string;
      status?: string;
      sort_by?: string;
      order?: string;
    }): Promise<UsersPage> {
      return serverFetch<UsersPage>('/api/admin/users', { params });
    },

    /**
     * Get single user by ID (admin)
     */    async getUser(userId: number): Promise<User> {
      return serverFetch<User>(`/api/admin/users/${userId}`);
    },

    /**
     * Get user statistics (admin dashboard)
     */
    async getStatistics(): Promise<UserStatistics> {
      return serverFetch<UserStatistics>('/api/admin/users/statistics');
    },
  },

  /**
   * Pipeline Management
   */
  pipeline: {
    /**
     * Get all consultation statuses (Admin endpoint)
     */    async getConsultationStatuses(): Promise<ConsultationStatus[]> {
      return serverFetch<ConsultationStatus[]>('/api/admin/consultation-statuses');
    },

    /**
     * Get pipeline stages (Admin endpoint)
     */    async getPipelineStages(params?: { status_id?: number }): Promise<PipelineStage[]> {
      return serverFetch<PipelineStage[]>('/api/admin/pipeline-stages', { params });
    },

    /**
     * Get full pipeline with leads and stats (Public endpoint)
     */
    async getFullPipeline(params?: {
      include_leads?: boolean;
      include_stats?: boolean;
      date_from?: string;
      date_to?: string;
    }): Promise<FullPipeline> {
      return serverFetch<FullPipeline>('/api/pipeline/all', { params });
    },
  },

  /**
   * Organization Management
   */
  organization: {
    /**
     * Get organization units tree
     */    async getUnitsTree(): Promise<OrganizationUnit[]> {
      return serverFetch<OrganizationUnit[]>('/api/organization-units');
    },

    /**
     * Get organization unit by ID
     */    async getUnit(unitId: number): Promise<OrganizationUnit> {
      return serverFetch<OrganizationUnit>(`/api/organization-units/${unitId}`);
    },

    /**
     * Get organization tree with aggregation
     */    async getTreeWithAggregation(): Promise<OrganizationTreeWithAggregation[]> {
      return serverFetch<OrganizationTreeWithAggregation[]>('/api/organization-units/tree-with-aggregation');
    },

    /**
     * Get major programs
     */    async getMajorPrograms(): Promise<MajorProgram[]> {
      return serverFetch<MajorProgram[]>('/api/major-programs');
    },

    /**
     * Get program offerings
     */    async getProgramOfferings(): Promise<ProgramOffering[]> {
      return serverFetch<ProgramOffering[]>('/api/program-offerings');
    },
  },

  /**
   * Notification Management (Admin)
   */
  notifications: {
    /**
     * Get notification templates (Admin endpoint - no /admin prefix in backend)
     */
    async getTemplates(params?: {
      page?: number;
      page_size?: number;
      search?: string;
    }): Promise<NotificationTemplatesPage> {
      return serverFetch<NotificationTemplatesPage>('/api/notification-templates', { params });
    },

    /**
     * Get notification rules (Admin endpoint - no /admin prefix in backend)
     */
    async getRules(params?: {
      page?: number;
      page_size?: number;
      event?: string;
      is_active?: boolean;
    }): Promise<NotificationRulesPage> {
      return serverFetch<NotificationRulesPage>('/api/notification-rules', { params });
    },

    /**
     * Get notification event groups
     */    async getEventGroups(): Promise<EventGroup[]> {
      return serverFetch<EventGroup[]>('/api/notifications/event-groups');
    },
  },

  /**
   * System Configuration
   */
  config: {
    /**
     * Get system configuration list
     */
    async getConfigs(params?: {
      page?: number;
      page_size?: number;
      search?: string;
    }): Promise<unknown> {
      return serverFetch<unknown>('/api/admin/config', { params });
    },

    /**
     * Get degree levels
     */    async getDegreeLevels(params?: { active_only?: boolean }): Promise<DegreeLevel[]> {
      return serverFetch<DegreeLevel[]>('/api/admin/degree-levels', { params });
    },

    /**
     * Get offering types
     */    async getOfferingTypes(params?: { active_only?: boolean }): Promise<OfferingType[]> {
      return serverFetch<OfferingType[]>('/api/admin/offering-types', { params });
    },

    /**
     * Get document types
     */    async getDocumentTypes(params?: { active_only?: boolean }): Promise<DocumentType[]> {
      return serverFetch<DocumentType[]>('/api/admin/document-types', { params });
    },
  },

  /**
   * Tuition Discount Policies
   */
  tuitionDiscount: {
    /**
     * Get tuition discount policies
     */
    async getPolicies(params?: {
      page?: number;
      page_size?: number;
    }): Promise<TuitionDiscountPoliciesPage> {
      return serverFetch<TuitionDiscountPoliciesPage>('/api/admin/tuition-discount-policies', { params });
    },
  },

  /**
   * Monitoring & Analytics
   */
  monitoring: {
    /**
     * Get lead distribution statistics
     */
    async getDistributionStats(params?: {
      start_date?: string;
      end_date?: string;
    }): Promise<DistributionStats> {
      return serverFetch<DistributionStats>('/api/admin/distribution/stats', { params });
    },
  },

  /**
   * Distribution Rules
   */
  distributionRules: {
    /**
     * Get all distribution rules
     */    async getRules(): Promise<DistributionRule[]> {
      return serverFetch<DistributionRule[]>('/api/admin/distribution-rules');
    },
  },

  /**
   * Policies & Permissions
   */
  policies: {
    /**
     * Get policy statistics (Admin endpoint under roles router)
     */    async getStatistics(): Promise<PermissionStatistics> {
      return serverFetch<PermissionStatistics>('/api/admin/roles/policies/statistics');
    },
  },
};

// ============================================
// TOP-LEVEL ENDPOINTS (User-facing)
// ============================================

/**
 * Pipeline (alias to admin.pipeline for convenience)
 */
const pipeline = admin.pipeline;

/**
 * User Notifications
 */
const notifications = {
  /**
   * Get user notifications
   */
  async getNotifications(params?: {
    page?: number;
    page_size?: number;
    unread_only?: boolean;
  }): Promise<NotificationsPage> {
    return serverFetch<NotificationsPage>('/api/notifications', { params });
  },

  /**
   * Get notification preferences
   * ✅ PHASE 1 - WEEK 3 - DAY 1
   */  async getPreferences(): Promise<NotificationPreferences> {
    return serverFetch<NotificationPreferences>('/api/notifications/preferences');
  },

  /**
   * Get event group preferences
   * ✅ PHASE 1 - WEEK 3 - DAY 1
   */
  async getEventGroupPreferences(): Promise<EventGroupPreferencesResponse> {
    return serverFetch<EventGroupPreferencesResponse>('/api/notifications/event-groups');
  },
};

/**
 * User Sessions
 * ✅ PHASE 1 - WEEK 3 - DAY 1
 */
const sessions = {
  /**
   * Get active user sessions
   */
  async getActiveSessions(): Promise<UserSessionListResponse> {
    return serverFetch<UserSessionListResponse>('/api/sessions');
  },
};

// ============================================
// EXPORT
// ============================================

/**
 * Server-side API client
 *
 * Only use in Server Components (not Client Components)
 */
export const serverApi = {
  leads,
  users,
  admin,
  pipeline,
  notifications,
  sessions,
};

/**
 * Low-level fetch wrapper (for custom endpoints)
 */
export { serverFetch };
