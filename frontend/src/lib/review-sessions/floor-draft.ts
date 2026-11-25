/**
 * GĐ2-B F2 — bản soạn điểm sàn của màn M3 (thiết kế giao diện GĐ2-B §3.4; phụ lục HĐ4 E10 §1.1). CHỈ trình bày + gom thân gửi đi,
 * KHÔNG luật nghiệp vụ (`frontend/CLAUDE.md` thin client; đính chính §3, đính chính 2):
 *  - nhóm "Cần nhập sàn" đọc CỜ máy chủ `floor_applicable` — KHÔNG suy từ `state` / chỉ tiêu / nhóm; hai nhóm còn lại đọc NGUYÊN
 *    `state` máy chủ (bảng "ánh xạ nhóm" của phụ lục E10); `state` lạ ⇒ nhóm "khác", không đoán;
 *  - ô nhập và dòng được gửi đọc CỜ `floor_accepted` (cùng vị từ E4 `review_floor_bad_member`); dòng không nhận được mà còn mức
 *    đang lưu bị BỎ khi lưu (phụ lục E10 §1.1, dòng "khi Lưu");
 *  - kiểm DẠNG điểm theo HĐ4 §1.4 / HĐ3 — ≥ 0, ≤ 2 chữ số thập phân, ≤ 999,99 (cùng mẫu máy chủ `_SCORE_IN_TEXT`, nhận thêm dấu phẩy
 *    — chuẩn hoá dấu thập phân là trình bày [ĐX thiết kế §3.4]); gửi CHUỖI dấu chấm đúng hai chữ số ("15,5" ⇒ "15.50"). Ô trống =
 *    không có sàn (bỏ khỏi danh sách gửi) — KHÔNG thành 0.
 *
 * Bản soạn = CHỈ những ô người dùng đã gõ (`overrides`, theo id học vụ); ô chưa gõ hiện mức ĐANG lưu của E10 (của CHÍNH lần xét — không
 * chép từ lần xét trước, owner G10). Bản soạn do màn cha giữ (khuôn F01-4) ⇒ sống qua lúc E3 / E10 tải lại lỗi; chỉ xoá khi lưu thành
 * công hoặc người dùng bấm "Bỏ thay đổi" / "Dùng bản mới".
 */
import type { ReviewFloor, ReviewFloorCandidate, ReviewFloorIn } from "@/lib/zod/review-sessions"

// ═══════════════════════════════════════ dạng điểm ═══════════════════════════════════════
/** Ô nhập: 1–3 chữ số phần nguyên, tối đa 2 chữ số thập phân, dấu chấm HOẶC phẩy; chỉ chữ số ASCII (như máy chủ). */
export const FLOOR_INPUT_PATTERN = /^([0-9]{1,3})(?:[.,]([0-9]{1,2}))?$/

export type FloorInput = { kind: "empty" } | { kind: "ok"; value: string } | { kind: "invalid" }

/** Chuẩn hoá MỘT ô: trống ⇒ `empty`; đúng dạng ⇒ chuỗi gửi đi "NNN.DD"; còn lại ⇒ `invalid`. Không đổi sang số thực. */
export function normalizeFloorInput(raw: string): FloorInput {
  const s = raw.trim()
  if (s === "") return { kind: "empty" }
  const m = FLOOR_INPUT_PATTERN.exec(s)
  if (!m) return { kind: "invalid" }
  const whole = m[1].replace(/^0+(?=[0-9])/, "")
  const frac = (m[2] ?? "").padEnd(2, "0")
  return { kind: "ok", value: `${whole}.${frac}` }
}

/** Chuỗi điểm máy chủ ("18.25") ⇒ chữ hiển thị dấu phẩy ("18,25") [ĐX thiết kế §3.4]. Không làm tròn, không đổi sang số. */
export function floorScoreDisplay(score: string): string {
  return score.replace(".", ",")
}

// ═══════════════════════════════════════ bản soạn ═══════════════════════════════════════
export interface FloorDraft {
  /** ô người dùng đã gõ, theo `offering_academic_info_id` — chuỗi NGUYÊN như đã gõ ("" = bỏ mức của dòng ấy) */
  overrides: Readonly<Record<number, string>>
  /** vừa gặp 409 `REVIEW_SESSION_STALE` ⇒ hiện bảng so cho tới khi người dùng chọn "Dùng bản mới" / lưu thành công */
  staleConflict: boolean
  /** id học vụ máy chủ chỉ ra (400 `review_floor_bad_member` / `review_floor_duplicate`, 422 theo `loc`) ⇒ tô đỏ */
  flaggedIds: readonly number[]
}

export const EMPTY_FLOOR_DRAFT: FloorDraft = { overrides: {}, staleConflict: false, flaggedIds: [] }

/** Chữ của ô một dòng: người dùng đã gõ ⇒ đúng chữ ấy; chưa gõ ⇒ mức ĐANG lưu (E10) hoặc trống. */
export function floorDraftText(item: ReviewFloorCandidate, overrides: FloorDraft["overrides"]): string {
  const own: string | undefined = overrides[item.offering_academic_info_id]
  if (own !== undefined) return own
  return item.floor_score === null ? "" : floorScoreDisplay(item.floor_score)
}

export interface FloorsPlan {
  /** thân `floors` của E4 — TOÀN BỘ danh sách (thay toàn bộ), sắp id tăng như `SessionOut.floors` */
  floors: ReviewFloorIn[]
  /** dòng nhận sàn được mà ô sai dạng ⇒ khoá "Lưu" */
  invalidIds: number[]
  /** dòng máy chủ báo KHÔNG nhận được (`floor_accepted = false`) mà còn mức đang lưu ⇒ bỏ khi lưu */
  droppedIds: number[]
}

/** Gom thân gửi E4 từ E10 + bản soạn. Chỉ dòng `floor_accepted`; ô trống ⇒ không gửi dòng ấy. */
export function buildFloorsPlan(items: readonly ReviewFloorCandidate[], overrides: FloorDraft["overrides"]): FloorsPlan {
  const floors: ReviewFloorIn[] = []
  const invalidIds: number[] = []
  const droppedIds: number[] = []
  for (const item of items) {
    const id = item.offering_academic_info_id
    if (!item.floor_accepted) {
      if (item.floor_score !== null) droppedIds.push(id)
      continue
    }
    const v = normalizeFloorInput(floorDraftText(item, overrides))
    if (v.kind === "invalid") invalidIds.push(id)
    else if (v.kind === "ok") floors.push({ offering_academic_info_id: id, floor_score: v.value })
  }
  floors.sort((a, b) => a.offering_academic_info_id - b.offering_academic_info_id)
  return { floors, invalidIds, droppedIds }
}

export interface FloorConflict {
  item: ReviewFloorCandidate
  /** chữ người dùng đang soạn (nguyên văn) */
  mine: string
  /** mức vừa lưu ở nơi khác (E10 mới) — `null` = không có sàn */
  saved: string | null
}

/** Sau 409 STALE: những dòng NGƯỜI DÙNG ĐÃ SỬA mà khác mức vừa lưu ở nơi khác (so chuỗi đã chuẩn hoá — không so số). */
export function floorDraftConflicts(
  items: readonly ReviewFloorCandidate[],
  overrides: FloorDraft["overrides"],
): FloorConflict[] {
  const out: FloorConflict[] = []
  for (const item of items) {
    if (!item.floor_accepted) continue
    const mine: string | undefined = overrides[item.offering_academic_info_id]
    if (mine === undefined) continue
    const v = normalizeFloorInput(mine)
    const mineValue = v.kind === "ok" ? v.value : v.kind === "empty" ? null : mine
    if (mineValue !== item.floor_score) out.push({ item, mine, saved: item.floor_score })
  }
  return out
}

// ═══════════════════════════════════════ nhóm hiển thị ═══════════════════════════════════════
export const FLOOR_GROUP_KEYS = ["needs_floor", "closed", "not_reviewable", "other"] as const
export type FloorGroupKey = (typeof FLOOR_GROUP_KEYS)[number]

/** Phụ lục E10 §1.1 "ánh xạ nhóm": ba `state` của nhóm "Không xét được". */
const NOT_REVIEWABLE_STATES: readonly string[] = ["quota_not_configured", "group_missing", "deleted"]

export interface FloorGroup {
  key: FloorGroupKey
  items: ReviewFloorCandidate[]
}

/**
 * Nhóm dòng E10 để HIỂN THỊ, giữ thứ tự máy chủ trong từng nhóm. "Cần nhập sàn" = CỜ `floor_applicable` (máy chủ tính — giao diện
 * không tự đoán từ `state`); dòng không áp dụng: `state` `quota_closed` ⇒ "đã đóng"; ba `state` "không xét được"; còn lại ⇒ "khác".
 */
export function groupFloorCandidates(items: readonly ReviewFloorCandidate[]): FloorGroup[] {
  const groups: Record<FloorGroupKey, ReviewFloorCandidate[]> = { needs_floor: [], closed: [], not_reviewable: [], other: [] }
  for (const item of items) {
    if (item.floor_applicable) groups.needs_floor.push(item)
    else if (item.state === "quota_closed") groups.closed.push(item)
    else if (NOT_REVIEWABLE_STATES.includes(item.state)) groups.not_reviewable.push(item)
    else groups.other.push(item)
  }
  return FLOOR_GROUP_KEYS.map((key) => ({ key, items: groups[key] }))
}

// ═══════════════════════════════════════ đọc thân lỗi E4 ═══════════════════════════════════════
/** Mảng id công khai trong thân lỗi 400 (`offering_academic_info_ids`, `duplicate_offering_academic_info_ids`). */
export function idListFrom(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((x): x is number => typeof x === "number" && Number.isInteger(x)) : []
}

/**
 * 422 — `errors[].loc` của máy chủ GIỮ chỉ số phần tử (`["body", "floors", 3, "floor_score"]`); `readApiError` chỉ giữ phần chuỗi
 * nên đọc thẳng `errors` của thân. Chỉ số ⇒ id của dòng đã gửi ở đúng vị trí ấy.
 */
export function floorIdsFromValidation(data: Record<string, unknown> | undefined, sentIds: readonly number[]): number[] {
  const raw = data?.errors
  const errors: unknown[] = Array.isArray(raw) ? raw : []
  const out = new Set<number>()
  for (const e of errors) {
    const loc = e && typeof e === "object" && Array.isArray((e as { loc?: unknown }).loc) ? (e as { loc: unknown[] }).loc : []
    const at = loc.indexOf("floors")
    const idx = at >= 0 ? loc[at + 1] : undefined
    if (typeof idx === "number" && Number.isInteger(idx) && idx >= 0 && idx < sentIds.length) out.add(sentIds[idx])
  }
  return [...out].sort((a, b) => a - b)
}

// ═══════════════════════════════════════ owner G2 — một dòng "lưu lần cuối" ═══════════════════════════════════════
/**
 * Owner G2: MỘT dòng chung "lưu lần cuối bởi … lúc …", không cột "ai sửa" cho từng dòng. E4 thay toàn bộ (xoá hết rồi chèn —
 * BGL4 D2) nên mọi `FloorOut` mang cùng người / lúc của lần lưu gần nhất; lấy dòng `updated_at` muộn nhất cho chắc. `[]` ⇒ `null`.
 */
export function lastFloorSave(floors: readonly ReviewFloor[]): { userId: number; at: string } | null {
  let best: ReviewFloor | null = null
  for (const f of floors) {
    if (best === null || Date.parse(f.updated_at) > Date.parse(best.updated_at)) best = f
  }
  return best === null ? null : { userId: best.updated_by_user_id, at: best.updated_at }
}
