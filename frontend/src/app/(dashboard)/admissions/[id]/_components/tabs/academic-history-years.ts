/**
 * Lịch sử học tập — sinh dòng "thêm nhanh" và nhắc nhẹ về năm học.
 *
 * Owner 22-11 (`gd2/g5/QUYET-DINH-OWNER-G5-NUT-THEM-NHANH-VA-DO-2026-11-22.md`
 * mục B): cán bộ gõ NĂM BẮT ĐẦU của lớp đầu cấp (số đầu của "Năm học
 * 2022–2023" trên học bạ); mỗi lớp một dòng `Y → Y+1`.
 *
 * Quy ước năm — giống phía tính KV (`priority_service.kv_entry_school_years`):
 * một dòng `year_from → year_to` là năm vào học → năm học xong, gồm các năm học
 * BẮT ĐẦU từ `year_from` tới `year_to − 1`. Vd 2022 → 2025 = năm học
 * 2022–2023, 2023–2024, 2024–2025.
 *
 * Tầng giao diện CHỈ giúp nhập và nhắc (không chặn lưu / nộp); KV do backend
 * tính.
 */

import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

/** Một dòng của mảng `academic_history` trong form. */
export type AcademicRow = NonNullable<AdmissionProfileUpdateInput["academic_history"]>[number]

// Dải lớp theo cấp học — nguồn DUY NHẤT cho quick-add + phân loại notices,
// tránh magic number rải rác (vd đổi range quick-add nhưng quên đổi filter
// notices → lệch âm thầm). graduationType gán cho mọi lớp của cấp.
export const GRADE_BANDS = {
  THCS: { start: 6, end: 9, graduationType: "THCS" },
  THPT: { start: 10, end: 12, graduationType: "THPT" },
} as const

export type GradeBand = (typeof GRADE_BANDS)[keyof typeof GRADE_BANDS]

export const bandYears = (b: { start: number; end: number }) => b.end - b.start + 1
export const bandGradesLabel = (b: { start: number; end: number }) =>
  Array.from({ length: bandYears(b) }, (_, i) => b.start + i).join("/")

// Khớp `academicRecordSchema` (năm 1900–2100).
const MIN_YEAR = 1900
const MAX_YEAR = 2100

/** "2022" ⇒ "2022–2023". */
export const schoolYearLabel = (startYear: number) => `${startYear}–${startYear + 1}`

const isYear = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v)

/**
 * Năm bắt đầu lớp đầu cấp gõ vào ô ⇒ số, hoặc `null` khi không hợp lệ: đúng 4
 * chữ số, và mọi dòng sinh ra nằm trong 1900–2100.
 */
export function parseBandStartYear(band: GradeBand, raw: string): number | null {
  const text = raw.trim()
  if (!/^\d{4}$/.test(text)) return null
  const year = Number(text)
  if (year < MIN_YEAR || year + bandYears(band) > MAX_YEAR) return null
  return year
}

/** Năm tốt nghiệp của cấp = năm học xong lớp cuối. Vd THPT bắt đầu 2022 ⇒ 2025. */
export const bandGraduationYear = (band: GradeBand, startYear: number) => startYear + bandYears(band)

/** Mỗi lớp một dòng: lớp đầu `startYear → startYear+1`, lớp kế tiếp +1 năm. */
export function buildBandRecords(band: GradeBand, startYear: number): AcademicRow[] {
  return Array.from({ length: bandYears(band) }, (_, i) => ({
    school_id: null,
    school_name: "",
    level: null,
    year_from: startYear + i,
    year_to: startYear + i + 1,
    grade_to: band.start + i,
    gpa: null,
    graduation_type: band.graduationType,
  }))
}

/** Câu xem trước: "Lớp 10: 2022–2023, lớp 11: 2023–2024, lớp 12: 2024–2025." */
export function bandPreviewLabel(band: GradeBand, startYear: number): string {
  const parts = Array.from(
    { length: bandYears(band) },
    (_, i) => `lớp ${band.start + i}: ${schoolYearLabel(startYear + i)}`,
  )
  const text = parts.join(", ")
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`
}

/**
 * Gợi ý năm bắt đầu lớp 6 khi hồ sơ đã có dòng THPT: năm bắt đầu lớp 10 − 4.
 * Năm bắt đầu lớp 10 = `year_from` SỚM NHẤT của các dòng lớp cuối 10–12. Không
 * có dòng THPT / năm gợi ý ra ngoài 1900–2100 ⇒ `null`.
 */
export function suggestThcsStartYear(
  rows: ReadonlyArray<{ grade_to?: number | null; year_from?: number | null } | null | undefined>,
): number | null {
  const thptStarts: number[] = []
  for (const r of rows) {
    if (!r || r.grade_to == null) continue
    const start = r.year_from
    if (r.grade_to >= GRADE_BANDS.THPT.start && r.grade_to <= GRADE_BANDS.THPT.end && isYear(start)) {
      thptStarts.push(start)
    }
  }
  if (thptStarts.length === 0) return null
  const year = Math.min(...thptStarts) - bandYears(GRADE_BANDS.THCS)
  return parseBandStartYear(GRADE_BANDS.THCS, String(year))
}

/**
 * Nhắc nhẹ về năm học (không chặn): dòng 0 năm học, hai dòng trùng năm học, hở
 * năm học giữa các dòng. "Trường #n" = thứ tự hiển thị trên màn hình.
 */
export function yearNotices(
  rows: ReadonlyArray<{ year_from?: number | null; year_to?: number | null } | null | undefined>,
): string[] {
  const notices: string[] = []
  const spans: Array<{ no: number; from: number; to: number }> = []

  rows.forEach((r, i) => {
    if (!r) return
    const from = r.year_from
    const to = r.year_to
    if (!isYear(from) || !isYear(to)) return
    if (from === to) {
      notices.push(
        `Trường #${i + 1}: "Từ năm" và "Đến năm" đều là ${from}, chưa có năm học nào. Một năm học ghi hai năm liền nhau, vd năm học ${schoolYearLabel(from - 1)} ghi ${from - 1} → ${from}; đối chiếu học bạ.`,
      )
    } else if (to > from) {
      spans.push({ no: i + 1, from, to })
    }
  })

  // Trùng năm học: năm học y thuộc dòng khi from ≤ y < to.
  for (let a = 0; a < spans.length; a++) {
    for (let b = a + 1; b < spans.length; b++) {
      const first = Math.max(spans[a].from, spans[b].from)
      const last = Math.min(spans[a].to, spans[b].to) - 1
      if (first > last) continue
      const years = Array.from({ length: last - first + 1 }, (_, k) => schoolYearLabel(first + k))
      notices.push(
        `Trường #${spans[a].no} và #${spans[b].no} cùng có năm học ${years.join(", ")} — xem lại nếu không phải chuyển trường giữa năm.`,
      )
    }
  }

  // Hở năm học: giữa các dòng (xếp theo năm bắt đầu) có năm học không thuộc dòng nào.
  const sorted = [...spans].sort((x, y) => x.from - y.from || x.no - y.no)
  let reach = sorted.length ? sorted[0].to : 0
  let reachNo = sorted.length ? sorted[0].no : 0
  for (const s of sorted.slice(1)) {
    if (s.from > reach) {
      const gap =
        s.from - reach === 1
          ? schoolYearLabel(reach)
          : `${schoolYearLabel(reach)} đến ${schoolYearLabel(s.from - 1)}`
      notices.push(`Hở năm học ${gap} (giữa Trường #${reachNo} và #${s.no}) — bỏ qua nếu em nghỉ học thời gian đó.`)
    }
    if (s.to > reach) {
      reach = s.to
      reachNo = s.no
    }
  }

  return notices
}
