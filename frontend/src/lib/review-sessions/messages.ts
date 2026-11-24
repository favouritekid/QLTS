/**
 * GĐ2-B — câu tiếng Việt và nhãn cho màn lần xét (thiết kế giao diện GĐ2-B, Phụ lục A + §5). Chỉ ÁNH XẠ mã / trạng thái máy chủ
 * → câu (trình bày): KHÔNG quyết nút nào hiện (máy chủ quyết qua `available_actions`), KHÔNG suy trạng thái. Giá trị lạ ⇒ hiện
 * chữ máy chủ (trạng thái, tab) hoặc bỏ qua (hành động) — HĐ4 §1.8. Không `console.*`.
 *
 * Nhãn câu: câu lấy từ Phụ lục A / câu máy chủ / câu có sẵn trong ứng dụng ghi nguồn ở chú thích; câu MỚI của đợt F0 / F1 / F2 ghi
 * `[ĐX]` — chờ owner duyệt cùng G8 (bàn giao từng đợt liệt kê đủ).
 */
import { readApiError } from "@/lib/error-handler"
import type { ReviewRoundOption } from "@/lib/zod/review-sessions"

import type { FloorGroupKey } from "./floor-draft"

// ═══════════════════════════════════════ nhãn ═══════════════════════════════════════
/** Phụ lục A "Trạng thái lần xét" (`locked` / `signed` của GĐ2-C có sẵn nhãn). */
export const SESSION_STATUS_LABEL: Record<string, string> = {
  draft: "Nháp",
  cancelled: "Đã huỷ",
  locked: "Đã khoá",
  signed: "Đã ký",
}

/** Trạng thái lạ ⇒ hiện NGUYÊN chữ máy chủ (HĐ4 §1.8). */
export function sessionStatusLabel(status: string): string {
  return SESSION_STATUS_LABEL[status] ?? status
}

/** Bộ lọc trạng thái của E2 — đúng hai giá trị máy chủ nhận ở GĐ2-B (giá trị khác ⇒ 422). */
export const SESSION_STATUS_FILTERS = ["draft", "cancelled"] as const
export type SessionStatusFilter = (typeof SESSION_STATUS_FILTERS)[number]

/** Phụ lục A "Hành động" — thứ tự nút trên thanh nút. */
export const SESSION_ACTIONS = ["edit_floors", "run_evaluate", "cancel"] as const
export type SessionAction = (typeof SESSION_ACTIONS)[number]
export const SESSION_ACTION_LABEL: Record<SessionAction, string> = {
  edit_floors: "Sửa điểm sàn",
  run_evaluate: "Kiểm hồ sơ",
  cancel: "Huỷ lần xét",
}

/**
 * Hành động máy chủ cho phép mà giao diện BIẾT vẽ nút — giữ thứ tự cố định; giá trị lạ BỎ QUA (HĐ4 §1.8). Không thêm hành
 * động nào máy chủ không trả (thin client).
 */
export function knownSessionActions(availableActions: readonly string[]): SessionAction[] {
  return SESSION_ACTIONS.filter((a) => availableActions.includes(a))
}

/** Phụ lục A "Trạng thái lượt kiểm". */
export const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "Đang chờ chạy",
  running: "Đang chạy",
  done: "Xong",
  failed: "Hỏng",
}
export function runStatusLabel(status: string): string {
  return RUN_STATUS_LABEL[status] ?? status
}

/** Tab [CHỐT ĐTB4 §6.7] — thứ tự máy chủ (HĐ4 §2 E9). */
export const ROW_TABS = ["auto", "needs_decision", "not_passed", "ineligible"] as const
export const TAB_LABEL: Record<string, string> = {
  auto: "Đạt — máy đề xuất",
  needs_decision: "Cần Ban thư ký quyết",
  not_passed: "Chưa đạt — chờ lần sau",
  ineligible: "Chưa đủ điều kiện",
}
export function tabLabel(tab: string): string {
  return TAB_LABEL[tab] ?? tab
}

export interface TabCountEntry {
  tab: string
  label: string
  count: number
}

/** Số theo tab của MÁY CHỦ — bốn tab biết trước theo thứ tự cố định, tab lạ (GĐ2-C `excluded`) nối sau với chữ máy chủ. */
export function tabCountEntries(counts: Record<string, number> | null | undefined): TabCountEntry[] {
  if (!counts) return []
  const known = ROW_TABS.filter((t) => t in counts)
  const extra = Object.keys(counts)
    .filter((t) => !(ROW_TABS as readonly string[]).includes(t))
    .sort()
  return [...known, ...extra].map((tab) => ({ tab, label: tabLabel(tab), count: counts[tab] }))
}

/** Thiết kế §3.3 — trạng thái bảng chỉ tiêu năm. */
export const QUOTA_TABLE_STATUS_LABEL: Record<string, string> = {
  draft: "Nháp",
  locked: "Đã khoá",
}
export function quotaTableStatusLabel(status: string): string {
  return QUOTA_TABLE_STATUS_LABEL[status] ?? status
}

/**
 * Nhãn tình trạng đợt — CÙNG chữ trang "Cấu hình tuyển sinh › Đợt" đang dùng (`RoundsManagementTab.tsx` `statusLabel`). CHỈ là
 * nhãn. Đợt nào được chọn để tạo lần xét do MÁY CHỦ quyết (owner G1); hộp "Tạo lần xét" khoá thêm đợt đã lưu trữ như một lớp UX
 * (`CreateReviewSessionDialog.tsx` `roundSelectable`).
 */
export function roundStateLabel(round: Pick<ReviewRoundOption, "is_active" | "archived_at">): string {
  if (round.archived_at) return "Đã lưu trữ"
  if (round.is_active) return "Đang hoạt động"
  return "Tạm dừng"
}

/** Thiết kế §4.3 (KT-2): máy chủ chưa trả tên người thao tác (S3) ⇒ hiện số id. */
export function userRef(userId: number | null | undefined): string {
  return userId === null || userId === undefined ? "—" : `Người dùng #${userId}`
}

// ═══════════════════════════════════════ câu cố định ═══════════════════════════════════════
/** Phụ lục A "Câu khác". */
export const REVIEW_DRAFT_NOTE = "Lần xét nháp không đổi gì trên hồ sơ; mỗi lượt kiểm là một bản chụp không sửa được."
/** Phụ lục A "Câu khác". */
export const CANCELLED_FLOORS_NOTE =
  "Lần xét đã huỷ — điểm sàn đã được giải phóng. Mức sàn đã dùng của từng lượt kiểm xem ở lượt ấy."
/** Phụ lục A "Câu khác". */
export const NO_DONE_RUN = "Chưa có lượt kiểm nào xong."
/** Thiết kế §3.2 (M1 rỗng). */
export const LIST_EMPTY = "Chưa có lần xét nào cho bộ lọc này."
/** Thiết kế §3.2 — nhãn khi `config_changed_since_run`. [ĐX] */
export const CONFIG_CHANGED_BADGE = "Cấu hình đã đổi"
/** Thiết kế §3.3 — băng khi `latest_run.config_changed_since_run`. [ĐX] */
export const CONFIG_CHANGED_BANNER =
  "Điểm sàn hoặc bảng chỉ tiêu đã đổi sau lượt kiểm gần nhất — kết quả đang xem có thể không còn đúng. Bấm \"Kiểm hồ sơ\" để có kết quả mới."
/** Thiết kế §3.3 — băng khi `quota_table.status = "draft"`. [ĐX] */
export function quotaTableDraftBanner(year: number): string {
  return `Bảng chỉ tiêu năm ${year} đang ở trạng thái nháp.`
}
/** Thiết kế §3.8 — hộp huỷ. [ĐX] */
export const CANCEL_CONFIRM_TEXT =
  "Huỷ là trạng thái cuối, không mở lại. Mọi điểm sàn của lần xét được giải phóng (dời năm ngành không còn bị chặn bởi lần xét này). Các lượt kiểm cũ vẫn xem được, giữ đúng mức sàn đã dùng."
/** Thiết kế §3.8 — 409 `REVIEW_SESSION_STALE` ở hộp huỷ (giữ lý do đã gõ). */
export const CANCEL_STALE = "Lần xét vừa được sửa ở nơi khác — xem lại rồi bấm Huỷ lần nữa."
/** Thiết kế §3.8 — 422 ở hộp huỷ. */
export const CANCEL_REASON_INVALID = "Lý do không được trống / quá 1000 ký tự"
/** [ĐX] — gợi ý dưới ô lý do huỷ. */
export const CANCEL_REASON_HINT = "Bắt buộc, tối đa 1000 ký tự."
/** [ĐX] — toast sau khi huỷ thành công. */
export const CANCEL_DONE = "Đã huỷ lần xét."
/** Thiết kế §3.2 — E1 mất kết nối / 5xx. */
export const CREATE_UNCERTAIN = "Chưa rõ đã tạo hay chưa — tải lại danh sách để xem."
/** Thiết kế §7.1 (phác thảo hộp "Tạo lần xét"). [ĐX] */
export const CREATE_NOTE = "Lần xét nháp chỉ để chạy thử: không đổi gì trên hồ sơ."
/** Thiết kế §3.2 — liên kết từ 409 `REVIEW_QUOTA_TABLE_MISSING`. */
export function quotaTableLinkLabel(year: number): string {
  return `Mở Bảng chỉ tiêu năm ${year}`
}
/**
 * Đính chính §2 + đính chính 2 §3: liên kết tới bảng chỉ tiêu LUÔN là `/quota-tables?year=<năm>` (không `/admin/quota-tables`:
 * chuyển hướng làm mất tham số; cán bộ là Thư ký bị proxy đẩy khỏi `/admin/*`).
 */
export function quotaTableHref(year: number): string {
  return `/quota-tables?year=${year}`
}
/** [ĐX] — nút của hành động có ở đợt giao diện sau (F3 "Kiểm hồ sơ"; "Sửa điểm sàn" đã mở ở F2). */
export const ACTION_NOT_YET = "Chức năng này có ở đợt giao diện sau."
/** Thiết kế §7.1 (phác thảo M1: lượt kiểm gần nhất chưa có). [ĐX] */
export const NO_RUN_YET = "Chưa chạy"
/** [ĐX] */
export const RELOADING = "Đang tải lại…"

// ═══════════════════════════════════════ F2 — điểm sàn (M3) ═══════════════════════════════════════
/** Phụ lục A "Trạng thái ngành ở chỉ tiêu tham khảo / màn sàn" — HĐ4 §4.10 (mở rộng được; lạ ⇒ chữ máy chủ). */
export const QUOTA_STATE_LABEL: Record<string, string> = {
  ok: "Có sàn",
  floor_missing: "Thiếu sàn",
  quota_closed: "Đóng tuyển (chỉ tiêu 0)",
  quota_not_configured: "Chưa có chỉ tiêu",
  group_missing: "Chưa thuộc nhóm",
  deleted: "Đã xoá",
}
export function quotaStateLabel(state: string): string {
  return QUOTA_STATE_LABEL[state] ?? state
}

/** Thiết kế §3.4: chỉ tiêu năm `null` ⇒ "Chưa cấu hình", `0` ⇒ "0 — đóng tuyệt đối" (HĐ4 §1.4: `null` ≠ `0`). Chỉ là nhãn. */
export function annualQuotaLabel(quota: number | null): string {
  if (!quota) return "0 — đóng tuyệt đối"
  if (quota === 0) return "0 — đóng tuyệt đối"
  return String(quota)
}

/** Thiết kế §3.4 / §7.2: "<mã> — <tên ngành>" (nhãn HIỆN TẠI máy chủ trả; trống ⇒ "—"). */
export function majorLabel(code: string | null, name: string | null): string {
  return `${code ?? "—"} — ${name ?? "—"}`
}

/** Phụ lục HĐ4 E10 §1.1 "ánh xạ nhóm" + phác thảo §7.2; nhóm "khác" (trạng thái mới của máy chủ) [ĐX]. */
export const FLOOR_GROUP_TITLE: Record<FloorGroupKey, string> = {
  needs_floor: "Cần nhập sàn",
  closed: "Không cần sàn — đã đóng (chỉ tiêu 0)",
  not_reviewable: "Không xét được — chưa có chỉ tiêu / chưa thuộc nhóm / đã xoá",
  other: "Trạng thái khác",
}
/** Phác thảo §7.2 — sau tiêu đề nhóm "Không xét được". */
export const NOT_REVIEWABLE_HINT = "(sửa ở Bảng chỉ tiêu năm)"
/** Phác thảo §7.2. */
export const INACTIVE_LABEL = "Đang ngừng"
/** Thiết kế §3.4 (`is_deleted`). */
export const DELETED_LABEL = "Đã xoá"

/** Tiêu đề thẻ (thiết kế §3.3 "Thẻ: Điểm sàn"). */
export const FLOORS_SECTION_TITLE = "Điểm sàn"
/** Owner G2 + phác thảo §7.2: MỘT dòng chung, không cột "ai sửa" từng dòng. */
export function floorsLastSaved(user: string, at: string): string {
  return `Danh sách điểm sàn lưu lần cuối bởi ${user} lúc ${at}`
}
/** [ĐX] — E3 `floors = []`. */
export const FLOORS_EMPTY = "Chưa có điểm sàn nào."
/** [ĐX] — E10 `items = []`. */
export function floorCandidatesEmpty(year: number): string {
  return `Năm ${year} chưa có học vụ nào.`
}
/** [ĐX] */
export const FLOORS_LOADING = "Đang tải danh sách ngành…"
/** [ĐX] — ô điểm sai dạng (kiểm DẠNG theo HĐ4 §1.4; máy chủ là chốt). */
export const FLOOR_INPUT_INVALID = "Điểm chưa đúng dạng: từ 0 đến 999,99, tối đa 2 chữ số sau dấu phẩy."
/** [ĐX] — dòng nhận sàn được nhưng máy chủ báo sàn không có tác dụng (`floor_applicable = false`, phụ lục E10 §1.1). */
export const FLOOR_NOT_APPLICABLE_NOTE = "Sàn không có tác dụng ở ngành này."
/** [ĐX] — dòng `floor_accepted = false` còn mức đang lưu (phụ lục E10 §1.1 "khi Lưu … phải bỏ ra"). */
export function floorDroppedNote(score: string): string {
  return `Đang lưu ${score} — học vụ không nhận điểm sàn được nữa, sẽ bỏ khi lưu.`
}
/** Phác thảo §7.2 "[ Lưu điểm sàn (12 ngành) ]". */
export function floorsSaveLabel(count: number): string {
  return `Lưu điểm sàn (${count} ngành)`
}
/** Phác thảo §7.2. */
export const FLOORS_DISCARD = "Bỏ thay đổi"
/** Thiết kế §3.4 — danh sách rỗng ⇒ hỏi lại. */
export const FLOORS_CONFIRM_EMPTY = "Xoá hết điểm sàn của lần xét này?"
/** [ĐX] */
export const FLOORS_CONFIRM_EMPTY_NOTE = "Danh sách gửi đi rỗng — mọi điểm sàn đang lưu của lần xét này sẽ bị xoá."
/** [ĐX] */
export const FLOORS_CONFIRM_EMPTY_YES = "Xoá hết"
/** [ĐX] */
export const FLOORS_CONFIRM_EMPTY_NO = "Không"
/** [ĐX] — thiết kế §3.4 "Trần 500 dòng (giới hạn kỹ thuật HĐ4) — quá ⇒ khoá nút Lưu, báo số dòng". */
export function floorsTooMany(count: number, max: number): string {
  return `Có ${count} dòng điểm sàn — quá giới hạn ${max} dòng của máy chủ; bớt dòng rồi lưu.`
}
/** Phác thảo §7.2 — 409 STALE. */
export const FLOORS_STALE_TITLE = "Điểm sàn vừa được lưu ở nơi khác"
/** [ĐX] — dòng người dùng không sửa đã lấy mức vừa lưu (bản soạn chỉ giữ ô đã gõ). */
export const FLOORS_STALE_NOTE = "Dòng bạn không sửa đã lấy mức vừa lưu. Các dòng bạn đã sửa khác mức vừa lưu:"
/** [ĐX] */
export const FLOORS_STALE_NO_DIFF = "Không dòng nào bạn đã sửa khác mức vừa lưu."
/** Phác thảo §7.2. */
export const FLOORS_COL_MINE = "Bạn đang soạn"
/** Phác thảo §7.2. */
export const FLOORS_COL_SAVED = "Vừa lưu ở nơi khác"
/** Phác thảo §7.2. */
export const FLOORS_USE_NEW = "Dùng bản mới (bỏ thay đổi của tôi)"
/** Phác thảo §7.2. */
export const FLOORS_SAVE_MINE = "Lưu bản của tôi đè lên"
/** [ĐX] — ô trống ở bảng so. */
export const FLOOR_EMPTY_VALUE = "(trống)"
/** [ĐX] — toast sau khi lưu thành công. */
export const FLOORS_SAVED = "Đã lưu điểm sàn."
/** Thiết kế §3.4 dòng 422. */
export const FLOORS_INVALID_422 = "Điểm sàn chưa đúng dạng."
/** [ĐX] — thiết kế §3.4 dòng 400 `bad_member` "gợi ý bỏ các dòng đó rồi lưu lại". */
export const FLOORS_BAD_MEMBER_HINT = "Bỏ mức sàn ở các dòng tô đỏ rồi lưu lại."
/** [ĐX] — E10 không còn `edit_floors` (lần xét vừa đổi trạng thái ở nơi khác). */
export const FLOORS_NOT_EDITABLE = "Lần xét không còn sửa điểm sàn được."

// ═══════════════════════════════════════ lỗi — MỘT hàm (thiết kế §5) ═══════════════════════════════════════
/** §5 — đóng băng (503 + `code` hai tầng, `readApiError` nhận diện). */
export const FROZEN_MESSAGE =
  "Đang đóng băng tuyển sinh — tạm thời không tạo, sửa, huỷ hay chạy kiểm được; vẫn xem được."
/** §5 — 403: KHÔNG hiện `detail` (câu Casbin tiếng Anh). */
export const FORBIDDEN_MESSAGE = "Chỉ Admin dùng được chức năng này ở giai đoạn hiện tại."
/** §5 — 404 lần xét (hoặc 404 không mã của cổng Thư ký ở GĐ2-C). */
export const SESSION_NOT_FOUND_MESSAGE = "Không tìm thấy lần xét (hoặc bạn không có quyền xem)."
/** §5 — 404 lượt kiểm. */
export const RUN_NOT_FOUND_MESSAGE = "Không tìm thấy lượt kiểm."
/** §5 — 422. */
export const INVALID_MESSAGE = "Thông tin chưa đúng dạng."
/** §5 — 429. */
export const RATE_LIMITED_MESSAGE = "Thao tác quá nhiều trong thời gian ngắn — chờ ít phút rồi thử lại."
/** §5 — mất kết nối / 502 / 504 ở route GHI. */
export const WRITE_UNCERTAIN_MESSAGE = "Chưa rõ đã ghi hay chưa — đang tải lại để kiểm tra."
/** §5 — 500 khác. */
export const SERVER_ERROR_MESSAGE = "Máy chủ gặp lỗi. Tải lại để xem đã ghi hay chưa."
/** [ĐX] — mất kết nối / 502 / 504 ở route ĐỌC. */
export const READ_NETWORK_MESSAGE = "Không kết nối được máy chủ — bấm \"Tải lại\" để thử lại."
/** [ĐX] — 401 lọt qua cơ chế làm mới phiên. */
export const UNAUTHORIZED_MESSAGE = "Phiên đăng nhập đã hết hạn — đăng nhập lại rồi thử lại."
/** [ĐX] — phản hồi 2xx sai hợp đồng (Zod) hoặc lỗi không phải HTTP. */
export const BAD_RESPONSE_MESSAGE =
  "Dữ liệu máy chủ trả về không đúng dạng — tải lại để xem; nếu vẫn lỗi, báo quản trị hệ thống."
/** §5 — mã lạ. */
export function unknownErrorMessage(code: string): string {
  return `Có lỗi (mã: ${code}).`
}

/**
 * Mã máy (`error_code`) của lần xét có câu `detail` là câu cho người dùng (R7) — thiết kế §5 dòng "Mã đã biết". Tiền tố
 * `REVIEW_` cũng được coi là đã biết (mã mới cùng họ).
 */
export const REVIEW_KNOWN_ERROR_CODES: ReadonlySet<string> = new Set([
  "REVIEW_QUOTA_TABLE_MISSING",
  "REVIEW_SESSION_STALE",
  "REVIEW_SESSION_NOT_DRAFT",
  "REVIEW_RUN_IN_PROGRESS",
  "REVIEW_RUN_NOT_DONE",
  "REVIEW_CONFIG_UNAVAILABLE",
  "REVIEW_ISOLATION_UNSUPPORTED",
  "PRIORITY_RATE_NOT_CONFIGURED",
  "ACADEMIC_INFO_IN_REVIEW_FLOOR",
])

/**
 * `reason_code` của HĐ4 §5 (máy chủ `admission_review_errors.py`) + phụ lục HĐ4 E10 §2 (S1, owner G1 (c)): `review_round_archived`
 * (400 `VALIDATION_ERROR` {`admission_round_id`} — đợt đã lưu trữ). Câu hiện là `detail` NGUYÊN VĂN của máy chủ (một nguồn câu).
 */
export const REVIEW_KNOWN_REASON_CODES: ReadonlySet<string> = new Set([
  "review_round_invalid",
  "review_round_archived",
  "review_floor_duplicate",
  "review_floor_bad_member",
  "review_session_not_found",
  "review_run_not_found",
  "review_quota_table_missing",
  "review_session_stale",
  "review_session_not_draft",
  "review_run_in_progress",
  "review_run_not_done",
  "fee_gate_mode_invalid",
  "residence_proof_doc_type_missing",
])

export type ReviewErrorKind =
  | "frozen"
  | "known"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "invalid"
  | "rate_limited"
  | "uncertain"
  | "network"
  | "server"
  | "bad_response"
  | "unknown"

export interface ReviewErrorView {
  kind: ReviewErrorKind
  message: string
  status?: number
  errorCode?: string
  reasonCode?: string
  /** thân lỗi (object) — màn đọc thêm trường công khai (vd `academic_year` của 409 thiếu bảng) */
  data?: Record<string, unknown>
  /** 422 — vị trí lỗi (`loc`) để tô ô */
  validation: { loc: string[]; msg: string }[]
}

/**
 * Thiết kế §5 — MỘT hàm đọc lỗi cho mọi màn lần xét, dựa trên `readApiError` (một bộ đọc thân lỗi, R11). Rẽ nhánh CHỈ theo
 * `error_code` / `reason_code` / `code` / mã HTTP — KHÔNG theo chữ `detail`. `op`: thao tác đọc hay ghi (mất kết nối ở route
 * ghi ⇒ "chưa rõ đã ghi hay chưa").
 */
export function describeReviewSessionError(error: unknown, op: "read" | "write" = "read"): ReviewErrorView {
  const e = readApiError(error)
  const reasonCode = typeof e.data?.reason_code === "string" ? e.data.reason_code : undefined
  const base = { status: e.status, errorCode: e.errorCode, reasonCode, data: e.data, validation: e.validation }

  if (!e.isAxios) return { ...base, kind: "bad_response", message: BAD_RESPONSE_MESSAGE }
  if (e.frozen) return { ...base, kind: "frozen", message: FROZEN_MESSAGE }
  if (!e.hasResponse || e.status === 502 || e.status === 504) {
    return op === "write"
      ? { ...base, kind: "uncertain", message: WRITE_UNCERTAIN_MESSAGE }
      : { ...base, kind: "network", message: READ_NETWORK_MESSAGE }
  }
  if (e.status === 401) return { ...base, kind: "unauthorized", message: UNAUTHORIZED_MESSAGE }
  if (e.status === 403) return { ...base, kind: "forbidden", message: FORBIDDEN_MESSAGE }
  if (e.status === 404) {
    return {
      ...base,
      kind: "not_found",
      message: reasonCode === "review_run_not_found" ? RUN_NOT_FOUND_MESSAGE : SESSION_NOT_FOUND_MESSAGE,
    }
  }
  if (e.status === 429) return { ...base, kind: "rate_limited", message: RATE_LIMITED_MESSAGE }
  if (e.status === 422) return { ...base, kind: "invalid", message: INVALID_MESSAGE }

  const knownCode =
    (e.errorCode !== undefined && (REVIEW_KNOWN_ERROR_CODES.has(e.errorCode) || e.errorCode.startsWith("REVIEW_"))) ||
    (reasonCode !== undefined && REVIEW_KNOWN_REASON_CODES.has(reasonCode))
  if (knownCode) {
    return {
      ...base,
      kind: "known",
      message: e.detail ?? unknownErrorMessage(e.errorCode ?? reasonCode ?? String(e.status)),
    }
  }
  if (e.status === 500) return { ...base, kind: "server", message: SERVER_ERROR_MESSAGE }
  return { ...base, kind: "unknown", message: unknownErrorMessage(e.errorCode ?? `HTTP ${e.status ?? "?"}`) }
}
