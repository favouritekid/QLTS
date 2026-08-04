import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import { debtReportResponseSchema } from "@/lib/zod/finance"
import { filenameFromDisposition } from "@/lib/utils/download-blob"
import type { DebtReportFilters, DebtReportResponse } from "@/types/finance.types"

export async function getDebtReport(filters?: DebtReportFilters): Promise<DebtReportResponse> {
  const response = await api.get<DebtReportResponse>(API_ENDPOINTS.FINANCE.DEBT_REPORT, {
    params: filters,
  })
  // Runtime-validate the contract (throws on drift) instead of trusting the cast.
  return debtReportResponseSchema.parse(response.data) as DebtReportResponse
}

/**
 * Xuất báo cáo công nợ ra tệp (server-side).
 *
 * Trước đây CSV được dựng ở TRÌNH DUYỆT từ dữ liệu đã tải: header là khoá kỹ
 * thuật tiếng Anh, không BOM (Excel tiếng Việt mojibake), ô tiền bọc thành
 * chuỗi nên không cộng được, tên tệp cố định nên xuất nhiều lần đè lên nhau.
 */
export async function exportDebtReport(
  format: "xlsx" | "csv",
  filters?: DebtReportFilters,
): Promise<{ blob: Blob; filename: string }> {
  const response = await api.get<Blob>(API_ENDPOINTS.FINANCE.DEBT_REPORT_EXPORT, {
    params: { ...filters, format },
    responseType: "blob",
  })
  return {
    blob: response.data,
    filename: filenameFromDisposition(
      response.headers["content-disposition"],
      `bao_cao_cong_no.${format}`,
    ),
  }
}

export const financeReportsApi = {
  getDebtReport,
  exportDebtReport,
}
