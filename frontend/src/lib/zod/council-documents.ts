/**
 * Văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1) — Zod mirror của
 * `Backend_FastAPI/app/schemas/council_document.py` (+ `DecisionParams` của
 * `app/services/council_document_render_service.py`).
 *
 * Phản hồi: `z.object` KHÔNG strict (máy chủ chỉ THÊM trường, không bớt —
 * FRONTEND_ARCHITECTURE_V3 §0.6); trường bắt buộc thiếu / sai kiểu ⇒ parse NỔ.
 * Yêu cầu: `.strict()` như `extra="forbid"` của Pydantic. Chỉ kiểm ĐỊNH DẠNG
 * (thin validation §2.5) — luật mã hồ sơ (9 / 12 chữ số, trùng, khớp hồ sơ),
 * cặp đợt / tháng, thứ tự ngày… do máy chủ quyết và báo lỗi.
 *
 * ⚠️ DỮ LIỆU CÁ NHÂN: `ma_ho_so` (danh sách CCCD) — chỉ trong bộ nhớ, không
 * storage / console / URL (xem `src/hooks/admin/useCouncilDocuments.ts`).
 */
import { z } from "zod"

// ── cờ quyền giao diện (GET /quyen) ──────────────────────────────────────────
export const councilDocumentPermissionsSchema = z.object({
  xem_mau: z.boolean(),
  tai_mau_len: z.boolean(),
  xem_danh_sach_bo: z.boolean(),
  tao_bo: z.boolean(),
  xem_chi_tiet_bo: z.boolean(),
  tai_tep: z.boolean(),
  xoa_bo: z.boolean(),
  xem_ma_ho_so: z.boolean(),
  xem_nhat_ky_tai: z.boolean(),
  xem_nhat_ky_xoa: z.boolean(),
})
export type CouncilDocumentPermissions = z.infer<
  typeof councilDocumentPermissionsSchema
>
export type CouncilDocumentPermissionKey = keyof CouncilDocumentPermissions

export const councilDocumentPermissionsOutSchema = z.object({
  permissions: councilDocumentPermissionsSchema,
})

// ── kho mẫu ──────────────────────────────────────────────────────────────────
/** Loại mẫu máy chủ nhận (`kho_mau.LOAI_MAU`). Hiển thị: loại lạ ⇒ in nguyên. */
export const COUNCIL_TEMPLATE_KINDS = ["bien_ban", "quyet_dinh", "danh_sach"] as const
export type CouncilTemplateKind = (typeof COUNCIL_TEMPLATE_KINDS)[number]

export const councilTemplateSchema = z.object({
  id: z.number().int(),
  loai: z.string(),
  hieu_luc_tu: z.string(),
  sha256: z.string(),
  kich_thuoc: z.number().int(),
  nguoi_tai_id: z.number().int().nullable(),
  tai_luc: z.string(),
  ghi_chu: z.string().nullable(),
})
export type CouncilTemplate = z.infer<typeof councilTemplateSchema>
export const councilTemplateListSchema = z.array(councilTemplateSchema)

// ── bộ văn bản ───────────────────────────────────────────────────────────────
export const councilSetSchema = z.object({
  id: z.number().int(),
  nguoi_tao_id: z.number().int().nullable(),
  tao_luc: z.string(),
  moc_chup: z.string(),
  unit_id: z.number().int().nullable(),
  trinh_do: z.string(),
  so_ho_so: z.number().int(),
  so_tep: z.number().int(),
  kich_thuoc_tong: z.number().int(),
  nam_hoc: z.number().int().nullable(),
  tham_so_quyet_dinh: z.record(z.string(), z.unknown()).nullable(),
})
export type CouncilSet = z.infer<typeof councilSetSchema>
export const councilSetListSchema = z.array(councilSetSchema)

export const councilSetFileSchema = z.object({
  thu_tu: z.number().int(),
  path: z.string(),
  sha256: z.string(),
  kich_thuoc: z.number().int(),
})
export type CouncilSetFile = z.infer<typeof councilSetFileSchema>

export const councilSetDetailSchema = councilSetSchema.extend({
  thong_tin_dung: z.record(z.string(), z.unknown()),
  tep: z.array(councilSetFileSchema),
})
export type CouncilSetDetail = z.infer<typeof councilSetDetailSchema>

/** Danh sách mã đầu vào (CHỈ admin) — DỮ LIỆU CÁ NHÂN. */
export const councilSetInputCodesSchema = z.object({
  set_id: z.number().int(),
  so_ho_so: z.number().int(),
  ma_ho_so: z.array(z.string()),
})
export type CouncilSetInputCodes = z.infer<typeof councilSetInputCodesSchema>

export const councilSetDeletionSchema = z.object({
  id: z.number().int(),
  set_id: z.number().int(),
  so_ho_so: z.number().int(),
  so_tep: z.number().int(),
  danh_sach_tep: z.array(z.record(z.string(), z.unknown())),
  nguoi_xoa_id: z.number().int(),
  xoa_luc: z.string(),
  ly_do: z.string(),
})
export type CouncilSetDeletion = z.infer<typeof councilSetDeletionSchema>
export const councilSetDeletionListSchema = z.array(councilSetDeletionSchema)

export const councilDownloadLogSchema = z.object({
  id: z.number().int(),
  set_id: z.number().int(),
  thu_tu: z.number().int(),
  path: z.string(),
  sha256: z.string(),
  nguoi_tai_id: z.number().int(),
  tai_luc: z.string(),
})
export type CouncilDownloadLog = z.infer<typeof councilDownloadLogSchema>
export const councilDownloadLogListSchema = z.array(councilDownloadLogSchema)

// ── yêu cầu ──────────────────────────────────────────────────────────────────
const ngayIso = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Ngày dạng YYYY-MM-DD")

/** `DecisionParams` (extra="forbid"): mọi trường tuỳ chọn, vắng thì chỗ ấy để trống. */
export const decisionParamsSchema = z
  .object({
    so_quyet_dinh: z.string().regex(/^[0-9]{1,6}$/, "1–6 chữ số").nullable().optional(),
    ngay_quyet_dinh: ngayIso.nullable().optional(),
    dot_so: z.string().regex(/^[0-9]{1,2}$/, "1–2 chữ số").nullable().optional(),
    dot_thang: z.number().int().min(1).max(12).nullable().optional(),
    so_bien_ban: z.string().regex(/^[0-9]{1,6}$/, "1–6 chữ số").nullable().optional(),
    ngay_bien_ban: ngayIso.nullable().optional(),
  })
  .strict()
export type DecisionParams = z.infer<typeof decisionParamsSchema>

/** `CouncilSetCreate` (extra="forbid") — `ma_ho_so` GIỮ thứ tự người nhập.
 * `xac_nhan_trang_thai` (lượt G): admin xác nhận ĐÚNG số hồ sơ theo trạng thái máy chủ vừa báo
 * (409) — giao diện chỉ gửi lại nguyên số đếm của máy chủ, máy chủ kiểm. */
export const councilSetCreateSchema = z
  .object({
    ma_ho_so: z.array(z.string()).min(1),
    academic_year: z.number().int(),
    tham_so_quyet_dinh: decisionParamsSchema.nullable().optional(),
    xac_nhan_trang_thai: z.record(z.string(), z.number().int().min(1)).nullable().optional(),
  })
  .strict()
export type CouncilSetCreate = z.infer<typeof councilSetCreateSchema>

// ── cổng dựng bộ (lượt G — 400 chặn / 409 cần xác nhận): `kiem_tra_dung_bo` của thân lỗi ──
/** Một lý do chặn: mã, câu của máy chủ, trạng thái (nếu là lý do trạng thái), SỐ DÒNG (đếm từ 1).
 * Không có mã hồ sơ — chỉ số dòng của ô nhập. */
export const councilSetGateItemSchema = z.object({
  ma: z.string(),
  mo_ta: z.string(),
  trang_thai: z.string().nullable(),
  so_ho_so: z.number().int(),
  dong: z.array(z.number().int()),
})
export type CouncilSetGateItem = z.infer<typeof councilSetGateItemSchema>

export const councilSetGateSchema = z.object({
  muc: z.string(),
  so_dong: z.number().int(),
  chan: z.array(councilSetGateItemSchema),
  canh_bao: z.object({
    so_ho_so_theo_trang_thai: z.record(z.string(), z.number().int()),
    dong_theo_trang_thai: z.record(z.string(), z.array(z.number().int())),
  }),
  can_admin_xac_nhan: z.boolean(),
  nguoi_goi_duoc_xac_nhan: z.boolean(),
})
export type CouncilSetGate = z.infer<typeof councilSetGateSchema>

/** `CouncilSetDelete` (extra="forbid") — lý do BẮT BUỘC (máy chủ kiểm rỗng / trần). */
export const councilSetDeleteSchema = z.object({ ly_do: z.string() }).strict()
export type CouncilSetDelete = z.infer<typeof councilSetDeleteSchema>
