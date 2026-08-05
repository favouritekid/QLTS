/**
 * Ngày hiệu lực của chính sách ưu đãi học phí.
 *
 * Triệu chứng đã gặp thật trên màn này: chọn hiệu lực từ 05/08 thì hệ thống
 * lưu 04/08 — chính sách áp sớm một ngày, và `valid_to` cũng hết hạn sớm một
 * ngày. Nguyên nhân là `toISOString()`: `DatePicker` trả `Date` 00:00 GIỜ ĐỊA
 * PHƯƠNG, còn `toISOString()` quy về UTC, nên ở Việt Nam (UTC+7) ngày rơi lùi.
 *
 * Ca này kiểm chính phép biến đổi mà form dùng. Nó cố ý KHÔNG dựng cả form:
 * lỗi nằm ở một dòng chuyển đổi, và một bài kiểm chạm đúng dòng đó thì đọc
 * được và không vỡ mỗi lần bố cục thay đổi.
 *
 * 🔴 Phải chạy ở múi giờ dương: ở UTC hai cách tính cho cùng kết quả.
 */
const TZ_GOC = process.env.TZ
process.env.TZ = "Asia/Ho_Chi_Minh"

import { readFileSync } from "node:fs"
import { join } from "node:path"

import { afterAll, describe, it, expect } from "vitest"

import { calendarDateToISO } from "@/lib/utils/vn-date"

afterAll(() => {
  if (TZ_GOC === undefined) delete process.env.TZ
  else process.env.TZ = TZ_GOC
})

describe("ngày hiệu lực chính sách ưu đãi", () => {
  it("guard: bộ test chạy ở múi giờ Việt Nam", () => {
    expect(new Date(2026, 7, 5).getTimezoneOffset()).toBe(-420)
  })

  it("bấm 05/08 trên lịch thì gửi lên 2026-08-05", () => {
    // Đây đúng là thứ `DatePicker` trả về khi người dùng bấm ngày 05.
    const nguoiDungBam = new Date(2026, 7, 5, 0, 0, 0)
    expect(calendarDateToISO(nguoiDungBam)).toBe("2026-08-05")
  })

  it("cách cũ (toISOString) lùi đúng một ngày — lý do bản vá tồn tại", () => {
    const nguoiDungBam = new Date(2026, 7, 5, 0, 0, 0)
    expect(nguoiDungBam.toISOString().split("T")[0]).toBe("2026-08-04")
  })

  it("ngày kết thúc cuối tháng không bị lùi sang tháng trước", () => {
    // `valid_to` 31/08 hoá 30/08 là hết hạn sớm một ngày; nếu là 01/09 thì
    // cách cũ còn đẩy nó về tháng 8.
    expect(calendarDateToISO(new Date(2026, 8, 1, 0, 0, 0))).toBe("2026-09-01")
    expect(calendarDateToISO(new Date(2026, 7, 31, 0, 0, 0))).toBe("2026-08-31")
  })
})

describe("call site của form ưu đãi", () => {
  // Ba ca trên kiểm phép biến đổi, nhưng KHÔNG chạm form: trả `onSubmit` về
  // `toISOString()` thì chúng vẫn xanh. Ca này khoá đúng call site — thứ duy
  // nhất quyết định lỗi có quay lại hay không.
  const nguon = readFileSync(
    join(process.cwd(), "src/app/(dashboard)/admin/tuition-discount/_components/TuitionDiscountClient.tsx"),
    "utf8",
  )

  it("payload dùng calendarDateToISO cho cả valid_from và valid_to", () => {
    expect(nguon).toMatch(/valid_from:.*calendarDateToISO\(/)
    expect(nguon).toMatch(/valid_to:.*calendarDateToISO\(/)
  })

  it("đường ĐỌC dùng parseNgayLich, không dùng new Date thẳng", () => {
    // Vá một nửa vòng thì vẫn lệch: `new Date("2026-08-05")` là UTC nửa đêm,
    // nên mở một chính sách cũ ra sửa (dù không đụng ô ngày) sẽ lùi ngày trên
    // mọi máy ở múi giờ âm — và bản CŨ lại đúng ở chính đường này, vì hai đầu
    // cùng quy về UTC.
    expect(nguon).not.toMatch(/new Date\(policy\.valid_(from|to)\)/)
    expect(nguon).toMatch(/parseNgayLich\(policy\.valid_from\)/)
    expect(nguon).toMatch(/parseNgayLich\(policy\.valid_to\)/)
  })

  it("không còn LỜI GỌI toISOString nào trong file", () => {
    // Bất kỳ ngày nào gửi lên từ màn này đều phải đi qua lịch địa phương.
    // Khớp lời gọi (`x.toISOString()`) chứ không khớp chữ trong ghi chú —
    // nếu không, ca này đỏ vì chính đoạn giải thích vì sao nó tồn tại.
    expect(nguon).not.toMatch(/\.toISOString\(/)
  })
})
