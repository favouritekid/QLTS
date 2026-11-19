/**
 * GĐ2-F1 — trạng thái soạn thảo bảng chỉ tiêu (ô nhập là CHUỖI) ⇄ thân PUT.
 *
 * Bất biến chính (quyết định owner 19-11 câu 4): ô chỉ tiêu / trần TRỐNG ⇒ gửi `null` (máy chủ từ chối 422 — chưa nhập),
 * KHÔNG BAO GIỜ thành 0. 0 chỉ khi người dùng gõ rõ "0". Không tính toán nghiệp vụ nào ở đây (không cộng chỉ tiêu, không so
 * trần): máy chủ là chốt.
 */
import type { QuotaGroupMemberOut, QuotaTableOut, QuotaTablePut } from "@/lib/zod/quota-tables"

export interface DraftMember {
  offering_academic_info_id: number
  /** Nhãn hiển thị (mã + tên ngành + hình thức) — chỉ để xem. */
  label: string
  /** Ô chỉ tiêu năm, đúng như người dùng gõ; "" = trống. */
  quota: string
}

export interface DraftGroup {
  /** Khoá React ổn định cho nhóm đang soạn (không gửi đi). */
  key: string
  code: string
  name: string
  /** Ô trần nhóm, đúng như người dùng gõ; "" = trống. */
  ceiling: string
  members: DraftMember[]
}

/** Ô số (chuỗi) ⇒ giá trị gửi máy chủ: trống ⇒ `null`; còn lại ⇒ số đúng như gõ (máy chủ kiểm nguyên / ≥ 0). */
export function parseCountInput(raw: string): number | null {
  const s = raw.trim()
  return s === "" ? null : Number(s)
}

/** Giá trị máy chủ ⇒ ô nhập: `null` (chưa có chỉ tiêu) ⇒ "" — không hiện thành "0". */
export function countToInput(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value)
}

export function memberLabel(m: Pick<QuotaGroupMemberOut, "major_code" | "major_name" | "offering_type" | "offering_academic_info_id">): string {
  const ten = [m.major_code, m.major_name].filter((x) => x && x.trim()).join(" — ")
  const base = ten || `Học vụ #${m.offering_academic_info_id}`
  return m.offering_type ? `${base} (${m.offering_type})` : base
}

let seq = 0
export function newGroupKey(): string {
  seq += 1
  return `nhom-moi-${seq}`
}

export function draftFromTable(table: QuotaTableOut | null): DraftGroup[] {
  if (!table) return []
  return table.groups.map((g) => ({
    key: `nhom-${g.id}`,
    code: g.code,
    name: g.name,
    ceiling: countToInput(g.ceiling),
    members: g.members.map((m) => ({
      offering_academic_info_id: m.offering_academic_info_id,
      label: memberLabel(m),
      quota: countToInput(m.annual_admission_quota),
    })),
  }))
}

export function draftToPutBody(version: number, groups: DraftGroup[]): QuotaTablePut {
  return {
    version,
    groups: groups.map((g) => ({
      code: g.code,
      name: g.name,
      ceiling: parseCountInput(g.ceiling),
      members: g.members.map((m) => ({
        offering_academic_info_id: m.offering_academic_info_id,
        annual_admission_quota: parseCountInput(m.quota),
      })),
    })),
  }
}
