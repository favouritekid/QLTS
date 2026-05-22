/**
 * AcademicHistoryTab — Commit 5 fast-entry anchors.
 *
 * Pin:
 *   - Quick-add "Thêm 3 năm THPT" button tạo 3 record (lớp 10/11/12).
 *   - Free-text school warning render khi nhập school_name không qua picker.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { useForm, FormProvider } from "react-hook-form"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import * as React from "react"
import type { UseFormReturn } from "react-hook-form"

// Mock VnSchoolPicker — heavy dependency chain (react-query).
vi.mock("@/components/admissions/VnSchoolPicker", () => ({
  VnSchoolPicker: ({ value, onChange }: { value: { school_name: string }; onChange: (v: { school_id: null; school_name: string; level: null }) => void }) => (
    <input
      data-testid="mock-vn-school-picker"
      value={value.school_name ?? ""}
      onChange={(e) => onChange({ school_id: null, school_name: e.target.value, level: null })}
    />
  ),
}))

import { AcademicHistoryTab } from "./AcademicHistoryTab"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

function Harness({
  defaults,
  isEditable = true,
  exposeForm,
}: {
  defaults?: Partial<AdmissionProfileUpdateInput>
  isEditable?: boolean
  exposeForm?: (form: UseFormReturn<AdmissionProfileUpdateInput>) => void
}) {
  const form = useForm<AdmissionProfileUpdateInput>({
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
