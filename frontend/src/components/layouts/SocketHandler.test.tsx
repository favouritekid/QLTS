/**
 * SocketHandler Event Scoping Tests (P2 anchor 2026-05-22)
 *
 * Pin contract:
 *   - ADMISSION_* domain events (admission_result_published, decision_*,
 *     waitlist_*) → cascade invalidate admissionsKeys.all + detail + lead detail.
 *   - data_updated với operation="update" + resource_type="admission_profile"
 *     → detail-only scope (KHÔNG list/counts/stats cascade).
 *   - data_updated với operation="create"|"delete" admission_profile →
 *     admissionsKeys.all cascade.
 *   - application_minor_corrected → detail-only.
 *
 * Test strategy: stub `socketService.getSocket()` trả socket mock với
 * `on/off/onAny/offAny` registry. Render SocketHandler, fire socket
 * "connect", rồi gọi handler đã đăng ký với synthetic payload. Verify
 * `queryClient.invalidateQueries` calls qua spy.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

// Mocks MUST be hoisted before component import
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

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}))

// Socket stub w/ event registry
type SocketHandler = (...args: unknown[]) => void
const socketStub = {
  handlers: new Map<string, SocketHandler[]>(),
  on(event: string, handler: SocketHandler) {
    const list = this.handlers.get(event) ?? []
    list.push(handler)
    this.handlers.set(event, list)
  },
  off(event: string, handler: SocketHandler) {
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

// Import AFTER mocks
import { SocketHandler as SocketHandlerComponent } from "./SocketHandler"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import { leadsKeys } from "@/hooks/useLeads"

function renderHandler() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")
  const result = render(
    <QueryClientProvider client={queryClient}>
      <SocketHandlerComponent />
    </QueryClientProvider>,
  )
  return { queryClient, invalidateSpy, ...result }
}

async function fireConnect() {
  // Component first registers a 'connect' handler then setIsSocketConnected.
  // Fire connect to trigger the listener-registration effect.
  act(() => {
    socketStub.fire("connect")
  })
  // Allow effects to flush
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

describe("SocketHandler — admission event scoping (P2 anchor)", () => {
  beforeEach(() => {
    socketStub.reset()
    vi.clearAllMocks()
  })

  describe("ADMISSION_* domain events → cascade invalidation", () => {
    it.each([
      "admission_result_published",
      "admission_decision_admitted",
      "admission_decision_waitlisted",
      "admission_decision_rejected",
      "admission_waitlist_promoted",
      "admission_waitlist_rejected",
    ])("%s invalidates admissionsKeys.all + detail + lead detail", async (event) => {
      const { invalidateSpy } = renderHandler()
      await fireConnect()

      act(() => {
        socketStub.fire(event, { application_id: 42, lead_id: 99 })
      })

      // Cascade root key
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.all }),
      )
      // Targeted detail
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.detail(42) }),
      )
      // Lead projection
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: leadsKeys.detail(99) }),
      )

      invalidateSpy.mockRestore()
    })
  })

  describe("data_updated admission_profile → scope by operation", () => {
    it("operation=update → admissionDetails scope only (NO list/stats)", async () => {
      const { invalidateSpy, queryClient } = renderHandler()
      await fireConnect()

      act(() => {
        socketStub.fire("data_updated", {
          resource_type: "admission_profile",
          operation: "update",
          resource_id: 42,
          timestamp: new Date().toISOString(),
        })
      })

      // Debounce 300ms → wait
      await act(async () => {
        await new Promise((r) => setTimeout(r, 400))
      })

      // Detail key invalidated
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.detail(42) }),
      )

      // List/stats key should NOT have been invalidated by data_updated
      const allCalls = invalidateSpy.mock.calls.filter(([opts]) => {
        const key = (opts as { queryKey: readonly unknown[] }).queryKey
        return (
          Array.isArray(key) &&
          key.length === 1 &&
          key[0] === "admissions"
        )
      })
      expect(allCalls.length).toBe(0)

      invalidateSpy.mockRestore()
      queryClient.clear()
    })

    it("operation=create → admissionsKeys.all cascade (list rows change)", async () => {
      const { invalidateSpy, queryClient } = renderHandler()
      await fireConnect()

      act(() => {
        socketStub.fire("data_updated", {
          resource_type: "admission_profile",
          operation: "create",
          resource_id: 50,
          timestamp: new Date().toISOString(),
        })
      })

      await act(async () => {
        await new Promise((r) => setTimeout(r, 400))
      })

      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.all }),
      )

      invalidateSpy.mockRestore()
      queryClient.clear()
    })
  })

  describe("application_minor_corrected → detail-only", () => {
    it("invalidates admission detail only, NOT root cascade", async () => {
      const { invalidateSpy, queryClient } = renderHandler()
      await fireConnect()

      act(() => {
        socketStub.fire("application_minor_corrected", {
          application_id: 77,
          lead_id: 88,
          changed_fields: ["full_name"],
          actor_id: 1,
          corrected_at: new Date().toISOString(),
        })
      })

      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.detail(77) }),
      )

      // No root cascade (admissionsKeys.all) — list/counts/stats stay cached
      const rootCalls = invalidateSpy.mock.calls.filter(([opts]) => {
        const key = (opts as { queryKey: readonly unknown[] }).queryKey
        return (
          Array.isArray(key) &&
          key.length === 1 &&
          key[0] === "admissions"
        )
      })
      expect(rootCalls.length).toBe(0)

      invalidateSpy.mockRestore()
      queryClient.clear()
    })
  })
})
