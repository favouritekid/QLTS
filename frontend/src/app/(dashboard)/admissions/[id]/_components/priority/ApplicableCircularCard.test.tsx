/**
 * V3 — ApplicableCircularCard: hiển thị đúng giá trị BE tính, nút theo cờ quyền,
 * hộp thoại gửi đúng thân và đòi xác nhận khi BE nói cần.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import userEvent from "@testing-library/user-event"

import { render, screen, waitFor } from "@/test/utils/test-utils"
import {
  ApplicableCircularCard,
  ApplicableCircularDialog,
  deriveCircularDisplay,
} from "./ApplicableCircularCard"

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false)
    Element.prototype.releasePointerCapture = vi.fn()
  }
})

vi.mock("@/hooks/useMediaQuery", () => ({
  useMediaQuery: () => false,
  useIsMobile: () => false,
  useIsTablet: () => false,
  useIsDesktop: () => true,
}))

const mutateImpl = vi.fn()
vi.mock("@/lib/hooks/use-applicable-circular", () => ({
  useChangeApplicableCircular: () => ({ mutateAsync: mutateImpl, isPending: false }),
}))

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const BASE = {
  id: 7,
  version: 3,
  permissions: {} as Record<string, boolean>,
  applicable_circular: "TT05_2021" as "TT05_2021" | "TT76_2026" | null,
  applicable_circular_effective: "TT05_2021" as const,
  applicable_circular_effective_basis: "stored" as const,
  applicable_circular_source: "default_first_submit" as const,
  first_submitted_at: "2026-10-20T03:00:00+00:00",
  first_submitted_source: "submit_transition" as const,
  priority_catalog_warning: null,
}

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe("deriveCircularDisplay", () => {
  it("hồ sơ đã nộp: nhãn thông tư + nguồn + ngày nộp đầu theo giờ VN", () => {
    const v = deriveCircularDisplay(BASE)
    expect(v.circularLabel).toBe("TT 05/2021/TT-BLĐTBXH")
    expect(v.basisLabel).toBe("Mặc định theo ngày nộp đầu")
    // 03:00Z = 10:00 giờ VN
    expect(v.firstSubmittedLabel).toContain("10:00")
    expect(v.firstSubmittedLabel).toContain("20/10/2026")
  })

  it("hồ sơ chưa nộp: nhãn 'Dự kiến' và 'Chưa nộp'", () => {
    const v = deriveCircularDisplay({
      ...BASE,
      applicable_circular: null,
      applicable_circular_effective: "TT76_2026",
      applicable_circular_effective_basis: "predicted",
      applicable_circular_source: null,
      first_submitted_at: null,
      first_submitted_source: null,
    })
    expect(v.circularLabel).toBe("TT 76/2026/TT-BGDĐT")
    expect(v.basisLabel).toBe("Dự kiến — áp dụng nếu nộp hôm nay")
    expect(v.firstSubmittedLabel).toBe("Chưa nộp")
  })

  it("thiếu chứng cứ ngày nộp: nói rõ, không bịa ngày", () => {
    const v = deriveCircularDisplay({
      ...BASE,
      applicable_circular_source: "backfill_missing_evidence",
      first_submitted_at: null,
      first_submitted_source: "missing_evidence",
    })
    expect(v.firstSubmittedLabel).toBe("Thiếu ngày nộp đầu (dữ liệu cũ)")
    expect(v.basisLabel).toBe("Gán TT 05/2021 — thiếu ngày nộp đầu")
  })
})

describe("ApplicableCircularCard", () => {
  it("hiện cảnh báo danh mục khi BE trả", () => {
    wrap(
      <ApplicableCircularCard
        profile={{
          ...BASE,
          priority_catalog_warning: { code: "kv_catalog_provisional", circular: "TT05_2021", message: "Danh mục TẠM" },
        }}
      />,
    )
    expect(screen.getByTestId("priority-catalog-warning")).toHaveTextContent("Danh mục TẠM")
  })

  it("ẩn nút đổi khi BE không cấp quyền", () => {
    wrap(<ApplicableCircularCard profile={BASE} />)
    expect(screen.queryByTestId("applicable-circular-change-button")).not.toBeInTheDocument()
  })

  it("hiện nút đổi khi permissions.change_applicable_circular", () => {
    wrap(<ApplicableCircularCard profile={{ ...BASE, permissions: { change_applicable_circular: true } }} />)
    expect(screen.getByTestId("applicable-circular-change-button")).toBeInTheDocument()
  })
})

describe("ApplicableCircularDialog", () => {
  beforeEach(() => {
    mutateImpl.mockReset()
    mutateImpl.mockResolvedValue({})
  })

  async function dienForm(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByTestId("circular-select"))
    await user.click(await screen.findByRole("option", { name: "TT 76/2026/TT-BGDĐT" }))
    await user.type(screen.getByTestId("circular-reason-input"), "Ly do du dai hai muoi ky tu tro len")
  }

  it("gửi đúng thân: version, thông tư mới, lý do đã trim, không xác nhận khi không cần", async () => {
    const user = userEvent.setup()
    wrap(
      <ApplicableCircularDialog
        open
        onOpenChange={vi.fn()}
        profileId={7}
        profileVersion={3}
        stored="TT05_2021"
        effective="TT05_2021"
        requiresAck={false}
      />,
    )
    await dienForm(user)
    await user.click(screen.getByTestId("circular-submit"))
    await waitFor(() =>
      expect(mutateImpl).toHaveBeenCalledWith({
        version: 3,
        circular: "TT76_2026",
        reason: "Ly do du dai hai muoi ky tu tro len",
        acknowledge_post_publish: false,
      }),
    )
  })

  it("khi BE nói cần xác nhận: chưa tick thì không gửi được", async () => {
    const user = userEvent.setup()
    wrap(
      <ApplicableCircularDialog
        open
        onOpenChange={vi.fn()}
        profileId={7}
        profileVersion={3}
        stored="TT05_2021"
        effective="TT05_2021"
        requiresAck
      />,
    )
    await dienForm(user)
    expect(screen.getByTestId("circular-submit")).toBeDisabled()
    await user.click(screen.getByTestId("circular-ack-checkbox"))
    expect(screen.getByTestId("circular-submit")).toBeEnabled()
  })
})

describe("ApplicableCircularCard — ghim thông tư đang DỰ KIẾN (V3 F25)", () => {
  it("chưa lưu, đang dự kiến TT 05: hộp thoại cho chọn TT 05 để ghim qua 03-11", async () => {
    const user = userEvent.setup()
    wrap(
      <ApplicableCircularCard
        profile={{
          ...BASE,
          applicable_circular: null,
          applicable_circular_source: null,
          applicable_circular_effective_basis: "predicted",
          first_submitted_at: null,
          first_submitted_source: null,
          permissions: { change_applicable_circular: true },
        }}
      />,
    )
    await user.click(screen.getByTestId("applicable-circular-change-button"))
    await user.click(screen.getByTestId("circular-select"))
    expect(await screen.findByRole("option", { name: "TT 05/2021/TT-BLĐTBXH" })).toBeInTheDocument()
  })

  it("đã lưu TT 05: không đề nghị đổi sang chính TT 05", async () => {
    const user = userEvent.setup()
    wrap(
      <ApplicableCircularCard
        profile={{
          ...BASE,
          applicable_circular: "TT05_2021",
          applicable_circular_source: "manual",
          permissions: { change_applicable_circular: true },
        }}
      />,
    )
    await user.click(screen.getByTestId("applicable-circular-change-button"))
    await user.click(screen.getByTestId("circular-select"))
    await screen.findByRole("option", { name: "TT 76/2026/TT-BGDĐT" })
    expect(screen.queryByRole("option", { name: "TT 05/2021/TT-BLĐTBXH" })).not.toBeInTheDocument()
  })
})
