/**
 * Vitest tests cho PathDetailDrawer 5-tab (Phase 2 v8.2 PR-2D.1 v4a).
 *
 * Anchor:
 * - 5 tabs render
 * - Quota tab client guard (admit ≤ round)
 * - Identity tab can_edit gate
 * - Lifecycle tab can_activate gate (thin-client)
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Test-debt fix 2026-05-11: FM-2 added useRouter cho tab URL state sync.
// Mock per-test override `useSearchParams` để test active tab Vòng đời
// (Lifecycle) cần pre-set `?tab=lifecycle` initial state — Tabs component
// dùng `value={tab}` controlled (URL-derived), không phải `defaultValue`.
const tabReplaceMock = vi.fn()
const searchParamsMock = vi.fn(() => new URLSearchParams())
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: tabReplaceMock, push: vi.fn() }),
  useSearchParams: () => searchParamsMock(),
  usePathname: () => "/admin/admission-config",
}))

const hoisted = vi.hoisted(() => {
  const defaultPath = {
    id: 109,
    display_name: "CNTT - Học bạ",
    status: "draft",
    can_edit: true,
    can_activate: false,
    validation_errors: [] as string[],
    round_quota: 50,
    admit_quota: 30,
    submission_count: 5,
    display_order: 1,
    visibility: "public",
    application_fee: null,
    allow_unverified_submission: false,
    criteria: { id: 200, code: "HB2026_CNTT" },
    admission_method: { id: 1, code: "hoc_ba" },
    admission_method_id: 1,
  }
  return {
    defaultPath,
    mockUseAdmissionPath: vi.fn(() => ({ data: defaultPath, isLoading: false })),
    mockUpdateQuota: vi.fn(),
    mockUpdatePath: vi.fn(),
    mockActivate: vi.fn(),
    mockDeactivate: vi.fn(),
  }
})

vi.mock("@/hooks/admissions/useAdmissionPaths", () => ({
  admissionPathKeys: { all: ["admission-paths"] },
  useAdmissionPath: hoisted.mockUseAdmissionPath,
  useUpdateAdmissionPath: () => ({ mutateAsync: hoisted.mockUpdatePath, isPending: false }),
  useActivateAdmissionPath: () => ({ mutateAsync: hoisted.mockActivate, isPending: false }),
  useDeactivateAdmissionPath: () => ({ mutateAsync: hoisted.mockDeactivate, isPending: false }),
}))

vi.mock("@/hooks/admissions/useQuotaMatrix", () => ({
  quotaMatrixKeys: { all: ["quota-matrix"] },
  useUpdatePathQuota: () => ({ mutateAsync: hoisted.mockUpdateQuota, isPending: false }),
}))

vi.mock("../ConfigCriteria", () => ({
  ConfigCriteria: () => <div data-testid="config-criteria-stub">criteria form</div>,
}))
vi.mock("../ConfigDocuments", () => ({
  ConfigDocuments: () => <div data-testid="config-documents-stub">documents form</div>,
}))

const toastError = vi.fn()
const toastSuccess = vi.fn()
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}))

import { PathDetailDrawer } from "./PathDetailDrawer"

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  hoisted.mockUpdateQuota.mockReset()
  hoisted.mockUpdatePath.mockReset()
  hoisted.mockActivate.mockReset()
  hoisted.mockDeactivate.mockReset()
  toastError.mockReset()
  toastSuccess.mockReset()
  tabReplaceMock.mockReset()
  // Reset URL search params về default empty cho mỗi test; test có thể
  // override qua searchParamsMock.mockReturnValue(...) inside test body.
  searchParamsMock.mockImplementation(() => new URLSearchParams())
  // Reset path mock to default; per-test override với mockReturnValue if needed
  hoisted.mockUseAdmissionPath.mockReturnValue({
    data: hoisted.defaultPath,
    isLoading: false,
  })
})

describe("PathDetailDrawer 5-tab", () => {
  it("renders 5 tabs + path display_name in header", () => {
    render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))
    expect(screen.getByText("CNTT - Học bạ")).toBeTruthy()
    expect(screen.getByRole("tab", { name: /Chỉ tiêu/ })).toBeTruthy()
    expect(screen.getByRole("tab", { name: /Định danh/ })).toBeTruthy()
    expect(screen.getByRole("tab", { name: /Tiêu chí/ })).toBeTruthy()
    expect(screen.getByRole("tab", { name: /Giấy tờ/ })).toBeTruthy()
    expect(screen.getByRole("tab", { name: /Vòng đời/ })).toBeTruthy()
  })

  it("ANCHOR (Quota tab client guard): blocks save khi admit > round", async () => {
    const user = userEvent.setup()
    render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))

    const submitInput = screen.getByLabelText(/Trần submit/) as HTMLInputElement
    const admitInput = screen.getByLabelText(/Trần admit/) as HTMLInputElement

    await user.clear(submitInput)
    await user.type(submitInput, "10")
    await user.clear(admitInput)
    await user.type(admitInput, "50")

    await user.click(screen.getByRole("button", { name: /Lưu chỉ tiêu/ }))
    expect(toastError).toHaveBeenCalledWith(
      "Trần admit phải ≤ trần submit. Giảm trần admit hoặc tăng trần submit.",
    )
    expect(hoisted.mockUpdateQuota).not.toHaveBeenCalled()
  })

  it("ANCHOR (thin-client can_edit=false): Quota inputs disabled, save button disabled", () => {
    hoisted.mockUseAdmissionPath.mockReturnValue({
      data: { ...hoisted.defaultPath, can_edit: false },
      isLoading: false,
    })
    render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))

    const submitInput = screen.getByLabelText(/Trần submit/) as HTMLInputElement
    expect(submitInput.disabled).toBe(true)
    const saveBtn = screen.getByRole("button", { name: /Lưu chỉ tiêu/ }) as HTMLButtonElement
    expect(saveBtn.disabled).toBe(true)
  })

  it("ANCHOR (thin-client can_activate=false): Activate button disabled, validation_errors render từ API", async () => {
    hoisted.mockUseAdmissionPath.mockReturnValue({
      data: {
        ...hoisted.defaultPath,
        status: "draft",
        can_activate: false,
        validation_errors: ["Missing criteria"],
      },
      isLoading: false,
    })
    // Pre-set ?tab=lifecycle vì Tabs component controlled bởi URL (FM-2).
    // Click tab Vòng đời trong test không persist vì mock router stateless.
    searchParamsMock.mockReturnValue(new URLSearchParams("tab=lifecycle"))
    render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))

    await waitFor(() => {
      const activateBtn = screen.getByRole("button", {
        name: /Kích hoạt/,
      }) as HTMLButtonElement
      expect(activateBtn.disabled).toBe(true)
    })
    expect(screen.getByText(/Missing criteria/)).toBeTruthy()
  })

  it("ANCHOR (status=active): shows Deactivate button, NOT Activate", async () => {
    hoisted.mockUseAdmissionPath.mockReturnValue({
      data: {
        ...hoisted.defaultPath,
        status: "active",
        can_activate: true,
      },
      isLoading: false,
    })
    searchParamsMock.mockReturnValue(new URLSearchParams("tab=lifecycle"))
    render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Vô hiệu hoá/ })).toBeTruthy()
    })
    expect(screen.queryByRole("button", { name: /Kích hoạt/ })).toBeNull()
  })

  // FM-2 contract anchor: click tab updates ?tab= URL searchParam via
  // router.replace. Trade-off cho 2 Lifecycle tests trên dùng pre-set
  // ?tab=lifecycle (avoid mock router stateless click→URL gap) —
  // anchor test này verify click→URL contract observable từ outside.
  // 5-tab `it.each` cover toàn bộ FM-2 contract thay vì 1 tab anchor.
  //
  // Edge: tab "quota" là default → click "quota" KHÔNG add ?tab=quota
  // (component xóa param khi value === default per FM-2 impl line 99).
  // Test "quota" verify replaceMock called với URL KHÔNG chứa "tab=".
  it.each([
    ["identity", "Định danh"],
    ["criteria", "Tiêu chí"],
    ["documents", "Giấy tờ"],
    ["lifecycle", "Vòng đời"],
  ])(
    "ANCHOR (FM-2): click tab %s updates ?tab=%s URL",
    async (param, label) => {
      const user = userEvent.setup()
      render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))
      // Click tab — Radix Tabs trigger button accessible qua role=tab.
      // Tên trigger là Vietnamese label.
      const tabTrigger = screen.getByRole("tab", {
        name: new RegExp(label, "i"),
      })
      await user.click(tabTrigger)
      // replaceMock được gọi với URL chứa `tab=<param>`. Format:
      // `${pathname}?tab=<param>` hoặc query string variant.
      expect(tabReplaceMock).toHaveBeenCalled()
      const lastCall = tabReplaceMock.mock.calls.at(-1)
      const url = lastCall?.[0] as string
      expect(url).toContain(`tab=${param}`)
    },
  )

  // Bug #1 anchor test (2026-05-11): khi BE return 400 với response.data.detail,
  // toast phải hiển thị BE detail KHÔNG phải axios generic "Request failed
  // with status code 400". parseApiError helper xử lý parse + fallback.
  it("ANCHOR (Bug #1): toast hiển thị BE detail thay vì axios generic khi save quota fail", async () => {
    const user = userEvent.setup()
    hoisted.mockUpdateQuota.mockRejectedValueOnce({
      response: { data: { detail: "Tier 1 chain violated: tổng admit_quota=80 vượt cap năm=70" } },
    })
    render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))

    const submitInput = screen.getByLabelText(/Trần submit/) as HTMLInputElement
    const admitInput = screen.getByLabelText(/Trần admit/) as HTMLInputElement
    await user.clear(submitInput)
    await user.type(submitInput, "100")
    await user.clear(admitInput)
    await user.type(admitInput, "80")

    await user.click(screen.getByRole("button", { name: /Lưu chỉ tiêu/ }))

    await waitFor(() => {
      expect(toastError).toHaveBeenCalledWith(
        "Tier 1 chain violated: tổng admit_quota=80 vượt cap năm=70",
      )
    })
  })

  it("ANCHOR (FM-2): click tab Quota (default) clears ?tab= URL param", async () => {
    const user = userEvent.setup()
    // Start from non-default tab để có tab=criteria trong URL trước click
    searchParamsMock.mockReturnValue(new URLSearchParams("tab=criteria"))
    render(wrap(<PathDetailDrawer pathId={109} onClose={() => {}} />))
    const quotaTab = screen.getByRole("tab", { name: /Chỉ tiêu/i })
    await user.click(quotaTab)
    expect(tabReplaceMock).toHaveBeenCalled()
    const lastCall = tabReplaceMock.mock.calls.at(-1)
    const url = lastCall?.[0] as string
    // Default tab "quota" xóa ?tab= param khỏi URL — FM-2 contract line 99
    // `if (next === "quota") params.delete("tab")`.
    expect(url).not.toContain("tab=")
  })
})
