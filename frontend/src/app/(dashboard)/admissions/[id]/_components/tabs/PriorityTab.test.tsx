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
  it("renders 2 main dropdown sections", () => {
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getAllByText(/Trình độ học vấn/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Trình độ văn hóa/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Trình độ chuyên môn/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Cơ sở xác định KV/i).length).toBeGreaterThan(0)
  })

  it("preview matrix shows NOT_RESOLVED when cultural not set", () => {
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(screen.getByText(/NOT_RESOLVED/i)).toBeInTheDocument()
    expect(screen.getByText(/Cần khai trình độ văn hóa trước/i)).toBeInTheDocument()
  })

  it("preview matrix shows THPT when cultural=graduated_thpt", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ cultural_education_level: "graduated_thpt" }}
      />
    )
    expect(screen.getByText(/^THPT$/)).toBeInTheDocument()
    expect(screen.getByText(/KV resolve từ lịch sử học THPT/i)).toBeInTheDocument()
  })

  it("preview matrix shows TC when graduated_thcs + trung_cap (liên thông path)", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thcs",
          vocational_qualification: "trung_cap",
        }}
      />
    )
    expect(screen.getByText(/^TC$/)).toBeInTheDocument()
    expect(screen.getByText(/KV resolve từ lịch sử học TC/i)).toBeInTheDocument()
  })

  it("preview matrix shows COMMUNE_FALLBACK when graduated_thcs + none", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thcs",
          vocational_qualification: "none",
        }}
      />
    )
    expect(screen.getByText(/COMMUNE_FALLBACK/i)).toBeInTheDocument()
  })

  it("preview matrix shows COMMUNE_SPECIAL when basis=permanent_address_special", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thpt",
          area_resolution_basis: "permanent_address_special",
        }}
      />
    )
    expect(screen.getByText(/COMMUNE_SPECIAL/i)).toBeInTheDocument()
  })

  it("preview matrix shows MANUAL when basis=manual_override", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{
          cultural_education_level: "graduated_thpt",
          area_resolution_basis: "manual_override",
        }}
      />
    )
    expect(screen.getByText(/^MANUAL$/)).toBeInTheDocument()
  })

  it("commune_code input shown when basis=permanent_address_special", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ area_resolution_basis: "permanent_address_special" }}
      />
    )
    expect(
      screen.getByText(/Mã xã\/phường hộ khẩu thường trú/i)
    ).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/01_00025/i)).toBeInTheDocument()
  })

  it("commune_code input hidden when basis=high_school (default)", () => {
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

  it("manual_override basis shows warning callout", () => {
    render(
      <HarnessWrapper
        profile={buildProfile()}
        defaults={{ area_resolution_basis: "manual_override" }}
      />
    )
    expect(screen.getAllByText(/Manual Override/i).length).toBeGreaterThan(0)
    expect(
      screen.getByText(/Lý do override bắt buộc khai báo/i)
    ).toBeInTheDocument()
  })

  it("renders snapshot card when profile has priority_resolution_snapshot", () => {
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
    expect(
      screen.getByText(/Kết quả xác định KV \(Backend\)/i)
    ).toBeInTheDocument()
    expect(screen.getByText(/^KV2$/)).toBeInTheDocument()
    expect(
      screen.getByText("tiebreak_graduation_school")
    ).toBeInTheDocument()
    expect(screen.getByText("thpt_multi_school")).toBeInTheDocument()
  })

  it("does NOT render snapshot card when profile has no snapshot", () => {
    render(<HarnessWrapper profile={buildProfile()} />)
    expect(
      screen.queryByText(/Kết quả xác định KV \(Backend\)/i)
    ).not.toBeInTheDocument()
  })
})
