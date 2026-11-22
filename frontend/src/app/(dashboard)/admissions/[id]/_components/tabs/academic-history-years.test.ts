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
  parseBandStartYear,
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
  it("năm bắt đầu SỚM NHẤT của dòng lớp 10–12, trừ 4", () => {
    expect(
      suggestThcsStartYear([
        { grade_to: 11, year_from: 2023 },
        { grade_to: 10, year_from: 2022 },
        { grade_to: 9, year_from: 2015 },
      ]),
    ).toBe(2018)
  })

  it("chưa có dòng THPT có năm ⇒ không gợi ý", () => {
    expect(suggestThcsStartYear([])).toBeNull()
    expect(suggestThcsStartYear([{ grade_to: 9, year_from: 2015 }, { grade_to: 10, year_from: null }, null])).toBeNull()
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
      'Trường #2: "Từ năm" và "Đến năm" đều là 2024, chưa có năm học nào. Một năm học ghi hai năm liền nhau, vd năm học 2023–2024 ghi 2023 → 2024; đối chiếu học bạ.',
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
