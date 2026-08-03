import { useMutation, useQuery } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { financeReportsApi } from "@/lib/api/finance-reports"
import { blobErrorMessage, downloadBlob } from "@/lib/utils/download-blob"
import type { ApiErrorResponse } from "@/types/api.types"
import type { DebtReportFilters, DebtReportResponse } from "@/types/finance.types"

export const debtReportKeys = {
  all: ["finance", "debt-report"] as const,
  detail: (filters?: DebtReportFilters) => [...debtReportKeys.all, filters] as const,
}

export function useDebtReport(filters?: DebtReportFilters, options?: { enabled?: boolean }) {
  return useQuery<DebtReportResponse, AxiosError<ApiErrorResponse>>({
    queryKey: debtReportKeys.detail(filters),
    queryFn: () => financeReportsApi.getDebtReport(filters),
    enabled: options?.enabled ?? true,
    staleTime: 1000 * 30,
  })
}

/**
 * Xuất báo cáo công nợ.
 *
 * ⚠️ Lỗi PHẢI đọc qua `blobErrorMessage`: `responseType:'blob'` khiến axios bọc
 * body lỗi JSON thành Blob, dùng thẳng `data.detail` sẽ luôn ra undefined.
 */
export function useDebtReportExport() {
  return useMutation<
    { blob: Blob; filename: string },
    AxiosError<ApiErrorResponse>,
    { format: "xlsx" | "csv"; filters?: DebtReportFilters }
  >({
    mutationFn: ({ format, filters }) =>
      financeReportsApi.exportDebtReport(format, filters),
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename)
      toast.success("Đã tải báo cáo công nợ")
    },
    onError: async (error) =>
      toast.error(
        await blobErrorMessage(error, "Không xuất được báo cáo công nợ"),
      ),
  })
}
