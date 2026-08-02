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

import { cookies, headers as nextHeaders } from 'next/headers';
import { redirect, unstable_rethrow } from 'next/navigation';
import { isValidRedirect, stripRsc } from '@/lib/auth/login-redirect';
import type {
  Lead,
  LeadDetail,
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
import type { AdmissionListParams, AdmissionProfileResponse, AdmissionsPageLite } from '@/lib/zod/admissions';
import type { EnhancedOfficerStats } from '@/hooks/useDashboardStats';
import type { CollaboratorsPage } from '@/types/collaborator.types';
import type {
  PublicAdmissionsDocumentsResponse,
  PublicAdmissionsMethodsResponse,
  PublicAdmissionsProgramsResponse,
  PublicAdmissionsTuitionResponse,
} from '@/types/public-admissions.types';

// ============================================
// CONFIGURATION
// ============================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

/**
 * Get backend API URL for server-side fetches.
 * Prefers BACKEND_INTERNAL_URL when available (Docker environment),
 * regardless of NODE_ENV, since server components always run inside the container.
 */
function getBackendUrl(): string {
  if (process.env.BACKEND_INTERNAL_URL) {
    return process.env.BACKEND_INTERNAL_URL;
  }
  return API_BASE_URL;
}

// ============================================
// SERVER-SIDE FETCH WRAPPER
// ============================================

interface FetchOptions extends RequestInit {
  params?: Record<string, unknown>; // Generic query parameters - type varies by endpoint
}

/** Đích mặc định khi không xác định được trang người dùng đang xem. */
const SERVER_401_FALLBACK_TARGET = '/dashboard';

/**
 * URL trang cứu phiên cho một 401 phát sinh trong Server Component.
 *
 * Return-url lấy từ `x-qlts-pathname` — header do `proxy.ts` **chuyển tiếp vào
 * request** (`NextResponse.next({ request: { headers } })`); header đặt lên
 * response sẽ không đọc được ở đây.
 *
 * 🔴 Giá trị đó KHÔNG được tin thẳng. Proxy ghi đè nó ở mọi request đi qua,
 * nhưng nếu một đường nào đó lọt (matcher không phủ, request nội bộ), client có
 * thể tự gửi `x-qlts-pathname: //evil.com` và biến trang cứu phiên thành open
 * redirect. Nên vẫn lọc `isValidRedirect` rồi mới dùng, thiếu/hỏng thì về đích
 * mặc định.
 */
async function buildSessionRefreshRedirect(): Promise<string> {
  let raw: string | null = null;
  try {
    raw = (await nextHeaders()).get('x-qlts-pathname');
  } catch {
    // Ngoài ngữ cảnh request (build tĩnh) — dùng đích mặc định.
  }

  // 🔴 Thứ tự: LỌC trước, strip sau.
  //
  // `stripRsc()` chạy qua `new URL(value, base)`, nên `//evil.com/x` được parse
  // thành một URL tuyệt đối rồi trả về `pathname` — tức `/x`. Strip trước thì
  // giá trị ngoại lai bị "rửa" thành một path nội bộ trông hợp lệ và
  // `isValidRedirect` không còn gì để từ chối.
  const target =
    raw && isValidRedirect(raw) ? stripRsc(raw) : SERVER_401_FALLBACK_TARGET;

  const params = new URLSearchParams({ redirect: target, source: 'server_401' });
  return `/session-refresh?${params.toString()}`;
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

  // Get explicit headers
  const providedHeaders = (fetchOptions.headers as Record<string, string>) || {};
  
  // Get cookies: Use provided header OR fetch from request (if not provided)
  let cookieHeader = providedHeaders['Cookie'];

  if (!cookieHeader) {
    try {
      const cookieStore = await cookies();
      cookieHeader = cookieStore.toString();
    } catch (err) {
      // A thrown cookies() under cacheComponents is Next's dynamic-render BAILOUT
      // signal, not a real error — rethrow it so the segment renders dynamically
      // and the auth cookie IS forwarded. Swallowing it sends the request WITHOUT
      // auth → 401, which callers then turn into a 404/broken render (the class of
      // bug that made every SSR detail page — leads/[id], admissions/[id],
      // admin/users/[id] — 404 on direct load). unstable_rethrow only re-throws
      // framework control-flow (bailout/redirect/notFound); genuine cookies()
      // failures (e.g. inside "use cache" without an explicit header) fall through
      // and the request fails with 401 downstream as before.
      unstable_rethrow(err);
    }
  }

  // Prepare headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...providedHeaders,
  };

  // Forward authentication cookies
  if (cookieHeader) {
    headers['Cookie'] = cookieHeader;
  }

  // Forward the REAL client IP so backend per-IP rate limits key on the actual
  // visitor. SSR fetches hit the backend directly (bypassing nginx, which is the
  // layer that sets X-Real-IP), so without this every server-rendered call keys
  // on THIS frontend container's single IP → one shared bucket for all users →
  // prod-wide 429 once the tier limit is crossed. Read the real IP from the
  // INBOUND request (nginx set it there) and pass it through unchanged.
  if (!headers['X-Real-IP']) {
    try {
      const inbound = await nextHeaders();
      // ONLY X-Real-IP: nginx sets it to $remote_addr and overwrites any client
      // value → non-spoofable. Deliberately do NOT fall back to X-Forwarded-For
      // (its first hop is client-appendable → forwarding it as a trusted X-Real-IP
      // would let a client forge the backend rate-limit key). In prod nginx always
      // sets X-Real-IP, so a fallback would only ever fire off-nginx anyway.
      const realIp = inbound.get('x-real-ip');
      if (realIp) headers['X-Real-IP'] = realIp;
    } catch (err) {
      // Rethrow Next's dynamic-render bailout (see the cookies() catch above);
      // only a genuine headers()-unavailable case should be swallowed.
      unstable_rethrow(err);
      // headers() unavailable (e.g. inside a "use cache" scope, ISR, or
      // generateMetadata) — leave X-Real-IP unset; the backend then keys on this
      // container's IP. ⚠️ INVARIANT: any get_client_ip-keyed (ENFORCED) endpoint
      // reached via SSR MUST force dynamic render (call `await connection()` first,
      // as the /tuyen-sinh public catalog pages do) so headers() is available here;
      // otherwise all its cached renders collapse into one bucket. Today the only
      // `use cache` callers target UNENFORCED (allowlisted) endpoints, so this is
      // latent — do not wrap an enforced endpoint in `use cache` without threading
      // the client IP through the cache boundary (mirror how cookieHeader is passed).
    }
  }

  // Execute fetch
  let response: Response;
  try {
    response = await fetch(url.toString(), {
      ...fetchOptions,
      headers,
      credentials: 'include', // Include cookies
      cache: fetchOptions.cache || 'no-store', // Default: no cache for fresh data
    });
  } catch (networkError) {
    // Network error (ECONNREFUSED, DNS failure, timeout)
    // Likely backend is restarting — throw descriptive error for error boundary
    throw new Error(`Backend unavailable: ${networkError instanceof Error ? networkError.message : 'network error'}`);
  }

  // Handle non-OK responses
  if (!response.ok) {
    // 401 Unauthorized — nhưng KHÔNG kết luận phiên đã chết.
    //
    // `force_login` xoá sạch cả `refresh_token`, tức biến một access token hết
    // hạn 15 phút thành mất phiên 30 ngày. Server Component không có cách nào
    // phân biệt hai thứ đó, nên nó phải chuyển sang trang cứu phiên và để
    // client hỏi backend — `source=server_401` báo cho proxy biết đừng shortcut
    // (server vừa từ chối thật, bằng chứng "token còn hạn" ở đó vô nghĩa).
    if (response.status === 401) {
      redirect(await buildSessionRefreshRedirect());
    }

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
   * Get single lead by ID (Server-Side).
   *
   * Backend returns `LeadDetail` (Lead + gate flags for thin client).
   *
   * @throws {Error} 404 if lead not found, 403 if no permission
   */
  async getLead(leadId: number): Promise<LeadDetail> {
    return serverFetch<LeadDetail>(`/api/leads/${leadId}`);
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
    /**
     * Get user statistics (admin dashboard)
     * @param cookieHeader Optional cookie string for cached contexts
     */
    async getStatistics(cookieHeader?: string): Promise<UserStatistics> {
      const options: FetchOptions = {};
      if (cookieHeader) {
        options.headers = { Cookie: cookieHeader };
      }
      return serverFetch<UserStatistics>('/api/admin/users/statistics', options);
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
    }, cookieHeader?: string): Promise<FullPipeline> {
      const options: FetchOptions = { params: params as Record<string, unknown> };
      if (cookieHeader) {
        options.headers = { Cookie: cookieHeader };
      }
      return serverFetch<FullPipeline>('/api/pipeline/board', options);
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
   * Collaborators Management
   */
  collaborators: {
    async getCollaborators(params?: {
      skip?: number;
      limit?: number;
      status?: string;
      unit_id?: number;
      search?: string;
      sort_by?: string;
      order?: string;
    }): Promise<CollaboratorsPage> {
      return serverFetch<CollaboratorsPage>('/api/collaborators', { params });
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
// OFFICER API (SERVER-SIDE)
// ============================================

const officer = {
  /**
   * Get officer dashboard stats (Server-Side)
   */
  async getDashboardStats(params?: {
    start_date?: string;
    end_date?: string;
    scope?: string;
  }): Promise<EnhancedOfficerStats> {
    return serverFetch<EnhancedOfficerStats>('/api/officer/dashboard', { params });
  },
};

// ============================================
// ADMISSIONS API (SERVER-SIDE)
// ============================================

// Moved to top imports

const admissions = {
  /**
   * Get admission profile by ID (Server-Side)
   */
  async getProfile(profileId: number): Promise<AdmissionProfileResponse> {
    return serverFetch<AdmissionProfileResponse>(`/api/admissions/${profileId}`);
  },

  /**
   * List admission profiles (Server-Side)
   */
  async listProfiles(params?: AdmissionListParams): Promise<AdmissionsPageLite> {
    return serverFetch<AdmissionsPageLite>('/api/admissions', {
      params: params as Record<string, unknown> | undefined,
    });
  },
};

// ============================================
// PUBLIC ADMISSIONS API (SERVER-SIDE)
// ============================================

type PublicAdmissionsCatalogParams = {
  audience?: string;
  admission_round_id?: number;
};

const publicAdmissions = {
  async getProgramsCatalog(params?: PublicAdmissionsCatalogParams): Promise<PublicAdmissionsProgramsResponse> {
    return serverFetch<PublicAdmissionsProgramsResponse>('/api/public/admissions/programs', { params });
  },

  async getMethodsCatalog(params?: PublicAdmissionsCatalogParams): Promise<PublicAdmissionsMethodsResponse> {
    return serverFetch<PublicAdmissionsMethodsResponse>('/api/public/admissions/methods', { params });
  },

  async getDocumentsCatalog(params?: PublicAdmissionsCatalogParams): Promise<PublicAdmissionsDocumentsResponse> {
    return serverFetch<PublicAdmissionsDocumentsResponse>('/api/public/admissions/documents', { params });
  },

  async getTuitionCatalog(params?: PublicAdmissionsCatalogParams): Promise<PublicAdmissionsTuitionResponse> {
    return serverFetch<PublicAdmissionsTuitionResponse>('/api/public/admissions/tuition', { params });
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
  admissions,
  officer,
  publicAdmissions,
};

/**
 * Low-level fetch wrapper (for custom endpoints)
 */
export { serverFetch };
