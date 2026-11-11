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
  // Lượt I (F230) — ghi nhận Quyết định đã ký (CHỈ admin). Máy chủ đã trả từ `bfba3a2e`.
  ghi_nhan_qd: z.boolean(),
  xem_danh_sach_qd: z.boolean(),
  xem_chi_tiet_qd: z.boolean(),
  tai_scan_qd: z.boolean(),
  huy_ghi_nhan_qd: z.boolean(),
  huy_hieu_luc_qd: z.boolean(),
  tao_bo_dieu_chinh: z.boolean(),
  ghi_nhan_dieu_chinh: z.boolean(),
  dung_lai_ban_ky: z.boolean(),
  so_bo_voi_hien_tai: z.boolean(),
  xem_nhom_cho: z.boolean(),
  cho_xet_lai: z.boolean(),
  xem_su_kien: z.boolean(),
  // Vòng giao diện — lượt gửi ghi nhận (đặc tả bản 2 mục 3.7). Máy chủ đã trả từ `dd6c725d`.
  mo_luot_gui: z.boolean(),
  xem_luot_gui: z.boolean(),
  phan_xu_luot_gui: z.boolean(),
  // ⏳ CHỜ MÁY CHỦ (đặc tả 3.10): máy chủ CHƯA trả hai cờ này ở `dd6c725d`. Thiếu ⇒ `false` (tắt tính năng —
  // fail-closed), KHÔNG làm vỡ cả trang quyền. Khi máy chủ đã trả: bỏ `.default(false)` (bắt buộc như các cờ trên) và
  // xoá tên khỏi `CO_CHO_MAY_CHU` — test `council-documents.test.ts` nhắc việc này.
  kiem_truoc: z.boolean().default(false),
  tai_ca_bo: z.boolean().default(false),
})
/** Cờ giao diện CHƯA có ở máy chủ (đang `.default(false)`). Rỗng khi máy chủ đã giao đủ. */
export const CO_CHO_MAY_CHU = ["kiem_truoc", "tai_ca_bo"] as const
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
  // ⏳ CHỜ MÁY CHỦ (đặc tả 3.4): các trường dưới CHƯA có ở `GET /sets` @dd6c725d ⇒ tuỳ chọn; khi máy chủ đã
  // trả thì bỏ `.optional()`. Giao diện KHÔNG suy tình trạng từ chỗ khác — vắng ⇒ không hiện cột/nhãn ấy.
  nguoi_tao_ten: z.string().nullable().optional(),
  /** `chua_ghi_nhan` | `con_hieu_luc` | `het_hieu_luc` | `da_huy_ghi_nhan` | `chua_xac_dinh` — máy chủ tính; lạ ⇒ in nguyên. */
  tinh_trang: z.string().optional(),
  luot_gui_cho: z.object({ ma: z.string(), tao_luc: z.string() }).nullable().optional(),
  // `quyet_dinh`: ở chi tiết bộ máy chủ ĐÃ trả một dict (loai, trang_thai, so_quyet_dinh, ngay_ky, so_ho_so —
  // `tom_tat_qd_cua_bo`); đặc tả 3.4/3.5 muốn hình khác ({id, loai, so_quyet_dinh, ngay_ky, goc}). Hai hình chưa
  // thống nhất ⇒ nhận cả hai dưới dạng dict, đọc từng khoá bằng `tomTatQuyetDinh` (không đoán).
  quyet_dinh: z.record(z.string(), z.unknown()).nullable().optional(),
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

// ═══════════════════════ Vòng giao diện GĐ1 — chọn hồ sơ → kiểm trước → dựng (đặc tả 3.1–3.3, 3.11) ═══════════════════
// ⏳ CHỜ MÁY CHỦ: `kiem-truoc`, `doi-ma`, `tim-ho-so`, `POST /sets` dạng id CHƯA có ở `dd6c725d`. Schema viết theo
// DTO của đặc tả (bản 1 + 2 + 3); khi máy chủ giao thì đối chiếu từng trường với `schemas/council_document.py`.
// ⚠️ Các DTO dưới có `ho_ten` / `cccd` (dữ liệu cá nhân): chỉ ở bộ nhớ React Query với `gcTime: 0`, không storage,
// không URL, không log (xem hook).

/** Mức kiểm trước của một dòng — máy chủ quyết. Giá trị lạ ⇒ `nhanMucKiem` in nguyên (không suy). */
export const COUNCIL_PREVIEW_LEVELS = ["duoc_dung", "can_xac_nhan", "bi_chan"] as const

export const councilPreviewReasonSchema = z.object({
  ma: z.string(),
  /** câu thật của cổng (máy chủ) — hiện NGUYÊN VĂN */
  cau: z.string(),
})
export type CouncilPreviewReason = z.infer<typeof councilPreviewReasonSchema>

export const councilPreviewRowSchema = z.object({
  /** thứ tự gửi dựng = thứ tự dòng của bộ (máy chủ sắp; giao diện KHÔNG đổi thứ tự) */
  stt: z.number().int(),
  /** số thứ tự trong nhóm ngành – trình độ trên Quyết định */
  stt_qd: z.number().int(),
  profile_id: z.number().int(),
  ho_ten: z.string(),
  trang_thai: z.string(),
  trang_thai_nhan: z.string(),
  nganh_nhan: z.string(),
  trinh_do: z.string(),
  duong_xet_nhan: z.string().nullable(),
  diem_in: z.string().nullable(),
  muc: z.string(),
  ly_do: z.array(councilPreviewReasonSchema),
})
export type CouncilPreviewRow = z.infer<typeof councilPreviewRowSchema>

export const councilPreviewSummarySchema = z.object({
  tong: z.number().int(),
  duoc_dung: z.number().int(),
  can_xac_nhan: z.number().int(),
  bi_chan: z.number().int(),
  theo_nganh: z.array(
    z.object({ nganh_nhan: z.string(), trinh_do: z.string(), so: z.number().int() }),
  ),
  /** đúng thứ `POST /sets` đòi ở `xac_nhan_trang_thai` */
  can_xac_nhan_theo_trang_thai: z.record(z.string(), z.number().int()),
  so_nhom: z.number().int(),
  du_kien_so_tep: z.number().int(),
})
export type CouncilPreviewSummary = z.infer<typeof councilPreviewSummarySchema>

export const councilSetPreviewSchema = z.object({
  kiem_luc: z.string(),
  /** dấu kiểm trước (HMAC) — gửi lại NGUYÊN VĂN khi dựng; không phải dữ liệu để giao diện đọc */
  phien_ban_kiem: z.string().min(1),
  dong: z.array(councilPreviewRowSchema),
  /** VỊ TRÍ (đếm từ 1) trong `profile_ids` đầu vào không khớp hồ sơ / ngoài phạm vi */
  khong_tim_thay: z.array(z.number().int()),
  tom_tat: councilPreviewSummarySchema,
})
export type CouncilSetPreview = z.infer<typeof councilSetPreviewSchema>

/** Yêu cầu `POST /sets/kiem-truoc` (extra="forbid"). `profile_ids` không trùng, 1…`COUNCIL_SET_MAX_PROFILES`. */
export const councilSetPreviewInSchema = z
  .object({
    academic_year: z.number().int(),
    profile_ids: z.array(z.number().int().positive()).min(1),
  })
  .strict()
export type CouncilSetPreviewIn = z.infer<typeof councilSetPreviewInSchema>

/** `POST /sets/doi-ma` — danh sách mã CHỈ ở thân (dữ liệu cá nhân). */
export const councilCodesInSchema = z
  .object({ academic_year: z.number().int(), ma_ho_so: z.array(z.string()).min(1) })
  .strict()
export type CouncilCodesIn = z.infer<typeof councilCodesInSchema>

export const councilCodesOutSchema = z.object({
  profile_ids: z.array(z.number().int()),
  /** `ly_do`: `rong` | `trung` | `ky_tu_la` | `khong_khop`; chỉ SỐ DÒNG, không giá trị */
  dong_loi: z.array(z.object({ dong: z.number().int(), ly_do: z.string() })),
})
export type CouncilCodesOut = z.infer<typeof councilCodesOutSchema>

/** `POST /sets/tim-ho-so` (đặc tả 3.11) — thân JSON, không tham số query. */
export const councilProfileSearchInSchema = z
  .object({
    academic_year: z.number().int(),
    tu_khoa: z.string().min(1).max(100).nullable().optional(),
    major_ids: z.array(z.number().int()).nullable().optional(),
    trang_thai: z.array(z.string()).nullable().optional(),
    page: z.number().int().min(1),
    page_size: z.number().int().min(1).max(100),
  })
  .strict()
export type CouncilProfileSearchIn = z.infer<typeof councilProfileSearchInSchema>

export const councilProfileSearchRowSchema = z.object({
  profile_id: z.number().int(),
  ho_ten: z.string(),
  /** DỮ LIỆU CÁ NHÂN — chỉ hiện trên bảng chọn, không lưu */
  cccd: z.string(),
  nganh_nhan: z.string(),
  trinh_do: z.string(),
  duong_xet_nhan: z.string().nullable(),
  trang_thai: z.string(),
  trang_thai_nhan: z.string(),
  // ⏳ CHỜ MÁY CHỦ: phiên A sẽ thêm `academic_year` vào dòng tìm hồ sơ; đến lúc đó bỏ `.optional()`.
  academic_year: z.number().int().optional(),
})
export type CouncilProfileSearchRow = z.infer<typeof councilProfileSearchRowSchema>

export const councilProfileSearchOutSchema = z.object({
  tong: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
  dong: z.array(councilProfileSearchRowSchema),
})
export type CouncilProfileSearchOut = z.infer<typeof councilProfileSearchOutSchema>

/** `POST /sets` dạng MỚI (đặc tả 3.3): `profile_ids` + `phien_ban_kiem` thay cho `ma_ho_so`. */
export const councilSetCreateByIdsSchema = z
  .object({
    profile_ids: z.array(z.number().int().positive()).min(1),
    phien_ban_kiem: z.string().min(1),
    academic_year: z.number().int(),
    tham_so_quyet_dinh: decisionParamsSchema.nullable().optional(),
    xac_nhan_trang_thai: z.record(z.string(), z.number().int().min(1)).nullable().optional(),
  })
  .strict()
export type CouncilSetCreateByIds = z.infer<typeof councilSetCreateByIdsSchema>

// ═══════════════════════ Quyết định đã ký (Lượt I — máy chủ đã có từ `bfba3a2e`) ═══════════════════════
/** `CouncilDecisionOut` — không dữ liệu cá nhân. Trạng thái / loại là chuỗi của máy chủ; lạ ⇒ in nguyên. */
export const councilDecisionSchema = z.object({
  id: z.number().int(),
  loai: z.string(),
  trang_thai: z.string(),
  can_bo: z.boolean(),
  set_id: z.number().int().nullable().optional(),
  goc_id: z.number().int().nullable().optional(),
  huy_qd_id: z.number().int().nullable().optional(),
  het_hieu_luc_boi_id: z.number().int().nullable().optional(),
  so_quyet_dinh: z.string(),
  ngay_ky: z.string(),
  pham_vi_so: z.number().int(),
  so_ho_so: z.number().int(),
  sha_tep_quyet_dinh: z.string().nullable().optional(),
  tham_so_ban_ky: z.record(z.string(), z.unknown()).nullable().optional(),
  xac_nhan: z.record(z.string(), z.unknown()).nullable().optional(),
  ghi_chu_mau: z.string().nullable().optional(),
  ghi_nhan_boi_id: z.number().int(),
  ghi_nhan_luc: z.string(),
  huy_ghi_nhan_boi_id: z.number().int().nullable().optional(),
  huy_ghi_nhan_luc: z.string().nullable().optional(),
  ly_do_huy_ghi_nhan: z.string().nullable().optional(),
})
export type CouncilDecision = z.infer<typeof councilDecisionSchema>
export const councilDecisionListSchema = z.array(councilDecisionSchema)

/** `CouncilQuotaWarningOut` (N9): một ô chỉ tiêu bị VƯỢT sau khi ghi nhận — không chặn. Chỉ id + số đếm. */
export const councilQuotaWarningSchema = z.object({
  /** `nganh` | `duong_xet` */
  loai: z.string(),
  chi_tieu: z.number().int(),
  academic_info_id: z.number().int().nullable().optional(),
  da_dung_cong_bo: z.number().int().nullable().optional(),
  da_dung_phe_duyet_cu: z.number().int().nullable().optional(),
  admission_path_id: z.number().int().nullable().optional(),
  da_dung: z.number().int().nullable().optional(),
  // ⏳ CHỜ MÁY CHỦ (đặc tả 3.8): tên ngành / đường xét để hiển thị. Thiếu ⇒ giao diện hiện mã + id.
  nhan: z.string().nullable().optional(),
})
export type CouncilQuotaWarning = z.infer<typeof councilQuotaWarningSchema>

/** `CouncilDecisionWriteOut` — văn bản + số đếm của thao tác. `lap_lai` / `goc` / `ma_luot_gui`: máy chủ đã trả từ `dd6c725d`. */
export const councilDecisionWriteSchema = councilDecisionSchema.extend({
  so_lieu: z.record(z.string(), z.unknown()).nullable().optional(),
  canh_bao_vuot_chi_tieu: z.array(councilQuotaWarningSchema),
  goc: z
    .object({ id: z.number().int(), so_quyet_dinh: z.string(), ngay_ky: z.string() })
    .nullable()
    .optional(),
  ma_luot_gui: z.string().nullable().optional(),
  /** gửi LẶP đúng nội dung ⇒ `true` (văn bản cũ, HTTP 200, không ghi lần hai) */
  lap_lai: z.boolean(),
})
export type CouncilDecisionWrite = z.infer<typeof councilDecisionWriteSchema>

/** `GET /decisions/{id}` (`CouncilDecisionDetailOut`) — dòng chỉ mang số dòng + id hồ sơ NỘI BỘ (không CCCD). */
export const councilDecisionDetailSchema = councilDecisionSchema.extend({
  dong: z.array(
    z.object({
      id: z.number().int(),
      stt: z.number().int(),
      set_row_id: z.number().int().nullable().optional(),
      profile_id: z.number().int().nullable().optional(),
      trang_thai_cha: z.string(),
      bi_bo_boi_id: z.number().int().nullable().optional(),
    }),
  ),
  scan: z.record(z.string(), z.unknown()).nullable().optional(),
  su_kien: z.array(
    z.object({
      id: z.number().int(),
      loai: z.string(),
      set_id: z.number().int().nullable().optional(),
      decision_id: z.number().int().nullable().optional(),
      hold_id: z.number().int().nullable().optional(),
      nguoi_id: z.number().int().nullable().optional(),
      luc: z.string(),
      so_lieu: z.record(z.string(), z.unknown()),
    }),
  ),
})
export type CouncilDecisionDetail = z.infer<typeof councilDecisionDetailSchema>

/**
 * `409` của ghi nhận / huỷ ghi nhận khi cần Admin xác nhận số hồ sơ theo loại (`_kiem_xac_nhan_dem`, khuôn F228 / C3):
 * thân lỗi có `xac_nhan_can`. Chỉ số đếm + số dòng, không dữ liệu cá nhân. Giao diện hiển thị ĐÚNG số này và gửi
 * lại nguyên văn khi người dùng gõ xác nhận — không tự tính.
 */
export const councilConfirmNeededSchema = z.object({
  so_ho_so_theo_loai: z.record(z.string(), z.number().int()),
  dong_theo_loai: z.record(z.string(), z.array(z.number().int())),
})
export type CouncilConfirmNeeded = z.infer<typeof councilConfirmNeededSchema>

/** `dong_bi_chan` của `409` ghi nhận: dòng có Quyết định hiệu lực khác / chờ Admin quyết / dấu AppSheet. */
export const councilBlockedRowsSchema = z.array(
  z.object({ dong: z.number().int(), ly_do: z.string() }),
)
export type CouncilBlockedRows = z.infer<typeof councilBlockedRowsSchema>

/** `CouncilDecisionCancelIn` (extra="forbid") — huỷ ghi nhận: lý do + gõ lại số hồ sơ + xác nhận trạng thái. */
export const councilDecisionCancelSchema = z
  .object({
    ly_do: z.string(),
    so_go_lai: z.string(),
    xac_nhan: z.record(z.string(), z.number().int().min(1)).nullable().optional(),
  })
  .strict()
export type CouncilDecisionCancel = z.infer<typeof councilDecisionCancelSchema>

// ═══════════════════════ Lượt gửi ghi nhận (đặc tả bản 2 mục 3.7 — máy chủ có từ `dd6c725d`) ═══════════════════════
/** `GET /sets/{id}/luot-ghi-nhan` — `trang_thai`: `cho_gui` | `da_ghi` | `da_chan`; lạ ⇒ coi là CHƯA XÁC ĐỊNH. */
export const councilSubmissionSchema = z.object({
  ma: z.string(),
  trang_thai: z.string(),
  tao_luc: z.string(),
  ket_thuc_luc: z.string().nullable().optional(),
  decision_id: z.number().int().nullable().optional(),
})
export type CouncilSubmission = z.infer<typeof councilSubmissionSchema>
export const councilSubmissionListSchema = z.array(councilSubmissionSchema)

export const councilSubmissionOpenSchema = z.object({ ma: z.string().min(1) })
export type CouncilSubmissionOpen = z.infer<typeof councilSubmissionOpenSchema>

/** `POST /luot-ghi-nhan/{ma}/chan`: `ket_qua` ∈ `chua_ghi_da_chan` | `da_ghi` (kèm `quyet_dinh`) | `dang_xu_ly`. */
export const councilSubmissionResolveSchema = z.object({
  ket_qua: z.string(),
  quyet_dinh: councilDecisionWriteSchema.nullable().optional(),
})
export type CouncilSubmissionResolve = z.infer<typeof councilSubmissionResolveSchema>

// ═══════════════════════ Đối chiếu bản ký (`GET /sets/{id}/so-voi-hien-tai`) ═══════════════════════
/** Số dòng + TÊN trường đã đổi — không giá trị cũ / mới. */
export const councilCompareSchema = z.object({
  set_id: z.number().int(),
  so_dong: z.number().int(),
  dong_khac: z.array(z.object({ stt: z.number().int(), truong: z.array(z.string()) })),
  khong_dung_lai_duoc: z.array(z.object({ stt: z.number().int(), ma: z.array(z.string()) })),
  mat_ho_so: z.array(z.number().int()),
})
export type CouncilCompare = z.infer<typeof councilCompareSchema>

// ═══════════════════════ Ô "Quyết định trúng tuyển" trên trang hồ sơ (đặc tả 3.9) ═══════════════════════
// ⏳ CHỜ MÁY CHỦ: DTO chi tiết hồ sơ CHƯA có `quyet_dinh_trung_tuyen`. Thẻ đọc qua `safeParse` — vắng / sai dạng
// ⇒ không hiện thẻ (không đoán).
export const councilProfileDecisionSchema = z.object({
  /** `co_qd_hieu_luc` | `cho_admin_quyet` | `da_cho_xet_lai` | `chua_co_qd` — máy chủ tính; lạ ⇒ in nguyên */
  tinh_trang: z.string(),
  van_ban: z
    .object({
      id: z.number().int(),
      loai: z.string(),
      so_quyet_dinh: z.string(),
      ngay_ky: z.string(),
      trang_thai: z.string(),
      set_id: z.number().int().nullable(),
    })
    .nullable(),
  /** CHỈ admin được trả */
  ly_do_huy_ghi_nhan: z.string().nullable().optional(),
  dau_appsheet: z.boolean(),
  dau_appsheet_so_qd: z.string().nullable(),
})
export type CouncilProfileDecision = z.infer<typeof councilProfileDecisionSchema>
