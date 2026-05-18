/**
 * PriorityTab — Vitest unit tests (Q9 #07 Phase D.2+D.4 redesign)
 *
 * Tests the live-preview UX with BE auto-resolve.
 * - Intro card with KV rates
 * - Snapshot card: "tạm tính" vs "đã chốt" header
 * - KV badge color-coded by KV1/KV2/KV2-NT/KV3
 * - Switch toggle for special case (replaces old "Cách tính KV" dropdown)
 * - commune_code input conditional on switch ON
 *
 * Mocks usePreviewPriorityKv hook to avoid network.
 */
import { describe, it, expect, vi, beforeAll } from "vitest"
import { useForm } from "react-hook-form"
import { Form } from "@/components/ui/form"
import { render, screen } from "@/test/utils/test-utils"
import { PriorityTab } from "./PriorityTab"
import type { AdmissionProfileResponse, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false)
  }
})

// Mock live preview hook — control returned data per test
const mockPreview = vi.fn()
vi.mock("@/lib/hooks/use-preview-priority-kv", () => ({
  usePreviewPriorityKv: (...args: unknown[]) => mockPreview(...args),
}))

function buildProfile(overrides?: Partial<AdmissionProfileResponse>) {
  return {
    id: 42,
    status: "draft",
    permissions: { edit: true },
    cultural_education_level: null,
    vocational_qualification: "none",
    area_resolution_basis: null,
    permanent_commune_code: null,
    priority_object_codes: [],
    priority_resolution_snapshot: null,
    ...overrides,
  } as unknown as AdmissionProfileResponse
}

function HarnessWrapper({
  profile,
  isEditable = true,
  defaults,
}: {
  profile: AdmissionProfileResponse
  isEditable?: boolean
  defaults?: Partial<AdmissionProfileUpdateInput>
}) {
  const form = useForm<AdmissionProfileUpdateInput>({
    defaultValues: {
      version: 1,
      cultural_education_level: defaults?.cultural_education_level ?? null,
      vocational_qualification: defaults?.vocational_qualification ?? "none",
      area_resolution_basis: defaults?.area_resolution_basis ?? null,
      permanent_commune_code: defaults?.permanent_commune_code ?? null,
      academic_history: defaults?.academic_history ?? null,
    } as any,
  })
  return (
    <Form {...form}>
      <PriorityTab form={form} profile={profile} isEditable={isEditable} />
    </Form>
  )
}

describe("PriorityTab", () => {
  beforeAll(() => {
    mockPreview.mockReset?.()
  })

  it("renders intro card + KV rates table", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/Về phần này/i)).toBeInTheDocument()
    expect(screen.getByText(/0,75đ/)).toBeInTheDocument()
    expect(screen.getByText(/0,50đ/)).toBeInTheDocument()
    expect(screen.getByText(/0,25đ/)).toBeInTheDocument()
    expect(screen.getByText(/không cộng/i)).toBeInTheDocument()
  })

  it("snapshot card shows 'tạm tính' header in draft state", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/Khu vực ưu tiên \(tạm tính\)/i)).toBeInTheDocument()
  })

  it("snapshot card shows 'đã chốt' header when frozen + non-draft status", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    const profile = buildProfile({
      status: "submitted" as any,
      // @ts-expect-error JSONB dynamic
      priority_resolution_snapshot: {
        kv_resolved: "KV2",
        pathway: "thpt_multi_school",
        rule_applied: "longest_duration",
      },
    })
    render(<HarnessWrapper profile={profile} />)
    expect(screen.getByText(/Khu vực ưu tiên \(đã chốt\)/i)).toBeInTheDocument()
    expect(screen.getByText(/KV2 \(\+0,25đ\)/)).toBeInTheDocument()
  })

  it("live preview KV1 badge shows when preview returns KV1", () => {
    mockPreview.mockReturnValue({
      data: {
        kv_resolved: "KV1",
        pathway: "thpt_multi_school",
        rule_applied: "longest_duration",
        requires_manual_override: false,
        reason: null,
        breakdown: { kv_totals: { KV1: 3 }, winner_years: 3 },
      },
      isLoading: false,
    })
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ cultural_education_level: "graduated_thpt" }}
      />
    )
    expect(screen.getByText(/KV1 \(\+0,75đ\)/)).toBeInTheDocument()
    expect(screen.getByText(/sẽ chốt khi nộp hồ sơ/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Theo lịch sử học các trường THPT/i)
    ).toBeInTheDocument()
  })

  it("live preview loading state shows spinner text", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: true })
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ cultural_education_level: "graduated_thpt" }}
      />
    )
    expect(screen.getByText(/Đang tính/i)).toBeInTheDocument()
  })

  it("'Chưa đủ thông tin' message when cultural not set", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/Chưa đủ thông tin để tính KV/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Vui lòng khai trình độ văn hóa/i)
    ).toBeInTheDocument()
  })

  it("preview returns null KV with manual override flag → shows 'Cần cán bộ xem xét'", () => {
    mockPreview.mockReturnValue({
      data: {
        kv_resolved: null,
        pathway: null,
        rule_applied: "ambiguous_requires_manual",
        requires_manual_override: true,
        reason: "tied_graduation_year_and_grade",
        breakdown: null,
      },
      isLoading: false,
    })
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ cultural_education_level: "graduated_thpt" }}
      />
    )
    expect(
      screen.getByText(/Cần cán bộ xem xét\/ấn định thủ công/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Có 2 trường ngang nhau/i)
    ).toBeInTheDocument()
  })

  it("special case toggle (switch) renders + reveals commune_code input when ON", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ area_resolution_basis: "permanent_address_special" }}
      />
    )
    expect(
      screen.getByText(/Thí sinh thuộc nhóm đặc biệt/i)
    ).toBeInTheDocument()
    expect(
      screen.getByLabelText(/Mã xã\/phường nơi thường trú/i)
    ).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/01_00025.*Phường Giảng Võ/i)
    ).toBeInTheDocument()
  })

  it("special case toggle OFF hides commune_code input", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(
      screen.queryByLabelText(/Mã xã\/phường nơi thường trú/i)
    ).not.toBeInTheDocument()
  })

  it("does NOT render old 'Cách tính KV' dropdown (replaced by switch)", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(<HarnessWrapper profile={buildProfile()} />)
    // Old dropdown labels — should NOT exist
    expect(
      screen.queryByText(/Bình thường \(mặc định\)/i)
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Override thủ công \(cần officer phê duyệt\)/i)
    ).not.toBeInTheDocument()
  })

  it("manual_override basis shows admin warning callout", () => {
    mockPreview.mockReturnValue({ data: undefined, isLoading: false })
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ area_resolution_basis: "manual_override" }}
      />
    )
    expect(screen.getByText(/Manual Override/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Lý do thay đổi/i)
    ).toBeInTheDocument()
  })
})
