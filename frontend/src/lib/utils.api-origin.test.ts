// src/lib/utils.api-origin.test.ts
/**
 * Khoá hợp đồng: **`API_BASE_URL` không cấp đặc quyền cho bất kỳ origin nào.**
 *
 * 🔴 VÌ SAO TỆP NÀY VẪN TỒN TẠI SAU KHI NHÁNH URL-TUYỆT-ĐỐI BỊ GỠ
 * Bản trước của tệp này sinh ra để chạm tới nhánh "so origin API", vốn chỉ
 * chạy được khi `API_BASE_URL` khác rỗng — ở `utils.test.ts` biến đó rỗng nên
 * đột biến đổi `resolved.origin !== api` thành `trimmed.startsWith(api)` **đi
 * qua trọn vẹn 50/50 ca xanh**. Nhánh ấy nay đã GỠ, nên nếu chỉ xoá tệp đi thì
 * không còn gì chặn người sau lặng lẽ thêm lại nó.
 *
 * Vì vậy tệp đổi vai: vẫn mock `API_BASE_URL`, rồi khẳng định rằng **kể cả khi
 * biến đó có giá trị**, URL tuyệt đối trỏ tới chính origin ấy vẫn bị TỪ CHỐI.
 * Đó là phép kiểm duy nhất phân biệt được "đã gỡ nhánh" với "nhánh vẫn còn".
 *
 * ⚠️ VAI TRÒ CỦA GIÁ TRỊ MOCK: chỉ là **một giá trị KHÁC RỖNG**, đủ để nhánh
 * phụ thuộc `API_BASE_URL !== ""` được chạm tới. Nó **KHÔNG** phải giá trị
 * production và không nói gì về môi trường thật — giá trị production nằm trong
 * `.env.production`, bộ ca này không đọc, và các nguồn trong kho cho ba giá trị
 * khác nhau (`https://${DOMAIN}` là template, `http://localhost:8000`,
 * `http://127.0.0.1:8100`). Vì thế dùng origin TỔNG HỢP dưới `.invalid` — TLD
 * dành riêng, không bao giờ phân giải — để ý đồ của bộ ca tự nói lên chính nó
 * và không ai đọc nhầm thành một sự thật về môi trường.
 *
 * ⚖️ Hợp đồng: nhận ĐÚNG MỘT dạng — chuỗi bắt đầu bằng `/`, không bắt đầu bằng
 * `//`, sau chuẩn hoá vẫn nội bộ. Hai lý do kỹ thuật: **fail-closed**, và
 * **xoá phụ thuộc vào cấu hình origin** (hành vi guard không còn đổi theo
 * `NEXT_PUBLIC_API_URL`).
 *
 * `vi.mock` được hoist theo TỆP, nên phải tách riêng thay vì nhét chung.
 */
import { describe, it, expect, vi } from "vitest";

/** Origin TỔNG HỢP — vai trò duy nhất: khác rỗng. Không phải giá trị thật. */
const API_ORIGIN_TONG_HOP = "https://api.example.invalid";

vi.mock("@/lib/api/client", () => ({
  API_BASE_URL: "https://api.example.invalid",
}));

const { resolveSafeUrl, isSafeUrl } = await import("./utils");

/** Origin của chính app khi chạy bộ ca (jsdom mặc định). */
const APP_ORIGIN = "http://localhost:3000";

/**
 * Mọi URL TUYỆT ĐỐI đều bị từ chối — không ngoại lệ, không phụ thuộc origin.
 *
 * Ba nhóm phải nằm CÙNG một bảng, vì điều đang được khoá chính là "cả ba nhóm
 * cho ra CÙNG một kết quả". Tách ra thành ba describe sẽ làm mất đúng ý ấy.
 */
const TUYET_DOI_PHAI_CHAN: Array<[string, string]> = [
  // Trùng API origin — trước khi gỡ nhánh, nhóm này ĐƯỢC QUA.
  ["đúng API origin", `${API_ORIGIN_TONG_HOP}/leads?tab=a#b`],
  ["đúng API origin, gốc", `${API_ORIGIN_TONG_HOP}/`],
  ["đúng API origin, kèm cổng mặc định", "https://api.example.invalid:443/leads"],
  // Trùng APP origin — guard CŨ (`isSafeUrl` trên main) cho qua qua nhánh
  // `window.location.origin`; nhánh ấy cũng không còn.
  ["đúng APP origin", `${APP_ORIGIN}/leads?tab=a`],
  // Origin lạ — luôn phải chặn, ở mọi phiên bản.
  ["origin lạ", "https://evil.example/x"],
  ["tiền tố khớp API origin nhưng origin khác", "https://api.example.invalid.evil.com/x"],
  ["userinfo @ giả API origin", "https://api.example.invalid@evil.com/x"],
  ["userinfo @ kèm cổng", "https://api.example.invalid:8443@evil.com/x"],
  ["gạch nối giả API origin", "https://api.example.invalid-evil.com/x"],
  ["http (không https) đúng host API", "http://api.example.invalid/leads"],
  ["protocol-relative tới host API", "//api.example.invalid/leads"],
];

describe("URL tuyệt đối bị TỪ CHỐI kể cả khi API_BASE_URL có giá trị", () => {
  it.each(TUYET_DOI_PHAI_CHAN)("CHẶN %s", (_ten, tai) => {
    expect(resolveSafeUrl(tai)).toBeNull();
  });

  it.each(TUYET_DOI_PHAI_CHAN)("%s: `isSafeUrl` cũng phải false", (_ten, tai) => {
    expect(isSafeUrl(tai)).toBe(false);
  });
});

describe("đường nội bộ KHÔNG bị ảnh hưởng bởi API_BASE_URL", () => {
  it("đường dẫn tương đối vẫn trả đúng đích", () => {
    expect(resolveSafeUrl("/leads")).toBe("/leads");
    expect(resolveSafeUrl("/leads?tab=a#b")).toBe("/leads?tab=a#b");
  });

  it("dot-segment tụt xuống `//` vẫn bị chặn", () => {
    expect(resolveSafeUrl("/..//evil.example")).toBeNull();
  });

  it("kết quả KHÔNG đổi khi `API_BASE_URL` khác — hành vi không còn phụ thuộc cấu hình", () => {
    // Cùng đầu vào, cùng kết quả, dù module này mock API_BASE_URL thành một
    // giá trị khác rỗng còn `utils.test.ts` để nó RỖNG.
    expect(resolveSafeUrl("/leads")).toBe("/leads");
    expect(resolveSafeUrl(`${API_ORIGIN_TONG_HOP}/leads`)).toBeNull();
  });
});
