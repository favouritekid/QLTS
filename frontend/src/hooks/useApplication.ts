// src/hooks/useApplication.ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { leadsKeys } from "@/hooks/useLeads";
import type { ApiErrorResponse } from "@/types/api.types";
import type {
  Application,
  ApplicationCreate,
  ApplicationUpdate,
} from "@/types/lead.types";

// =====================================================================
// MUTATIONS - APPLICATION (HỒ SƠ TUYỂN SINH)
// =====================================================================

/**
 * Create a new application for a lead
 *
 * @example
 * ```tsx
 * const createApplication = useCreateApplication(leadId);
 *
 * createApplication.mutate();
 * ```
 */
export function useCreateApplication(leadId: number) {
  const queryClient = useQueryClient();

  return useMutation<Application, AxiosError<ApiErrorResponse>, void>({
    mutationFn: async () => {
      const payload: ApplicationCreate = { lead_id: leadId };
      const response = await api.post<Application>(
        API_ENDPOINTS.APPLICATIONS.CREATE(leadId),
        payload
      );
      return response.data;
    },

    onSuccess: () => {
      toast.success("Đã tạo hồ sơ tuyển sinh!", {
        description: "Bạn có thể bắt đầu điền thông tin hồ sơ",
      });

      // Invalidate lead detail to refetch with new application
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(leadId) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId) });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg || "Validation error").join(", ")
            : "Không thể tạo hồ sơ tuyển sinh";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing application
 *
 * @example
 * ```tsx
 * const updateApplication = useUpdateApplication(applicationId);
 *
 * updateApplication.mutate({
 *   status: 'completed',
 *   major_program_id: 1,
 *   program_offering_id: 2,
 *   criterion_id: 'hoc_ba_2025',
 *   documents: {
 *     scores: { Toan: 8.5, Van: 7.0 },
 *     checklist: [...]
 *   }
 * });
 * ```
 */
export function useUpdateApplication(applicationId: number) {
  const queryClient = useQueryClient();

  return useMutation<
    Application,
    AxiosError<ApiErrorResponse>,
    ApplicationUpdate
  >({
    mutationFn: async (data) => {
      const response = await api.put<Application>(
        API_ENDPOINTS.APPLICATIONS.UPDATE(applicationId),
        data
      );
      return response.data;
    },

    onSuccess: (updatedApplication) => {
      toast.success("Đã lưu hồ sơ!", {
        description: "Thông tin hồ sơ đã được cập nhật",
      });

      // Invalidate lead detail (which contains application)
      queryClient.invalidateQueries({
        queryKey: leadsKeys.detail(updatedApplication.lead_id),
      });
      queryClient.invalidateQueries({
        queryKey: leadsKeys.timeline(updatedApplication.lead_id),
      });
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((e) => e.msg || "Validation error").join(", ")
            : "Không thể cập nhật hồ sơ";
      toast.error("Lỗi", { description: message });
    },
  });
}
