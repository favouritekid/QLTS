// src/lib/api/refresh-coordination/safe-retry.single-source.test.ts
/**
 * `safe-retry.ts` lấy mã `AUTH_STATE_UNAVAILABLE` từ `error-codes.ts` — không
 * tự viết lại.
 *
 * Một bản chép tay CÙNG giá trị cho kết quả y hệt hôm nay, nên so giá trị không
 * phân biệt được bản chép với nguồn. Ở đây ta ĐỔI nguồn (mock `error-codes.ts`
 * sang một giá trị dò) rồi đòi danh sách thử lại đi theo — cùng cách dò mà test
 * backend `test_refresh_takes_everything_from_the_class` dùng cho
 * `AuthStateUnavailable`.
 */
import { describe, it, expect, vi } from "vitest";

const PROBE = "AUTH_STATE_SOURCE_PROBE";

vi.mock("../error-codes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../error-codes")>()),
  AUTH_STATE_UNAVAILABLE_ERROR_CODE: "AUTH_STATE_SOURCE_PROBE",
}));

import { isSafeRetryableResponse } from "./safe-retry";

describe("safe-retry.ts — một nguồn cho mã 503", () => {
  it("đổi hằng ở error-codes.ts ⇒ cặp 503 được thử lại đổi theo", () => {
    expect(isSafeRetryableResponse(503, PROBE)).toBe(true);
    // Chuỗi cũ không còn khớp: không có bản chép thứ hai nào giữ nó lại.
    expect(isSafeRetryableResponse(503, "AUTH_STATE_UNAVAILABLE")).toBe(false);
  });

  it("vẫn khớp theo CẶP: mã dò đi với status khác thì không thử lại", () => {
    expect(isSafeRetryableResponse(500, PROBE)).toBe(false);
    expect(isSafeRetryableResponse(429, PROBE)).toBe(false);
  });

  it("cặp 429 RATE_LIMITED không bị ảnh hưởng", () => {
    expect(isSafeRetryableResponse(429, "RATE_LIMITED")).toBe(true);
  });
});
