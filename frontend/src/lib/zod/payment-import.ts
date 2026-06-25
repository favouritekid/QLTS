/**
 * Zod schemas + types cho Import file thu học phí hàng loạt (BV-4).
 *
 * Mirror CHÍNH XÁC backend `app/schemas/finance.py` (PaymentImport*).
 * Decimal → JSON string (như các schema finance khác). status để z.string()
 * (xử lý unknown qua config map default — CLAUDE.md rule 3).
 *
 * @see Backend_FastAPI/app/schemas/finance.py
 * @see Backend_FastAPI/app/routers/payments.py (5 route import)
 */
import { z } from "zod"

import { formatVND } from "@/lib/zod/finance"

/** Format tiền an toàn: null/rỗng/non-numeric → "—" (tránh "NaN ₫"). */
export function formatAmount(amount?: string | null): string {
  if (amount == null || amount === "" || Number.isNaN(Number(amount))) return "—"
  return formatVND(amount)
}

// ============================================================================
// RESPONSE SCHEMAS (mirror backend)
// ============================================================================
export const paymentImportAllocationSchema = z.object({
  invoice_id: z.number().int(),
  installment_no: z.number().int(),
  amount: z.string(),
})
export type PaymentImportAllocation = z.infer<typeof paymentImportAllocationSchema>

export const paymentImportRowSchema = z.object({
  row_no: z.number().int(),
  status: z.string(), // matched | warned | error
  message: z.string().nullable().optional(),
  citizen_id: z.string().nullable().optional(),
  profile_id: z.number().int().nullable().optional(),
  fee_id: z.number().int().nullable().optional(),
  amount: z.string().nullable().optional(),
  method_code: z.string().nullable().optional(),
  payment_date: z.string().nullable().optional(),
  reference: z.string().nullable().optional(),
  allocations: z.array(paymentImportAllocationSchema).default([]),
  payment_ids: z.array(z.number().int()).nullable().optional(),
})
export type PaymentImportRow = z.infer<typeof paymentImportRowSchema>

export const paymentImportPreviewSchema = z.object({
  batch_id: z.number().int(),
  academic_year: z.number().int(),
  semester_no: z.number().int(),
  file_name: z.string(),
  status: z.string(),
  row_count: z.number().int(),
  matched_count: z.number().int(),
  warned_count: z.number().int(),
  failed_count: z.number().int(),
  total_amount: z.string(),
  rows: z.array(paymentImportRowSchema).default([]),
})
export type PaymentImportPreview = z.infer<typeof paymentImportPreviewSchema>

export const paymentImportCommitSchema = z.object({
  batch_id: z.number().int(),
  status: z.string(),
  committed_count: z.number().int(),
  failed_count: z.number().int(),
  payment_count: z.number().int(),
  total_amount: z.string(),
  rows: z.array(paymentImportRowSchema).default([]),
})
export type PaymentImportCommit = z.infer<typeof paymentImportCommitSchema>

export const paymentImportVoidSchema = z.object({
  batch_id: z.number().int(),
  status: z.string(),
  reversed_count: z.number().int(),
  reversed_amount: z.string(),
  void_reason: z.string().nullable().optional(),
})
export type PaymentImportVoidResult = z.infer<typeof paymentImportVoidSchema>

export const paymentImportBatchSummarySchema = z.object({
  id: z.number().int(),
  academic_year: z.number().int(),
  semester_no: z.number().int(),
  file_name: z.string(),
  status: z.string(), // preview | committed | void
  row_count: z.number().int(),
  matched_count: z.number().int(),
  warned_count: z.number().int(),
  failed_count: z.number().int(),
  total_amount: z.string(),
  created_at: z.string(),
  committed_at: z.string().nullable().optional(),
  voided_at: z.string().nullable().optional(),
  // BE quyết quyền đảo lô của người xem (thin-client: FE đọc flag, không check role)
  can_void: z.boolean().default(false),
})
export type PaymentImportBatchSummary = z.infer<
  typeof paymentImportBatchSummarySchema
>

export const paymentImportBatchListSchema = z.object({
  items: z.array(paymentImportBatchSummarySchema).default([]),
  total: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
})
export type PaymentImportBatchList = z.infer<typeof paymentImportBatchListSchema>

// ============================================================================
// FORM SCHEMAS (local)
// ============================================================================
// Lưu ý: KHÔNG dùng `invalid_type_error` (API Zod v3, bị Zod v4 bỏ qua → message
// chết). Đặt message ở .int()/.min()/.max(); giá trị rỗng/NaN/thập phân đều rơi vào
// 1 trong các check này nên luôn ra message tiếng Việt.
export const paymentImportPreviewFormSchema = z.object({
  academic_year: z.coerce
    .number()
    .int("Năm học phải là số nguyên")
    .min(2020, "Năm học từ 2020")
    .max(2100, "Năm học đến 2100"),
  semester_no: z.coerce
    .number()
    .int("Học kỳ phải là số nguyên")
    .min(1, "Học kỳ từ 1")
    .max(12, "Học kỳ đến 12"),
})
export type PaymentImportPreviewForm = z.infer<
  typeof paymentImportPreviewFormSchema
>

export const paymentImportVoidFormSchema = z.object({
  reason: z
    .string()
    .trim()
    .min(3, "Lý do đảo lô tối thiểu 3 ký tự")
    .max(500, "Lý do tối đa 500 ký tự"),
})
export type PaymentImportVoidForm = z.infer<typeof paymentImportVoidFormSchema>

// ============================================================================
// STATUS CONFIG (badge) — handle unknown qua fallback ở component
// ============================================================================
export const ROW_STATUS_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  matched: {
    label: "Khớp",
    className: "border-green-200 bg-green-100 text-green-800",
  },
  warned: {
    label: "Cảnh báo",
    className: "border-amber-200 bg-amber-100 text-amber-800",
  },
  error: {
    label: "Lỗi",
    className: "border-red-200 bg-red-100 text-red-800",
  },
}

export const BATCH_STATUS_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  preview: {
    label: "Xem trước",
    className: "border-blue-200 bg-blue-100 text-blue-800",
  },
  committed: {
    label: "Đã ghi tiền",
    className: "border-green-200 bg-green-100 text-green-800",
  },
  void: {
    label: "Đã đảo",
    className: "border-gray-200 bg-gray-100 text-gray-700",
  },
}
