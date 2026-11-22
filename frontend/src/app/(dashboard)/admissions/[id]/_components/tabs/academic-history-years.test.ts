/**
 * academic-history-years — hàm thuần của nút thêm nhanh + nhắc nhẹ năm học
 * (owner 22-11, `gd2/g5/QUYET-DINH-OWNER-G5-NUT-THEM-NHANH-VA-DO-2026-11-22.md`
 * mục B). Quy ước năm giống phía tính KV: dòng a → b gồm năm học a … b − 1.
 */

import { describe, it, expect } from "vitest"
import {
  GRADE_BANDS,
  bandGraduationYear,
  bandPreviewLabel,
  buildBandRecords,
  YEAR_INPUT_HINT,
  isMergedLienCapRow,
  lienCapMissingGradeNotices,
  mergedLienCapNotices,
  parseBandStartYear,
  rowSchoolYearsLabel,
  suggestThcsStartYear,
  yearNotices,
} from "./academic-history-years"

describe("buildBandRecords / bandGraduationYear", () => {
  it("THPT bắt đầu 2022 ⇒ 2022→2023, 2023→2024, 2024→2025 (lớp 10/11/12), tốt nghiệp 2025", () => {
    expect(buildBandRecords(GRADE_BANDS.THPT, 2022)).toEqual([
      { school_id: null, school_name: "", level: null, year_from: 2022, year_to: 2023, grade_to: 10, gpa: null, graduation_type: "THPT" },
      { school_id: null, school_name: "", level: null, year_from: 2023, year_to: 2024, grade_to: 11, gpa: null, graduation_type: "THPT" },
      { school_id: null, school_name: "", level: null, year_from: 2024, year_to: 2025, grade_to: 12, gpa: null, graduation_type: "THPT" },
    ])
    expect(bandGraduationYear(GRADE_BANDS.THPT, 2022)).toBe(2025)
  })

  it("THCS bắt đầu 2018 ⇒ 4 dòng một năm, hết lớp 9 năm 2022", () => {
    const rows = buildBandRecords(GRADE_BANDS.THCS, 2018)
    expect(rows.map((r) => [r.grade_to, r.year_from, r.year_to])).toEqual([
      [6, 2018, 2019],
      [7, 2019, 2020],
      [8, 2020, 2021],
      [9, 2021, 2022],
    ])
    expect(bandGraduationYear(GRADE_BANDS.THCS, 2018)).toBe(2022)
  })

  it("mọi dòng sinh ra đều có year_to = year_from + 1 (không còn dòng 0 năm)", () => {
    for (const band of [GRADE_BANDS.THPT, GRADE_BANDS.THCS]) {
      for (const r of buildBandRecords(band, 2000)) expect(r.year_to).toBe(r.year_from + 1)
    }
  })

  it("câu xem trước", () => {
    expect(bandPreviewLabel(GRADE_BANDS.THPT, 2022)).toBe("Lớp 10: 2022–2023, lớp 11: 2023–2024, lớp 12: 2024–2025.")
  })
})

describe("parseBandStartYear", () => {
  it("chỉ nhận 4 chữ số và giữ mọi dòng trong 1900–2100", () => {
    expect(parseBandStartYear(GRADE_BANDS.THPT, " 2022 ")).toBe(2022)
    expect(parseBandStartYear(GRADE_BANDS.THPT, "")).toBeNull()
    expect(parseBandStartYear(GRADE_BANDS.THPT, "22")).toBeNull()
    expect(parseBandStartYear(GRADE_BANDS.THPT, "2022.5")).toBeNull()
    expect(parseBandStartYear(GRADE_BANDS.THPT, "1899")).toBeNull()
    expect(parseBandStartYear(GRADE_BANDS.THPT, "1900")).toBe(1900)
    expect(parseBandStartYear(GRADE_BANDS.THPT, "2097")).toBe(2097) // lớp 12: 2099 → 2100
    expect(parseBandStartYear(GRADE_BANDS.THPT, "2098")).toBeNull()
    expect(parseBandStartYear(GRADE_BANDS.THCS, "2096")).toBe(2096)
    expect(parseBandStartYear(GRADE_BANDS.THCS, "2097")).toBeNull()
  })
})

describe("suggestThcsStartYear", () => {
  it("năm bắt đầu lớp 10 SỚM NHẤT suy từ các dòng THPT, trừ 4", () => {
    expect(
      suggestThcsStartYear([
        { grade_to: 11, year_from: 2023, year_to: 2024 },
        { grade_to: 10, year_from: 2022, year_to: 2023 },
        { grade_to: 9, year_from: 2015, year_to: 2016 },
      ]),
    ).toBe(2018)
  })

  it("vào trường ở lớp 11 (chỉ có dòng 2023 → 2025, lớp 12) ⇒ lớp 10 bắt đầu 2022 ⇒ gợi ý 2018 (không lệch 1 năm)", () => {
    expect(suggestThcsStartYear([{ level: "THPT", grade_to: 12, year_from: 2023, year_to: 2025 }])).toBe(2018)
  })

  it("ở lại lớp ghi một dòng 2021 → 2025 lớp 12 ⇒ lớp 10 bắt đầu 2021 ⇒ gợi ý 2017", () => {
    expect(suggestThcsStartYear([{ level: "THPT", grade_to: 12, year_from: 2021, year_to: 2025 }])).toBe(2017)
  })

  it("BỎ dòng liên cấp (dòng gộp từ lớp 6 làm lệch phép suy) và dòng 0 năm", () => {
    expect(suggestThcsStartYear([{ level: "THCS_THPT", grade_to: 12, year_from: 2016, year_to: 2023 }])).toBeNull()
    expect(suggestThcsStartYear([{ level: "THPT", grade_to: 12, year_from: 2025, year_to: 2025 }])).toBeNull()
    expect(
      suggestThcsStartYear([
        { level: "THCS_THPT", grade_to: 12, year_from: 2016, year_to: 2023 },
        { level: "THPT", grade_to: 12, year_from: 2022, year_to: 2025 },
      ]),
    ).toBe(2018)
  })

  it("chưa có dòng THPT đủ năm ⇒ không gợi ý", () => {
    expect(suggestThcsStartYear([])).toBeNull()
    expect(
      suggestThcsStartYear([
        { grade_to: 9, year_from: 2015, year_to: 2016 },
        { grade_to: 10, year_from: null, year_to: 2023 },
        { grade_to: 10, year_from: 2022, year_to: null },
        null,
      ]),
    ).toBeNull()
  })
})

describe("yearNotices", () => {
  it("dòng liền mạch ⇒ không nhắc", () => {
    expect(yearNotices(buildBandRecords(GRADE_BANDS.THPT, 2022))).toEqual([])
  })

  it("dòng 0 năm không bị tính là trùng hay hở; dòng năm ngược / thiếu năm bỏ qua", () => {
    expect(
      yearNotices([
        { year_from: 2022, year_to: 2025 },
        { year_from: 2024, year_to: 2024 },
        { year_from: 2026, year_to: 2023 },
        { year_from: null, year_to: 2025 },
        undefined,
      ]),
    ).toEqual([
      'Trường #2: "Từ năm" và "Đến năm" cùng là 2024 — theo cách ghi năm học hiện nay, dòng này chưa có năm học nào.',
    ])
  })

  it("trùng nhiều năm học ⇒ liệt kê từng năm", () => {
    expect(yearNotices([{ year_from: 2020, year_to: 2023 }, { year_from: 2021, year_to: 2024 }])).toEqual([
      "Trường #1 và #2 cùng có năm học 2021–2022, 2022–2023 — xem lại nếu không phải chuyển trường giữa năm.",
    ])
  })

  it("hở năm học tính theo dòng vươn xa nhất, không theo dòng liền trước", () => {
    // #1 2016→2023 phủ hết #2 2019→2020 (trùng 2019–2020) ⇒ #3 2023→2024 nối liền #1, không hở.
    expect(
      yearNotices([
        { year_from: 2016, year_to: 2023 },
        { year_from: 2019, year_to: 2020 },
        { year_from: 2023, year_to: 2024 },
      ]),
    ).toEqual(["Trường #1 và #2 cùng có năm học 2019–2020 — xem lại nếu không phải chuyển trường giữa năm."])
  })
})

describe("yearNotices — năm gõ dở, dòng thiếu năm (Codex G5 lượt 2 P2)", () => {
  it("năm gõ dở (202) không phải năm hợp lệ ⇒ không nhắc trùng / 0 năm với năm vô lý", () => {
    expect(yearNotices([{ year_from: 202, year_to: 2023 }, { year_from: 2022, year_to: 2023 }])).toEqual([])
    expect(yearNotices([{ year_from: 202, year_to: 202 }])).toEqual([])
  })

  it("dòng thiếu Đến năm nằm giữa ⇒ KHÔNG báo hở giữa hai dòng kề nó", () => {
    expect(
      yearNotices([
        { year_from: 2021, year_to: 2022 },
        { year_from: 2022, year_to: null },
        { year_from: 2023, year_to: 2024 },
      ]),
    ).toEqual([])
  })

  it("đủ năm mọi dòng thì vẫn báo hở (đối chứng)", () => {
    expect(
      yearNotices([
        { year_from: 2021, year_to: 2022 },
        { year_from: 2023, year_to: 2024 },
      ]),
    ).toEqual(["Hở năm học 2022–2023 (giữa Trường #1 và #2) — bỏ qua nếu em nghỉ học thời gian đó."])
  })
})

describe("rowSchoolYearsLabel / YEAR_INPUT_HINT (owner 'điểm 1 và 2' việc 2)", () => {
  it("câu giải thích cách ghi năm", () => {
    expect(YEAR_INPUT_HINT).toBe("Năm học 2022–2023 ghi 2022 → 2023.")
  })

  it("xem trước năm học của một dòng theo quy ước a … b − 1", () => {
    expect(rowSchoolYearsLabel({ year_from: 2022, year_to: 2023 })).toBe("Dòng này: năm học 2022–2023.")
    expect(rowSchoolYearsLabel({ year_from: 2022, year_to: 2025 })).toBe(
      "Dòng này: năm học 2022–2023, 2023–2024, 2024–2025.",
    )
    expect(rowSchoolYearsLabel({ year_from: 2016, year_to: 2023 })).toBe(
      "Dòng này: 7 năm học, 2016–2017 đến 2022–2023.",
    )
    expect(rowSchoolYearsLabel({ year_from: 2025, year_to: 2025 })).toBe("Dòng này: chưa có năm học nào.")
    expect(rowSchoolYearsLabel({ year_from: 2025, year_to: 2024 })).toBeNull()
    expect(rowSchoolYearsLabel({ year_from: 2022, year_to: undefined })).toBeNull()
    expect(rowSchoolYearsLabel({ year_from: 202, year_to: 2023 })).toBeNull()
  })
})

describe("lienCapMissingGradeNotices (Codex G5 lượt 2 P2)", () => {
  it("dòng liên cấp thiếu / sai Lớp cuối ⇒ nhắc; đủ lớp hoặc không phải liên cấp ⇒ không", () => {
    expect(
      lienCapMissingGradeNotices([
        { level: "THPT", grade_to: null },
        { level: "THCS_THPT", grade_to: null },
        { level: "THCS_THPT", grade_to: 12 },
        { level: "THCS_THPT", grade_to: 9 },
        { level: "THCS_THPT", grade_to: 13 },
        null,
      ]),
    ).toEqual([
      'Trường #2 là trường liên cấp: cần ghi "Lớp cuối" (lớp cuối cùng em học ở trường này) để tính được khu vực.',
      'Trường #5 là trường liên cấp: cần ghi "Lớp cuối" (lớp cuối cùng em học ở trường này) để tính được khu vực.',
    ])
  })
})

describe("isMergedLienCapRow / mergedLienCapNotices — phản chiếu Q8 ('3 năm cuối') của phía tính KV", () => {
  const lc = (year_from: number | null, year_to: number | null, grade_to: number | null, level = "THCS_THPT") => ({
    level,
    year_from,
    year_to,
    grade_to,
  })

  it("bật khi số năm của dòng liên cấp vượt phần lớp 10..lớp cuối; không bật ở biên và các ca khác", () => {
    expect(isMergedLienCapRow(lc(2015, 2023, 12))).toBe(true) // 8 > 3
    expect(isMergedLienCapRow(lc(2015, 2022, 10))).toBe(true) // 7 > 1
    expect(isMergedLienCapRow(lc(2016, 2022, 11))).toBe(true) // 6 > 2
    expect(isMergedLienCapRow(lc(2020, 2023, 12))).toBe(false) // 3 = 3: đúng biên
    expect(isMergedLienCapRow(lc(2021, 2022, 10))).toBe(false) // 1 = 1: đúng biên
    expect(isMergedLienCapRow(lc(2022, 2023, 12))).toBe(false) // vào ở lớp 12
    expect(isMergedLienCapRow(lc(2021, 2025, 12, "THPT"))).toBe(false) // THPT tính đủ mọi năm
    expect(isMergedLienCapRow(lc(2015, 2020, 9))).toBe(false) // lớp cuối ≤ 9: không có phần THPT
    expect(isMergedLienCapRow(lc(2015, 2023, null))).toBe(false) // thiếu lớp cuối: phía tính tự dừng có nhãn
    expect(isMergedLienCapRow(lc(null, 2023, 12))).toBe(false)
    expect(isMergedLienCapRow(null)).toBe(false)
  })

  it("câu nhắc đánh số theo thứ tự dòng trên màn hình", () => {
    expect(mergedLienCapNotices([lc(2019, 2022, 12, "THPT"), lc(2015, 2023, 12)])).toEqual([
      "Trường #2 là trường liên cấp ghi gộp nhiều năm: khu vực chỉ tính các năm cuối từ lớp 10 trở lên. Nếu em ở lại lớp ở cấp 3, tách mỗi năm học một dòng.",
    ])
  })
})
