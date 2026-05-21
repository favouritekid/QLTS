/**
 * Q9 #07 Phase E.4 — PriorityInputsSection render tests.
 *
 * v2 (2026-05-21) — officer KHÔNG chọn basis (auto resolve ở BE engine).
 * Section chỉ render 2 dropdown trình độ + hint dòng derived basis.
 *
 * Pins:
 *   - Cultural + vocational dropdowns render với options
 *   - NO radio "Theo trường học / Theo nơi thường trú"
 *   - NO commune_code input ở §1 (source-of-truth: tab Thông tin)
 *   - Hint dòng đề cập "Hệ thống tự xác định"
 *   - Main flow MUST NOT show "Bật trường hợp đặc biệt", PTDT, MOET copy.
 *   - Disabled state propagates to all selects
 */
import { describe, it, expect } from "vitest"
import { useForm, FormProvider } from "react-hook-form"
import { render, screen } from "@/test/utils/test-utils"

import { PriorityInputsSection } from "./PriorityInputsSection"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

function Wrapper({
  isEditable = true,
  defaultValues = {} as Partial<AdmissionProfileUpdateInput>,
}: {
  isEditable?: boolean
  defaultValues?: Partial<AdmissionProfileUpdateInput>
}) {
  const form = useForm<AdmissionProfileUpdateInput>({
    defaultValues: {
      cultural_education_level: null,
      vocational_qualification: null,
      area_resolution_basis: null,
      permanent_commune_code: null,
      version: 1,
      ...defaultValues,
    },
  })
  return (
    <FormProvider {...form}>
      <PriorityInputsSection form={form} isEditable={isEditable} />
    </FormProvider>
  )
}

describe("PriorityInputsSection — render (v2 auto basis)", () => {
  it("renders heading 'Trình độ' + 2 dropdowns", () => {
    render(<Wrapper />)
    expect(screen.getByText(/^Trình độ$/i)).toBeInTheDocument()
    expect(screen.getByTestId("cultural-education-level-select")).toBeInTheDocument()
    expect(screen.getByTestId("vocational-qualification-select")).toBeInTheDocument()
  })

  it("renders 'auto basis' hint informing officer engine resolves", () => {
    render(<Wrapper />)
    const hint = screen.getByTestId("auto-basis-hint")
    expect(hint).toBeInTheDocument()
    expect(hint).toHaveTextContent(/tự xác định/i)
    expect(hint).toHaveTextContent(/khu vực ưu tiên/i)
  })

  it("does NOT render basis radio (v1 removed — auto-resolve ở BE engine)", () => {
    render(<Wrapper />)
    expect(screen.queryByTestId("area-resolution-basis-radio")).not.toBeInTheDocument()
    expect(screen.queryByTestId("area-basis-by-school")).not.toBeInTheDocument()
    expect(screen.queryByTestId("area-basis-by-permanent-address")).not.toBeInTheDocument()
  })

  it("does NOT render permanent_commune_code input ở §1 (source-of-truth ở tab Thông tin)", () => {
    render(<Wrapper />)
    expect(screen.queryByTestId("commune-code-field")).not.toBeInTheDocument()
    expect(screen.queryByTestId("permanent-commune-code-input")).not.toBeInTheDocument()
  })

  it("commune input NOT shown even when area_resolution_basis = 'permanent_address_special' (legacy field)", () => {
    render(
      <Wrapper
        defaultValues={{ area_resolution_basis: "permanent_address_special" }}
      />,
    )
    expect(screen.queryByTestId("commune-code-field")).not.toBeInTheDocument()
  })
})

describe("PriorityInputsSection — main flow copy guards", () => {
  it("does NOT render legacy basis copy ('Theo trường học' / 'Theo nơi thường trú')", () => {
    render(<Wrapper />)
    const section = screen.getByTestId("priority-inputs-section")
    expect(section).not.toHaveTextContent(/Theo trường học/i)
    expect(section).not.toHaveTextContent(/Theo nơi thường trú/i)
  })

  it("does NOT render 'Bật trường hợp đặc biệt' / PTDT / quân nhân copy", () => {
    render(<Wrapper />)
    const section = screen.getByTestId("priority-inputs-section")
    expect(section).not.toHaveTextContent(/Bật trường hợp đặc biệt/i)
    expect(section).not.toHaveTextContent(/PTDT/i)
    expect(section).not.toHaveTextContent(/quân nhân/i)
    expect(section).not.toHaveTextContent(/CAND/)
    expect(section).not.toHaveTextContent(/dự bị ĐH/i)
    expect(section).not.toHaveTextContent(/lớp tạo nguồn/i)
  })

  it("does NOT render legal/data references (TT 05/2021, MOET) in main flow", () => {
    render(<Wrapper />)
    const section = screen.getByTestId("priority-inputs-section")
    expect(section).not.toHaveTextContent(/TT 05\/2021/)
    expect(section).not.toHaveTextContent(/MOET/i)
  })
})

describe("PriorityInputsSection — disabled state", () => {
  it("disables 2 trình độ selects when isEditable=false", () => {
    render(<Wrapper isEditable={false} />)
    expect(screen.getByTestId("cultural-education-level-select")).toBeDisabled()
    expect(screen.getByTestId("vocational-qualification-select")).toBeDisabled()
  })
})
