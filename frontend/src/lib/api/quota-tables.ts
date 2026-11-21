/**
 * GĐ2-A / GĐ2-F1 — API bảng chỉ tiêu năm / nhóm ngành. Chỉ Admin (máy chủ là chốt: Casbin + `require_quota_table_admin`).
 *
 *   GET  /api/admission-config/quota-tables/{năm}          — 404 khi năm chưa có bảng
 *   PUT  /api/admission-config/quota-tables/{năm}          — thay TOÀN BỘ nội dung; `version` 0 = tạo mới
 *   POST /api/admission-config/quota-tables/{năm}/lock     — `{version}`
 *   POST /api/admission-config/quota-tables/{năm}/unlock   — `{version, reason}` (lý do bắt buộc)
 */
import { api } from "@/lib/api/client"
import type { QuotaTableLock, QuotaTableOut, QuotaTablePut, QuotaTableUnlock } from "@/lib/zod/quota-tables"

const base = (year: number) => `/api/admission-config/quota-tables/${year}`

export const quotaTablesApi = {
  async get(year: number): Promise<QuotaTableOut> {
    const { data } = await api.get<QuotaTableOut>(base(year))
    return data
  },
  async put(year: number, body: QuotaTablePut): Promise<QuotaTableOut> {
    const { data } = await api.put<QuotaTableOut>(base(year), body)
    return data
  },
  async lock(year: number, body: QuotaTableLock): Promise<QuotaTableOut> {
    const { data } = await api.post<QuotaTableOut>(`${base(year)}/lock`, body)
    return data
  },
  async unlock(year: number, body: QuotaTableUnlock): Promise<QuotaTableOut> {
    const { data } = await api.post<QuotaTableOut>(`${base(year)}/unlock`, body)
    return data
  },
}
