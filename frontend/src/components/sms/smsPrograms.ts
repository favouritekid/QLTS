// src/components/sms/smsPrograms.ts
// Logic gom/khử-trùng ngành cho landing 2 tầng (THUẦN dữ liệu, không JSX).
// Quy tắc "biến thể cùng TÊN (CĐ/TC) = 1 ngành" sống DUY NHẤT ở đây: tier-1
// gộp thành card có nhiều chip trình độ (`groupPrograms`), tier-2 "Các ngành
// khác" lấy đại diện đầu mỗi tên (`dedupeByName`). Đổi luật → sửa 1 file.
import type { LucideIcon } from "lucide-react"

import type { SmsLandingProgram } from "@/lib/zod/sms"

import { programGlyph } from "./programIcon"
import {
  GROUP_ORDER,
  programEditorial,
  tuitionTier,
  type TuitionLevel,
} from "./smsContent"

/** 1 biến thể trình độ của 1 ngành (CĐ/TC cùng tên) — giữ id riêng để đo dwell §16. */
export type ProgramVariant = { id: number; degreeLevel: string; code: string }

/** View-model 1 card ngành (đã GỘP theo TÊN). Icon resolve SẴN (component chỉ
 *  member-access, thoả react-compiler). `level` = mức ưu đãi học phí MẠNH NHẤT
 *  trong các biến thể (suy từ học phí thật) → quyết badge card. */
export type ProgramCardVM = {
  name: string
  Icon: LucideIcon
  level: TuitionLevel
  variants: ProgramVariant[]
}

// Thứ tự ưu tiên mức ưu đãi (mạnh nhất thắng khi gộp biến thể).
const TUITION_RANK: Record<"free" | "70" | "30", number> = {
  free: 3,
  "70": 2,
  "30": 1,
}

/** Gom ngành BE: nhóm theo group editorial (GROUP_ORDER), rồi GỘP theo TÊN
 *  (biến thể CĐ/TC cùng tên = 1 card, mỗi biến thể 1 chip link riêng). Nhóm lạ
 *  (ngoài GROUP_ORDER) gom cuối để không rớt ngành. */
export function groupPrograms(
  programs: readonly SmsLandingProgram[],
): { group: string; items: ProgramCardVM[] }[] {
  // group -> (tên -> card); Map giữ thứ tự chèn (first-seen) trong mỗi nhóm.
  const byGroup = new Map<string, Map<string, ProgramCardVM>>()
  for (const p of programs) {
    const ed = programEditorial(p.name)
    let cards = byGroup.get(ed.group)
    if (!cards) {
      cards = new Map()
      byGroup.set(ed.group, cards)
    }
    let card = cards.get(p.name)
    if (!card) {
      card = {
        name: p.name,
        Icon: programGlyph(p.name).Icon,
        level: null,
        variants: [],
      }
      cards.set(p.name, card)
    }
    // Mức ưu đãi mạnh nhất giữa các biến thể (miễn 100% > 70% > 30%).
    const lv = tuitionTier(p.code)
    const cur = card.level
    if (lv && (cur === null || TUITION_RANK[lv] > TUITION_RANK[cur])) {
      card.level = lv
    }
    card.variants.push({
      id: p.id,
      degreeLevel: p.degree_level,
      code: p.code,
    })
  }
  const order = [
    ...GROUP_ORDER.filter((g) => byGroup.has(g)),
    ...[...byGroup.keys()].filter((g) => !GROUP_ORDER.includes(g)),
  ]
  return order.map((g) => ({ group: g, items: [...byGroup.get(g)!.values()] }))
}

/** Khử trùng theo TÊN (biến thể cùng tên = 1 mục, giữ mục ĐẦU gặp); loại các
 *  tên trong `exclude`. Dùng cho "Các ngành khác" tier-2. */
export function dedupeByName(
  programs: readonly SmsLandingProgram[],
  exclude: Iterable<string> = [],
): SmsLandingProgram[] {
  const seen = new Set<string>(exclude)
  const out: SmsLandingProgram[] = []
  for (const p of programs) {
    if (seen.has(p.name)) continue
    seen.add(p.name)
    out.push(p)
  }
  return out
}
