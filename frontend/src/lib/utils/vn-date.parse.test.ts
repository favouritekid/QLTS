// src/lib/utils/vn-date.parse.test.ts
/**
 * `parseNgayLich` — chuỗi `"YYYY-MM-DD"` giữ nguyên ô lịch của nó.
 *
 * 🔴 File này chạy ở **múi giờ ÂM** (New York), không phải Việt Nam. Đó là
 * toàn bộ lý do nó tồn tại: `new Date("2026-08-05")` được JavaScript parse
 * thành UTC nửa đêm, nên ở múi giờ dương nó vẫn ra ngày 05 và bài kiểm sẽ
 * xanh với cả bản sai. Chỉ ở múi giờ âm hai cách mới tách nhau ra.
 *
 * Cột `Date` trong cơ sở dữ liệu không mang giờ và không mang múi giờ — nó là
 * một ô lịch. Đưa nó qua một phép quy đổi múi giờ là gán cho nó thứ nó không
 * có, rồi nhận về một ô lịch khác.
 */
const TZ_GOC = process.env.TZ
process.env.TZ = "America/New_York"

import { afterAll, describe, it, expect } from "vitest"

import { parseNgayLich } from "./vn-date"

afterAll(() => {
  if (TZ_GOC === undefined) delete process.env.TZ
  else process.env.TZ = TZ_GOC
})

describe("parseNgayLich", () => {
  it("guard: bộ test chạy ở múi giờ ÂM, nếu không nó vô nghĩa", () => {
    // UTC-4 (mùa hè) ⇒ offset dương theo quy ước của getTimezoneOffset.
    expect(new Date(2026, 7, 5).getTimezoneOffset()).toBeGreaterThan(0)
  })

  it("giữ đúng ô lịch", () => {
    const d = parseNgayLich("2026-08-05")
    expect(d.getFullYear()).toBe(2026)
    expect(d.getMonth()).toBe(7)
    expect(d.getDate()).toBe(5)
  })

  it("cách cũ (new Date với chuỗi chỉ có ngày) lùi một ngày", () => {
    // Khoá LÝ DO tồn tại của hàm. Nếu ca này đỏ vì JavaScript đổi cách parse
    // thì cả hàm lẫn ghi chú phải được đọc lại.
    expect(new Date("2026-08-05").getDate()).toBe(4)
  })

  it("qua mốc tháng và mốc năm", () => {
    expect(parseNgayLich("2026-09-01").getMonth()).toBe(8)
    expect(parseNgayLich("2026-09-01").getDate()).toBe(1)
    expect(parseNgayLich("2027-01-01").getFullYear()).toBe(2027)
    expect(parseNgayLich("2026-12-31").getDate()).toBe(31)
  })

  it("đi vòng tròn với calendarDateToISO", async () => {
    // Đọc lên rồi ghi xuống phải ra đúng chuỗi ban đầu — đây là vòng đời thật
    // của một chính sách được mở ra sửa mà không đụng ô ngày.
    const { calendarDateToISO } = await import("./vn-date")
    for (const s of ["2026-08-05", "2026-01-01", "2026-12-31", "2027-02-28"]) {
      expect(calendarDateToISO(parseNgayLich(s))).toBe(s)
    }
  })
})
