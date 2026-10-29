/**
 * F131 — nhận diện 403 "phải đổi mật khẩu" và trang đích của nó.
 */
import { describe, it, expect } from "vitest";
import {
  FORCED_PASSWORD_CHANGE_PATH,
  FORCED_PASSWORD_CHANGE_URL,
  isOnForcedPasswordChangePage,
  isPasswordChangeRequiredBody,
} from "./forced-password-change";

describe("isPasswordChangeRequiredBody", () => {
  it("nhận đúng thân 403 của backend", () => {
    expect(
      isPasswordChangeRequiredBody({
        detail: { code: "PASSWORD_CHANGE_REQUIRED", message: "x" },
        error_code: "HTTP_403",
      }),
    ).toBe(true);
  });

  it.each([
    ["detail là chuỗi", { detail: "PASSWORD_CHANGE_REQUIRED" }],
    ["mã khác", { detail: { code: "MFA_REQUIRED" } }],
    ["mã chỉ ở error_code", { error_code: "PASSWORD_CHANGE_REQUIRED" }],
    ["detail null", { detail: null }],
    ["null", null],
    ["chuỗi", "PASSWORD_CHANGE_REQUIRED"],
    ["undefined", undefined],
  ])("không nhận: %s", (_ten, body) => {
    expect(isPasswordChangeRequiredBody(body)).toBe(false);
  });
});

describe("trang đích", () => {
  it("là trang CÓ form đổi mật khẩu, không phải route /settings/change-password (không tồn tại)", () => {
    expect(FORCED_PASSWORD_CHANGE_PATH).toBe("/settings");
    expect(FORCED_PASSWORD_CHANGE_URL).toBe("/settings?forced=true");
  });

  it.each([
    ["/settings", true],
    ["/settings/security", false],
    ["/settings/change-password", false],
    ["/leads", false],
    [null, false],
  ])("isOnForcedPasswordChangePage(%s) = %s", (pathname, expected) => {
    expect(isOnForcedPasswordChangePage(pathname)).toBe(expected);
  });
});
