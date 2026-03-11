// hooks/useKpiSetup.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { CoverageReport } from "@/types/kpi-setup.types";

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
