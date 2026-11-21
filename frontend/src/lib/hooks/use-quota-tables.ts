/**
 * GĐ2-F1 — React Query cho bảng chỉ tiêu năm. Thành công ⇒ ghi thẳng phản hồi vào cache (máy chủ trả bảng mới); lỗi ⇒ làm
 * mới bảng (vd 409 `quota_table_stale`: người khác vừa sửa / khoá — cờ `available_actions` có thể đã đổi).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { quotaTablesApi } from "@/lib/api/quota-tables"
import type { QuotaTableLock, QuotaTableOut, QuotaTablePut, QuotaTableUnlock } from "@/lib/zod/quota-tables"

export const quotaTableKeys = {
  all: ["quota-tables"] as const,
  detail: (year: number) => ["quota-tables", year] as const,
}

export function useQuotaTable(year: number) {
  return useQuery<QuotaTableOut>({
    queryKey: quotaTableKeys.detail(year),
    queryFn: () => quotaTablesApi.get(year),
    // 404 = năm chưa có bảng (trạng thái hợp lệ), 403 = không phải Admin: không thử lại.
    retry: false,
  })
}

function useQuotaTableMutation<TBody>(year: number, call: (year: number, body: TBody) => Promise<QuotaTableOut>) {
  const queryClient = useQueryClient()
  return useMutation<QuotaTableOut, Error, TBody>({
    mutationFn: (body) => call(year, body),
    onSuccess: (table) => {
      queryClient.setQueryData(quotaTableKeys.detail(year), table)
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: quotaTableKeys.detail(year) })
    },
  })
}

export function useSaveQuotaTable(year: number) {
  return useQuotaTableMutation<QuotaTablePut>(year, quotaTablesApi.put)
}

export function useLockQuotaTable(year: number) {
  return useQuotaTableMutation<QuotaTableLock>(year, quotaTablesApi.lock)
}

export function useUnlockQuotaTable(year: number) {
  return useQuotaTableMutation<QuotaTableUnlock>(year, quotaTablesApi.unlock)
}
