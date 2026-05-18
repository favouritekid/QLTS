/**
 * PriorityTab — Vitest unit tests (Q9 #07 Phase D.3)
 *
 * Verifies:
 * - Renders 3 sections (cultural/vocational + basis + snapshot)
 * - Preview matrix derives basis correctly (THPT/TC/COMMUNE_FALLBACK/etc.)
 * - area_resolution_basis switch reveals commune_code input
 * - Manual override basis shows warning callout
 * - Snapshot card renders when profile has priority_resolution_snapshot
 */
import { describe, it, expect, vi, beforeAll } from "vitest"
import { useForm } from "react-hook-form"
import { Form } from "@/components/ui/form"
import { render, screen, fireEvent } from "@/test/utils/test-utils"
import { PriorityTab } from "./PriorityTab"
import type { AdmissionProfileResponse, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false)
  }
})

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
    } as any,
  })
  return (
    <Form {...form}>
      <PriorityTab form={form} profile={profile} isEditable={isEditable} />
    </Form>
  )
}

describe("PriorityTab", () => {
  it("renders intro card + snapshot card + 2 input sections", () => {
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/Về phần này/i)).toBeInTheDocument()
    expect(screen.getByText(/Khu vực ưu tiên đã xác định/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Trình độ học vấn/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Cách tính khu vực ưu tiên/i).length).toBeGreaterThan(0)
  })

  it("intro card explains KV rates (KV1 0.75đ, KV2-NT 0.50đ, KV2 0.25đ, KV3 không cộng)", () => {
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/0,75đ/)).toBeInTheDocument()
    expect(screen.getByText(/0,50đ/)).toBeInTheDocument()
    expect(screen.getByText(/0,25đ/)).toBeInTheDocument()
    expect(screen.getByText(/không cộng điểm/i)).toBeInTheDocument()
  })

  it("snapshot empty state when profile has no resolved KV", () => {
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/Chưa được tính/i)).toBeInTheDocument()
    expect(
      screen.getByText(/KV sẽ tự động xác định khi hồ sơ được nộp/i)
    ).toBeInTheDocument()
  })

  it("preview shows 'Chưa đủ thông tin' when cultural not set", () => {
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/Chưa đủ thông tin/i)).toBeInTheDocument()
  })

  it("preview shows 'Theo trường THPT/GDTX' when cultural=graduated_thpt", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ cultural_education_level: "graduated_thpt" }}
      />
    )
    expect(screen.getByText(/Theo trường THPT\/GDTX đã học/i)).toBeInTheDocument()
  })

  it("preview shows 'Theo trường Trung cấp' khi graduated_thcs + trung_cap (liên thông)", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thcs",
          vocational_qualification: "trung_cap",
        }}
      />
    )
    expect(screen.getByText(/Theo trường Trung cấp đã học/i)).toBeInTheDocument()
  })

  it("preview shows 'Theo hộ khẩu' khi graduated_thcs + none (COMMUNE_FALLBACK)", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thcs",
          vocational_qualification: "none",
        }}
      />
    )
    expect(
      screen.getAllByText(/Theo hộ khẩu thường trú/i).length
    ).toBeGreaterThan(0)
  })

  it("preview shows 'Theo hộ khẩu (đặc biệt)' khi basis=permanent_address_special", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thpt",
          area_resolution_basis: "permanent_address_special",
        }}
      />
    )
    expect(
      screen.getAllByText(/Theo hộ khẩu \(trường hợp đặc biệt\)/i).length
    ).toBeGreaterThan(0)
  })

  it("preview shows 'Cán bộ ấn định thủ công' khi basis=manual_override", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thpt",
          area_resolution_basis: "manual_override",
        }}
      />
    )
    expect(
      screen.getAllByText(/Cán bộ ấn định thủ công/i).length
    ).toBeGreaterThan(0)
  })

  it("commune_code input shown khi basis=permanent_address_special", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ area_resolution_basis: "permanent_address_special" }}
      />
    )
    expect(
      screen.getByText(/Mã xã\/phường hộ khẩu thường trú/i)
    ).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/01_00025.*Phường Giảng Võ/i)).toBeInTheDocument()
  })

  it("commune_code input hidden khi basis=high_school (default)", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ area_resolution_basis: "high_school" }}
      />
    )
    expect(
      screen.queryByText(/Mã xã\/phường hộ khẩu thường trú/i)
    ).not.toBeInTheDocument()
  })

  it("manual_override basis shows warning callout 'chế độ thủ công'", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ area_resolution_basis: "manual_override" }}
      />
    )
    expect(screen.getByText(/chế độ thủ công/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Lý do thay đổi/i)
    ).toBeInTheDocument()
  })

  it("renders KV badge + Vietnamese pathway label when snapshot has data", () => {
    const profile = buildProfile({
      // @ts-expect-error — snapshot is dynamic JSONB, not in static type yet
      priority_resolution_snapshot: {
        kv_resolved: "KV2",
        rule_applied: "tiebreak_graduation_school",
        pathway: "thpt_multi_school",
        breakdown: { winner_years: 3, graduation_school_id: 162 },
      },
    })
    render(<HarnessWrapper profile={profile} />)
    // KV badge với rate label
    expect(screen.getByText(/KV2 \(\+0,25đ\)/)).toBeInTheDocument()
    // Vietnamese pathway label (not raw code)
    expect(
      screen.getByText(/Theo lịch sử học các trường THPT/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Trường tốt nghiệp \(khi thời gian học bằng nhau\)/i)
    ).toBeInTheDocument()
  })
})
