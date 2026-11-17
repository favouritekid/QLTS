/**
 * GĐ1b — API client lô duyệt giấy (hợp đồng bản 4 §2.1) và lô duyệt chéo (§2.2 — cùng khuôn, tiền tố riêng, thân xem
 * trước có `grant_id`). Mọi phản hồi qua Zod.
 *
 * ⚠️ `execute` KHÔNG BAO GIỜ được gọi lại tự động: hàm này không thử lại, hook đặt `retry: false`; mất phản hồi ⇒
 * giao diện TRA lô bằng `GET` (§5.9). Thân `execute` không mang danh sách — máy chủ chạy đúng danh sách đã lưu lúc
 * xem trước.
 */
import { api } from "@/lib/api/client"
import {
  batchListSchema,
  batchViewSchema,
  bulkPreviewSchema,
  bulkVerifyPreviewBodySchema,
  crossBulkVerifyPreviewBodySchema,
  executeBatchBodySchema,
  finalizeBatchBodySchema,
  finalizeBatchResponseSchema,
  type BatchList,
  type BatchListScope,
  type BatchView,
  type BulkPreview,
  type BulkVerifyFilter,
  type FinalizeBatchResponse,
} from "@/lib/zod/document-review"

export const BULK_VERIFY_PREFIX = "/api/admissions/documents/bulk-verify"
export const CROSS_BULK_VERIFY_PREFIX = "/api/admissions/cross-review/bulk-verify"

/**
 * Đường lô: Quản lý / Admin (`batch`) hoặc cán bộ có quyền chéo (`cross`). `grantId` (= `grant_id_by_action.verify`)
 * CHỈ cần cho bước xem trước của lô chéo; tra / chạy / chốt / danh sách theo mã lô, máy chủ kiểm người tạo.
 */
export type BulkEndpoint = { mode: "batch" } | { mode: "cross"; grantId?: number }

export function bulkPrefix(endpoint: BulkEndpoint): string {
  return endpoint.mode === "cross" ? CROSS_BULK_VERIFY_PREFIX : BULK_VERIFY_PREFIX
}

/** Chọn hồ sơ cho lô: theo bộ lọc của danh sách (máy chủ chọn — §5.9) hoặc theo id (vd "Xác nhận kiểm tra" một hồ sơ). */
export type BulkSelection =
  | { kind: "filter"; filter: BulkVerifyFilter }
  | { kind: "profiles"; profileIds: number[] }

export async function previewBulkVerify(
  endpoint: BulkEndpoint,
  selection: BulkSelection,
  includeOptional: boolean,
): Promise<BulkPreview> {
  let body: unknown
  if (endpoint.mode === "cross") {
    if (selection.kind !== "profiles") {
      throw new Error("Lô duyệt chéo chỉ nhận danh sách hồ sơ")
    }
    if (endpoint.grantId === undefined) {
      throw new Error("Lô duyệt chéo cần quyền duyệt (grant_id_by_action.verify)")
    }
    body = crossBulkVerifyPreviewBodySchema.parse({
      profile_ids: selection.profileIds,
      include_optional: includeOptional,
      grant_id: endpoint.grantId,
    })
  } else {
    body = bulkVerifyPreviewBodySchema.parse(
      selection.kind === "filter"
        ? { filter: selection.filter, include_optional: includeOptional }
        : { profile_ids: selection.profileIds, include_optional: includeOptional },
    )
  }
  const res = await api.post(`${bulkPrefix(endpoint)}/preview`, body)
  return bulkPreviewSchema.parse(res.data)
}

/** Chạy lô đã xem trước — gọi ĐÚNG MỘT LẦN mỗi lần người dùng bấm. */
export async function executeBatch(
  endpoint: BulkEndpoint,
  batchId: string,
  confirmationText: string,
): Promise<BatchView> {
  const body = executeBatchBodySchema.parse({ confirmation_text: confirmationText })
  const res = await api.post(`${bulkPrefix(endpoint)}/${encodeURIComponent(batchId)}/execute`, body)
  return batchViewSchema.parse(res.data)
}

/** Tra một lô (chỉ đọc). */
export async function getBatch(endpoint: BulkEndpoint, batchId: string): Promise<BatchView> {
  const res = await api.get(`${bulkPrefix(endpoint)}/${encodeURIComponent(batchId)}`)
  return batchViewSchema.parse(res.data)
}

/** Chốt lô gián đoạn — `reason` bắt buộc khi Admin chốt lô của người khác (máy chủ trả 422 nếu thiếu). */
export async function finalizeBatch(
  endpoint: BulkEndpoint,
  batchId: string,
  reason?: string,
): Promise<FinalizeBatchResponse> {
  const trimmed = reason?.trim()
  const body = finalizeBatchBodySchema.parse(trimmed ? { reason: trimmed } : {})
  const res = await api.post(`${bulkPrefix(endpoint)}/${encodeURIComponent(batchId)}/finalize`, body)
  return finalizeBatchResponseSchema.parse(res.data)
}

/** Danh sách lô (cửa sổ hiển thị 30 ngày, 20 / trang, con trỏ). `scope=all` chỉ Admin. */
export async function listBatches(
  endpoint: BulkEndpoint,
  scope: BatchListScope,
  cursor?: string | null,
): Promise<BatchList> {
  const params: Record<string, string | number> = { scope, limit: 20 }
  if (cursor) params.cursor = cursor
  const res = await api.get(bulkPrefix(endpoint), { params })
  return batchListSchema.parse(res.data)
}
