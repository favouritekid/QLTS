/**
 * GĐ2-F1 — câu tiếng Việt cho lỗi của bảng chỉ tiêu năm. Chỉ ÁNH XẠ mã máy chủ → câu (trình bày); nhãn ngành lấy từ dữ
 * liệu đang có trên màn hình (id → nhãn). Mã lạ ⇒ câu chung, không lộ chuỗi nội bộ. Không `console.*`.
 */
import { readApiError, type ApiErrorView } from "@/lib/error-handler"

import type { DraftGroup } from "./draft"

/** Mã RIÊNG của máy chủ cho "năm chưa có bảng" (`admission_quota_table_service._not_found`). */
export const QUOTA_TABLE_NOT_FOUND = "quota_table_not_found"

/**
 * Rà hợp nhất 23-11 H4: GET bảng chỉ tiêu nay đi qua cổng Thư ký Hội đồng — người chưa được gán nhận 404 thân CHUNG
 * (`{detail, error_code: "RESOURCE_NOT_FOUND"}`, không `reason_code`). "Năm chưa có bảng" CHỈ khi 404 mang đúng mã riêng — không
 * suy từ mã HTTP. MỘT vị từ cho trang (khối "chưa có bảng" + nút tạo) và cho câu lỗi bên dưới.
 */
export function isQuotaTableNotFound(e: ApiErrorView | null | undefined): boolean {
  return e?.status === 404 && e.data?.reason_code === QUOTA_TABLE_NOT_FOUND
}

/** Cờ thao tác của máy chủ (`available_actions` — thân 200 hoặc thân 404 "năm chưa có bảng") có `action` không. */
export function serverAllows(actions: unknown, action: string): boolean {
  return Array.isArray(actions) && actions.includes(action)
}

/** [ĐX — câu mới, chờ owner duyệt] 404 của cổng: không thấy bảng, hoặc người xem chưa được gán quyền Thư ký Hội đồng. */
export const QUOTA_TABLE_NO_ACCESS_MESSAGE =
  "Không xem được bảng chỉ tiêu — không tìm thấy, hoặc bạn chưa được gán quyền Thư ký Hội đồng."

export interface QuotaErrorContext {
  year: number
  /** id học vụ → nhãn ngành (từ bảng đang xem / danh sách ngành của năm). */
  labelOf: (offeringAcademicInfoId: number) => string
  /** Nhóm đang soạn (để đọc vị trí lỗi 422 của thân PUT). */
  draft?: DraftGroup[]
}

const ids = (v: unknown): number[] =>
  Array.isArray(v) ? v.filter((x): x is number => typeof x === "number" && Number.isInteger(x)) : []
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [])

const LOCKED_MESSAGE = "Bảng chỉ tiêu năm này đã khoá — Admin mở khoá (có lý do) trước khi sửa."

/** 409 theo `reason_code` (máy chủ: `admission_quota_table_service.MESSAGES`). */
export function quotaConflictText(reasonCode: string | undefined, data: Record<string, unknown> | undefined, ctx: QuotaErrorContext): string {
  switch (reasonCode) {
    case "quota_table_stale": {
      const v = typeof data?.current_version === "number" ? ` (phiên bản hiện tại: ${data.current_version})` : ""
      return `Bảng chỉ tiêu hoặc chỉ tiêu ngành của năm đã được sửa ở nơi khác (có thể ở trang Cấu hình tuyển sinh) sau khi bạn mở${v} — tải lại bảng rồi làm lại.`
    }
    case "quota_table_locked":
      return LOCKED_MESSAGE
    case "quota_table_already_locked":
      return "Bảng chỉ tiêu năm này đã khoá rồi."
    case "quota_table_not_locked":
      return "Bảng chỉ tiêu năm này chưa khoá — không có gì để mở khoá."
    case "quota_table_member_quota_missing": {
      const ds = ids(data?.offering_academic_info_ids).map(ctx.labelOf)
      return (
        "Chưa khoá được: ngành sau chưa có chỉ tiêu năm (ô trống) — " +
        (ds.length ? ds.join("; ") : "không rõ ngành") +
        ". Nhập chỉ tiêu cho mọi ngành (0 chỉ khi chỉ tiêu thật sự bằng 0) rồi khoá lại."
      )
    }
    case "quota_table_member_deleted": {
      const ds = ids(data?.offering_academic_info_ids).map(ctx.labelOf)
      return (
        "Chưa khoá được: ngành sau đã bị xoá nhưng vẫn nằm trong nhóm — " +
        (ds.length ? ds.join("; ") : "không rõ ngành") +
        ". Gỡ khỏi nhóm (lưu bảng) rồi khoá lại."
      )
    }
    default:
      return "Không thực hiện được với bảng chỉ tiêu — tải lại bảng để xem trạng thái mới."
  }
}

interface RawIssue {
  loc: unknown[]
  msg?: string
}

function issueText(issue: RawIssue, ctx: QuotaErrorContext): string | null {
  const loc = issue.loc
  const gi = loc[0] === "body" && loc[1] === "groups" && typeof loc[2] === "number" ? loc[2] : null
  if (gi === null) {
    if (loc[0] === "body" && loc[1] === "reason") return "Lý do mở khoá là bắt buộc."
    if (loc[0] === "body" && loc[1] === "quota_fingerprint") return "Thiếu dấu chỉ tiêu lúc mở bảng — tải lại trang rồi làm lại."
    return null
  }
  const g = ctx.draft?.[gi]
  const tenNhom = g?.code?.trim() ? `Nhóm ${g.code.trim()}` : `Nhóm thứ ${gi + 1}`
  if (loc[3] === "ceiling") return `${tenNhom}: trần chỉ tiêu còn trống hoặc không hợp lệ (số nguyên ≥ 0).`
  if (loc[3] === "code" || loc[3] === "name") return `${tenNhom}: mã / tên nhóm không được để trống.`
  if (loc[3] === "members" && typeof loc[4] === "number") {
    const m = g?.members[loc[4]]
    const ten = m ? ctx.labelOf(m.offering_academic_info_id) : `ngành thứ ${loc[4] + 1}`
    if (loc[5] === "annual_admission_quota") {
      return `${tenNhom} — ${ten}: chỉ tiêu năm còn trống hoặc không hợp lệ (số nguyên ≥ 0; 0 chỉ khi chỉ tiêu bằng 0).`
    }
    return `${tenNhom} — ${ten}: thông tin ngành không hợp lệ.`
  }
  return `${tenNhom}: thông tin chưa hợp lệ.`
}

export function describeQuotaTableError(error: unknown, ctx: QuotaErrorContext): string {
  const e = readApiError(error)
  if (!e.hasResponse) return "Không kết nối được máy chủ — chưa rõ đã ghi hay chưa. Tải lại bảng để xem."
  if (e.frozen) return "Tuyển sinh đang tạm đóng băng — thao tác chưa được ghi."
  const reasonCode = typeof e.data?.reason_code === "string" ? e.data.reason_code : undefined
  if (e.status === 409) {
    // Trigger CSDL (bảng đã khoá) trả `error_code` QUOTA_TABLE_LOCKED, không có `reason_code`.
    if (!reasonCode && e.errorCode === "QUOTA_TABLE_LOCKED") return LOCKED_MESSAGE
    return quotaConflictText(reasonCode, e.data, ctx)
  }
  if (e.status === 400) {
    if (reasonCode === "quota_table_duplicate") {
      const ma = strs(e.data?.duplicate_group_codes)
      const nganh = ids(e.data?.duplicate_offering_academic_info_ids).map(ctx.labelOf)
      const phan = [
        ma.length ? `mã nhóm trùng: ${ma.join(", ")}` : "",
        nganh.length ? `ngành nằm ở hơn một chỗ: ${nganh.join("; ")}` : "",
      ].filter(Boolean)
      return `Chưa lưu được — ${phan.join(" · ") || "có mã nhóm trùng hoặc một ngành nằm ở hơn một chỗ"}.`
    }
    if (reasonCode === "quota_table_bad_member") {
      const nganh = ids(e.data?.offering_academic_info_ids).map(ctx.labelOf)
      return `Chưa lưu được — ngành không thuộc năm ${ctx.year} (không tồn tại, đã xoá hoặc khác năm): ${nganh.join("; ") || "không rõ"}.`
    }
    return "Chưa lưu được — thông tin bảng chỉ tiêu không hợp lệ."
  }
  if (e.status === 422) {
    const raw = Array.isArray(e.data?.errors) ? (e.data?.errors as unknown[]) : []
    const cau = raw
      .map((x) => {
        const o = x && typeof x === "object" ? (x as Record<string, unknown>) : {}
        return issueText({ loc: Array.isArray(o.loc) ? o.loc : [], msg: typeof o.msg === "string" ? o.msg : undefined }, ctx)
      })
      .filter((x): x is string => Boolean(x))
    const duyNhat = Array.from(new Set(cau))
    return duyNhat.length ? `Chưa lưu được: ${duyNhat.join(" ")}` : "Thông tin chưa hợp lệ — kiểm tra lại các ô."
  }
  if (e.status === 403) return "Chỉ Admin được xem / sửa / khoá bảng chỉ tiêu năm."
  if (e.status === 404) return isQuotaTableNotFound(e) ? `Năm ${ctx.year} chưa có bảng chỉ tiêu.` : QUOTA_TABLE_NO_ACCESS_MESSAGE
  if (e.status === 429) return "Thao tác quá nhanh — thử lại sau ít phút."
  return "Máy chủ gặp lỗi — thử lại sau."
}
