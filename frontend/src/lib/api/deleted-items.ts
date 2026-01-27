// src/lib/api/deleted-items.ts
/**
 * API client for Admin Deleted Items Management
 *
 * Provides functions to view and restore soft-deleted items:
 * - Deleted Leads
 * - Deleted Consultations
 */

import { api } from "./client";
import type { Lead, Consultation } from "@/types/lead.types";

// ============================================
// TYPES
// ============================================

export interface DeletedLeadSummary {
  id: number;
  full_name: string;
  phone: string | null;
  email: string | null;
  deleted_at: string;
  deleted_by_name: string | null;
  consultation_count: number;
}

export interface DeletedConsultationSummary {
  id: number;
  lead_id: number;
  lead_name: string;
  consultation_status_name: string | null;
  consultation_date: string | null;
  deleted_at: string;
  notes: string | null;
}

export interface DeletedItemsResponse {
  deleted_leads: DeletedLeadSummary[];
  deleted_consultations: DeletedConsultationSummary[];
  total_leads: number;
  total_consultations: number;
}

export interface DeletedItemsParams {
  limit?: number;
  search?: string;
}

// ============================================
// API FUNCTIONS
// ============================================

/**
 * Get list of deleted items (leads and consultations)
 *
 * @param params - Query parameters for filtering
 * @returns List of deleted leads and consultations
 */
export async function getDeletedItems(
  params?: DeletedItemsParams
): Promise<DeletedItemsResponse> {
  const response = await api.get<DeletedItemsResponse>(
    "/api/admin/deleted-items",
    { params }
  );
  return response.data;
}

/**
 * Restore a deleted lead
 *
 * @param leadId - ID of the lead to restore
 * @returns The restored lead
 */
export async function restoreDeletedLead(leadId: number): Promise<Lead> {
  const response = await api.post<Lead>(
    `/api/admin/deleted-items/leads/${leadId}/restore`
  );
  return response.data;
}

/**
 * Restore a deleted consultation (via admin endpoint)
 *
 * @param consultationId - ID of the consultation to restore
 * @returns The restored consultation
 */
export async function restoreDeletedConsultation(
  consultationId: number
): Promise<Consultation> {
  const response = await api.post<Consultation>(
    `/api/admin/deleted-items/consultations/${consultationId}/restore`
  );
  return response.data;
}

// ============================================
// EXPORT
// ============================================

export const deletedItemsApi = {
  getDeletedItems,
  restoreDeletedLead,
  restoreDeletedConsultation,
};

export default deletedItemsApi;
