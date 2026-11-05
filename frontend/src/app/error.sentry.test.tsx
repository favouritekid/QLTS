/**
 * Sentry phía GIAO DIỆN (lượt F) — hiện KHÔNG có đường nào đưa dữ liệu (kể cả danh sách
 * mã hồ sơ) vào một sự kiện Sentry:
 *
 * 1. Cấu hình (quét tĩnh, chạy trên chính cây mã): không nơi nào khởi tạo Sentry —
 *    không `Sentry.init`, không `withSentryConfig` trong `next.config.*`, không
 *    `instrumentation*.ts`, không `sentry.*.config.*`; nơi DUY NHẤT nhập `@sentry/` là
 *    `src/app/error.tsx` (dynamic import khi có `NEXT_PUBLIC_SENTRY_DSN`).
 * 2. Đo THẬT qua SDK đã cài (bản ghim trong package-lock): `error.tsx` gọi
 *    `captureException` với lỗi mang mã giả khi đặt DSN giả ⇒ SDK không có client (chưa
 *    init) ⇒ không một lời gọi mạng nào (fetch / XHR / sendBeacon).
 *
 * Ai BẬT Sentry phía giao diện ⇒ (1) đỏ: phải kèm MỘT chỗ chủ sở hữu bộ lọc dữ liệu cá
 * nhân (beforeSend / beforeBreadcrumb, tắt replay …) + test bằng transport giả — xem báo
 * cáo lượt F mục Sentry. Không đổi DSN, không bật Sentry ở đây.
 */
import fs from "node:fs"
import path from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"
import { render, waitFor } from "@testing-library/react"

import GlobalError from "./error"

const GOC = path.resolve(__dirname, "../..") // thư mục frontend
const maGia = (n: number) => "099" + "999" + String(n).padStart(6, "0")

function tepNguon(thu_muc: string): string[] {
  const out: string[] = []
  const di = (d: string) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue
      const p = path.join(d, e.name)
      if (e.isDirectory()) di(p)
      else if (/\.(ts|tsx|js|jsx|mjs|cjs)$/.test(e.name)) out.push(p)
    }
  }
  di(thu_muc)
  return out
}

const tuongDoi = (p: string) => path.relative(GOC, p).split(path.sep).join("/")

describe("Sentry giao diện — cấu hình: không nơi nào khởi tạo", () => {
  it("không tệp instrumentation / sentry.*.config ở gốc frontend hay src", () => {
    const ten = [...fs.readdirSync(GOC), ...fs.readdirSync(path.join(GOC, "src"))]
    const la = ten.filter((t) => /^instrumentation(-client)?\.(ts|js|mjs)$/.test(t) || /^sentry\..*\.config\./.test(t))
    expect(la, "BẬT Sentry giao diện ⇒ phải kèm bộ lọc dữ liệu cá nhân MỘT chỗ + test (báo cáo lượt F)").toEqual([])
  })

  it("next.config không bọc withSentryConfig", () => {
    const cfg = fs.readdirSync(GOC).filter((t) => /^next\.config\./.test(t))
    expect(cfg.length).toBeGreaterThan(0)
    for (const t of cfg) {
      expect(fs.readFileSync(path.join(GOC, t), "utf8").includes("withSentryConfig"), t).toBe(false)
    }
  })

  it("nơi DUY NHẤT nhập @sentry/ trong mã nguồn là src/app/error.tsx, và không ai gọi init", () => {
    const tep = tepNguon(path.join(GOC, "src")).filter((p) => !/\.(test|spec)\.[tj]sx?$/.test(p))
    const nhap = tep.filter((p) => fs.readFileSync(p, "utf8").includes("@sentry/")).map(tuongDoi)
    expect(nhap).toEqual(["src/app/error.tsx"])
    const loi = fs.readFileSync(path.join(GOC, "src/app/error.tsx"), "utf8")
    expect(/\binit\s*\(/.test(loi)).toBe(false)
  })
})

describe("Sentry giao diện — đo thật qua SDK đã cài", () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it("error.tsx gọi captureException với lỗi mang mã giả ⇒ không client, 0 lời gọi mạng", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "https://khoa-gia@o0.ingest.invalid/0")
    vi.spyOn(console, "error").mockImplementation(() => undefined)
    vi.spyOn(console, "warn").mockImplementation(() => undefined)
    const mang: string[] = []
    const fetchGoc = globalThis.fetch
    globalThis.fetch = (async (...a: unknown[]) => {
      mang.push("fetch " + String(a[0]))
      throw new Error("chặn mạng trong test")
    }) as typeof fetch
    const xhrOpen = vi.spyOn(XMLHttpRequest.prototype, "open").mockImplementation(() => {
      mang.push("xhr")
    })
    const nav = navigator as Navigator & { sendBeacon?: (...a: unknown[]) => boolean }
    const beaconGoc = nav.sendBeacon
    nav.sendBeacon = (...a: unknown[]) => {
      mang.push("beacon " + String(a[0]))
      return true
    }
    try {
      const Sentry = await import("@sentry/nextjs")
      const scope = Sentry.getCurrentScope()
      const bat = vi.spyOn(scope, "captureException")
      const ma = [maGia(1), maGia(2)]
      render(<GlobalError error={new Error("loi gia " + ma.join(","))} reset={() => undefined} />)
      await waitFor(() => expect(bat).toHaveBeenCalledTimes(1)) // đường gọi CÓ chạy (không xanh rỗng)
      await new Promise((r) => setTimeout(r, 50))
      expect(Sentry.getClient()).toBeUndefined()
      expect(scope.getClient()).toBeUndefined()
      expect(mang).toEqual([])
      expect(xhrOpen).not.toHaveBeenCalled()
    } finally {
      globalThis.fetch = fetchGoc
      nav.sendBeacon = beaconGoc
    }
  })
})
