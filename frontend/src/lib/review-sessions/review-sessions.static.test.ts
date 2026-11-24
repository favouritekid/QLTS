/**
 * GĐ2-B — quét TĨNH mã của màn lần xét (thiết kế §6.1 "Không kiểm vai … thêm test tĩnh", khuôn `khong-luu-ma.static.test.ts`):
 *  - không kiểm vai (`.role`, `role ===`, `useAuth`, `ADMIN_ROLES`, `hasAdminAccess`, `isAdmin`) — nút theo `available_actions`;
 *  - không liên kết `/admin/quota-tables` (đính chính §2: chuyển hướng làm mất `?year=`; cán bộ là Thư ký bị proxy chặn);
 *  - không `console.*`.
 * Cùng tệp — nơi đặt màn (thiết kế R4 / KT-5, owner G12): trang ngoài `/admin/*`, proxy cho cán bộ đi tiếp (máy chủ quyết ai xem),
 * mục menu "Lần xét tuyển" ngay dưới "Bảng chỉ tiêu năm".
 *
 * Biến thể phá dự kiến: thêm `{user.role === "admin" && <Nút/>}` vào một tệp của màn ⇒ ĐỎ; đặt trang ở
 * `app/(dashboard)/admin/review-sessions` ⇒ ĐỎ; dời mục menu ⇒ ĐỎ.
 */
import fs from "node:fs"
import path from "node:path"

import { NextRequest } from "next/server"
import { describe, expect, it } from "vitest"

import { navigationConfig } from "@/lib/config/navigation"
import { proxy } from "@/proxy"

const SRC = path.resolve(__dirname, "../..") // frontend/src
const TRANG = "app/(dashboard)/review-sessions"

function tepTrongThuMuc(rel: string): string[] {
  const out: string[] = []
  const di = (d: string) => {
    for (const e of fs.readdirSync(path.join(SRC, d), { withFileTypes: true })) {
      const p = `${d}/${e.name}`
      if (e.isDirectory()) di(p)
      else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p)
    }
  }
  di(rel)
  return out
}

const TEP = [
  "lib/zod/review-sessions.ts",
  "lib/api/review-sessions.ts",
  "lib/hooks/use-review-sessions.ts",
  ...tepTrongThuMuc("lib/review-sessions"),
  ...tepTrongThuMuc(TRANG),
]

/** Bỏ chú thích (khối + dòng) — chú thích được phép NHẮC tới vai / đường cũ. */
function ma(t: string): string {
  return fs
    .readFileSync(path.join(SRC, t), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1")
}

const CAM: [string, RegExp][] = [
  [".role", /\.role\b/],
  ["role ===", /\brole\s*[!=]==?/],
  ["useAuth", /\buseAuth\b/],
  ["ADMIN_ROLES", /\bADMIN_ROLES\b/],
  ["hasAdminAccess", /\bhasAdminAccess\b/],
  ["isAdmin", /\bisAdmin\b/],
  ["/admin/quota-tables", /\/admin\/quota-tables/],
  ["console", /\bconsole\s*\./],
]

describe("màn lần xét — không kiểm vai, không đường /admin/quota-tables", () => {
  it("đủ tệp để quét (không xanh rỗng)", () => {
    for (const bat_buoc of [
      "lib/zod/review-sessions.ts",
      "lib/api/review-sessions.ts",
      "lib/hooks/use-review-sessions.ts",
      "lib/review-sessions/messages.ts",
      "lib/review-sessions/url.ts",
      `${TRANG}/page.tsx`,
    ]) {
      expect(TEP, `thiếu trong danh sách quét: ${bat_buoc}`).toContain(bat_buoc)
    }
    for (const t of TEP) expect(fs.existsSync(path.join(SRC, t)), t).toBe(true)
  })

  it.each(CAM)("không %s", (_ten, mau) => {
    expect(TEP.filter((t) => mau.test(ma(t)))).toEqual([])
  })
})

// ───────────────────────────── nơi đặt màn ─────────────────────────────
function token(role: string): string {
  const b64 = (o: unknown) =>
    Buffer.from(JSON.stringify(o)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({
    sub: `${role}1`,
    user_id: 25,
    role,
    type: "access",
    jti: "jti-gd2b",
    exp: Math.floor(Date.now() / 1000) + 600,
  })}.sig`
}

describe("màn lần xét — nơi đặt (ngoài /admin) và mục menu", () => {
  it("trang ở app/(dashboard)/review-sessions, KHÔNG dưới /admin", () => {
    expect(fs.existsSync(path.join(SRC, `${TRANG}/page.tsx`))).toBe(true)
    expect(fs.existsSync(path.join(SRC, "app/(dashboard)/admin/review-sessions"))).toBe(false)
  })

  it.each(["/review-sessions", "/review-sessions/3"])(
    "cán bộ (token còn hạn) vào %s ⇒ proxy cho đi tiếp (GĐ2-C mở cho Thư ký là cán bộ; máy chủ quyết ai xem)",
    async (duong) => {
      const req = new NextRequest(new URL(duong, "https://qlts.tnpc.edu.vn"))
      req.cookies.set("access_token", token("officer"))
      const res = await proxy(req)
      expect(res.headers.get("location")).toBeNull()
      expect(res.headers.get("x-middleware-request-x-qlts-pathname")).toBe(duong)
    },
  )

  it("owner G12: mục 'Lần xét tuyển' trỏ /review-sessions, NGAY DƯỚI 'Bảng chỉ tiêu năm' trong cùng nhóm", () => {
    const nhom = navigationConfig.groups.find((g) => g.items.some((i) => i.label === "Bảng chỉ tiêu năm"))
    expect(nhom).toBeDefined()
    const nhan = (nhom?.items ?? []).map((i) => i.label)
    const vt = nhan.indexOf("Bảng chỉ tiêu năm")
    expect(nhan[vt + 1]).toBe("Lần xét tuyển")
    const muc = nhom?.items[vt + 1]
    expect(muc?.href).toBe("/review-sessions")
  })
})
