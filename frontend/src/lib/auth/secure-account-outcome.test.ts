/**
 * Khoá hợp đồng FE của "Bảo mật tài khoản" (F38): backend trả
 * `relogin_required=true` khi đã thu hồi MỌI phiên và xoá cookie ⇒ FE phải đưa
 * người dùng tới trang đăng nhập (lối `force_login`), không tới trang cài đặt.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { secureAccountOutcome } from "./secure-account-outcome";

describe("secureAccountOutcome", () => {
  it("relogin_required=true ⇒ tới /login?force_login=true, câu báo nói phải đăng nhập lại", () => {
    const kq = secureAccountOutcome({ message: "x", sessions_revoked: 3, relogin_required: true });
    expect(kq.next).toEqual({ kind: "relogin", url: "/login?force_login=true" });
    expect(kq.message).toContain("đăng nhập");
    expect(kq.message).not.toContain("đổi mật khẩu");
  });

  it("relogin_required=false ⇒ giữ phiên, tới form đổi mật khẩu BỊ BUỘC", () => {
    const kq = secureAccountOutcome({ message: "x", sessions_revoked: 2, relogin_required: false });
    expect(kq.next).toEqual({ kind: "settings", url: "/settings?forced=true" });
    expect(kq.message).toContain("2 phiên");
    expect(kq.message).toContain("đổi mật khẩu");
  });
});

describe("call site ở hai màn hình Bảo mật tài khoản", () => {
  // Hai ca trên chỉ kiểm phép quyết định, KHÔNG chạm màn hình: một màn hình bỏ
  // qua helper (quay lại câu cứng + `router.push("/settings")`) thì chúng vẫn
  // xanh. Ca này khoá đúng chỗ nối — nhánh `relogin` phải tải trang tới URL của
  // helper, và không còn câu báo cứng nào bỏ qua `relogin_required`.
  const MAN_HINH = [
    "src/app/(dashboard)/settings/security/_components/SecurityClient.tsx",
    "src/app/(dashboard)/settings/login-history/_components/LoginHistoryClient.tsx",
  ];

  it.each(MAN_HINH)("%s đi qua secureAccountOutcome và tải trang khi phải đăng nhập lại", (tep) => {
    const nguon = readFileSync(join(process.cwd(), tep), "utf8");
    expect(nguon).toMatch(/secureAccountOutcome\(response\)/);
    expect(nguon).toMatch(/kind === "relogin"[\s\S]{0,400}window\.location\.assign\(next\.url\)/);
    expect(nguon).not.toMatch(/Đang chuyển đến trang đổi mật khẩu/);
  });

  // F131: nhánh giữ phiên phải tới ĐÚNG đích của helper (form bị buộc), không
  // còn `router.push("/settings")` cứng.
  it.each(MAN_HINH)("%s: nhánh giữ phiên đi tới next.url của helper", (tep) => {
    const nguon = readFileSync(join(process.cwd(), tep), "utf8");
    expect(nguon).toMatch(/router\.push\(next\.url\)/);
    expect(nguon).not.toMatch(/router\.push\("\/settings"\)/);
  });
});
