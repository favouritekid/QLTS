// src/components/layouts/SocketHandler.safe-link.test.tsx
/**
 * Bất biến ở TẦNG SINK cho hai điểm điều hướng của `SocketHandler`:
 * `notification.link` (sự kiện `notification`) và `data.action_url`
 * (sự kiện `system_alert`).
 *
 * 🔴 VÌ SAO TỆP NÀY PHẢI TỒN TẠI RIÊNG
 * `utils.test.ts` chứng minh `resolveSafeUrl` trả `null`; nó KHÔNG chứng minh
 * `SocketHandler` đã gọi hàm đó. Đo 22-09: `SocketHandler.test.tsx` có 503
 * dòng và **0 lần nhắc** `action_url`, `notification.link` hay
 * `resolveSafeUrl` — nghĩa là gỡ guard khỏi cả HAI sink này vẫn không một ca
 * nào đỏ. Guard có, mà không ca nào canh. Đó đúng là khuôn "required check vẫn
 * xanh vì không ai nhìn" ở CLAUDE.md §11, chỉ khác tầng.
 *
 * `action_url` đáng canh nhất trong sáu sink: nó tới từ query param THÔ của
 * `POST /admin/system/alert` (`routers/admin/system.py`, 0 validator), nên
 * guard phía frontend là guard DUY NHẤT trên đường đó.
 *
 * Bất biến nghiệm thu KHÔNG phải "hàm trả null" mà là: **nút hành động chỉ
 * hiện khi đích an toàn, và lúc bấm thì đi tới ĐÚNG đích đã chuẩn hoá** —
 * không phải chuỗi gốc. Kiểm một chuỗi rồi điều hướng bằng chuỗi khác chính là
 * khe đã đẻ ra open redirect ở đường cứu phiên.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

// Mocks PHẢI hoist trước khi import component.
vi.mock("@/lib/stores/auth.store", () => ({
  useAuthStore: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      isAuthenticated: true,
      logout: vi.fn(),
      user: { id: 1, role: "admin" },
    }),
}))

vi.mock("@/hooks/useNotifications", () => ({
  useAddNotification: () => vi.fn(),
  useMarkAsRead: () => ({ mutate: vi.fn() }),
}))

vi.mock("@/hooks/useNotificationPreferences", () => ({
  useNotificationPreferences: () => ({ data: undefined }),
}))

/** Tuỳ chọn của một lượt gọi toast — chỉ giữ phần bộ ca này cần. */
type TuyChonToast = {
  action?: { label: string; onClick: () => void }
}

const goiToast: Array<{ tieuDe: unknown; tuyChon: TuyChonToast }> = []

function ghiToast(tieuDe: unknown, tuyChon?: TuyChonToast) {
  goiToast.push({ tieuDe, tuyChon: tuyChon ?? {} })
}

vi.mock("sonner", () => ({
  toast: {
    success: ghiToast,
    error: ghiToast,
    info: ghiToast,
    warning: ghiToast,
  },
}))

vi.mock("@/components/layouts/SecurityBanner", () => ({
  bumpSuspiciousLoginBanner: vi.fn(),
}))

type BoNhanSuKien = (...args: unknown[]) => void
const socketStub = {
  handlers: new Map<string, BoNhanSuKien[]>(),
  on(event: string, handler: BoNhanSuKien) {
    const list = this.handlers.get(event) ?? []
    list.push(handler)
    this.handlers.set(event, list)
  },
  off(event: string, handler: BoNhanSuKien) {
    const list = this.handlers.get(event) ?? []
    this.handlers.set(
      event,
      list.filter((h) => h !== handler),
    )
  },
  onAny: vi.fn(),
  offAny: vi.fn(),
  emit: vi.fn(),
  fire(event: string, ...args: unknown[]) {
    for (const handler of this.handlers.get(event) ?? []) handler(...args)
  },
  reset() {
    this.handlers.clear()
  },
  get connected() {
    return true
  },
}

vi.mock("@/lib/socket/client", () => ({
  socketService: {
    getSocket: () => socketStub,
    connect: vi.fn(),
    disconnect: vi.fn(),
    isConnected: () => true,
  },
}))

// Import SAU mocks.
import { SocketHandler as SocketHandlerComponent } from "./SocketHandler"

/**
 * Mỗi tải trọng là MỘT cách thoát site khác nhau — không phải cách viết khác
 * của cùng một cách.
 *
 * ⚠️ TAB/LF/CR ở đây là ký tự THẬT (`\t`, `\n`, `\r`), không phải chuỗi
 * `"%09"`. Trình phân giải URL của WHATWG XOÁ chúng trước khi parse, nên
 * `"/\t/evil.example"` biến thành `"//evil.example"` — đổi origin. Một ca viết
 * literal `"%09"` sẽ XANH mà không hề chạm tới lỗ hổng.
 */
const DICH_NGUY_HIEM: Array<[string, string]> = [
  ["TAB nội bộ", "/\t/evil.example"],
  ["LF nội bộ", "/\n/evil.example"],
  ["CR nội bộ", "/\r/evil.example"],
  ["một backslash", "/\\evil.example"],
  ["domain nối đuôi", "https://qlts.example.evil.com/x"],
  ["userinfo @", "https://qlts.example@evil.com/x"],
  ["scheme-relative", "//evil.example/x"],
  ["javascript:", "javascript:alert(1)"],
  ["dot-segment tụt xuống `//`", "/..//evil.example"],
]

let originalLocation: Location

function renderHandler() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <SocketHandlerComponent />
    </QueryClientProvider>,
  )
}

async function fireConnect() {
  act(() => {
    socketStub.fire("connect")
  })
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

/** Gói payload tối thiểu cho sự kiện `notification`. */
function thongBao(link: string | null) {
  return {
    id: 1,
    title: "Tiêu đề",
    message: "nội dung",
    type: "info",
    is_read: false,
    created_at: "2026-09-20T00:00:00.000Z",
    link,
  }
}

beforeEach(() => {
  socketStub.reset()
  goiToast.length = 0
  originalLocation = window.location
  Object.defineProperty(window, "location", {
    value: { href: "https://qlts.example/goc", assign: vi.fn(), reload: vi.fn() },
    writable: true,
    configurable: true,
  })
})

afterEach(() => {
  Object.defineProperty(window, "location", {
    value: originalLocation,
    writable: true,
    configurable: true,
  })
  vi.clearAllMocks()
})

describe("SocketHandler · sự kiện `notification` — nút không dẫn ra khỏi site", () => {
  it.each(DICH_NGUY_HIEM)(
    "%s: KHÔNG dựng nút hành động nào",
    async (_ten, link) => {
      renderHandler()
      await fireConnect()

      await act(async () => {
        socketStub.fire("notification", thongBao(link))
      })

      expect(goiToast.length).toBeGreaterThan(0)
      for (const { tuyChon } of goiToast) {
        expect(tuyChon.action).toBeUndefined()
      }
    },
  )

  it("liên kết nội bộ: nút hiện, và bấm thì đi tới ĐÍCH ĐÃ CHUẨN HOÁ", async () => {
    renderHandler()
    await fireConnect()

    await act(async () => {
      socketStub.fire("notification", thongBao("/ho-so/123?tab=a#b"))
    })

    const coAction = goiToast.filter((g) => g.tuyChon.action)
    expect(coAction.length).toBe(1)

    act(() => {
      coAction[0].tuyChon.action?.onClick()
    })
    expect(window.location.href).toBe("/ho-so/123?tab=a#b")
  })

  it("`/a/../b` được chuẩn hoá về `/b` TRƯỚC khi điều hướng", async () => {
    renderHandler()
    await fireConnect()

    await act(async () => {
      socketStub.fire("notification", thongBao("/a/../b"))
    })

    const coAction = goiToast.filter((g) => g.tuyChon.action)
    expect(coAction.length).toBe(1)
    act(() => {
      coAction[0].tuyChon.action?.onClick()
    })
    // Điều hướng bằng ĐÍCH, không bằng chuỗi gốc `/a/../b`.
    expect(window.location.href).toBe("/b")
  })
})

describe("SocketHandler · sự kiện `system_alert` — `action_url` là guard DUY NHẤT", () => {
  it.each(DICH_NGUY_HIEM)(
    "%s: KHÔNG dựng nút 'View'",
    async (_ten, actionUrl) => {
      renderHandler()
      await fireConnect()

      await act(async () => {
        socketStub.fire("system_alert", {
          severity: "warning",
          message: "canh bao",
          action_url: actionUrl,
        })
      })

      expect(goiToast.length).toBeGreaterThan(0)
      for (const { tuyChon } of goiToast) {
        expect(tuyChon.action).toBeUndefined()
      }
    },
  )

  it("`action_url` nội bộ: nút hiện và bấm thì đi tới đích đã chuẩn hoá", async () => {
    renderHandler()
    await fireConnect()

    await act(async () => {
      socketStub.fire("system_alert", {
        severity: "error",
        message: "canh bao",
        action_url: "/admin/system?tab=log",
      })
    })

    const coAction = goiToast.filter((g) => g.tuyChon.action)
    expect(coAction.length).toBe(1)
    act(() => {
      coAction[0].tuyChon.action?.onClick()
    })
    expect(window.location.href).toBe("/admin/system?tab=log")
  })

  it("thiếu `action_url` hoàn toàn thì cũng không có nút (không ném)", async () => {
    renderHandler()
    await fireConnect()

    await act(async () => {
      socketStub.fire("system_alert", { severity: "info", message: "chi la tin" })
    })

    expect(goiToast.length).toBeGreaterThan(0)
    for (const { tuyChon } of goiToast) {
      expect(tuyChon.action).toBeUndefined()
    }
  })
})
