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
  // Vòng giao diện — đường chọn hồ sơ (đặc tả 3.1 / 3.2 / 3.10; MỖI route một cờ). Máy chủ đã trả từ `5feb425d`.
  kiem_truoc: z.boolean(),
  tim_ho_so: z.boolean(),
  doi_ma: z.boolean(),
  // Vòng giao diện — đợt 2 (máy chủ `083a428d`): tải cả bộ (`GET /sets/{id}/tai-ca-bo`) + người tạo bộ cho bộ lọc danh sách
  // (`GET /nguoi-tao-bo`, MỖI route một cờ). Bắt buộc như mọi cờ trên: vắng ⇒ hợp đồng gãy ⇒ từ chối cả phản hồi.
  tai_ca_bo: z.boolean(),
  xem_nguoi_tao_bo: z.boolean(),
})
/**
 * Cờ giao diện CHƯA có ở máy chủ (đang `.default(false)`). RỖNG từ đợt 2 (`083a428d`): máy chủ đã trả đủ — thêm cờ mới
 * chờ máy chủ thì thêm tên vào đây VÀ `.default(false)` ở schema; test `council-documents.test.ts` khoá hai vế khớp nhau.
 */
export const CO_CHO_MAY_CHU: readonly CouncilDocumentPermissionKey[] = []
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
  // Đợt 2 (máy chủ `083a428d`, đặc tả 3.4 / 3.5): BỐN trường dưới LUÔN có khoá ở `GET /sets` và `GET /sets/{id}` — danh
  // sách và chi tiết CÙNG một hình. Ở phản hồi của `POST /sets`, `POST …/dung-lai-ban-ky`, `POST /decisions/{id}/bo-dieu-chinh`
  // (bộ vừa dựng) cả bốn = `null`, nên KHÔNG dùng `.optional()` (vắng khoá ⇒ hợp đồng gãy) mà dùng `.nullable()`.
  // Giao diện KHÔNG suy tình trạng từ chỗ khác — `null` ⇒ hiện "—".
  nguoi_tao_ten: z.string().nullable(),
  /** `chua_ghi_nhan` | `con_hieu_luc` | `het_hieu_luc` | `da_huy_ghi_nhan` | `chua_xac_dinh` — máy chủ tính; lạ ⇒ in nguyên. */
  tinh_trang: z.string().nullable(),
  /** CHỈ admin thấy; Quản lý luôn `null` (kể cả khi `tinh_trang = chua_xac_dinh`). Danh sách lượt đầy đủ: `GET /sets/{id}/luot-ghi-nhan`. */
  luot_gui_cho: z.object({ ma: z.string(), tao_luc: z.string() }).nullable(),
  /** Văn bản đã ký CHƯA huỷ ghi nhận, mới nhất của bộ (+ Quyết định gốc khi là bổ sung); chưa có ⇒ `null`. */
  quyet_dinh: z
    .object({
      id: z.number().int(),
      loai: z.string(),
      trang_thai: z.string(),
      so_quyet_dinh: z.string(),
      ngay_ky: z.string(),
      so_ho_so: z.number().int(),
      goc: z
        .object({ id: z.number().int(), so_quyet_dinh: z.string(), ngay_ky: z.string() })
        .nullable(),
    })
    .nullable(),
})
export type CouncilSet = z.infer<typeof councilSetSchema>
export type CouncilSetDecisionSummary = NonNullable<CouncilSet["quyet_dinh"]>

/** `GET /nguoi-tao-bo` — người tạo phân biệt của các bộ trong phạm vi người gọi (bộ lọc "Người tạo"); `ten` = họ tên, không có thì tên đăng nhập. */
export const councilSetCreatorSchema = z.object({
  id: z.number().int(),
  ten: z.string(),
})
export type CouncilSetCreator = z.infer<typeof councilSetCreatorSchema>
export const councilSetCreatorListSchema = z.array(councilSetCreatorSchema)
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
  // Đợt 2 (đặc tả 5.7): tên người xoá (họ tên, không có thì tên đăng nhập) — LUÔN có khoá; `null` (tài khoản không còn)
  // ⇒ giao diện giữ "Tài khoản #n".
  nguoi_xoa_ten: z.string().nullable(),
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
  // Đợt 2 (đặc tả 5.7): tên người tải — LUÔN có khoá; `null` ⇒ giao diện giữ "Tài khoản #n".
  nguoi_tai_ten: z.string().nullable(),
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
// Máy chủ đã giao `kiem-truoc`, `doi-ma`, `tim-ho-so`, `POST /sets` dạng id từ `5feb425d`; schema dưới ĐÃ đối chiếu từng
// trường với `schemas/council_document.py` ở SHA ấy (11-11). Đính chính so với đặc tả: máy chủ trả MÃ trạng thái, KHÔNG
// trả `trang_thai_nhan` — nhãn lấy từ `status-config` (nguồn nhãn duy nhất, `nhanTrangThai`).
// ⚠️ Các DTO dưới có `ho_ten` / `cccd` (dữ liệu cá nhân): chỉ ở bộ nhớ React Query với `gcTime: 0`, không storage,
// không URL, không log (xem hook). Cả ba route kiểm / tìm / đổi mã trả `Cache-Control: no-store`.

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
  /** MÃ trạng thái hồ sơ — nhãn do giao diện ánh xạ (`nhanTrangThai`), máy chủ không trả nhãn */
  trang_thai: z.string(),
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
  // Máy chủ LUÔN trả (`5feb425d`), tính bằng đúng cổng quyền xác nhận hiện có. `false` ⇒ khối xác nhận khoá, nói tài
  // khoản không xác nhận được. Vắng ⇒ phản hồi bị từ chối (không đoán).
  nguoi_goi_duoc_xac_nhan: z.boolean(),
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
  /** `ly_do`: `rong` | `trung` | `ky_tu_la` | `sai_dinh_dang` | `khong_khop` | `nhieu_ho_so`; chỉ SỐ DÒNG, không giá trị.
   * Hồ sơ ngoài phạm vi đơn vị của người gọi ⇒ `khong_khop` (máy chủ không phân biệt với "không có"). */
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
  /** cùng cột "Ngành" của màn Hồ sơ tuyển sinh (`lead.offering`) — KHÔNG phải ngành xét chính xác (chỉ `kiem-truoc` có) */
  nganh_nhan: z.string(),
  /** `major_program.degree_level` dạng chữ */
  trinh_do: z.string(),
  /** danh sách dạng nhẹ không nạp nguyện vọng ⇒ máy chủ LUÔN trả `null`; đường xét / điểm in chính xác chỉ ở `kiem-truoc` */
  duong_xet_nhan: z.string().nullable(),
  /** MÃ trạng thái — nhãn do giao diện ánh xạ (`nhanTrangThai`) */
  trang_thai: z.string(),
  academic_year: z.number().int(),
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
  // Đợt 2 (đặc tả 3.8): tên ngành (học vụ) / tên hiển thị của đường xét, chỉ để hiển thị. Cảnh báo ĐÃ LƯU trước bản này
  // không có khoá ⇒ máy chủ trả `null` (hoặc vắng khi đọc lại sự kiện cũ) ⇒ giao diện hiện mã + id. Vì vậy KHÔNG bắt buộc.
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
// Đợt 2 (máy chủ `083a428d`): CHỈ `GET /api/admissions/{id}` gán `quyet_dinh_trung_tuyen`; route khác trả
// `AdmissionProfileResponse` (vd PUT cập nhật) ⇒ `null`. Thẻ đọc qua `safeParse` — `null` / vắng / sai dạng ⇒ không hiện
// thẻ (không đoán), KHÔNG làm vỡ cả trang hồ sơ.
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
