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
  params?: Record<string, any>;
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
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...fetchOptions.headers,
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
    return serverFetch<LeadsPage>('/api/leads', { params });
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
   *
   * @example
   * ```ts
   * const user = await serverApi.users.getCurrentUser();
   * ```
   */
  async getCurrentUser(): Promise<any> {
    return serverFetch<any>('/api/users/me');
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
};

/**
 * Low-level fetch wrapper (for custom endpoints)
 */
export { serverFetch };
