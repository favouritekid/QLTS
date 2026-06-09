// src/hooks/useLeads.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { leadsApi } from "@/lib/api/leads";
import { workflowContextKeys } from "@/hooks/useWorkflowContext";
import type { ApiErrorResponse } from "@/types/api.types";
import type { ReopenRequestItem } from "@/lib/api/leads";
import type {
  Lead,
  LeadDetail,
  LeadCreate,
  LeadUpdate,
  LeadsPage,
  LeadListParams,
  AssignLead,
  BulkAssignLeads,
  BulkAssignResult,
  BulkUpdateStageResult,
  LeadAction,
  LeadImportResult,
  TimelineItem,
  LeadInsights,
  Consultation,
  ConsultationCreate,
  ConsultationCreateResult,
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
// QUERY INVALIDATION HELPERS
// =====================================================================

/**
 * Invalidate lead-related queries with optimized batching.
 * Only invalidates pipeline when a status-changing operation is performed.
 *
 * @param queryClient - React Query client
 * @param leadId - ID of the lead to invalidate
 * @param options - Control which queries to invalidate
 */
type InvalidationOptions = {
  detail?: boolean;
  timeline?: boolean;
  insights?: boolean;
  lists?: boolean;
  pipeline?: boolean;
};

const invalidateLeadQueries = (
  queryClient: ReturnType<typeof useQueryClient>,
  leadId: number,
  options: InvalidationOptions = {}
) => {
  const { detail = true, timeline = false, insights = false, lists = false, pipeline = false } = options;

  // Batch invalidations for better performance
  const invalidations: Promise<void>[] = [];

  if (detail) {
    invalidations.push(queryClient.invalidateQueries({ queryKey: leadsKeys.detail(leadId) }));
  }
  if (timeline) {
    invalidations.push(queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId) }));
  }
  if (insights) {
    invalidations.push(queryClient.invalidateQueries({ queryKey: leadsKeys.insights(leadId) }));
  }
  if (lists) {
    // Use refetchType: 'active' to only refetch visible queries
    invalidations.push(queryClient.invalidateQueries({
      queryKey: leadsKeys.lists(),
      refetchType: 'active'
    }));
  }
  if (pipeline) {
    invalidations.push(queryClient.invalidateQueries({
      queryKey: ["pipeline"],
      refetchType: 'active'
    }));
  }

  return Promise.all(invalidations);
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
      const data = await leadsApi.getLeads(params);
      if (!data) throw new Error("Failed to fetch leads");
      return data;
    },
    staleTime: 1000 * 5, // 5 seconds - shorter for real-time updates
    gcTime: 1000 * 60 * 5, // 5 minutes in cache
    initialData: options?.initialData,
    // Keep the previous page visible while a new query is fetching so the
    // table does not flash back to a skeleton when filters switch (e.g.
    // post-hydration localStorage restore, pagination, sort, etc.).
    placeholderData: (previousData) => previousData,
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
  options?: { initialData?: LeadDetail }
) {
  // GET /leads/{id} returns LeadDetail (Lead + permissions/available_actions/action_blockers).
  // Other endpoints (update/create/assign) return plain Lead — see useUpdateLead for cache merge strategy.
  return useQuery<LeadDetail, AxiosError<ApiErrorResponse>>({
    queryKey: leadsKeys.detail(id),
    queryFn: async () => {
      const data = (await leadsApi.getLead(id)) as LeadDetail | null;
      if (!data) throw new Error("Failed to fetch lead");
      return data;
    },
    enabled: enabled && !!id,
    initialData: options?.initialData,
    // ✅ FIX: Increased staleTime to reduce unnecessary re-fetches
    // Invalidation will still trigger refetch when needed (e.g., after mutations)
    staleTime: 1000 * 30, // 30 seconds - allows caching while mutations still trigger updates
    gcTime: 1000 * 60 * 5, // 5 minutes in cache
  });
}

/**
 * Get lead reassign quota for current user
 */
import { type ReassignQuota } from "@/lib/api/leads";

export function useReassignQuota(enabled: boolean = true) {
  return useQuery<ReassignQuota>({
    queryKey: ["leads", "reassign-quota"],
    queryFn: async () => {
      const data = await leadsApi.getReassignQuota();
      if (!data) throw new Error("Failed to fetch reassign quota");
      return data;
    },
    staleTime: 1000 * 60, // 1 minute
    enabled,
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
export function useLeadTimeline(
  leadId: number,
  options?: { initialData?: TimelineItem[] }
) {
  return useQuery<TimelineItem[], AxiosError<ApiErrorResponse>>({
    queryKey: leadsKeys.timeline(leadId),
    queryFn: async () => {
      const data = await leadsApi.getLeadTimeline(leadId);
      if (!data) throw new Error("Failed to fetch lead timeline");
      return data;
    },
    enabled: !!leadId,
    staleTime: 1000 * 30, // 30 seconds
    initialData: options?.initialData,
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
export function useLeadInsights(
  leadId: number,
  options?: { initialData?: LeadInsights }
) {
  return useQuery<LeadInsights, AxiosError<ApiErrorResponse>>({
    queryKey: leadsKeys.insights(leadId),
    queryFn: async () => {
      const data = await leadsApi.getLeadInsights(leadId);
      if (!data) throw new Error("Failed to fetch lead insights");
      return data;
    },
    enabled: !!leadId,
    staleTime: 1000 * 30, // 30 seconds - reduced for better responsiveness after lead updates
    gcTime: 1000 * 60 * 10, // 10 minutes in cache
    initialData: options?.initialData,
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
    onSuccess: async (newLead) => {
      toast.success("Tạo lead thành công!", {
        description: newLead.full_name,
      });

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' }),
      ]);
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : error.response?.data?.message || error.message || "Không thể tạo lead mới";
      toast.error("Tạo lead thất bại", { description: message });
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
    { previousLead: LeadDetail | undefined }
  >({
    mutationFn: async ({ id, data }) => {
      return await leadsApi.updateLead(id, data);
    },

    // Optimistic update
    onMutate: async ({ id, data }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: leadsKeys.detail(id) });

      // Snapshot the previous value (cached as LeadDetail from GET /leads/{id})
      const previousLead = queryClient.getQueryData<LeadDetail>(leadsKeys.detail(id));

      // Optimistically update the cache (only merge scalar fields to avoid corrupting nested objects)
      // Preserve LeadDetail gate fields (permissions/available_actions/action_blockers) via spread.
      if (previousLead) {
        const scalarUpdates: Partial<Lead> = {};
        for (const [key, value] of Object.entries(data)) {
          // Allow null (clears nullable fields like email, phone2, offering_id).
          // typeof null === "object" in JS, so must check for null explicitly.
          if (value !== undefined && (value === null || typeof value !== "object")) {
            (scalarUpdates as Record<string, unknown>)[key] = value;
          }
        }
        queryClient.setQueryData<LeadDetail>(leadsKeys.detail(id), {
          ...previousLead,
          ...scalarUpdates,
        });
      }

      return { previousLead };
    },

    // Rollback on error
    onError: (err, variables, context) => {
      if (context?.previousLead) {
        queryClient.setQueryData(leadsKeys.detail(variables.id), context.previousLead);
      }

      const detail = err.response?.data?.detail;
      const errorMessage =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : err.response?.data?.message || err.message || "Không thể cập nhật lead";

      // ✅ Phase 2: Actionable toast with retry button
      toast.error("Cập nhật lead thất bại", {
        description: errorMessage,
        duration: 10000,
      });
    },

    onSuccess: async (updatedLead) => {
      toast.success("Cập nhật lead thành công!", {
        description: updatedLead.full_name,
      });

      // Merge update response (plain Lead) into cached LeadDetail ONLY when a
      // prior detail entry exists — else skip seeding. Reason: the update
      // endpoint returns plain `Lead` without gate fields
      // (permissions/available_actions/action_blockers). If no detail cache
      // exists yet (e.g. update triggered from list/dialog without visiting
      // detail page), casting plain Lead to LeadDetail would pollute the cache
      // with missing gate fields. A later create-page visit could render the
      // stale cache first and fall back to permissive UI before refetch lands.
      // Instead: leave cache empty, let useLead fetch a fresh LeadDetail.
      const existingDetail = queryClient.getQueryData<LeadDetail>(
        leadsKeys.detail(updatedLead.id),
      );
      if (existingDetail) {
        queryClient.setQueryData<LeadDetail>(leadsKeys.detail(updatedLead.id), {
          ...existingDetail,
          ...updatedLead,
        });
      }

      // Invalidate detail WITHOUT refetchType filter so the stale mark persists
      // even if no observer is active right now — next useLead() mount refetches.
      // Other queries stay on active-only to avoid background work.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id) }),
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: leadsKeys.insights(updatedLead.id), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' }),
      ]);
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

    onSuccess: async (_, __, context) => {
      toast.success("Xóa lead thành công!");

      // Invalidate the specific lead's queries
      if (context?.deletedLeadId) {
        queryClient.invalidateQueries({ queryKey: leadsKeys.detail(context.deletedLeadId) });
        queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(context.deletedLeadId) });
        queryClient.invalidateQueries({ queryKey: leadsKeys.insights(context.deletedLeadId) });
      }
      await queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' });
      queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Không thể xóa lead";
      
      // ✅ Phase 2: Actionable toast with longer duration
      toast.error("Xóa lead thất bại", {
        description: message,
        duration: 10000,
      });
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

    onSuccess: async (updatedLead) => {
      toast.success("Phân công lead thành công!", {
        description: `Đã phân công cho tư vấn viên #${updatedLead.assigned_officer_id}`,
      });

      // Invalidate queries
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' }),
      ]);
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : error.response?.data?.message || error.message || "Không thể phân công lead";
      toast.error("Phân công thất bại", { description: message });
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
    BulkAssignResult,
    AxiosError<ApiErrorResponse>,
    BulkAssignLeads
  >({
    mutationFn: async (data) => {
      return await leadsApi.bulkAssignLeads(data);
    },

    onSuccess: async (result) => {
      toast.success(`Phân công thành công ${result.successful}/${result.total} lead`);
      if (result.failed > 0) {
        toast.warning(`${result.failed} lead không thể phân công`);
      }

      // Invalidate lead lists and pipeline — don't wipe individual lead details
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' }),
      ]);
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Phân công hàng loạt thất bại";
      toast.error("Lỗi phân công", { description: message });
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
    BulkUpdateStageResult,
    AxiosError<ApiErrorResponse>,
    { lead_ids: number[]; pipeline_stage_id: string }
  >({
    mutationFn: async (data) => {
      return await leadsApi.bulkUpdateLeadsStage(data);
    },

    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' }),
      ]);
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Cập nhật giai đoạn thất bại";
      toast.error("Lỗi cập nhật", { description: message });
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
    { message: string; deleted_count: number; skipped?: Array<{ lead_id: number; reason: string }> },
    AxiosError<ApiErrorResponse>,
    { lead_ids: number[] }
  >({
    mutationFn: async (data) => {
      return await leadsApi.bulkDeleteLeads(data);
    },

    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' }),
      ]);
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Xóa hàng loạt thất bại";
      toast.error("Lỗi xóa", { description: message });
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

    onSuccess: async (updatedLead, variables) => {
      const actionMessages: Record<string, string> = {
        reject: "Đã từ chối lead",
        convert: "Chuyển đổi lead thành công!",
        reassign: "Phân công lại thành công!",
        mark_lost: "Đã đánh dấu thất bại",
        reopen: "Đã mở lại lead",
      };

      toast.success(actionMessages[variables.data.action] || "Thao tác thành công", {
        description: updatedLead.full_name,
      });

      // Invalidate queries
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id), refetchType: 'active' }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' }),
        // ✅ FIX BUG-17: Invalidate workflow context so current_phase/allowed_statuses refresh
        queryClient.invalidateQueries({
          queryKey: workflowContextKeys.byLead(updatedLead.id),
          exact: true,
          refetchType: 'active',
        }),
      ]);
    },

    onError: (error, variables) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : `Thao tác ${variables.data.action} thất bại`;
      toast.error("Lỗi thao tác", { description: message });
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
    ConsultationCreateResult,
    AxiosError<ApiErrorResponse>,
    { leadId: number; data: ConsultationCreate }
  >({
    mutationFn: async ({ leadId, data }) => {
      return await leadsApi.addConsultation(leadId, data);
    },

    onSuccess: async (result, { leadId }) => {
      toast.success("Ghi nhận tư vấn thành công!");

      // ✅ PR4: Warn when soft-terminal guard blocked status update
      if (!result.status_updated && result.terminal_guard_reason) {
        toast.warning(result.terminal_guard_reason, { duration: 6000 });
      }

      // ✅ FIX: Invalidate queries with exact: true to prevent cascade
      // Using invalidateQueries instead of refetchQueries to let React Query
      // handle deduplication and prevent multiple refetches
      await queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(leadId),
        exact: true,
        refetchType: 'active'
      });

      // Invalidate timeline separately (different query key structure)
      queryClient.invalidateQueries({
        queryKey: leadsKeys.timeline(leadId),
        exact: true,
        refetchType: 'active'
      });

      // Invalidate lists (background refresh)
      queryClient.invalidateQueries({
        queryKey: leadsKeys.lists(),
        refetchType: 'active'
      });

      // ✅ FIX: Only invalidate allowedNextStatuses for this specific lead
      queryClient.invalidateQueries({
        queryKey: ["pipeline", "allowedNextStatuses"],
        refetchType: 'active'
      });

      // ✅ FIX BUG-17: Invalidate workflow context so current_phase/allowed_statuses refresh
      queryClient.invalidateQueries({
        queryKey: workflowContextKeys.byLead(leadId),
        exact: true,
        refetchType: 'active'
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Thêm tư vấn thất bại";
      toast.error("Lỗi tư vấn", { description: message });
    },
  });
}

/**
 * Reopen a consultation-terminal lead (sts20 → sts04). Manager/admin only —
 * the button visibility is gated by ``lead.permissions.can_reopen`` from the API.
 *
 * @example
 * ```tsx
 * const reopen = useReopenLead();
 * reopen.mutate({ leadId: 123, reason: "Khách đổi ý, muốn tư vấn lại" });
 * ```
 */
export function useReopenLead() {
  const queryClient = useQueryClient();

  return useMutation<
    Lead,
    AxiosError<ApiErrorResponse>,
    { leadId: number; reason: string }
  >({
    mutationFn: async ({ leadId, reason }) => {
      return await leadsApi.reopenLead(leadId, { reason });
    },

    onSuccess: async (_updatedLead, { leadId }) => {
      toast.success("Đã mở lại tư vấn", {
        description: "Lead trở về trạng thái tư vấn — bạn có thể tiếp tục.",
      });

      // Detail (cờ permissions + status đổi) + timeline + lists + workflow context.
      await queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(leadId),
        exact: true,
        refetchType: "active",
      });
      queryClient.invalidateQueries({
        queryKey: leadsKeys.timeline(leadId),
        exact: true,
        refetchType: "active",
      });
      queryClient.invalidateQueries({
        queryKey: leadsKeys.lists(),
        refetchType: "active",
      });
      queryClient.invalidateQueries({
        queryKey: workflowContextKeys.byLead(leadId),
        exact: true,
        refetchType: "active",
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Không thể mở lại tư vấn";
      toast.error("Lỗi mở lại tư vấn", { description: message });
    },
  });
}

// =====================================================================
// REOPEN REQUESTS (Phase B) — officer xin → manager/admin duyệt
// =====================================================================

export const reopenRequestKeys = {
  all: ["reopen-requests"] as const,
  list: (status?: string) =>
    [...reopenRequestKeys.all, "list", status ?? "all"] as const,
};

function _reopenErr(fallback: string) {
  return (error: AxiosError<ApiErrorResponse>) => {
    const detail = error.response?.data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e) => e.msg).join(", ")
          : fallback;
    toast.error(fallback, { description: message });
  };
}

/** Inbox duyệt (manager/admin) — IDOR-scoped ở backend. */
export function useReopenRequests(status?: string) {
  return useQuery<ReopenRequestItem[], AxiosError<ApiErrorResponse>>({
    queryKey: reopenRequestKeys.list(status),
    queryFn: () => leadsApi.listReopenRequests(status),
  });
}

/** Officer XIN mở lại lead. */
export function useCreateReopenRequest() {
  const queryClient = useQueryClient();
  return useMutation<
    ReopenRequestItem,
    AxiosError<ApiErrorResponse>,
    { leadId: number; reason: string }
  >({
    mutationFn: ({ leadId, reason }) =>
      leadsApi.createReopenRequest(leadId, { reason }),
    onSuccess: async (_d, { leadId }) => {
      toast.success("Đã gửi yêu cầu mở lại", {
        description: "Yêu cầu đang chờ quản lý duyệt.",
      });
      await queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(leadId),
        exact: true,
        refetchType: "active",
      });
      queryClient.invalidateQueries({ queryKey: reopenRequestKeys.all });
    },
    onError: _reopenErr("Không gửi được yêu cầu mở lại"),
  });
}

/** Manager/admin DUYỆT yêu cầu → lead mở lại. */
export function useApproveReopenRequest() {
  const queryClient = useQueryClient();
  return useMutation<
    ReopenRequestItem,
    AxiosError<ApiErrorResponse>,
    { requestId: number; note?: string }
  >({
    mutationFn: ({ requestId, note }) =>
      leadsApi.approveReopenRequest(requestId, { note }),
    onSuccess: (r) => {
      toast.success("Đã duyệt — lead được mở lại");
      queryClient.invalidateQueries({ queryKey: reopenRequestKeys.all });
      queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(r.lead_id),
        exact: true,
        refetchType: "active",
      });
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
    },
    onError: _reopenErr("Không duyệt được yêu cầu"),
  });
}

/** Manager/admin TỪ CHỐI yêu cầu (note bắt buộc). */
export function useRejectReopenRequest() {
  const queryClient = useQueryClient();
  return useMutation<
    ReopenRequestItem,
    AxiosError<ApiErrorResponse>,
    { requestId: number; note: string }
  >({
    mutationFn: ({ requestId, note }) =>
      leadsApi.rejectReopenRequest(requestId, { note }),
    onSuccess: () => {
      toast.success("Đã từ chối yêu cầu");
      queryClient.invalidateQueries({ queryKey: reopenRequestKeys.all });
    },
    onError: _reopenErr("Không từ chối được yêu cầu"),
  });
}

/** Officer HỦY yêu cầu pending của chính mình. */
export function useCancelReopenRequest() {
  const queryClient = useQueryClient();
  return useMutation<
    ReopenRequestItem,
    AxiosError<ApiErrorResponse>,
    { requestId: number; leadId?: number }
  >({
    mutationFn: ({ requestId }) => leadsApi.cancelReopenRequest(requestId),
    onSuccess: (_d, { leadId }) => {
      toast.success("Đã hủy yêu cầu mở lại");
      queryClient.invalidateQueries({ queryKey: reopenRequestKeys.all });
      if (leadId) {
        queryClient.invalidateQueries({
          queryKey: leadsKeys.detail(leadId),
          exact: true,
          refetchType: "active",
        });
      }
    },
    onError: _reopenErr("Không hủy được yêu cầu"),
  });
}

/**
 * Update a consultation (admin: all, officer: most recent only)
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

    onSuccess: async (_consultation, { leadId, data }) => {
      toast.success("Cập nhật tư vấn thành công!");

      // ✅ FIX: Use invalidateQueries with exact: true to prevent cascade
      await queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(leadId),
        exact: true,
        refetchType: 'active'
      });

      queryClient.invalidateQueries({
        queryKey: leadsKeys.timeline(leadId),
        exact: true,
        refetchType: 'active'
      });

      // ✅ OPTIMIZED: Only invalidate pipeline if status was updated
      const statusChanged = !!data.status_id;
      if (statusChanged) {
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' });
        queryClient.invalidateQueries({ queryKey: ["pipeline", "allowedNextStatuses"], refetchType: 'active' });

        // ✅ FIX BUG-17: Invalidate workflow context when status changes
        queryClient.invalidateQueries({
          queryKey: workflowContextKeys.byLead(leadId),
          exact: true,
          refetchType: 'active'
        });
      }
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e: { msg: string }) => e.msg).join(", ")
            : "Cập nhật tư vấn thất bại";
      toast.error("Lỗi cập nhật", { description: message });
    },
  });
}

/**
 * Delete a consultation (admin: all, officer: most recent only)
 *
 * Shows an undo toast that allows restoring the consultation within 10 seconds.
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

    onSuccess: async (_, { leadId, consultationId }) => {
      // ✅ FIX: Use invalidateQueries with exact: true to prevent cascade
      await queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(leadId),
        exact: true,
        refetchType: 'active'
      });

      queryClient.invalidateQueries({
        queryKey: leadsKeys.timeline(leadId),
        exact: true,
        refetchType: 'active'
      });

      // Invalidate lists and pipeline
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' });
      queryClient.invalidateQueries({ queryKey: ["pipeline", "allowedNextStatuses"], refetchType: 'active' });

      // ✅ FIX BUG-17: Invalidate workflow context (delete may change workflow state)
      queryClient.invalidateQueries({
        queryKey: workflowContextKeys.byLead(leadId),
        exact: true,
        refetchType: 'active'
      });

      // ✅ UNDO TOAST: Show toast with undo button for 10 seconds
      toast.success("Đã xóa ghi nhận tư vấn", {
        description: "Bấm Hoàn tác để khôi phục",
        duration: 10000, // 10 seconds
        action: {
          label: "Hoàn tác",
          onClick: async () => {
            try {
              await leadsApi.restoreConsultation(leadId, consultationId);
              toast.success("Đã khôi phục ghi nhận tư vấn");
              // Refresh data after restore
              await queryClient.invalidateQueries({
                queryKey: leadsKeys.detail(leadId),
                exact: true,
                refetchType: 'active'
              });
              queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId), exact: true, refetchType: 'active' });
              queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' });
              queryClient.invalidateQueries({ queryKey: ["pipeline", "allowedNextStatuses"], refetchType: 'active' });
              queryClient.invalidateQueries({ queryKey: workflowContextKeys.byLead(leadId), exact: true, refetchType: 'active' });
            } catch {
              toast.error("Không thể khôi phục", {
                description: "Vui lòng thử lại hoặc liên hệ admin",
              });
            }
          },
        },
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Xóa tư vấn thất bại";
      toast.error("Lỗi xóa", { description: message });
    },
  });
}

/**
 * Restore a soft-deleted consultation
 *
 * @example
 * ```tsx
 * const restoreConsultation = useRestoreConsultation();
 * restoreConsultation.mutate({ leadId: 123, consultationId: 456 });
 * ```
 */
export function useRestoreConsultation() {
  const queryClient = useQueryClient();

  return useMutation<
    Consultation,
    AxiosError<ApiErrorResponse>,
    { leadId: number; consultationId: number }
  >({
    mutationFn: async ({ leadId, consultationId }) => {
      return await leadsApi.restoreConsultation(leadId, consultationId);
    },

    onSuccess: async (_, { leadId }) => {
      toast.success("Đã khôi phục ghi nhận tư vấn");

      // ✅ FIX: Use invalidateQueries with exact: true to prevent cascade
      await queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(leadId),
        exact: true,
        refetchType: 'active'
      });

      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId), exact: true, refetchType: 'active' });
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' });
      queryClient.invalidateQueries({ queryKey: ["pipeline", "allowedNextStatuses"], refetchType: 'active' });

      // ✅ FIX BUG-17: Invalidate workflow context (restore may change workflow state)
      queryClient.invalidateQueries({
        queryKey: workflowContextKeys.byLead(leadId),
        exact: true,
        refetchType: 'active'
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Không thể khôi phục ghi nhận tư vấn";
      toast.error("Lỗi khôi phục", { description: message });
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
      toast.success("Nhập dữ liệu thành công!", {
        description: `${result.successful_imports} lead đã nhập, ${result.failed_imports} thất bại`,
      });

      // Invalidate all lead lists
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists(), refetchType: 'active' });
      queryClient.invalidateQueries({ queryKey: ["pipeline"], refetchType: 'active' });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Nhập dữ liệu thất bại";
      toast.error("Lỗi nhập dữ liệu", { description: message });
    },
  });
}

/**
 * Download import template (CSV/Excel)
 *
 * @example
 * ```tsx
 * const downloadTemplate = useDownloadImportTemplate();
 * downloadTemplate.mutate({ format: 'csv' });
 * ```
 */
export function useDownloadImportTemplate() {
  return useMutation<
    Blob,
    AxiosError<ApiErrorResponse>,
    { format: 'csv' | 'xlsx' }
  >({
    mutationFn: async ({ format }) => {
      return await leadsApi.downloadImportTemplate(format);
    },

    onSuccess: (blob, { format }) => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `lead_import_template.${format}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      toast.success("Tải mẫu thành công!", {
        description: `File lead_import_template.${format} đã được tải về`,
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : "Không thể tải mẫu import";
      toast.error("Lỗi tải mẫu", { description: message });
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
    mutationFn: async ({ format = "csv", filters }) => {
      return await leadsApi.exportLeads(filters, format);
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

      toast.success("Xuất dữ liệu thành công!", {
        description: "File đã được tải về",
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : "Xuất dữ liệu thất bại";
      toast.error("Lỗi xuất dữ liệu", { description: message });
    },
  });
}
