// src/hooks/usePipeline.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { pipelineApi } from "@/lib/api/pipeline";
import { leadsKeys } from "@/hooks/useLeads";
import type { ApiErrorResponse } from "@/types/api.types";
import type { Lead } from "@/types/lead.types";
import type {
  PipelineStage,
  PipelineStageCreate,
  PipelineStageUpdate,
  ConsultationStatus,
  ConsultationStatusCreate,
  ConsultationStatusUpdate,
  FullPipeline,
  PipelineQueryParams,
  MoveLeadPayload,
  AllowedTransition, // ✅ Import mới
  AllowedTransitionCreate,
} from "@/types/pipeline.types";

// =====================================================================
// QUERY KEYS
// =====================================================================

export const pipelineKeys = {
  all: ["pipeline"] as const,
  stages: () => [...pipelineKeys.all, "stages"] as const,
  fullPipeline: (params?: PipelineQueryParams) => [...pipelineKeys.all, "full", params] as const,
  stageLeads: (stageId: string) => [...pipelineKeys.all, "stageLeads", stageId] as const,
  consultationStatuses: () => [...pipelineKeys.all, "consultationStatuses"] as const,
  // ✅ FSM v3.1: Cache by currentStatusId ONLY (not leadId)
  // Rationale: FSM results depend on (status, phase), and most leads share the same phase.
  // This enables React Query deduplication across concurrent requests for same status.
  allowedNextStatuses: (currentStatusId?: string | null) =>
    [...pipelineKeys.all, "allowedNextStatuses", currentStatusId] as const,
  allowedTransitions: () => [...pipelineKeys.all, "allowedTransitions"] as const,
  stats: (params?: PipelineQueryParams) => [...pipelineKeys.all, "stats", params] as const,
};

// =====================================================================
// QUERIES (READ) - PIPELINE STAGES
// =====================================================================

/**
 * Get all pipeline stages (ordered)
 *
 * ✅ PHASE 1 - WEEK 2: Support initialData from Server Components
 *
 * @example
 * ```tsx
 * const { data: stages, isLoading } = usePipelineStages();
 * // Or with initialData from server:
 * const { data: stages } = usePipelineStages({ initialData: serverStages });
 * ```
 */
export function usePipelineStages(options?: { initialData?: PipelineStage[] }) {
  return useQuery<PipelineStage[], AxiosError<ApiErrorResponse>>({
    queryKey: pipelineKeys.stages(),
    queryFn: async () => {
      return await pipelineApi.getStages();
    },
    staleTime: 1000 * 60 * 5, // 5 minutes (stages don't change frequently)
    gcTime: 1000 * 60 * 10, // 10 minutes in cache
    initialData: options?.initialData, // ✅ Use initialData from Server Component
  });
}

/**
 * Get full pipeline with all stages and statistics
 *
 * @example
 * ```tsx
 * const { data: pipeline } = useFullPipeline({
 *   unit_id: 1,
 *   date_from: '2025-01-01',
 *   date_to: '2025-12-31',
 * });
 * ```
 */
export function useFullPipeline(
  params?: PipelineQueryParams,
  options?: { initialData?: FullPipeline }
) {
  return useQuery<FullPipeline, AxiosError<ApiErrorResponse>>({
    queryKey: pipelineKeys.fullPipeline(params),
    queryFn: async () => {
      return await pipelineApi.getFullPipeline(params);
    },
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 2 - DAY 5: Support SSR
    staleTime: 1000 * 30, // 30 seconds
    gcTime: 1000 * 60 * 5, // 5 minutes in cache
  });
}

/**
 * Get leads in a specific stage
 *
 * @example
 * ```tsx
 * const { data: leads } = useLeadsInStage('new_lead');
 * ```
 */
export function useLeadsInStage(stageId: string) {
  return useQuery<Lead[], AxiosError<ApiErrorResponse>>({
    queryKey: pipelineKeys.stageLeads(stageId),
    queryFn: async () => {
      return await pipelineApi.getLeadsInStage(stageId);
    },
    enabled: !!stageId,
    staleTime: 1000 * 30, // 30 seconds
  });
}

/**
 * Get pipeline statistics
 *
 * @example
 * ```tsx
 * const { data: stats } = usePipelineStats({ unit_id: 1 });
 * ```
 */
export function usePipelineStats(params?: PipelineQueryParams) {
  return useQuery<
    {
      total_leads: number;
      conversion_rate?: number;
      avg_time_in_pipeline_days?: number;
      stage_statistics: Array<{
        stage_id: string;
        stage_name: string;
        lead_count: number;
        conversion_rate: number;
      }>;
    },
    AxiosError<ApiErrorResponse>
  >({
    queryKey: pipelineKeys.stats(params),
    queryFn: async () => {
      return await pipelineApi.getPipelineStats(params);
    },
    staleTime: 1000 * 60, // 1 minute
    gcTime: 1000 * 60 * 5, // 5 minutes in cache
  });
}

// =====================================================================
// QUERIES (READ) - CONSULTATION STATUSES
// =====================================================================

/**
 * Get all consultation statuses
 * Uses public pipeline endpoint to allow officer access
 *
 * ✅ PHASE 1 - WEEK 2: Support initialData from Server Components
 *
 * @example
 * ```tsx
 * const { data: statuses } = useConsultationStatuses();
 * // Or with initialData from server:
 * const { data: statuses } = useConsultationStatuses({ initialData: serverStatuses });
 * ```
 */
export function useConsultationStatuses(options?: { initialData?: ConsultationStatus[] }) {
  return useQuery<ConsultationStatus[], AxiosError<ApiErrorResponse>>({
    queryKey: pipelineKeys.consultationStatuses(),
    queryFn: async () => {
      // Use public endpoint instead of admin endpoint for officer access
      const fullPipeline = await pipelineApi.getFullPipeline();

      // Backend returns statuses as a separate top-level array
      // Type assertion needed because FullPipeline type may not include statuses
      const response = fullPipeline as { stages: unknown[]; statuses?: ConsultationStatus[] };

      return response.statuses || [];
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
    gcTime: 1000 * 60 * 10, // 10 minutes in cache
    initialData: options?.initialData, // ✅ Use initialData from Server Component
  });
}

/**
 * Get allowed next statuses from current status (FSM v3.1)
 * Returns only valid transitions based on:
 * - Workflow transitions (allowed_transitions table)
 * - Phase guards (user/role cannot cross phases)
 * - Trigger type (hide system-only statuses)
 * - Lead phase (derived from admission_profile)
 *
 * @param currentStatusId - Current consultation status ID (null/undefined for new leads)
 * @param leadId - Lead ID to derive phase from admission_profile (optional, not used in cache key)
 *
 * @example
 * ```tsx
 * // Get next allowed statuses for a specific lead
 * const { data: nextStatuses } = useAllowedNextStatuses('sts01', 123);
 *
 * // Get initial status for new lead (NULL → NOT_CONTACTED only)
 * const { data: initialStatuses } = useAllowedNextStatuses(null);
 * ```
 *
 * @note v3.1: Cache key uses currentStatusId ONLY (not leadId) to enable deduplication.
 * FSM results depend on (status, phase), and most leads share the same phase (consultation).
 * This prevents N+1 API calls when rendering multiple lead cards with same status.
 */
export function useAllowedNextStatuses(currentStatusId?: string | null, leadId?: number) {
  return useQuery<ConsultationStatus[], AxiosError<ApiErrorResponse>>({
    // ✅ v3.1: Cache by status only - enables deduplication across components
    queryKey: pipelineKeys.allowedNextStatuses(currentStatusId),
    queryFn: async () => {
      // leadId still passed to API for phase derivation, just not in cache key
      return await pipelineApi.getAllowedNextStatuses(currentStatusId || null, leadId);
    },
    // ✅ Only fetch when currentStatusId is explicitly provided (not undefined)
    // This prevents unnecessary API calls when the hook is mounted but not yet needed
    enabled: currentStatusId !== undefined,
    staleTime: 1000 * 60 * 5, // 5 minutes (workflow rules don't change frequently)
    gcTime: 1000 * 60 * 10, // 10 minutes in cache
    // ✅ v3.1: Prevent refetch on mount if data already in cache
    refetchOnMount: false,
    // ✅ v3.1: Don't refetch when window regains focus
    refetchOnWindowFocus: false,
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - PIPELINE STAGES
// =====================================================================

/**
 * Create a new pipeline stage (admin only)
 *
 * @example
 * ```tsx
 * const createStage = useCreatePipelineStage();
 *
 * createStage.mutate({
 *   id: 'follow_up',
 *   name: 'Follow Up',
 *   order: 5,
 * });
 * ```
 */
export function useCreatePipelineStage() {
  const queryClient = useQueryClient();

  return useMutation<PipelineStage, AxiosError<ApiErrorResponse>, PipelineStageCreate>({
    mutationFn: async (data) => {
      return await pipelineApi.createStage(data);
    },

    onSuccess: (newStage) => {
      toast.success("Pipeline stage created!", {
        description: newStage.name,
      });

      // Invalidate and refetch pipeline queries immediately
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.refetchQueries({ queryKey: pipelineKeys.stages() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.fullPipeline() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg || "Validation error").join(", ")
            : "Failed to create pipeline stage";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Update a pipeline stage (admin only)
 *
 * @example
 * ```tsx
 * const updateStage = useUpdatePipelineStage();
 *
 * updateStage.mutate({
 *   id: 'follow_up',
 *   data: { name: 'Follow Up - Updated' },
 * });
 * ```
 */
export function useUpdatePipelineStage() {
  const queryClient = useQueryClient();

  return useMutation<
    PipelineStage,
    AxiosError<ApiErrorResponse>,
    { id: string; data: PipelineStageUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      return await pipelineApi.updateStage(id, data);
    },

    onSuccess: (updatedStage) => {
      toast.success("Pipeline stage updated!", {
        description: updatedStage.name,
      });

      // Invalidate and refetch pipeline queries immediately
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.refetchQueries({ queryKey: pipelineKeys.stages() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.fullPipeline() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to update pipeline stage";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Delete a pipeline stage (admin only)
 *
 * @example
 * ```tsx
 * const deleteStage = useDeletePipelineStage();
 * deleteStage.mutate('follow_up');
 * ```
 */
export function useDeletePipelineStage() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, string>({
    mutationFn: async (id) => {
      await pipelineApi.deleteStage(id);
    },

    onSuccess: () => {
      toast.success("Pipeline stage deleted!");

      // Invalidate and refetch pipeline queries immediately
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.refetchQueries({ queryKey: pipelineKeys.stages() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.fullPipeline() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to delete pipeline stage";
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - CONSULTATION STATUSES
// =====================================================================

/**
 * Create a new consultation status (admin only)
 *
 * @example
 * ```tsx
 * const createStatus = useCreateConsultationStatus();
 *
 * createStatus.mutate({
 *   name: 'Rescheduled',
 *   color: '#FFA500',
 *   order: 5,
 * });
 * ```
 */
export function useCreateConsultationStatus() {
  const queryClient = useQueryClient();

  return useMutation<ConsultationStatus, AxiosError<ApiErrorResponse>, ConsultationStatusCreate>({
    mutationFn: async (data) => {
      return await pipelineApi.createConsultationStatus(data);
    },

    onSuccess: (newStatus) => {
      toast.success("Consultation status created!", {
        description: newStatus.name,
      });

      // Invalidate and refetch consultation status queries immediately
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.refetchQueries({ queryKey: pipelineKeys.consultationStatuses() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.fullPipeline() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to create consultation status";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Update a consultation status (admin only)
 *
 * @example
 * ```tsx
 * const updateStatus = useUpdateConsultationStatus();
 *
 * updateStatus.mutate({
 *   id: 123,
 *   data: { name: 'Rescheduled - Updated' },
 * });
 * ```
 */
export function useUpdateConsultationStatus() {
  const queryClient = useQueryClient();

  return useMutation<
    ConsultationStatus,
    AxiosError<ApiErrorResponse>,
    { id: string; data: ConsultationStatusUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      return await pipelineApi.updateConsultationStatus(id, data);
    },

    onSuccess: (updatedStatus) => {
      toast.success("Consultation status updated!", {
        description: updatedStatus.name,
      });

      // Invalidate and refetch consultation status queries immediately
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.refetchQueries({ queryKey: pipelineKeys.consultationStatuses() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.fullPipeline() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to update consultation status";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Delete a consultation status (admin only)
 *
 * @example
 * ```tsx
 * const deleteStatus = useDeleteConsultationStatus();
 * deleteStatus.mutate(123);
 * ```
 */
export function useDeleteConsultationStatus() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, string>({
    mutationFn: async (id) => {
      await pipelineApi.deleteConsultationStatus(id);
    },

    onSuccess: () => {
      toast.success("Consultation status deleted!");

      // Invalidate and refetch consultation status queries immediately
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.refetchQueries({ queryKey: pipelineKeys.consultationStatuses() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.fullPipeline() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to delete consultation status";
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS - PIPELINE OPERATIONS
// =====================================================================

/**
 * Move a lead to a different pipeline stage (drag & drop)
 *
 * @example
 * ```tsx
 * const moveLead = useMoveLeadToStage();
 *
 * moveLead.mutate({
 *   lead_id: 123,
 *   to_stage_id: 'consultation_scheduled',
 *   reason: 'Consultation booked for tomorrow',
 * });
 * ```
 */
export function useMoveLeadToStage() {
  const queryClient = useQueryClient();

  return useMutation<
    Lead,
    AxiosError<ApiErrorResponse>,
    MoveLeadPayload,
    {
      previousLeadsInOldStage?: Lead[];
      previousLeadsInNewStage?: Lead[];
      previousFullPipeline?: FullPipeline;
    }
  >({
    mutationFn: async (data) => {
      return await pipelineApi.moveLeadToStage(data);
    },

    // Optimistic update for better UX
    onMutate: async ({ lead_id, from_stage_id, to_stage_id }) => {
      // Cancel outgoing queries
      if (from_stage_id) {
        await queryClient.cancelQueries({
          queryKey: pipelineKeys.stageLeads(from_stage_id),
        });
      }
      await queryClient.cancelQueries({
        queryKey: pipelineKeys.stageLeads(to_stage_id),
      });
      await queryClient.cancelQueries({ queryKey: pipelineKeys.fullPipeline() });

      // Snapshot previous data
      const previousLeadsInOldStage = from_stage_id
        ? queryClient.getQueryData<Lead[]>(pipelineKeys.stageLeads(from_stage_id))
        : undefined;
      const previousLeadsInNewStage = queryClient.getQueryData<Lead[]>(
        pipelineKeys.stageLeads(to_stage_id)
      );
      const previousFullPipeline = queryClient.getQueryData<FullPipeline>(
        pipelineKeys.fullPipeline()
      );

      // Optimistically update cache (remove from old stage, add to new stage)
      if (previousLeadsInOldStage && from_stage_id) {
        const leadToMove = previousLeadsInOldStage.find((l) => l.id === lead_id);
        if (leadToMove) {
          // Remove from old stage
          queryClient.setQueryData<Lead[]>(
            pipelineKeys.stageLeads(from_stage_id),
            previousLeadsInOldStage.filter((l) => l.id !== lead_id)
          );

          // Add to new stage
          if (previousLeadsInNewStage) {
            queryClient.setQueryData<Lead[]>(pipelineKeys.stageLeads(to_stage_id), [
              ...previousLeadsInNewStage,
              { ...leadToMove, pipeline_stage_id: to_stage_id },
            ]);
          }
        }
      }

      return {
        previousLeadsInOldStage,
        previousLeadsInNewStage,
        previousFullPipeline,
      };
    },

    // Rollback on error
    onError: (err, { from_stage_id, to_stage_id }, context) => {
      if (context?.previousLeadsInOldStage && from_stage_id) {
        queryClient.setQueryData(
          pipelineKeys.stageLeads(from_stage_id),
          context.previousLeadsInOldStage
        );
      }
      if (context?.previousLeadsInNewStage) {
        queryClient.setQueryData(
          pipelineKeys.stageLeads(to_stage_id),
          context.previousLeadsInNewStage
        );
      }
      if (context?.previousFullPipeline) {
        queryClient.setQueryData(pipelineKeys.fullPipeline(), context.previousFullPipeline);
      }

      const detail = err.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to move lead";
      toast.error("Error", { description: message });
    },

    onSuccess: (updatedLead, { from_stage_id, to_stage_id }) => {
      toast.success("Lead moved successfully!", {
        description: `Moved to ${to_stage_id.replace(/_/g, " ")}`,
      });

      // Invalidate all relevant queries
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id) });

      if (from_stage_id) {
        queryClient.invalidateQueries({
          queryKey: pipelineKeys.stageLeads(from_stage_id),
        });
      }
      queryClient.invalidateQueries({
        queryKey: pipelineKeys.stageLeads(to_stage_id),
      });
    },
  });
}

/**
 * Revert a lead to a previous stage
 *
 * @example
 * ```tsx
 * const revertStatus = useRevertLeadStatus();
 *
 * revertStatus.mutate({
 *   leadId: 123,
 *   toStageId: 'contacted',
 *   reason: 'Consultation was cancelled',
 * });
 * ```
 */
export function useRevertLeadStatus() {
  const queryClient = useQueryClient();

  return useMutation<Lead, AxiosError<ApiErrorResponse>, { leadId: number }>({
    mutationFn: async ({ leadId }) => {
      return await pipelineApi.revertLeadStatus(leadId);
    },

    onSuccess: (updatedLead) => {
      toast.success("Lead status reverted!", {
        description: updatedLead.full_name,
      });

      // Invalidate queries
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(updatedLead.id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(updatedLead.id) });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to revert lead status";
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// QUERIES (READ) - ALLOWED TRANSITIONS
// =====================================================================

/**
 * Get all allowed transitions
 *
 * @example
 * ```tsx
 * const { data: transitions } = useAllowedTransitions();
 * ```
 */
export function useAllowedTransitions() {
  return useQuery<AllowedTransition[], AxiosError<ApiErrorResponse>>({
    queryKey: pipelineKeys.allowedTransitions(),
    queryFn: async () => {
      return await pipelineApi.getAllowedTransitions();
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
    gcTime: 1000 * 60 * 10, // 10 minutes in cache
  });
}

// =====================================================================
// MUTATIONS (CREATE, DELETE) - ALLOWED TRANSITIONS
// =====================================================================

/**
 * Create a new allowed transition (admin only)
 *
 * @example
 * ```tsx
 * const createTransition = useCreateAllowedTransition();
 *
 * createTransition.mutate({
 *   from_status_id: 'contacted',
 *   to_status_id: 'qualified',
 * });
 * ```
 */
export function useCreateAllowedTransition() {
  const queryClient = useQueryClient();

  return useMutation<AllowedTransition, AxiosError<ApiErrorResponse>, AllowedTransitionCreate>({
    mutationFn: async (data) => {
      return await pipelineApi.createAllowedTransition(data);
    },

    onSuccess: (newTransition) => {
      toast.success("Allowed transition created!", {
        description: `${newTransition.from_status_id} → ${newTransition.to_status_id}`,
      });

      // Invalidate and refetch allowed transitions queries
      queryClient.invalidateQueries({ queryKey: pipelineKeys.allowedTransitions() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.allowedTransitions() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg || "Validation error").join(", ")
            : "Failed to create allowed transition";
      toast.error("Error", { description: message });
    },
  });
}

/**
 * Delete an allowed transition (admin only)
 *
 * @example
 * ```tsx
 * const deleteTransition = useDeleteAllowedTransition();
 * deleteTransition.mutate(123);
 * ```
 */
export function useDeleteAllowedTransition() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await pipelineApi.deleteAllowedTransition(id);
    },

    onSuccess: () => {
      toast.success("Allowed transition deleted!");

      // Invalidate and refetch allowed transitions queries
      queryClient.invalidateQueries({ queryKey: pipelineKeys.allowedTransitions() });
      queryClient.refetchQueries({ queryKey: pipelineKeys.allowedTransitions() });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg).join(", ")
            : "Failed to delete allowed transition";
      toast.error("Error", { description: message });
    },
  });
}

// =====================================================================
// UTILITY FUNCTIONS
// =====================================================================

/**
 * Invalidate all pipeline-related caches
 * Useful after bulk operations or when you want to force a full refresh
 *
 * @example
 * ```tsx
 * const queryClient = useQueryClient();
 * invalidatePipelineCache(queryClient);
 * ```
 */
export function invalidatePipelineCache(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: pipelineKeys.all });
  queryClient.invalidateQueries({ queryKey: leadsKeys.all });
}
