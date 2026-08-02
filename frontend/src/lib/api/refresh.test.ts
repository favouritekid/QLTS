// src/lib/api/refresh.test.ts
/**
 * Cờ "đã cố ý giữ phiên" — phần của `refresh.ts` nằm ngoài luồng phối hợp.
 *
 * ⚠️ Phần lớn nội dung cũ của tệp này đã CHUYỂN chỗ, không phải bị bỏ:
 *
 *  - single-flight "nhiều lời gọi ⇒ một POST" → `refresh.cross-tab.test.ts`.
 *    Ở đó dùng HAI module context nên chứng minh được khoá liên-tab thật, chứ
 *    không chỉ chứng minh `inflight` nội module (bản cũ gọi hai lần trong cùng
 *    module nên xanh kể cả khi khoá liên-tab hỏng hoàn toàn).
 *  - cooldown sau `429 RATE_LIMITED` → `lock.contract.test.ts` (tôn trọng
 *    `retryAt`) và `refresh.outcome-matrix.test.ts` (ghi đủ vào nhật ký). Biến
 *    `blockedUntil` cục bộ đã bỏ hẳn: cooldown nay nằm trong nhật ký dùng
 *    chung, một nguồn duy nhất.
 *  - phân loại lỗi: predicate cũ đã thay bằng `shouldClearAuthCookies`,
 *    phủ ở `refresh.brand.test.ts` và `refresh.outcome-matrix.test.ts`.
 *    ⚠️ Contract đã ĐỔI có chủ đích: `403` không còn là bằng chứng phiên chết
 *    (nay là `nonterminal-stop`, GIỮ cookie) — xem `fail-preserve` trong
 *    `refresh.ts`.
 */
import { describe, it, expect } from "vitest";

import { markSessionKeptAlive, isSessionKeptAliveError } from "./refresh";

describe("cờ session-kept-alive", () => {
  it("đánh dấu rồi thì nhận ra được", () => {
    const error = markSessionKeptAlive(new Error("tạm thời"));

    expect(isSessionKeptAliveError(error)).toBe(true);
  });

  it("lỗi thường KHÔNG mang cờ", () => {
    // `useAuth` dựa vào cờ này để bỏ qua một 401 mà interceptor đã cố ý giữ
    // phiên. Nếu lỗi thường cũng mang cờ thì một 401 thật sẽ không còn đăng
    // xuất được nữa.
    expect(isSessionKeptAliveError(new Error("bình thường"))).toBe(false);
    expect(isSessionKeptAliveError(null)).toBe(false);
    expect(isSessionKeptAliveError(undefined)).toBe(false);
    expect(isSessionKeptAliveError("chuỗi")).toBe(false);
  });

  it("trả lại CHÍNH object đã truyền vào, không sao chép", () => {
    // Interceptor đánh dấu rồi `Promise.reject` chính nó. Sao chép sẽ làm mất
    // các trường của `AxiosError` mà tầng trên còn đọc — nhất là `response`,
    // thứ mà predicate retry của React Query dựa vào.
    const error = new Error("gốc");

    expect(markSessionKeptAlive(error)).toBe(error);
  });
});
