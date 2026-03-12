// src/hooks/useKpiPlanning.ts
// React Query hooks for KPI Planning API — Phase C
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type {
  BatchOverrideRequest,
  Holiday,
  HolidayCreate,
  HolidayListResponse,
  HolidayStatus,
  HolidayUpdate,
  KpiPlan,
  KpiPlanCloneRequest,
  KpiPlanCreate,
  KpiPlanListResponse,
  KpiPlanMonth,
  KpiPlanPreviewRequest,
  KpiPlanPreviewResponse,
  KpiPlanUpdate,
  MonthOverrideRequest,
  MonthResetRequest,
  WorkingDaysOverrideRequest,
  AssignOfficerQuotaRequest,
  AssignOfficerQuotaResponse,
} from "@/types/kpi-planning.types";

interface ApiError {
  detail: string;
}

const BASE = "/api/admin/kpi-planning";

// =============================================================================
// QUERY KEY FACTORY
// =============================================================================

export const kpiPlanningKeys = {
  all: ["kpi-planning"] as const,
  plans: () => [...kpiPlanningKeys.all, "plans"] as const,
  planList: (filters?: Record<string, unknown>) =>
    [...kpiPlanningKeys.plans(), { filters }] as const,
  planDetail: (id: number) =>
    [...kpiPlanningKeys.plans(), "detail", id] as const,
  holidays: () => [...kpiPlanningKeys.all, "holidays"] as const,
  holidayList: (year?: number) =>
    [...kpiPlanningKeys.holidays(), { year }] as const,
  holidayStatus: (year: number) =>
    [...kpiPlanningKeys.holidays(), "status", year] as const,
};

// =============================================================================
// PLAN QUERIES
// =============================================================================

export function useKpiPlans(params?: {
  fiscal_year?: number;
  unit_id?: number;
  is_active?: boolean;
  skip?: number;
  limit?: number;
}) {
  return useQuery<KpiPlanListResponse, AxiosError<ApiError>>({
    queryKey: kpiPlanningKeys.planList(params as Record<string, unknown>),
    queryFn: async () => {
      const res = await api.get<KpiPlanListResponse>(`${BASE}/plans`, {
        params,
      });
      return res.data;
    },
  });
}

export function useKpiPlan(planId: number, enabled = true) {
  return useQuery<KpiPlan, AxiosError<ApiError>>({
    queryKey: kpiPlanningKeys.planDetail(planId),
    queryFn: async () => {
      const res = await api.get<KpiPlan>(`${BASE}/plans/${planId}`);
      return res.data;
    },
    enabled,
  });
}

// =============================================================================
// PLAN MUTATIONS
// =============================================================================

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation<KpiPlan, AxiosError<ApiError>, KpiPlanCreate>({
    mutationFn: async (data) => {
      const res = await api.post<KpiPlan>(`${BASE}/plans`, data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã tạo KPI Plan thành công");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.plans() });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi tạo KPI Plan");
    },
  });
}

export function useUpdatePlan(planId: number) {
  const qc = useQueryClient();
  return useMutation<KpiPlan, AxiosError<ApiError>, KpiPlanUpdate>({
    mutationFn: async (data) => {
      const res = await api.put<KpiPlan>(`${BASE}/plans/${planId}`, data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã cập nhật KPI Plan");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.planDetail(planId) });
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.plans() });
      qc.invalidateQueries({ queryKey: ["kpi-setup"] });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi cập nhật");
    },
  });
}

export function useDeletePlan() {
  const qc = useQueryClient();
  return useMutation<void, AxiosError<ApiError>, number>({
    mutationFn: async (planId) => {
      await api.delete(`${BASE}/plans/${planId}`);
    },
    onSuccess: () => {
      toast.success("Đã vô hiệu hóa KPI Plan");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.plans() });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi xóa plan");
    },
  });
}

export function useClonePlan() {
  const qc = useQueryClient();
  return useMutation<
    KpiPlan,
    AxiosError<ApiError>,
    { planId: number; data: KpiPlanCloneRequest }
  >({
    mutationFn: async ({ planId, data }) => {
      const res = await api.post<KpiPlan>(
        `${BASE}/plans/${planId}/clone`,
        data,
      );
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Đã clone KPI Plan sang năm ${data.fiscal_year}`);
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.plans() });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi clone KPI Plan");
    },
  });
}

export function useRegeneratePlan(planId: number) {
  const qc = useQueryClient();
  return useMutation<KpiPlan, AxiosError<ApiError>, void>({
    mutationFn: async () => {
      const res = await api.post<KpiPlan>(`${BASE}/plans/${planId}/regenerate`);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã tính lại KPI");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.planDetail(planId) });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi tính lại");
    },
  });
}

// =============================================================================
// PREVIEW (no mutation — just a query with manual trigger)
// =============================================================================

export function usePreviewPlan() {
  return useMutation<KpiPlanPreviewResponse, AxiosError<ApiError>, KpiPlanPreviewRequest>({
    mutationFn: async (data) => {
      const res = await api.post<KpiPlanPreviewResponse>(
        `${BASE}/plans/preview`,
        data,
      );
      return res.data;
    },
  });
}

// =============================================================================
// MONTH OVERRIDE / RESET
// =============================================================================

export function useOverrideMonth(planId: number) {
  const qc = useQueryClient();
  return useMutation<
    KpiPlanMonth,
    AxiosError<ApiError>,
    { monthId: number; data: MonthOverrideRequest }
  >({
    mutationFn: async ({ monthId, data }) => {
      const res = await api.put<KpiPlanMonth>(
        `${BASE}/months/${monthId}/override`,
        data,
      );
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã override KPI tháng");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.planDetail(planId) });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi override");
    },
  });
}

export function useResetMonthOverride(planId: number) {
  const qc = useQueryClient();
  return useMutation<
    KpiPlanMonth,
    AxiosError<ApiError>,
    { monthId: number; data: MonthResetRequest }
  >({
    mutationFn: async ({ monthId, data }) => {
      const res = await api.post<KpiPlanMonth>(
        `${BASE}/months/${monthId}/reset`,
        data,
      );
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã reset override");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.planDetail(planId) });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi reset");
    },
  });
}

export function useBatchOverride(planId: number) {
  const qc = useQueryClient();
  return useMutation<
    { updated: number; months: KpiPlanMonth[] },
    AxiosError<ApiError>,
    BatchOverrideRequest
  >({
    mutationFn: async (data) => {
      const res = await api.put(`${BASE}/months/batch-override`, data);
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Đã override ${data.updated} tháng`);
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.planDetail(planId) });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi batch override");
    },
  });
}

export function useOverrideWorkingDays(planId: number) {
  const qc = useQueryClient();
  return useMutation<
    KpiPlanMonth,
    AxiosError<ApiError>,
    { monthId: number; data: WorkingDaysOverrideRequest }
  >({
    mutationFn: async ({ monthId, data }) => {
      const res = await api.put<KpiPlanMonth>(
        `${BASE}/months/${monthId}/working-days`,
        data,
      );
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã cập nhật ngày làm việc");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.planDetail(planId) });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi cập nhật working days");
    },
  });
}

// =============================================================================
// HOLIDAY QUERIES & MUTATIONS
// =============================================================================

export function useHolidayStatus(year: number) {
  return useQuery<HolidayStatus, AxiosError<ApiError>>({
    queryKey: kpiPlanningKeys.holidayStatus(year),
    queryFn: async () => {
      const res = await api.get<HolidayStatus>(
        `${BASE}/holidays/status/${year}`,
      );
      return res.data;
    },
  });
}

export function useHolidays(year?: number) {
  return useQuery<HolidayListResponse, AxiosError<ApiError>>({
    queryKey: kpiPlanningKeys.holidayList(year),
    queryFn: async () => {
      const res = await api.get<HolidayListResponse>(`${BASE}/holidays`, {
        params: year ? { year } : undefined,
      });
      return res.data;
    },
  });
}

export function useCreateHoliday() {
  const qc = useQueryClient();
  return useMutation<Holiday, AxiosError<ApiError>, HolidayCreate>({
    mutationFn: async (data) => {
      const res = await api.post<Holiday>(`${BASE}/holidays`, data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã thêm ngày lễ");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.holidays() });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi thêm ngày lễ");
    },
  });
}

export function useUpdateHoliday() {
  const qc = useQueryClient();
  return useMutation<
    Holiday,
    AxiosError<ApiError>,
    { id: number; data: HolidayUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const res = await api.put<Holiday>(`${BASE}/holidays/${id}`, data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã cập nhật ngày lễ");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.holidays() });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi cập nhật");
    },
  });
}

export function useDeleteHoliday() {
  const qc = useQueryClient();
  return useMutation<void, AxiosError<ApiError>, number>({
    mutationFn: async (id) => {
      await api.delete(`${BASE}/holidays/${id}`);
    },
    onSuccess: () => {
      toast.success("Đã xóa ngày lễ");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.holidays() });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi xóa");
    },
  });
}

export function useSeedHolidays() {
  const qc = useQueryClient();
  return useMutation<
    { year: number; seeded: number },
    AxiosError<ApiError>,
    number
  >({
    mutationFn: async (year) => {
      const res = await api.post(`${BASE}/holidays/seed/${year}`);
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Đã seed ${data.seeded} ngày lễ cho năm ${data.year}`);
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.holidays() });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi seed holidays");
    },
  });
}

// =============================================================================
// OFFICER QUOTA ASSIGNMENT (V2)
// =============================================================================

export function useAssignOfficerQuota() {
  const qc = useQueryClient();
  return useMutation<
    AssignOfficerQuotaResponse,
    AxiosError<ApiError>,
    AssignOfficerQuotaRequest
  >({
    mutationFn: async (data) => {
      const res = await api.post<AssignOfficerQuotaResponse>(
        `${BASE}/plans/assign-officer-quota`,
        data,
      );
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã gán chỉ tiêu cho cán bộ");
      qc.invalidateQueries({ queryKey: kpiPlanningKeys.plans() });
      qc.invalidateQueries({ queryKey: ["kpi-setup"] });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi gán chỉ tiêu");
    },
  });
}
