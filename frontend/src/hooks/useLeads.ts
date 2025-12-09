// src/hooks/useLeads.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { leadsApi } from "@/lib/api/leads";
import type { ApiErrorResponse } from "@/types/api.types";
import type {
  Lead,
  LeadCreate,
  LeadUpdate,
  LeadsPage,
  LeadListParams,
  AssignLead,
  BulkAssignLeads,
  LeadAction,
  LeadImportResult,
  TimelineItem,
  LeadInsights,
  Consultation,
  ConsultationCreate,
  ConsultationUpdate,
} from "@/types/lead.types";

// =====================================================================
// QUERY KEYS
// =====================================================================

export const leadsKeys = {
  all: ["leads"] as const,
  lists: () => [...leadsKeys.all, "list"] as const,
  list: (params?: LeadListParams) => [...leadsKeys.lists(), params] as const,
  details: () => [...leadsKeys.all, "detail"] as const,
  detail: (id: number) => [...leadsKeys.details(), id] as const,
  timeline: (id: number) => [...leadsKeys.all, "timeline", id] as const,
  insights: (id: number) => [...leadsKeys.all, "insights", id] as const,
};

// =====================================================================
// QUERIES (READ) - LEADS
// =====================================================================

/**
 * Get paginated leads list with optional filters
 *
 * ✅ PHASE 1 - WEEK 1: Support initialData from Server Components
 *
 * @param params - Filter parameters
 * @param options - Query options including initialData
 *
 * @example
 * ```tsx
 * // Client-side only
 * const { data, isLoading } = useLeads({ page: 1 });
 *
 * // With initialData from Server Component
 * const { data } = useLeads({ page: 1 }, { initialData });
 * ```
 */
export function useLeads(
  params?: LeadListParams,
  options?: { initialData?: LeadsPage }
) {
  return useQuery<LeadsPage, AxiosError<ApiErrorResponse>>({
    queryKey: leadsKeys.list(params),
    queryFn: async () => {
      return await leadsApi.getLeads(params);
    },
    staleTime: 1000 * 30, // 30 seconds
    gcTime: 1000 * 60 * 5, // 5 minutes in cache
    initialData: options?.initialData, // ✅ Use initialData from Server Component
  });
}

/**
 * Get a single lead by ID
 *
 * @example
 * ```tsx
 * const { data: lead, isLoading } = useLead(123);
 * ```
 */
export function useLead(
  id: number,
  enabled: boolean = true,
  options?: { initialData?: Lead }
) {
  return useQuery<Lead, AxiosError<ApiErrorResponse>>({
    queryKey: leadsKeys.detail(id),
    queryFn: async () => {
      return await leadsApi.getLead(id);
    },
    enabled: enabled && !!id,
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 2 - DAY 5: Support SSR
    staleTime: 1000 * 60, // 1 minute
    gcTime: 1000 * 60 * 5, // 5 minutes in cache
  });
}

/**
 * Get timeline events for a lead
 *
 * @example
 * ```tsx
 * const { data: timeline } = useLeadTimeline(123);
 * ```
 */
export function useLeadTimeline(leadId: number) {
  return useQuery<TimelineItem[], AxiosError<ApiErrorResponse>>({
    queryKey: leadsKeys.timeline(leadId),
    queryFn: async () => {
      return await leadsApi.getLeadTimeline(leadId);
    },
    enabled: !!leadId,
    staleTime: 1000 * 30, // 30 seconds
  });
}

/**
 * Get AI-powered insights for a lead
 *
 * @example
 * ```tsx
 * const { data: insights } = useLeadInsights(123);
 * ```
 */
export function useLeadInsights(leadId: number) {
  return useQuery<LeadInsights, AxiosError<ApiErrorResponse>>({
    queryKey: leadsKeys.insights(leadId),
    queryFn: async () => {
      return await leadsApi.getLeadInsights(leadId);
    },
    enabled: !!leadId,
    staleTime: 1000 * 60 * 5, // 5 minutes (insights don't change frequently)
    gcTime: 1000 * 60 * 10, // 10 minutes in cache
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - LEADS
// =====================================================================

/**
 * Create a new lead
 *
 * @example
 * ```tsx
 * const createLead = useCreateLead();
 *
 * createLead.mutate({
 *   full_name: 'John Doe',
 *   email: 'john@example.com',
 *   phone: '0909123456',
 *   source: 'website',
 *   unit_id: 1,
 * });
 * ```
 */
export function useCreateLead() {
  const queryClient = useQueryClient();

  return useMutation<Lead, AxiosError<ApiErrorResponse>, LeadCreate>({
    mutationFn: async (data) => {
      return await leadsApi.createLead(data);
    },
    onSuccess: (newLead) => {
      toast.success("Lead created successfully!", {
        description: newLead.full_name,
      });

      // Invalidate all lead lists to refetch with new data
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });

      // Also invalidate pipeline queries as new lead affects pipeline stats
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg || "Validation error").join(", ")
            : error.response?.data?.message || "Failed to create lead";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Update an existing lead
 *
 * @example
 * ```tsx
 * const updateLead = useUpdateLead();
 *
 * updateLead.mutate({
 *   id: 123,
 *   data: { full_name: 'Jane Doe' }
 * });
 * ```
 */
export function useUpdateLead() {
  const queryClient = useQueryClient();

  return useMutation<
    Lead,
    AxiosError<ApiErrorResponse>,
    { id: number; data: LeadUpdate },
    { previousLead: Lead | undefined }
  >({
    mutationFn: async ({ id, data }) => {
      return await leadsApi.updateLead(id, data);
    },

    // Optimistic update
    onMutate: async ({ id, data }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: leadsKeys.detail(id) });

      // Snapshot the previous value
      const previousLead = queryClient.getQueryData<Lead>(leadsKeys.detail(id));

      // Optimistically update the cache
      if (previousLead) {
        queryClient.setQueryData<Lead>(leadsKeys.detail(id), {
          ...previousLead,
          ...data,
        } as Lead);
      }

      return { previousLead };
    },

    // Rollback on error
    onError: (err, { id }, context) => {
      if (context?.previousLead) {
        queryClient.setQueryData(leadsKeys.detail(id), context.previousLead);
      }

      const detail = err.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to update lead";
      toast.error("Error", { description: message });
    },

    onSuccess: (updatedLead) => {
      toast.success("Lead updated successfully!", {
        description: updatedLead.full_name,
      });

      // Invalidate queries - including insights which may change based on lead data
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.insights(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
}

/**
 * Delete a lead
 *
 * @example
 * ```tsx
 * const deleteLead = useDeleteLead();
 * deleteLead.mutate(123);
 * ```
 */
export function useDeleteLead() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number, { deletedLeadId: number }>({
    mutationFn: async (id) => {
      await leadsApi.deleteLead(id);
    },

    // Store lead ID in context for onSuccess
    onMutate: async (id) => {
      // Cancel any outgoing refetches to avoid race conditions
      await queryClient.cancelQueries({ queryKey: leadsKeys.detail(id) });
      return { deletedLeadId: id };
    },

    onSuccess: (_, __, context) => {
      toast.success("Lead deleted successfully!");

      // Invalidate the specific lead's queries
      if (context?.deletedLeadId) {
        queryClient.invalidateQueries({ queryKey: leadsKeys.detail(context.deletedLeadId) });
        queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(context.deletedLeadId) });
        queryClient.invalidateQueries({ queryKey: leadsKeys.insights(context.deletedLeadId) });
      }
      // Invalidate lists and pipeline
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to delete lead";
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS - LEAD ASSIGNMENT
// =====================================================================

/**
 * Assign a lead to an officer
 *
 * @example
 * ```tsx
 * const assignLead = useAssignLead();
 *
 * assignLead.mutate({
 *   leadId: 123,
 *   data: {
 *     officer_id: 5,
 *     reason: 'Has expertise in this field',
 *   }
 * });
 * ```
 */
export function useAssignLead() {
  const queryClient = useQueryClient();

  return useMutation<
    Lead,
    AxiosError<ApiErrorResponse>,
    { leadId: number; data: AssignLead }
  >({
    mutationFn: async ({ leadId, data }) => {
      return await leadsApi.assignLead(leadId, data);
    },

    onSuccess: (updatedLead) => {
      toast.success("Lead assigned successfully!", {
        description: `Assigned to officer #${updatedLead.assigned_officer_id}`,
      });

      // Invalidate queries
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to assign lead";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Bulk assign multiple leads to officers
 *
 * @example
 * ```tsx
 * const bulkAssign = useBulkAssignLeads();
 *
 * bulkAssign.mutate({
 *   lead_ids: [1, 2, 3],
 *   officer_id: 5,
 *   reason: 'Batch assignment',
 * });
 * ```
 */
export function useBulkAssignLeads() {
  const queryClient = useQueryClient();

  return useMutation<
    { message: string; assigned_count: number },
    AxiosError<ApiErrorResponse>,
    BulkAssignLeads
  >({
    mutationFn: async (data) => {
      return await leadsApi.bulkAssignLeads(data);
    },

    onSuccess: (result) => {
      toast.success("Bulk assignment successful!", {
        description: `${result.assigned_count} leads assigned`,
      });

      // Invalidate all lead-related queries
      queryClient.invalidateQueries({ queryKey: leadsKeys.all });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to bulk assign leads";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Bulk update leads pipeline stage
 * ✅ Option B: Bulk Stage Change
 *
 * @example
 * ```tsx
 * const bulkUpdateStage = useBulkUpdateLeadsStage();
 *
 * bulkUpdateStage.mutate({
 *   lead_ids: [1, 2, 3],
 *   pipeline_stage_id: 'stage_2',
 * });
 * ```
 */
export function useBulkUpdateLeadsStage() {
  const queryClient = useQueryClient();

  return useMutation<
    { message: string; updated_count: number },
    AxiosError<ApiErrorResponse>,
    { lead_ids: number[]; pipeline_stage_id: string }
  >({
    mutationFn: async (data) => {
      return await leadsApi.bulkUpdateLeadsStage(data);
    },

    onSuccess: async (result) => {
      // Force refetch leads list queries immediately (matches useLeads queryKey)
      await queryClient.refetchQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to update leads stage";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Bulk delete leads
 * ✅ Option B: Bulk Delete
 *
 * @example
 * ```tsx
 * const bulkDelete = useBulkDeleteLeads();
 *
 * bulkDelete.mutate({
 *   lead_ids: [1, 2, 3],
 * });
 * ```
 */
export function useBulkDeleteLeads() {
  const queryClient = useQueryClient();

  return useMutation<
    { message: string; deleted_count: number },
    AxiosError<ApiErrorResponse>,
    { lead_ids: number[] }
  >({
    mutationFn: async (data) => {
      return await leadsApi.bulkDeleteLeads(data);
    },

    onSuccess: async (result) => {
      // Force refetch leads list queries immediately (matches useLeads queryKey)
      await queryClient.refetchQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to delete leads";
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS - LEAD ACTIONS
// =====================================================================

/**
 * Perform an action on a lead (reject, convert, mark_lost, etc.)
 *
 * @example
 * ```tsx
 * const performAction = usePerformLeadAction();
 *
 * performAction.mutate({
 *   leadId: 123,
 *   action: 'reject',
 *   reason: 'Not qualified',
 * });
 * ```
 */
export function usePerformLeadAction() {
  const queryClient = useQueryClient();

  return useMutation<
    Lead,
    AxiosError<ApiErrorResponse>,
    { leadId: number; data: LeadAction }
  >({
    mutationFn: async ({ leadId, data }) => {
      return await leadsApi.performLeadAction(leadId, data);
    },

    onSuccess: (updatedLead, variables) => {
      const actionMessages: Record<string, string> = {
        reject: "Lead rejected",
        convert: "Lead converted successfully!",
        reassign: "Lead reassigned successfully!",
        mark_lost: "Lead marked as lost",
        reopen: "Lead reopened",
      };

      toast.success(actionMessages[variables.data.action] || "Action performed successfully", {
        description: updatedLead.full_name,
      });

      // Invalidate queries
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error, variables) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : `Failed to ${variables.data.action} lead`;
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS - CONSULTATIONS
// =====================================================================

/**
 * Add a consultation to a lead
 *
 * @example
 * ```tsx
 * const addConsultation = useAddConsultation();
 *
 * addConsultation.mutate({
 *   leadId: 123,
 *   data: {
 *     scheduled_at: '2025-01-15T10:00:00',
 *     notes: 'Initial consultation',
 *     consultation_status_id: 1,
 *   }
 * });
 * ```
 */
export function useAddConsultation() {
  const queryClient = useQueryClient();

  return useMutation<
    Consultation,
    AxiosError<ApiErrorResponse>,
    { leadId: number; data: ConsultationCreate }
  >({
    mutationFn: async ({ leadId, data }) => {
      return await leadsApi.addConsultation(leadId, data);
    },

    onSuccess: (consultation, { leadId }) => {
      toast.success("Consultation added successfully!");

      // Invalidate lead detail, timeline, insights and lists (for LeadCard updates)
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.insights(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to add consultation";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Update a consultation (admin: any, officer: most recent only)
 *
 * @example
 * ```tsx
 * const updateConsultation = useUpdateConsultation();
 * updateConsultation.mutate({
 *   leadId: 123,
 *   consultationId: 456,
 *   data: { notes: "Updated notes", status_id: "sts02" }
 * });
 * ```
 */
export function useUpdateConsultation() {
  const queryClient = useQueryClient();

  return useMutation<
    Consultation,
    AxiosError<ApiErrorResponse>,
    { leadId: number; consultationId: number; data: ConsultationUpdate }
  >({
    mutationFn: async ({ leadId, consultationId, data }) => {
      return await leadsApi.updateConsultation(leadId, consultationId, data);
    },

    onSuccess: (consultation, { leadId }) => {
      toast.success("Consultation updated successfully!");

      // Invalidate lead detail, timeline, insights and pipeline (if status changed)
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.insights(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(", ")
            : "Failed to update consultation";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Delete a consultation (admin: any, officer: most recent only)
 *
 * @example
 * ```tsx
 * const deleteConsultation = useDeleteConsultation();
 * deleteConsultation.mutate({ leadId: 123, consultationId: 456 });
 * ```
 */
export function useDeleteConsultation() {
  const queryClient = useQueryClient();

  return useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    { leadId: number; consultationId: number }
  >({
    mutationFn: async ({ leadId, consultationId }) => {
      await leadsApi.deleteConsultation(leadId, consultationId);
    },

    onSuccess: (_, { leadId }) => {
      toast.success("Consultation deleted successfully!");

      // Invalidate lead detail and timeline
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to delete consultation";
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS - IMPORT/EXPORT
// =====================================================================

/**
 * Import leads from CSV/Excel file
 *
 * @example
 * ```tsx
 * const importLeads = useImportLeads();
 *
 * importLeads.mutate(file);
 * ```
 */
export function useImportLeads() {
  const queryClient = useQueryClient();

  return useMutation<LeadImportResult, AxiosError<ApiErrorResponse>, File>({
    mutationFn: async (file) => {
      return await leadsApi.importLeads(file);
    },

    onSuccess: (result) => {
      toast.success("Import completed!", {
        description: `${result.successful_imports} leads imported, ${result.failed_imports} failed`,
      });

      // Invalidate all lead lists
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to import leads";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Export leads to CSV/Excel
 *
 * @example
 * ```tsx
 * const exportLeads = useExportLeads();
 *
 * exportLeads.mutate({
 *   format: 'csv',
 *   status: 'new',
 * });
 * ```
 */
export function useExportLeads() {
  return useMutation<
    Blob,
    AxiosError<ApiErrorResponse>,
    { format?: "csv" | "xlsx"; filters?: LeadListParams }
  >({
    mutationFn: async ({ filters }) => {
      return await leadsApi.exportLeads(filters);
    },

    onSuccess: (blob, variables) => {
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `leads_export_${new Date().toISOString().split("T")[0]}.${variables.format || "csv"}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      toast.success("Export successful!", {
        description: "File downloaded",
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : "Failed to export leads";
      toast.error("Error", { description: message });
    },
  });
}
