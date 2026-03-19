// hooks/useKpiSetup.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { CoverageReport, KpiConfigItem, KpiConfigCreate, KpiConfigUpdate } from "@/types/kpi-setup.types";

interface ApiError {
  detail: string;
}

interface CreateKpiTargetInput {
  kpi_code: string;
  annual_target: number;
  fiscal_year: number;
  officer_id: number;
}

interface UpdateKpiTargetInput {
  id: number;
  data: {
    annual_target: number;
  };
}

export const kpiSetupKeys = {
  all: ["kpi-setup"] as const,
  coverage: (fy: number) => [...kpiSetupKeys.all, "coverage", fy] as const,
  configs: () => [...kpiSetupKeys.all, "configs"] as const,
  configList: (filters: Record<string, unknown>) =>
    [...kpiSetupKeys.configs(), "list", filters] as const,
  targets: () => [...kpiSetupKeys.all, "targets"] as const,
  targetList: (filters: Record<string, unknown>) =>
    [...kpiSetupKeys.targets(), "list", filters] as const,
};

export function useKpiCoverage(fiscalYear: number) {
  return useQuery<CoverageReport, AxiosError<ApiError>>({
    queryKey: kpiSetupKeys.coverage(fiscalYear),
    queryFn: async () => {
      const res = await api.get<CoverageReport>("/api/admin/kpi-setup/coverage", {
        params: { fiscal_year: fiscalYear },
      });
      return res.data;
    },
    staleTime: 2 * 60 * 1000,
  });
}

export interface KpiTargetItem {
  id: number;
  kpi_code: string;
  annual_target: number;
  fiscal_year: number;
  unit_id: number | null;
  officer_id: number | null;
  achieved_ytd: number;
  is_active: boolean;
  last_sync_at: string | null;
  created_at: string;
}

export function useKpiTargets(params?: { fiscal_year?: number; is_active?: boolean }) {
  return useQuery<KpiTargetItem[], AxiosError<ApiError>>({
    queryKey: kpiSetupKeys.targetList(params || {}),
    queryFn: async () => {
      const res = await api.get<KpiTargetItem[]>("/api/admin/kpi-config/targets", { params });
      return res.data;
    },
    staleTime: 2 * 60 * 1000,
  });
}

export function useCreateKpiTarget() {
  const qc = useQueryClient();

  return useMutation<unknown, AxiosError<ApiError>, CreateKpiTargetInput>({
    mutationFn: async (data) => {
      const res = await api.post("/api/admin/kpi-config/targets", data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã gán chỉ tiêu KPI");
      qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
      qc.invalidateQueries({ queryKey: ["kpi-targets"] });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi gán chỉ tiêu");
    },
  });
}

export function useUpdateKpiTarget() {
  const qc = useQueryClient();

  return useMutation<unknown, AxiosError<ApiError>, UpdateKpiTargetInput>({
    mutationFn: async ({ id, data }) => {
      const res = await api.put(`/api/admin/kpi-config/targets/${id}`, data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã cập nhật chỉ tiêu KPI");
      qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
      qc.invalidateQueries({ queryKey: ["kpi-targets"] });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi cập nhật chỉ tiêu");
    },
  });
}

export function useKpiConfigs(params?: { kpi_code?: string; unit_id?: number; is_active?: boolean }) {
  return useQuery<KpiConfigItem[], AxiosError<ApiError>>({
    queryKey: kpiSetupKeys.configList(params || {}),
    queryFn: async () => {
      const res = await api.get<KpiConfigItem[]>("/api/admin/kpi-config/configs", { params });
      return res.data;
    },
    staleTime: 2 * 60 * 1000,
  });
}

export function useCreateKpiConfig() {
  const qc = useQueryClient();

  return useMutation<KpiConfigItem, AxiosError<ApiError>, KpiConfigCreate>({
    mutationFn: async (data) => {
      const res = await api.post("/api/admin/kpi-config/configs", data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã tạo cấu hình KPI");
      qc.invalidateQueries({ queryKey: kpiSetupKeys.configs() });
      qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi tạo cấu hình KPI");
    },
  });
}

export function useUpdateKpiConfig() {
  const qc = useQueryClient();

  return useMutation<KpiConfigItem, AxiosError<ApiError>, { id: number; data: KpiConfigUpdate }>({
    mutationFn: async ({ id, data }) => {
      const res = await api.put(`/api/admin/kpi-config/configs/${id}`, data);
      return res.data;
    },
    onSuccess: () => {
      toast.success("Đã cập nhật cấu hình KPI");
      qc.invalidateQueries({ queryKey: kpiSetupKeys.configs() });
      qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi cập nhật cấu hình KPI");
    },
  });
}

export function useDeleteKpiConfig() {
  const qc = useQueryClient();

  return useMutation<void, AxiosError<ApiError>, number>({
    mutationFn: async (id) => {
      await api.delete(`/api/admin/kpi-config/configs/${id}`);
    },
    onSuccess: () => {
      toast.success("Đã xóa cấu hình KPI");
      qc.invalidateQueries({ queryKey: kpiSetupKeys.configs() });
      qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi xóa cấu hình KPI");
    },
  });
}
