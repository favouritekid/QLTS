/**
 * Xuất danh sách học phí (PR-A / H1).
 *
 * @see Backend_FastAPI/app/services/tuition_export_service.py
 */
import { useMutation } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"

import { invoicesApi } from "@/lib/api/invoices"
import { blobErrorMessage, downloadBlob } from "@/lib/utils/download-blob"
import type { ApiErrorResponse } from "@/types/api.types"
import type { InvoiceExportFilters } from "@/types/finance.types"

interface ExportVariables {
  format: "xlsx" | "csv"
  filters: InvoiceExportFilters
}

/**
 * Tải file danh sách học phí theo bộ lọc đang xem.
 *
 * ⚠️ Lỗi PHẢI đọc qua `blobErrorMessage`: vì `responseType:'blob'`, axios bọc
 * body lỗi JSON thành Blob nên `error.response.data.detail` luôn undefined —
 * dùng thẳng sẽ nuốt mất câu "kết quả lọc vượt quá N dòng, hãy thu hẹp bộ lọc"
 * và người dùng chỉ thấy thông báo chung chung.
 */
export function useTuitionExport() {
  return useMutation<
    { blob: Blob; filename: string },
    AxiosError<ApiErrorResponse>,
    ExportVariables
  >({
    mutationFn: ({ format, filters }) =>
      invoicesApi.exportTuitionList(format, filters),
    onSuccess: ({ blob, filename }) => {
      // filename lấy từ Content-Disposition (backend gắn mốc thời gian) nên
      // xuất nhiều lần không đè lên nhau.
      downloadBlob(blob, filename)
      toast.success("Đã tải danh sách học phí")
    },
    onError: async (error) =>
      toast.error(
        await blobErrorMessage(error, "Không xuất được danh sách học phí"),
      ),
  })
}

export default useTuitionExport
