// src/hooks/useTuitionDiscount.ts
/**
 * React Query hooks for Tuition Discount Policy Management
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  TuitionDiscountPolicy,
  TuitionDiscountPolicyCreate,
  TuitionDiscountPolicyUpdate,
  TuitionDiscountPolicyListResponse,
  DiscountCalculationRequest,
  DiscountCalculationResponse,
} from "@/types/tuition-discount.types";

// =============================================================================
// QUERY KEYS
// =============================================================================

export const tuitionDiscountKeys = {
  all: ["tuition-discount-policies"] as const,
  lists: () => [...tuitionDiscountKeys.all, "list"] as const,
  list: (params: Record<string, unknown>) =>
    [...tuitionDiscountKeys.lists(), params] as const,
  details: () => [...tuitionDiscountKeys.all, "detail"] as const,
  detail: (id: number) => [...tuitionDiscountKeys.details(), id] as const,
};

// =============================================================================
// QUERIES
// =============================================================================

interface ListPoliciesParams {
  page?: number;
  pageSize?: number;
  isActive?: boolean;
  includeExpired?: boolean;
}

/**
 * Hook lấy danh sách chính sách ưu đãi học phí
 */
export function useTuitionDiscountPolicies(
  params: ListPoliciesParams = {},
  options?: { initialData?: TuitionDiscountPolicyListResponse }
) {
  const { page = 1, pageSize = 20, isActive, includeExpired = false } = params;

  return useQuery({
    queryKey: tuitionDiscountKeys.list({ page, pageSize, isActive, includeExpired }),
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      searchParams.set("page", String(page));
      searchParams.set("page_size", String(pageSize));
      searchParams.set("include_expired", String(includeExpired));
      if (isActive !== undefined) {
        searchParams.set("is_active", String(isActive));
      }

      const response = await apiClient.get<TuitionDiscountPolicyListResponse>(
        `${API_ENDPOINTS.ADMIN.TUITION_DISCOUNT.LIST}?${searchParams.toString()}`
      );
      return response.data;
    },
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 2 - DAY 3: Support SSR
  });
}

/**
 * Hook lấy chi tiết chính sách ưu đãi
 */
export function useTuitionDiscountPolicy(policyId: number | null) {
  return useQuery({
    queryKey: tuitionDiscountKeys.detail(policyId!),
    queryFn: async () => {
      const response = await apiClient.get<TuitionDiscountPolicy>(
        API_ENDPOINTS.ADMIN.TUITION_DISCOUNT.GET(policyId!)
      );
      return response.data;
    },
    enabled: policyId !== null && policyId > 0,
  });
}

// =============================================================================
// MUTATIONS
// =============================================================================

/**
 * Hook tạo chính sách ưu đãi mới
 */
export function useCreateTuitionDiscountPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: TuitionDiscountPolicyCreate) => {
      const response = await apiClient.post<TuitionDiscountPolicy>(
        API_ENDPOINTS.ADMIN.TUITION_DISCOUNT.CREATE,
        data
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: tuitionDiscountKeys.lists() });
      toast.success(`Đã tạo chính sách "${data.name}" thành công`);
    },
    onError: (error: Error) => {
      toast.error(`Lỗi khi tạo chính sách: ${error.message}`);
    },
  });
}

/**
 * Hook cập nhật chính sách ưu đãi
 */
export function useUpdateTuitionDiscountPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: TuitionDiscountPolicyUpdate;
    }) => {
      const response = await apiClient.put<TuitionDiscountPolicy>(
        API_ENDPOINTS.ADMIN.TUITION_DISCOUNT.UPDATE(id),
        data
      );
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: tuitionDiscountKeys.lists() });
      queryClient.invalidateQueries({
        queryKey: tuitionDiscountKeys.detail(data.id),
      });
      toast.success(`Đã cập nhật chính sách "${data.name}"`);
    },
    onError: (error: Error) => {
      toast.error(`Lỗi khi cập nhật chính sách: ${error.message}`);
    },
  });
}

/**
 * Hook xóa chính sách ưu đãi
 */
export function useDeleteTuitionDiscountPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      id,
      hardDelete = false,
    }: {
      id: number;
      hardDelete?: boolean;
    }) => {
      await apiClient.delete(
        `${API_ENDPOINTS.ADMIN.TUITION_DISCOUNT.DELETE(id)}?hard_delete=${hardDelete}`
      );
      return id;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tuitionDiscountKeys.lists() });
      toast.success("Đã xóa chính sách ưu đãi");
    },
    onError: (error: Error) => {
      toast.error(`Lỗi khi xóa chính sách: ${error.message}`);
    },
  });
}

/**
 * Hook tính toán ưu đãi học phí
 */
export function useCalculateDiscount() {
  return useMutation({
    mutationFn: async (request: DiscountCalculationRequest) => {
      const response = await apiClient.post<DiscountCalculationResponse>(
        API_ENDPOINTS.ADMIN.TUITION_DISCOUNT.CALCULATE,
        request
      );
      return response.data;
    },
    onError: (error: Error) => {
      toast.error(`Lỗi khi tính toán ưu đãi: ${error.message}`);
    },
  });
}
