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

/** Bậc "liên cấp" (THCS + THPT một trường) — khớp `VN_SCHOOL_LEVELS` / backend `KV_LIEN_CAP_LEVEL`. */
const LIEN_CAP_LEVEL = "THCS_THPT"

export const bandYears = (b: { start: number; end: number }) => b.end - b.start + 1
export const bandGradesLabel = (b: { start: number; end: number }) =>
  Array.from({ length: bandYears(b) }, (_, i) => b.start + i).join("/")

// Khớp `academicRecordSchema` (năm 1900–2100).
const MIN_YEAR = 1900
const MAX_YEAR = 2100

/** "2022" ⇒ "2022–2023". */
export const schoolYearLabel = (startYear: number) => `${startYear}–${startYear + 1}`

const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v)

/** Năm hợp lệ của schema (số nguyên 1900–2100). Số đang gõ dở (vd 202) KHÔNG tính (Codex G5 lượt 2 P2). */
const isYear = (v: unknown): v is number => isInt(v) && v >= MIN_YEAR && v <= MAX_YEAR

/** Dòng giải thích dưới ô "Từ năm" / "Đến năm" (owner "điểm 1 và 2", việc 2). */
export const YEAR_INPUT_HINT = "Năm học 2022–2023 ghi 2022 → 2023."

/**
 * Xem trước năm học của MỘT dòng (owner "điểm 1 và 2", việc 2): cùng quy ước với
 * phía tính KV (dòng a → b gồm năm học a … b − 1). Không suy luật KV (liên cấp
 * cắt phần lớp 10+ là việc của backend). Năm chưa hợp lệ / năm ngược ⇒ `null`.
 */
export function rowSchoolYearsLabel(
  r: { year_from?: number | null; year_to?: number | null } | null | undefined,
): string | null {
  if (!r) return null
  const from = r.year_from
  const to = r.year_to
  if (!isYear(from) || !isYear(to) || to < from) return null
  if (to === from) return "Dòng này: chưa có năm học nào."
  const n = to - from
  if (n <= 4) {
    const years = Array.from({ length: n }, (_, k) => schoolYearLabel(from + k))
    return `Dòng này: năm học ${years.join(", ")}.`
  }
  return `Dòng này: ${n} năm học, ${schoolYearLabel(from)} đến ${schoolYearLabel(to - 1)}.`
}

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
 *
 * Năm bắt đầu lớp 10 suy từ từng dòng THPT lớp cuối g ∈ 10..12, đủ hai năm a < b:
 * lớp đầu tại trường ≈ max(10, g − (b − a) + 1), nên lớp 10 bắt đầu ≈ a − (lớp
 * đầu − 10); lấy giá trị SỚM NHẤT. Vd chỉ có dòng vào trường ở lớp 11 (2023 →
 * 2025, lớp 12) ⇒ lớp 10 bắt đầu 2022 ⇒ gợi ý 2018. BỎ dòng liên cấp (dòng gộp từ
 * lớp 6 làm lệch phép suy, và đã chứa các năm THCS) và dòng 0 năm (chưa rõ năm
 * học — owner chưa quyết) — Codex G5 lượt 2 P1. Không có dòng dùng được / năm gợi
 * ý ra ngoài 1900–2100 ⇒ `null`. Chỉ là gợi ý, có xem trước trước khi bấm.
 */
export function suggestThcsStartYear(
  rows: ReadonlyArray<
    { level?: string | null; grade_to?: number | null; year_from?: number | null; year_to?: number | null } | null | undefined
  >,
): number | null {
  const grade10Starts: number[] = []
  for (const r of rows) {
    if (!r || r.level === LIEN_CAP_LEVEL) continue
    const grade = r.grade_to
    const from = r.year_from
    const to = r.year_to
    if (!isInt(grade) || grade < GRADE_BANDS.THPT.start || grade > GRADE_BANDS.THPT.end) continue
    if (!isYear(from) || !isYear(to) || to <= from) continue
    const firstGrade = Math.max(GRADE_BANDS.THPT.start, grade - (to - from) + 1)
    grade10Starts.push(from - (firstGrade - GRADE_BANDS.THPT.start))
  }
  if (grade10Starts.length === 0) return null
  const year = Math.min(...grade10Starts) - bandYears(GRADE_BANDS.THCS)
  return parseBandStartYear(GRADE_BANDS.THCS, String(year))
}

/**
 * Nhắc nhẹ về năm học (không chặn): dòng 0 năm học, hai dòng trùng năm học, hở
 * năm học giữa các dòng. "Trường #n" = thứ tự hiển thị trên màn hình.
 *
 * Câu "0 năm học" viết TRUNG TÍNH (owner "điểm 1 và 2", việc 3): không gợi ý sửa
 * thành năm nào — owner chưa quyết cách xử lý các dòng y→y đã lưu.
 * Kiểm "hở" chỉ chạy khi MỌI dòng đã có đủ hai năm hợp lệ (a < b): dòng thiếu năm,
 * năm gõ dở, năm ngược hay 0 năm học thì chưa biết dòng ấy phủ năm học nào, báo
 * "hở" giữa hai dòng kề nó sẽ sai (Codex G5 lượt 2 P2).
 */
export function yearNotices(
  rows: ReadonlyArray<{ year_from?: number | null; year_to?: number | null } | null | undefined>,
): string[] {
  const notices: string[] = []
  const spans: Array<{ no: number; from: number; to: number }> = []
  let allRowsKnown = true

  rows.forEach((r, i) => {
    if (!r) return
    const from = r.year_from
    const to = r.year_to
    if (!isYear(from) || !isYear(to) || to <= from) allRowsKnown = false
    if (!isYear(from) || !isYear(to)) return
    if (from === to) {
      notices.push(
        `Trường #${i + 1}: "Từ năm" và "Đến năm" cùng là ${from} — theo cách ghi năm học hiện nay, dòng này chưa có năm học nào.`,
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
  if (!allRowsKnown) return notices
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

/**
 * Dòng LIÊN CẤP ghi gộp nhiều năm (owner 22-11 "ở lại lớp",
 * `gd2/g5/QUYET-DINH-OWNER-G5-O-LAI-LOP-2026-11-22.md` mục 2): cấp liên cấp,
 * lớp cuối g ∈ 10..12, và (Đến năm − Từ năm) > (g − 9).
 *
 * PHẢN CHIẾU Q8 ("Suy 3 năm cuối") của phía tính KV
 * (`priority_service.kv_entry_school_years`): dòng liên cấp chỉ được tính g − 9
 * năm học cuối (phần lớp 10 trở lên). Dữ liệu không có lớp đầu, nên năm ở lại
 * lớp ở cấp 3 nằm trong một dòng gộp sẽ không được tính. Chỉ NHẮC, không chặn;
 * phía tính KV là nguồn chuẩn — đổi luật ở đó thì đổi điều kiện này theo.
 */
export function isMergedLienCapRow(
  r: { level?: string | null; grade_to?: number | null; year_from?: number | null; year_to?: number | null } | null | undefined,
): boolean {
  if (!r || r.level !== LIEN_CAP_LEVEL) return false
  const grade = r.grade_to
  const from = r.year_from
  const to = r.year_to
  if (!isInt(grade) || grade < GRADE_BANDS.THPT.start || grade > GRADE_BANDS.THPT.end) return false
  if (!isYear(from) || !isYear(to)) return false
  return to - from > grade - (GRADE_BANDS.THPT.start - 1)
}

/**
 * Dòng LIÊN CẤP thiếu / sai "Lớp cuối" (Codex G5 lượt 2 P2): phía tính KV DỪNG
 * (`lien_cap_missing_grade_to` — không biết đâu là phần lớp 10+). Nhắc trước để
 * cán bộ không chỉ thấy mã lỗi lúc nộp. Chỉ nhắc, không chặn.
 */
export function lienCapMissingGradeNotices(
  rows: ReadonlyArray<{ level?: string | null; grade_to?: number | null } | null | undefined>,
): string[] {
  const notices: string[] = []
  rows.forEach((r, i) => {
    if (!r || r.level !== LIEN_CAP_LEVEL) return
    const grade = r.grade_to
    if (isInt(grade) && grade >= 1 && grade <= GRADE_BANDS.THPT.end) return
    notices.push(
      `Trường #${i + 1} là trường liên cấp: cần ghi "Lớp cuối" (lớp cuối cùng em học ở trường này) để tính được khu vực.`,
    )
  })
  return notices
}

/** Câu nhắc cho từng dòng liên cấp gộp nhiều năm; "Trường #n" = thứ tự hiển thị. */
export function mergedLienCapNotices(
  rows: ReadonlyArray<Parameters<typeof isMergedLienCapRow>[0]>,
): string[] {
  const notices: string[] = []
  rows.forEach((r, i) => {
    if (isMergedLienCapRow(r))
      notices.push(
        `Trường #${i + 1} là trường liên cấp ghi gộp nhiều năm: khu vực chỉ tính các năm cuối từ lớp 10 trở lên. Nếu em ở lại lớp ở cấp 3, tách mỗi năm học một dòng.`,
      )
  })
  return notices
}
