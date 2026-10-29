// @vitest-environment jsdom
/**
 * F131 — đích sau đăng nhập: người bị buộc đổi mật khẩu đi THẲNG tới form.
 *
 * Hai lối đăng nhập thành công (mật khẩu, MFA) phải cùng đi qua
 * `postLoginTarget`; ca cuối khoá chỗ nối — một lối tự tính đích riêng là đỏ.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { postLoginTarget } from "./useAuth";

describe("postLoginTarget", () => {
  it("cờ bật ⇒ /settings?forced=true, bỏ qua cả ?redirect= hợp lệ", () => {
    expect(
      postLoginTarget(
        { role: "admin", password_reset_required: true },
        "?redirect=%2Fleads%2F42",
      ),
    ).toBe("/settings?forced=true");
  });

  it.each([
    ["officer", "/dashboard/officer"],
    ["collaborator", "/ctv"],
    ["admin", "/dashboard"],
  ])("cờ tắt, không redirect: %s ⇒ %s", (role, expected) => {
    expect(postLoginTarget({ role, password_reset_required: false }, "")).toBe(expected);
  });

  it("cờ tắt + redirect hợp lệ ⇒ giữ redirect như trước", () => {
    expect(
      postLoginTarget({ role: "admin", password_reset_required: false }, "?redirect=%2Fleads%2F42"),
    ).toBe("/leads/42");
  });

  it("cờ vắng (backend cũ) ⇒ như cờ tắt", () => {
    expect(postLoginTarget({ role: "admin" }, "")).toBe("/dashboard");
  });
});

describe("call site trong useAuth", () => {
  it("cả login lẫn verify-mfa đều điều hướng bằng postLoginTarget, không tự tính đích", () => {
    const nguon = readFileSync(join(process.cwd(), "src/hooks/useAuth.ts"), "utf8");
    const goi = nguon.match(/router\.push\(postLoginTarget\(user, window\.location\.search\)\)/g) ?? [];
    expect(goi).toHaveLength(2);
    // Chỉ còn MỘT chỗ tính defaultPath: bên trong postLoginTarget.
    expect(nguon.match(/const defaultPath =/g) ?? []).toHaveLength(1);
  });
});
