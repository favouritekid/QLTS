// src/lib/utils/vn-date.calendar.test.ts
/**
 * `calendarDateToISO` — giữ đúng ô ngày người dùng bấm trên lịch.
 *
 * 🔴 File này CỐ Ý chạy ở `TZ=Asia/Ho_Chi_Minh`, không phải UTC mặc định của
 * Vitest. Đây không phải cầu kỳ: ở UTC thì `new Date(2026, 7, 5)` và
 * `toISOString()` cho **cùng** một ngày, nên bản cài đặt sai (đi qua ISO) vẫn
 * xanh — một bài kiểm tra không thể đỏ. Lỗi chỉ hiện ra ở múi giờ dương, đúng
 * múi giờ mà người dùng thật đang ngồi.
 *
 * Ca `ban_cu_ghi_lui_mot_ngay` là lý do tồn tại của hàm: nó khoá **hành vi
 * sai** của `toISOString().split("T")[0]`. Nếu ngày nào đó ca đó đỏ vì
 * `toISOString` bỗng trả đúng ngày thì giả định của bản vá đã đổi, và cả hàm
 * lẫn ghi chú này phải được đọc lại.
 */

// Đặt TRƯỚC mọi lần tạo Date. Node đọc `process.env.TZ` động, nên gán ở đây là
// đủ; ca `guard` bên dưới xác nhận điều đó thay vì tin suông.
const TZ_GOC = process.env.TZ;
process.env.TZ = "Asia/Ho_Chi_Minh";

import { afterAll, describe, it, expect } from "vitest";
import { calendarDateToISO } from "./vn-date";

// Trả môi trường về nguyên trạng: worker của Vitest được dùng lại giữa các file,
// nên một biến TZ bỏ quên ở đây sẽ âm thầm đổi kết quả của file chạy sau.
afterAll(() => {
  if (TZ_GOC === undefined) delete process.env.TZ;
  else process.env.TZ = TZ_GOC;
});

describe("calendarDateToISO — môi trường", () => {
  it("guard: test phải chạy ở múi giờ Việt Nam, nếu không nó vô nghĩa", () => {
    // UTC+7 ⇒ getTimezoneOffset() = -420 phút. Ở UTC sẽ là 0 và mọi ca dưới
    // đây mất khả năng phân biệt đúng/sai.
    expect(new Date(2026, 7, 5).getTimezoneOffset()).toBe(-420);
  });
});

describe("calendarDateToISO", () => {
  it("trả đúng ô ngày được bấm", () => {
    expect(calendarDateToISO(new Date(2026, 7, 5, 0, 0, 0))).toBe("2026-08-05");
  });

  it("ban_cu_ghi_lui_mot_ngay: toISOString() cho ra NGÀY HÔM TRƯỚC", () => {
    const chon = new Date(2026, 7, 5, 0, 0, 0); // 05/08 00:00 giờ VN
    expect(chon.toISOString().split("T")[0]).toBe("2026-08-04");
    expect(calendarDateToISO(chon)).toBe("2026-08-05");
  });

  it("sát nửa đêm vẫn giữ nguyên ngày", () => {
    expect(calendarDateToISO(new Date(2026, 7, 5, 23, 59, 59))).toBe("2026-08-05");
    expect(calendarDateToISO(new Date(2026, 7, 6, 0, 0, 1))).toBe("2026-08-06");
  });

  it("đệm 0 cho tháng và ngày một chữ số", () => {
    expect(calendarDateToISO(new Date(2026, 0, 9))).toBe("2026-01-09");
  });

  it("qua mốc năm", () => {
    expect(calendarDateToISO(new Date(2026, 11, 31, 22, 0, 0))).toBe("2026-12-31");
    expect(calendarDateToISO(new Date(2027, 0, 1, 1, 0, 0))).toBe("2027-01-01");
  });
});
