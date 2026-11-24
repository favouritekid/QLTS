/**
 * KT-6 (owner 24-11: Thư ký Hội đồng CÓ THỂ là cán bộ thường) — màn của Thư ký nằm NGOÀI `/admin/*`; KHÔNG mở rộng
 * `ADMIN_ROLES`.
 *
 * Trước bản vá: trang "Bảng chỉ tiêu năm" ở `/admin/quota-tables`; `proxy.ts` đẩy mọi vai ngoài admin / manager khỏi `/admin/*`
 * về `/dashboard` TRƯỚC khi trang chạy ⇒ cán bộ được gán Thư ký không bao giờ tới được cổng máy chủ `require_review_secretary`
 * dù máy chủ cho họ xem.
 *
 * Chạy proxy THẬT với `NextRequest` (khuôn `proxy.test.ts` / `proxy.matrix.test.ts`). Proxy không biết ai là Thư ký — nó chỉ
 * đòi đăng nhập ở đường mới; ai xem được là việc của máy chủ (test trang: `quota-tables/_components/QuotaTablesPage.test.tsx`).
 */
import fs from "node:fs";
import path from "node:path";

import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";

import { ADMIN_ROLES, hasAdminAccess } from "@/lib/config/roles";
import { navigationConfig } from "@/lib/config/navigation";
import type { NavItem } from "@/types/navigation";

import { proxy } from "./proxy";

const BASE = "https://qlts.tnpc.edu.vn";

/** Mọi màn dành cho Ban thư ký (Admin + Quản lý / Cán bộ được gán) — phải nằm ngoài `/admin/*`. */
const THU_KY_ROUTES = ["/quota-tables"] as const;

function makeToken(payload: Record<string, unknown>): string {
  const b64 = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.sig`;
}

function accessToken(expiresInSeconds: number, role: string): string {
  return makeToken({
    sub: `${role}1`,
    user_id: 25,
    role,
    type: "access",
    jti: "jti-kt6",
    exp: Math.floor(Date.now() / 1000) + expiresInSeconds,
  });
}

function requestWith(token: string | undefined, pathname: string): NextRequest {
  const req = new NextRequest(new URL(pathname, BASE));
  if (token) req.cookies.set("access_token", token);
  return req;
}

function locationOf(res: Response): string {
  return decodeURIComponent(res.headers.get("location") ?? "");
}

/** Proxy cho đi tiếp: không chuyển hướng, chuyển tiếp đúng đường cho Server Component. */
function expectPassedThrough(res: Response, pathname: string) {
  expect(res.headers.get("location")).toBeNull();
  expect(res.headers.get("x-middleware-request-x-qlts-pathname")).toBe(pathname);
}

const allItems = (items: NavItem[]): NavItem[] => items.flatMap((i) => [i, ...allItems(i.children ?? [])]);
const NAV = allItems(navigationConfig.groups.flatMap((g) => g.items));

describe("KT-6 — màn Thư ký ngoài /admin: proxy", () => {
  it.each(THU_KY_ROUTES)("cán bộ (token còn hạn) vào %s ⇒ proxy cho đi tiếp (máy chủ quyết ai xem được)", async (route) => {
    const res = await proxy(requestWith(accessToken(600, "officer"), route));
    expectPassedThrough(res, route);
  });

  it.each(["admin", "manager", "accountant", "collaborator"])(
    "vai %s vào /quota-tables ⇒ proxy cũng cho đi tiếp (không chặn theo vai ở đường này)",
    async (role) => {
      const res = await proxy(requestWith(accessToken(600, role), "/quota-tables"));
      expectPassedThrough(res, "/quota-tables");
    },
  );

  it("đường mới vẫn đòi đăng nhập: không có access cookie ⇒ sang cứu phiên, giữ return-url", async () => {
    const res = await proxy(requestWith(undefined, "/quota-tables"));
    const loc = locationOf(res);
    expect(loc).toContain("/session-refresh");
    expect(loc).toContain("redirect=/quota-tables");
    expect(res.headers.get("x-middleware-request-x-qlts-pathname")).toBeNull();
  });

  it("đường mới vẫn đòi đăng nhập: token hỏng ⇒ về /login, xoá cookie", async () => {
    const res = await proxy(requestWith("khong-phai-jwt", "/quota-tables"));
    const loc = locationOf(res);
    expect(loc).toContain("/login");
    expect(loc).toContain("redirect=/quota-tables");
    expect(res.headers.get("set-cookie") ?? "").toContain("access_token=");
  });

  it("token hết hạn ở đường mới ⇒ cứu phiên, KHÔNG cho vào vỏ trang", async () => {
    const res = await proxy(requestWith(accessToken(-120, "officer"), "/quota-tables"));
    expect(locationOf(res)).toContain("/session-refresh");
    expect(res.headers.get("x-middleware-request-x-qlts-pathname")).toBeNull();
  });

  it.each(["/admin/quota-tables", "/admin/review-secretaries", "/admin/users"])(
    "chặn /admin/* GIỮ NGUYÊN: cán bộ vào %s ⇒ về /dashboard",
    async (p) => {
      const res = await proxy(requestWith(accessToken(600, "officer"), p));
      expect(new URL(res.headers.get("location") ?? "", BASE).pathname).toBe("/dashboard");
    },
  );

  it.each(["admin", "manager"])("%s vẫn vào được /admin/quota-tables (trang ấy chuyển hướng sang /quota-tables)", async (role) => {
    const res = await proxy(requestWith(accessToken(600, role), "/admin/quota-tables"));
    expectPassedThrough(res, "/admin/quota-tables");
  });

  it("ADMIN_ROLES KHÔNG mở rộng cho cán bộ", () => {
    expect([...ADMIN_ROLES]).toEqual(["admin", "manager"]);
    expect(hasAdminAccess("officer")).toBe(false);
  });
});

describe("KT-6 — màn Thư ký ngoài /admin: nơi đặt trang và menu", () => {
  it.each(THU_KY_ROUTES)("%s nằm ngoài /admin và có trang thật trong (dashboard)", (route) => {
    expect(route.startsWith("/admin")).toBe(false);
    const page = path.resolve(__dirname, `app/(dashboard)${route}/page.tsx`);
    expect(fs.existsSync(page)).toBe(true);
  });

  it("mục menu 'Bảng chỉ tiêu năm' trỏ đường ngoài /admin", () => {
    const muc = NAV.find((i) => i.label === "Bảng chỉ tiêu năm");
    expect(muc?.href).toBe("/quota-tables");
  });

  // §6 — mọi lối menu mà cán bộ có thể thấy (bộ lọc vai thô cho qua, kể cả mục theo cờ máy chủ) KHÔNG được dẫn vào `/admin/*`:
  // dẫn vào đó là bị proxy đá về `/dashboard` — đúng lỗi KT-6. Mục mới cho Thư ký (vd "Lần xét tuyển") đặt nhầm dưới `/admin`
  // với `roles` rỗng / có `officer` ⇒ đỏ ở đây.
  it("không mục menu nào cán bộ có thể thấy lại dẫn vào /admin/*", async () => {
    const thayDuoc = NAV.filter(
      (i) => (!i.roles || i.roles.length === 0 || i.roles.includes("officer")) && !(i.excludeRoles ?? []).includes("officer"),
    );
    expect(thayDuoc.length).toBeGreaterThan(0);
    for (const i of thayDuoc) {
      expect(i.href.startsWith("/admin"), `mục "${i.label}" (${i.href})`).toBe(false);
      const res = await proxy(requestWith(accessToken(600, "officer"), i.href));
      expect(new URL(res.headers.get("location") ?? BASE + "/__khong_chuyen__", BASE).pathname, `mục "${i.label}"`).not.toBe(
        "/dashboard",
      );
    }
  });
});
