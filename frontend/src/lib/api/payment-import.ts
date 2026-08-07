/**
 * Payment Import API client (BV-4) — import file thu học phí hàng loạt.
 *
 * 5 route (Backend_FastAPI/app/routers/payments.py):
 *   GET  /import/template?format=xlsx|csv   → tải file mẫu (blob)
 *   POST /import/preview (multipart)         → dry-run 3 nhóm matched/warned/error
 *   POST /import/{id}/commit                 → ghi tiền (auto-verify)
 *   POST /import/{id}/void {reason}          → đảo lô (manager/admin)
 *   GET  /import/batches                     → lịch sử lô (phân trang)
 *
 * Response parse qua Zod (mirror backend) → bắt drift contract sớm.
 */
import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import {
  paymentImportBatchDetailSchema,
  paymentImportBatchListSchema,
  paymentImportCommitSchema,
  paymentImportPreviewSchema,
  paymentImportVoidSchema,
  type PaymentImportBatchDetail,
  type PaymentImportBatchList,
  type PaymentImportCommit,
  type PaymentImportPreview,
  type PaymentImportVoidResult,
} from "@/lib/zod/payment-import"

const IMPORT = API_ENDPOINTS.FINANCE.PAYMENTS.IMPORT

/** Tải file mẫu import (xlsx khuyến nghị / csv). Trả Blob để trigger download. */
async function downloadTemplate(format: "xlsx" | "csv"): Promise<Blob> {
  const res = await api.get<Blob>(`${IMPORT.TEMPLATE}?format=${format}`, {
    responseType: "blob",
  })
  return res.data
}

/** Pha 1: xem trước (dry-run) — KHÔNG ghi tiền. multipart file + năm + kỳ. */
async function preview(params: {
  file: File
  academicYear: number
  semesterNo: number
}): Promise<PaymentImportPreview> {
  const form = new FormData()
  form.append("file", params.file)
  form.append("academic_year", String(params.academicYear))
  form.append("semester_no", String(params.semesterNo))
  const res = await api.post(IMPORT.PREVIEW, form)
  return paymentImportPreviewSchema.parse(res.data)
}

/**
 * Pha 2: ghi tiền (auto-verify) các dòng MATCHED/WARNING của lô.
 *
 * `confirmedRows` là những dòng kế toán đã soát, MỖI dòng kèm đúng phiếu mà
 * lượt commit trước trả về cho nó. Không còn cờ "bỏ qua cho TOÀN LÔ": một cờ
 * như vậy bỏ qua cả những cảnh báo sinh ra SAU khi kế toán soát, và nó không
 * nói được người bấm đã nhìn thấy gì.
 */
async function commit(
  batchId: number,
  confirmedRows?: Array<{ row_no: number; review_token: string }>,
): Promise<PaymentImportCommit> {
  const res = await api.post(
    IMPORT.COMMIT(batchId),
    confirmedRows?.length ? { confirmed_rows: confirmedRows } : undefined,
  )
  return paymentImportCommitSchema.parse(res.data)
}

/** Đảo (void) lô đã ghi tiền — rút lại toàn bộ Payment. Gate manager/admin. */
async function voidBatch(
  batchId: number,
  reason: string,
): Promise<PaymentImportVoidResult> {
  const res = await api.post(IMPORT.VOID(batchId), { reason })
  return paymentImportVoidSchema.parse(res.data)
}

/** Lịch sử lô import (mới nhất trước), phân trang. */
async function listBatches(
  page: number,
  pageSize: number,
): Promise<PaymentImportBatchList> {
  const res = await api.get(IMPORT.BATCHES, {
    params: { page, page_size: pageSize },
  })
  return paymentImportBatchListSchema.parse(res.data)
}

/** BV-5 R2: chi tiết 1 lô + per-row (xem lại sau commit). */
async function getBatchDetail(
  batchId: number,
): Promise<PaymentImportBatchDetail> {
  const res = await api.get(IMPORT.BATCH_DETAIL(batchId))
  return paymentImportBatchDetailSchema.parse(res.data)
}

/** BV-5 R1: tải file kết quả (nguyên dòng gốc + cột Trạng thái/Lý do). Trả Blob. */
async function downloadResult(
  batchId: number,
  format: "xlsx" | "csv",
): Promise<Blob> {
  const res = await api.get<Blob>(IMPORT.RESULT(batchId), {
    params: { format },
    responseType: "blob",
  })
  return res.data
}

export const paymentImportApi = {
  downloadTemplate,
  preview,
  commit,
  voidBatch,
  listBatches,
  getBatchDetail,
  downloadResult,
}
