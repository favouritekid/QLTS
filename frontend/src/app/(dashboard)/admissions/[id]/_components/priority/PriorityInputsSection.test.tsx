/**
 * Q9 #07 Phase E.4 — PriorityInputsSection render tests.
 *
 * Pins § 1 input section contract:
 *   - Cultural + vocational dropdowns render với options
 *   - Special-case switch — when on, reveals permanent_commune_code input
 *   - When off, commune input HIDDEN
 *   - Disabled state propagates to all controls
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

describe("PriorityInputsSection — render", () => {
  it("renders section heading + 2 dropdowns + switch", () => {
    render(<Wrapper />)
    expect(screen.getByText(/§ 1\./i)).toBeInTheDocument()
    expect(screen.getByTestId("cultural-education-level-select")).toBeInTheDocument()
    expect(screen.getByTestId("vocational-qualification-select")).toBeInTheDocument()
    expect(screen.getByTestId("special-case-switch")).toBeInTheDocument()
  })

  it("hides commune input by default (switch off)", () => {
    render(<Wrapper />)
    expect(screen.queryByTestId("commune-code-field")).not.toBeInTheDocument()
    expect(screen.queryByTestId("permanent-commune-code-input")).not.toBeInTheDocument()
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
    const sw = screen.getByTestId("special-case-switch")
    const commune = screen.getByTestId("permanent-commune-code-input")
    expect(cultural).toBeDisabled()
    expect(vocational).toBeDisabled()
    expect(sw).toBeDisabled()
    expect(commune).toBeDisabled()
  })
})
