/**
 * UtEvidenceCard tests — Phase E wireframe candidate-side UT picker.
 *
 * Mocks `useUtCatalog` hook to control catalog state. Wraps test renders with
 * react-hook-form provider for form state binding.
 *
 * Covers:
 * - Loading / empty catalog / error states
 * - Catalog rows render với code + description + bonus
 * - Toggle checkbox → updates form `priority_object_codes` array
 * - Toggle ON → init `priority_object_evidence[code] = { status: 'pending' }`
 * - Toggle OFF → remove evidence key
 * - Selected rows show status badge (pending/verified/rejected)
 * - "Xem thêm" expand button shown khi > INITIAL_VISIBLE
 * - Disabled prop blocks interaction
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@/test/utils/test-utils"
import { useForm, UseFormReturn } from "react-hook-form"
import { UtEvidenceCard } from "./UtEvidenceCard"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"
import type { PriorityObjectCatalogItem } from "@/lib/api/priority-objects"

// Mock the catalog hook
const mockCatalog = vi.fn()
vi.mock("@/lib/hooks/use-priority-object-catalog", () => ({
  useUtCatalog: () => mockCatalog(),
}))

const sampleCatalog: PriorityObjectCatalogItem[] = [
  {
    group_code: "UT1",
    sub_code: "01",
    description: "Anh hùng LLVTND, anh hùng lao động",
    bonus_points: 2.0,
    evidence_doc_type: "Quyết định phong tặng",
  },
  {
    group_code: "UT1",
    sub_code: "02",
    description: "Thương binh ≥81%, bệnh binh ≥81%",
    bonus_points: 2.0,
    evidence_doc_type: null,
  },
  {
    group_code: "UT2",
    sub_code: "04",
    description: "Con thương binh, con liệt sĩ",
    bonus_points: 1.0,
    evidence_doc_type: null,
  },
  {
    group_code: "UT2",
    sub_code: "06",
    description: "Dân tộc thiểu số rất ít người",
    bonus_points: 0.5,
    evidence_doc_type: null,
  },
  {
    group_code: "UT3",
    sub_code: "03",
    description: "Người dân tộc thiểu số",
    bonus_points: 0.75,
    evidence_doc_type: null,
  },
  {
    group_code: "UT3",
    sub_code: "07",
    description: "Hộ nghèo",
    bonus_points: 0.5,
    evidence_doc_type: null,
  },
]

/** Test harness — provides react-hook-form context. */
function TestHarness({
  defaultValues,
  onForm,
  disabled = false,
}: {
  defaultValues?: Partial<AdmissionProfileUpdateInput>
  onForm?: (form: UseFormReturn<AdmissionProfileUpdateInput>) => void
  disabled?: boolean
}) {
  const form = useForm<AdmissionProfileUpdateInput>({
    defaultValues: defaultValues ?? {},
  })
  if (onForm) onForm(form)
  return <UtEvidenceCard form={form} academicYear={2026} disabled={disabled} />
}

beforeEach(() => {
  mockCatalog.mockReset()
})

describe("UtEvidenceCard — loading / empty / error", () => {
  it("shows spinner when isLoading", () => {
    mockCatalog.mockReturnValue({ data: undefined, isLoading: true, error: null })
    render(<TestHarness />)
    expect(screen.getByTestId("ut-loading")).toBeInTheDocument()
  })

  it("shows empty-catalog CTA when catalog empty + not loading", () => {
    mockCatalog.mockReturnValue({ data: [], isLoading: false, error: null })
    render(<TestHarness />)
    expect(screen.getByTestId("ut-empty-catalog")).toBeInTheDocument()
    expect(screen.getByText(/liên hệ phòng tuyển sinh/i)).toBeInTheDocument()
  })

  it("shows error state when hook returns error", () => {
    mockCatalog.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("net"),
    })
    render(<TestHarness />)
    expect(screen.getByTestId("ut-error")).toBeInTheDocument()
  })
})

describe("UtEvidenceCard — catalog rendering", () => {
  it("renders UT rows with code + description + bonus", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 2),
      isLoading: false,
      error: null,
    })
    render(<TestHarness />)
    expect(screen.getByTestId("ut-row-01")).toHaveTextContent(/UT01/)
    expect(screen.getByTestId("ut-row-01")).toHaveTextContent(/Anh hùng LLVTND/)
    expect(screen.getByTestId("ut-row-01")).toHaveTextContent(/\+2,00đ/)
  })

  it("shows 'Xem thêm' button when catalog > INITIAL_VISIBLE", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog,
      isLoading: false,
      error: null,
    })
    render(<TestHarness />)
    expect(screen.getByTestId("ut-expand")).toBeInTheDocument()
    expect(screen.getByTestId("ut-expand")).toHaveTextContent(/Xem thêm 1 đối tượng/)
  })

  it("does NOT show 'Xem thêm' when catalog ≤ INITIAL_VISIBLE", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 3),
      isLoading: false,
      error: null,
    })
    render(<TestHarness />)
    expect(screen.queryByTestId("ut-expand")).not.toBeInTheDocument()
  })

  it("expands hidden rows when clicking 'Xem thêm'", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog,
      isLoading: false,
      error: null,
    })
    render(<TestHarness />)
    expect(screen.queryByTestId("ut-row-07")).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId("ut-expand"))
    expect(screen.getByTestId("ut-row-07")).toBeInTheDocument()
    expect(screen.getByTestId("ut-collapse")).toBeInTheDocument()
  })
})

describe("UtEvidenceCard — selection state binding", () => {
  it("toggle ON adds code to priority_object_codes + initializes evidence pending", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 2),
      isLoading: false,
      error: null,
    })
    let formRef: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    render(
      <TestHarness
        onForm={(f) => {
          formRef = f
        }}
      />,
    )

    const checkbox = screen.getByTestId("ut-checkbox-01")
    fireEvent.click(checkbox)

    expect(formRef!.getValues("priority_object_codes")).toEqual(["01"])
    expect(formRef!.getValues("priority_object_evidence")).toEqual({
      "01": { status: "pending" },
    })
  })

  it("toggle OFF removes code + evidence entry", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 2),
      isLoading: false,
      error: null,
    })
    let formRef: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    render(
      <TestHarness
        defaultValues={{
          priority_object_codes: ["01"],
          priority_object_evidence: { "01": { status: "pending" } },
        }}
        onForm={(f) => {
          formRef = f
        }}
      />,
    )

    fireEvent.click(screen.getByTestId("ut-checkbox-01"))

    expect(formRef!.getValues("priority_object_codes")).toEqual([])
    expect(formRef!.getValues("priority_object_evidence")).toEqual({})
  })

  it("shows verified status badge when evidence.status='verified'", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 2),
      isLoading: false,
      error: null,
    })
    render(
      <TestHarness
        defaultValues={{
          priority_object_codes: ["01"],
          priority_object_evidence: { "01": { status: "verified" } },
        }}
      />,
    )
    expect(screen.getByTestId("ut-status-01")).toHaveTextContent(/Đã duyệt/i)
  })

  it("shows rejected status + reason when evidence.status='rejected'", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 2),
      isLoading: false,
      error: null,
    })
    render(
      <TestHarness
        defaultValues={{
          priority_object_codes: ["01"],
          priority_object_evidence: {
            "01": { status: "rejected", reject_reason: "Minh chứng không hợp lệ" },
          },
        }}
      />,
    )
    expect(screen.getByTestId("ut-status-01")).toHaveTextContent(/Bị từ chối/i)
    expect(screen.getByText(/Minh chứng không hợp lệ/i)).toBeInTheDocument()
  })

  it("shows pending placeholder when selected but no evidence entry", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 2),
      isLoading: false,
      error: null,
    })
    render(
      <TestHarness
        defaultValues={{
          priority_object_codes: ["01"],
          priority_object_evidence: {},
        }}
      />,
    )
    // Component renders amber warning hint when checked but no evidence dict entry
    expect(screen.getByText(/Chưa có minh chứng/i)).toBeInTheDocument()
  })
})

describe("UtEvidenceCard — disabled state", () => {
  it("disables all checkboxes when disabled=true", () => {
    mockCatalog.mockReturnValue({
      data: sampleCatalog.slice(0, 2),
      isLoading: false,
      error: null,
    })
    render(<TestHarness disabled={true} />)
    const checkbox = screen.getByTestId("ut-checkbox-01")
    expect(checkbox).toBeDisabled()
  })
})
