// src/lib/api/refresh.brand.test.ts
/**
 * `isRefreshFailure()` gác cửa `shouldClearAuthCookies()`, tức gác quyết định
 * XOÁ cookie phiên 30 ngày. Nhận diện lỏng ở đây là bất kỳ object nào tình cờ
 * mang đúng hình dạng cũng đủ để đăng xuất người dùng.
 *
 * Hai yêu cầu ngược chiều nhau phải cùng đúng:
 *  - lỗi thật từ MỘT BẢN MODULE KHÁC vẫn phải được nhận (không dùng `instanceof`);
 *  - object bịa mang đúng tên/hình dạng phải bị từ chối.
 */
import { describe, it, expect, vi } from "vitest";

import {
  RefreshFailure,
  isRefreshFailure,
  shouldClearAuthCookies,
} from "./refresh";

const BRAND = Symbol.for("qlts.refresh-failure");

describe("nhận lỗi thật, kể cả từ bản module khác", () => {
  it("`RefreshFailure` của chính module này", () => {
    const error = new RefreshFailure({ kind: "terminal", status: 401 });

    expect(isRefreshFailure(error)).toBe(true);
    expect(shouldClearAuthCookies(error)).toBe(true);
  });

  it("`RefreshFailure` dựng từ MỘT BẢN MODULE KHÁC vẫn được nhận", async () => {
    vi.resetModules();
    const other = await import("./refresh");
    // Hai bản module khác nhau ⇒ `instanceof` sẽ trả false ở đây.
    expect(other.RefreshFailure).not.toBe(RefreshFailure);

    const fromOther = new other.RefreshFailure({ kind: "terminal", status: 401 });

    expect(fromOther instanceof RefreshFailure).toBe(false);
    expect(isRefreshFailure(fromOther)).toBe(true);
    expect(shouldClearAuthCookies(fromOther)).toBe(true);
  });
});

describe("từ chối mọi thứ chỉ TRÔNG GIỐNG", () => {
  it("object bịa tên nhưng KHÔNG có brand ⇒ không được xoá cookie", () => {
    const fake = { name: "RefreshFailure", outcome: { kind: "terminal" } };

    expect(isRefreshFailure(fake)).toBe(false);
    // Đây mới là hậu quả thật: một payload dựng từ JSON hoặc lỗi của thư viện
    // khác không được phép xoá phiên 30 ngày của người dùng.
    expect(shouldClearAuthCookies(fake)).toBe(false);
  });

  it.each([
    ["kind lạ", { [BRAND]: true, outcome: { kind: "có-lẽ-ổn" } }],
    ["kind = success", { [BRAND]: true, outcome: { kind: "success" } }],
    ["outcome không phải object", { [BRAND]: true, outcome: "terminal" }],
    ["thiếu outcome", { [BRAND]: true }],
    [
      "safe-retryable thiếu retryAt",
      { [BRAND]: true, outcome: { kind: "safe-retryable" } },
    ],
    [
      "safe-retryable retryAt vô hạn",
      { [BRAND]: true, outcome: { kind: "safe-retryable", retryAt: Number.NaN } },
    ],
    [
      "ambiguous reason ngoài allowlist",
      { [BRAND]: true, outcome: { kind: "ambiguous", reason: "chưa-rõ" } },
    ],
    ["ambiguous thiếu reason", { [BRAND]: true, outcome: { kind: "ambiguous" } }],
    [
      "terminal status sai kiểu",
      { [BRAND]: true, outcome: { kind: "terminal", status: "401" } },
    ],
    [
      "nonterminal errorCode sai kiểu",
      { [BRAND]: true, outcome: { kind: "nonterminal-stop", errorCode: 404 } },
    ],
  ])("%s ⇒ từ chối", (_label, value) => {
    expect(isRefreshFailure(value)).toBe(false);
  });

  it("có brand + outcome hợp lệ ⇒ nhận (để chắc phần trên không từ chối tất)", () => {
    const valid = {
      [BRAND]: true,
      outcome: { kind: "ambiguous", reason: "network" },
    };

    expect(isRefreshFailure(valid)).toBe(true);
    // …nhưng `ambiguous` KHÔNG phải bằng chứng phiên chết ⇒ vẫn giữ cookie.
    expect(shouldClearAuthCookies(valid)).toBe(false);
  });
});

describe("chỉ `terminal` mới cho xoá cookie", () => {
  it.each([
    ["safe-retryable", { kind: "safe-retryable", retryAt: Date.now() + 1000 }],
    ["nonterminal-stop", { kind: "nonterminal-stop", status: 404 }],
    ["ambiguous", { kind: "ambiguous", reason: "network" }],
  ] as const)("%s ⇒ GIỮ cookie", (_label, outcome) => {
    const error = new RefreshFailure(outcome);

    expect(isRefreshFailure(error)).toBe(true);
    expect(shouldClearAuthCookies(error)).toBe(false);
  });
});
