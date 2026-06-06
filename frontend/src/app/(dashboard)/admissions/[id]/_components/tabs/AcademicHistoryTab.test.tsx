/**
 * AcademicHistoryTab — Commit 5 fast-entry anchors.
 *
 * Pin:
 *   - Quick-add "Thêm 3 năm THPT" button tạo 3 record (lớp 10/11/12).
 *   - Free-text school warning render khi nhập school_name không qua picker.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react"
import { useForm, FormProvider } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import * as React from "react"
import type { UseFormReturn } from "react-hook-form"
import { admissionProfileUpdateSchema } from "@/lib/zod/admissions"

// Mock VnSchoolPicker — heavy dependency chain (react-query).
// - the input emits a free-text change (school_id stays null);
// - the button simulates picking a real school from the list (school_id set).
vi.mock("@/components/admissions/VnSchoolPicker", () => ({
  VnSchoolPicker: ({
    value,
    onChange,
  }: {
    value: { school_name: string }
    onChange: (v: {
      school_id: number | null
      school_name: string
      level: string | null
      current_kv?: string | null
    }) => void
  }) => (
    <div>
      <input
        data-testid="mock-vn-school-picker"
        value={value.school_name ?? ""}
        onChange={(e) => onChange({ school_id: null, school_name: e.target.value, level: null })}
      />
      <button
        type="button"
        data-testid="mock-pick-real-school"
        onClick={() =>
          onChange({ school_id: 42, school_name: "THPT Chuyên Nguyễn Du", level: "THPT", current_kv: "KV1" })
        }
      >
        pick
      </button>
    </div>
  ),
}))

import { AcademicHistoryTab } from "./AcademicHistoryTab"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

function Harness({
  defaults,
  isEditable = true,
  exposeForm,
  withResolver = false,
}: {
  defaults?: Partial<AdmissionProfileUpdateInput>
  isEditable?: boolean
  exposeForm?: (form: UseFormReturn<AdmissionProfileUpdateInput>) => void
  withResolver?: boolean
}) {
  const form = useForm<AdmissionProfileUpdateInput>({
    resolver: withResolver ? zodResolver(admissionProfileUpdateSchema) : undefined,
    mode: "onBlur",
    defaultValues: { academic_history: [], ...defaults } as AdmissionProfileUpdateInput,
  })
  React.useEffect(() => {
    exposeForm?.(form)
  }, [form, exposeForm])
  return (
    <FormProvider {...form}>
      <AcademicHistoryTab form={form} isEditable={isEditable} />
    </FormProvider>
  )
}

function renderTab(opts: Parameters<typeof Harness>[0] = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <Harness {...opts} />
    </QueryClientProvider>
  )
}

describe("AcademicHistoryTab — Commit 5 quick-add 3 năm THPT", () => {
  it("Button 'Thêm 3 năm THPT' render khi isEditable=true", () => {
    renderTab({ isEditable: true })
    expect(screen.getByTestId("academic-quick-add-thpt")).toBeInTheDocument()
  })

  it("Button KHÔNG render khi isEditable=false", () => {
    renderTab({ isEditable: false })
    expect(screen.queryByTestId("academic-quick-add-thpt")).not.toBeInTheDocument()
  })

  it("Click button tạo đúng 3 record lớp 10/11/12 + graduation_type=THPT ở lớp 12", () => {
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({
      isEditable: true,
      exposeForm: (f) => {
        capturedForm = f
      },
    })

    fireEvent.click(screen.getByTestId("academic-quick-add-thpt"))

    const history = capturedForm!.getValues("academic_history") ?? []
    expect(history).toHaveLength(3)
    expect(history[0].grade_to).toBe(10)
    expect(history[1].grade_to).toBe(11)
    expect(history[2].grade_to).toBe(12)
    // Lớp 12 = graduation_type THPT, lớp 10/11 null
    expect((history[2] as { graduation_type?: string | null }).graduation_type).toBe("THPT")
    expect((history[0] as { graduation_type?: string | null }).graduation_type).toBeNull()
  })
})

describe("AcademicHistoryTab — Commit 5 free-text school warning", () => {
  it("Render warning khi school_name có giá trị nhưng school_id=null", () => {
    renderTab({
      isEditable: true,
      defaults: {
        academic_history: [
          {
            school_id: null,
            school_name: "THPT Nguyễn Huệ",
            level: null,
            year_from: 2022,
            year_to: 2025,
            grade_to: 12,
            gpa: null,
          },
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.getByTestId("academic-freetext-warning-0")).toBeInTheDocument()
    expect(screen.getByTestId("academic-freetext-warning-0")).toHaveTextContent(
      /không dùng được để tự xác định KV/i
    )
  })

  it("KHÔNG render warning khi school_name empty", () => {
    renderTab({
      isEditable: true,
      defaults: {
        academic_history: [
          {
            school_id: null,
            school_name: "",
            level: null,
            year_from: 2022,
            year_to: 2025,
            grade_to: 12,
            gpa: null,
          },
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.queryByTestId("academic-freetext-warning-0")).not.toBeInTheDocument()
  })
})

describe("AcademicHistoryTab — school_name validation re-runs on pick (regression)", () => {
  it("clears 'Tên trường không được để trống' after a school is set (was: stale error persisted)", async () => {
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({
      isEditable: true,
      withResolver: true,
      exposeForm: (f) => {
        capturedForm = f
      },
      defaults: {
        academic_history: [
          { school_id: null, school_name: "", level: null, year_from: 2022, year_to: 2025, grade_to: 12, gpa: null },
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })

    // Empty school_name → validation marks it required (shown via the free-text FormMessage).
    await act(async () => {
      await capturedForm!.trigger("academic_history.0.school_name")
    })
    expect(screen.getByText("Tên trường không được để trống")).toBeInTheDocument()

    // Pick a real school FROM THE LIST (school_id set) — the reported scenario. The
    // onChange setValue uses shouldValidate, so the stale error must clear.
    fireEvent.click(screen.getByTestId("mock-pick-real-school"))
    expect(capturedForm!.getValues("academic_history.0.school_name")).toBe("THPT Chuyên Nguyễn Du")

    await waitFor(() => {
      expect(screen.queryByText("Tên trường không được để trống")).not.toBeInTheDocument()
    })
  })
})
