/**
 * Q9 #07 Phase E.4 — PriorityInputsSection render tests.
 *
 * Pins § 1 input section contract (officer-friendly UX refactor):
 *   - Cultural + vocational dropdowns render với options
 *   - "Cách xác định khu vực" radio: "Theo trường học" | "Theo nơi thường trú"
 *   - "Theo trường học" maps to area_resolution_basis = null
 *   - "Theo nơi thường trú" maps to area_resolution_basis = "permanent_address_special"
 *     và reveals permanent_commune_code input
 *   - Main flow MUST NOT show "Bật trường hợp đặc biệt", PTDT, MOET, TT 05/2021 copy.
 *   - Disabled state propagates to all controls
 */
import { describe, it, expect } from "vitest"
import { useForm, FormProvider } from "react-hook-form"
import { render, screen, fireEvent } from "@/test/utils/test-utils"
import { useEffect } from "react"

import { PriorityInputsSection } from "./PriorityInputsSection"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

function Wrapper({
  isEditable = true,
  defaultValues = {} as Partial<AdmissionProfileUpdateInput>,
  onAreaBasisChange,
}: {
  isEditable?: boolean
  defaultValues?: Partial<AdmissionProfileUpdateInput>
  onAreaBasisChange?: (v: AdmissionProfileUpdateInput["area_resolution_basis"]) => void
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
  const watched = form.watch("area_resolution_basis")
  // Surface the field value to the test via callback so we can assert
  // the radio→BE mapping without inspecting form internals directly.
  useEffect(() => {
    onAreaBasisChange?.(watched)
  }, [watched, onAreaBasisChange])
  return (
    <FormProvider {...form}>
      <PriorityInputsSection form={form} isEditable={isEditable} />
    </FormProvider>
  )
}

describe("PriorityInputsSection — render", () => {
  it("renders section heading + 2 dropdowns + radio group", () => {
    render(<Wrapper />)
    expect(screen.getByText(/Trình độ.*Khu vực/i)).toBeInTheDocument()
    expect(screen.getByTestId("cultural-education-level-select")).toBeInTheDocument()
    expect(screen.getByTestId("vocational-qualification-select")).toBeInTheDocument()
    expect(screen.getByTestId("area-resolution-basis-radio")).toBeInTheDocument()
    expect(screen.getByTestId("area-basis-by-school")).toBeInTheDocument()
    expect(screen.getByTestId("area-basis-by-permanent-address")).toBeInTheDocument()
  })

  it("defaults to 'Theo trường học' when area_resolution_basis is null", () => {
    render(<Wrapper defaultValues={{ area_resolution_basis: null }} />)
    expect(screen.getByTestId("area-basis-by-school")).toHaveAttribute(
      "aria-checked",
      "true",
    )
    expect(screen.getByTestId("area-basis-by-permanent-address")).toHaveAttribute(
      "aria-checked",
      "false",
    )
  })

  it("hides commune input when basis = 'Theo trường học'", () => {
    render(<Wrapper />)
    expect(screen.queryByTestId("commune-code-field")).not.toBeInTheDocument()
    expect(
      screen.queryByTestId("permanent-commune-code-input"),
    ).not.toBeInTheDocument()
  })

  it("reveals commune input when area_resolution_basis='permanent_address_special'", () => {
    render(
      <Wrapper
        defaultValues={{
          area_resolution_basis: "permanent_address_special",
        }}
      />,
    )
    expect(screen.getByTestId("commune-code-field")).toBeInTheDocument()
    expect(screen.getByTestId("permanent-commune-code-input")).toBeInTheDocument()
    expect(screen.getByTestId("area-basis-by-permanent-address")).toHaveAttribute(
      "aria-checked",
      "true",
    )
  })

  it("commune helper text uses short officer-friendly copy (no MOET / no 'trường hợp đặc biệt')", () => {
    render(
      <Wrapper
        defaultValues={{
          area_resolution_basis: "permanent_address_special",
        }}
      />,
    )
    const field = screen.getByTestId("commune-code-field")
    expect(field).toHaveTextContent(/Nhập mã xã\/phường/)
    expect(field).not.toHaveTextContent(/MOET/i)
    expect(field).not.toHaveTextContent(/893/)
    expect(field).not.toHaveTextContent(/7,453|7\.453/)
    expect(field).not.toHaveTextContent(/trường hợp đặc biệt/i)
  })
})

describe("PriorityInputsSection — radio→BE mapping", () => {
  it("selecting 'Theo nơi thường trú' writes area_resolution_basis = 'permanent_address_special'", () => {
    const observed: Array<unknown> = []
    render(
      <Wrapper
        onAreaBasisChange={(v) => observed.push(v)}
      />,
    )
    fireEvent.click(screen.getByTestId("area-basis-by-permanent-address"))
    expect(observed.at(-1)).toBe("permanent_address_special")
  })

  it("selecting 'Theo trường học' writes area_resolution_basis = null (NOT a sentinel string)", () => {
    const observed: Array<unknown> = []
    render(
      <Wrapper
        defaultValues={{ area_resolution_basis: "permanent_address_special" }}
        onAreaBasisChange={(v) => observed.push(v)}
      />,
    )
    fireEvent.click(screen.getByTestId("area-basis-by-school"))
    expect(observed.at(-1)).toBeNull()
  })
})

describe("PriorityInputsSection — main flow copy guards", () => {
  it("does NOT render 'Bật trường hợp đặc biệt' text anywhere in section", () => {
    render(<Wrapper />)
    const section = screen.getByTestId("priority-inputs-section")
    expect(section).not.toHaveTextContent(/Bật trường hợp đặc biệt/i)
    // Old switch should be gone entirely.
    expect(screen.queryByTestId("special-case-switch")).not.toBeInTheDocument()
  })

  it("does NOT render PTDT / quân nhân / dự bị ĐH / lớp tạo nguồn business copy in main flow", () => {
    render(
      <Wrapper
        defaultValues={{
          area_resolution_basis: "permanent_address_special",
        }}
      />,
    )
    const section = screen.getByTestId("priority-inputs-section")
    expect(section).not.toHaveTextContent(/PTDT/i)
    expect(section).not.toHaveTextContent(/quân nhân/i)
    expect(section).not.toHaveTextContent(/CAND/)
    expect(section).not.toHaveTextContent(/dự bị ĐH/i)
    expect(section).not.toHaveTextContent(/lớp tạo nguồn/i)
  })

  it("does NOT render legal/data references (TT 05/2021, MOET) in main flow", () => {
    render(
      <Wrapper
        defaultValues={{
          area_resolution_basis: "permanent_address_special",
        }}
      />,
    )
    const section = screen.getByTestId("priority-inputs-section")
    expect(section).not.toHaveTextContent(/TT 05\/2021/)
    expect(section).not.toHaveTextContent(/MOET/i)
  })
})

describe("PriorityInputsSection — disabled state", () => {
  it("disables all controls when isEditable=false", () => {
    render(
      <Wrapper
        isEditable={false}
        defaultValues={{
          area_resolution_basis: "permanent_address_special",
        }}
      />,
    )
    const cultural = screen.getByTestId("cultural-education-level-select")
    const vocational = screen.getByTestId("vocational-qualification-select")
    const radioBySchool = screen.getByTestId("area-basis-by-school")
    const radioByPerm = screen.getByTestId("area-basis-by-permanent-address")
    const commune = screen.getByTestId("permanent-commune-code-input")
    expect(cultural).toBeDisabled()
    expect(vocational).toBeDisabled()
    // Radix RadioGroupItem mirrors disabled via data-disabled + the underlying
    // button attribute.
    expect(radioBySchool).toBeDisabled()
    expect(radioByPerm).toBeDisabled()
    expect(commune).toBeDisabled()
  })
})
