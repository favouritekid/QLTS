// src/hooks/admissions/useAdmissionViewModel.test.ts
// @vitest-environment jsdom
/**
 * useAdmissionViewModel Hook Tests
 *
 * Validates BUG-29 fix: STATUS_LABELS and STATUS_COLORS must include
 * revision_requested and withdrawn statuses with correct Vietnamese labels.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook } from "@testing-library/react"

// ---------------------------------------------------------------------------
// Mock useGetAdmission
// ---------------------------------------------------------------------------

const useGetAdmissionMock = vi.fn()

vi.mock("./useAdmissions", () => ({
  useGetAdmission: (...args: unknown[]) => useGetAdmissionMock(...args),
}))

import { useAdmissionViewModel } from "./useAdmissionViewModel"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal mock data matching AdmissionProfileResponse shape */
function createMockAdmission(
  overrides: Partial<AdmissionProfileResponse> = {},
): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 100,
    full_name: "Nguyễn Văn A",
    dob: null,
    gender: null,
    email: null,
    phone: null,
    citizen_id: null,
    citizen_id_masked: null,
    social_insurance_number: null,
    nationality: null,
    ethnicity: null,
    religion: null,
    disability_type: null,
    permanent_province: null,
    permanent_district: null,
    permanent_ward: null,
    place_of_birth: null,
    native_place: null,
    union_entry_date: null,
    party_entry_date: null,
    party_official_entry_date: null,
    status: "draft",
    applied_rules: {
      min_gpa: null,
      min_score: null,
      method_type: null,
    },
    family_info: [],
    academic_history: [],
    admission_scores: null,
    documents_checklist: [],
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    permissions: {},
    eligibility_status: "pending",
    validation_errors: [],
    available_actions: [],
    completion_percent: 0,
    ...overrides,
  } as AdmissionProfileResponse
}

function setupMock(data: AdmissionProfileResponse | null) {
  useGetAdmissionMock.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    error: null,
    isSuccess: data !== null,
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useAdmissionViewModel", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe("STATUS_LABELS (BUG-29)", () => {
    it('should return label "Yêu cầu bổ sung" for revision_requested', () => {
      setupMock(createMockAdmission({ status: "revision_requested" }))

      const { result } = renderHook(() => useAdmissionViewModel(1))

      expect(result.current.data?.statusLabel).toBe("Yêu cầu bổ sung")
    })

    it('should return label "Đã rút hồ sơ" for withdrawn', () => {
      setupMock(createMockAdmission({ status: "withdrawn" }))

      const { result } = renderHook(() => useAdmissionViewModel(1))

      expect(result.current.data?.statusLabel).toBe("Đã rút hồ sơ")
    })
  })

  describe("STATUS_COLORS (BUG-29)", () => {
    it('should return color "orange" for revision_requested', () => {
      setupMock(createMockAdmission({ status: "revision_requested" }))

      const { result } = renderHook(() => useAdmissionViewModel(1))

      expect(result.current.data?.statusColor).toBe("orange")
    })

    it('should return color "gray" for withdrawn', () => {
      setupMock(createMockAdmission({ status: "withdrawn" }))

      const { result } = renderHook(() => useAdmissionViewModel(1))

      expect(result.current.data?.statusColor).toBe("gray")
    })
  })

  describe("all known statuses have labels and colors", () => {
    const expectedStatuses: Array<{
      status: string
      label: string
      color: string
    }> = [
      { status: "draft", label: "Nháp", color: "gray" },
      { status: "submitted", label: "Chờ duyệt", color: "yellow" },
      { status: "resubmitted", label: "Nộp lại", color: "amber" },
      { status: "approved", label: "Đã duyệt", color: "green" },
      { status: "rejected", label: "Từ chối", color: "red" },
      { status: "confirmed", label: "Đã xác nhận", color: "emerald" },
      { status: "enrolled", label: "Đã nhập học", color: "blue" },
      { status: "overridden", label: "Đã override", color: "purple" },
      { status: "revision_requested", label: "Yêu cầu bổ sung", color: "orange" },
      { status: "withdrawn", label: "Đã rút hồ sơ", color: "gray" },
    ]

    it.each(expectedStatuses)(
      'status "$status" should have label "$label" and color "$color"',
      ({ status, label, color }) => {
        setupMock(createMockAdmission({ status: status as AdmissionProfileResponse["status"] }))

        const { result } = renderHook(() => useAdmissionViewModel(1))

        expect(result.current.data?.statusLabel).toBe(label)
        expect(result.current.data?.statusColor).toBe(color)
        // Verify label is Vietnamese, not a raw English key
        expect(result.current.data?.statusLabel).not.toBe(status)
      },
    )
  })

  describe("null handling", () => {
    it("should return null viewModel when no data", () => {
      setupMock(null)

      const { result } = renderHook(() => useAdmissionViewModel(1))

      expect(result.current.data).toBeNull()
    })
  })
})
