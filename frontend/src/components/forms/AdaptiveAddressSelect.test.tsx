import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { AddressMode } from "@/lib/api/administrative"

const mockUseProvinces = vi.fn()
const mockUseDistricts = vi.fn()
const mockUseWards = vi.fn()

vi.mock("@/lib/hooks/useAdministrative", () => ({
  useProvinces: (...args: unknown[]) => mockUseProvinces(...args),
  useDistricts: (...args: unknown[]) => mockUseDistricts(...args),
  useWards: (...args: unknown[]) => mockUseWards(...args),
}))

vi.mock("@/components/ui/combobox", () => ({
  Combobox: ({
    value,
    onChange,
    options = [],
    placeholder = "combobox",
    disabled = false,
  }: {
    value: string
    onChange: (value: string) => void
    options?: Array<{ value: string; label: string }>
    placeholder?: string
    disabled?: boolean
  }) => (
    <label>
      <span>{placeholder}</span>
      <select
        aria-label={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={`${option.value}-${option.label}`} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  ),
}))

vi.mock("@/components/ui/label", () => ({
  Label: ({ children, className }: { children: ReactNode; className?: string }) => (
    <label className={className}>{children}</label>
  ),
}))

// --- Test data ---

const currentProvinces = [
  { code: "15", name: "Lao Cai" },
  { code: "66", name: "Dak Lak" },
]

const legacyProvinces = [
  { code: "10", name: "Lao Cai" },
  { code: "15", name: "Yen Bai" },
  { code: "54", name: "Phu Yen" },
  { code: "66", name: "Dak Lak" },
]

const legacyDistricts = [
  { code: "10_001", name: "Bat Xat", province_code: "10" },
]

// --- Helpers ---

interface Props {
  provinceValue?: string
  districtValue?: string | null
  wardValue?: string
  mode?: AddressMode
  onProvinceChange?: (v: string) => void
  onDistrictChange?: (v: string | null) => void
  onWardChange?: (v: string) => void
  onModeChange?: (m: AddressMode) => void
}

async function renderComponent(overrides: Props = {}) {
  const { AdaptiveAddressSelect } = await import("./AdaptiveAddressSelect")
  const props = {
    provinceValue: "",
    districtValue: null,
    wardValue: "",
    mode: "current" as AddressMode,
    onProvinceChange: vi.fn(),
    onDistrictChange: vi.fn(),
    onWardChange: vi.fn(),
    onModeChange: vi.fn(),
    ...overrides,
  }
  const result = render(<AdaptiveAddressSelect {...props} />)
  return { ...result, props }
}

// --- Tests ---

describe("AdaptiveAddressSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks()

    mockUseProvinces.mockImplementation((mode: AddressMode) => ({
      data: mode === "current" ? currentProvinces : legacyProvinces,
      isLoading: false,
    }))

    mockUseDistricts.mockImplementation((code?: string, enabled?: boolean) => ({
      data: enabled && code === "10" ? legacyDistricts : [],
      isLoading: false,
    }))

    mockUseWards.mockReturnValue({ data: [], isLoading: false })
  })

  // -----------------------------------------------------------------
  // MODE: CURRENT
  // -----------------------------------------------------------------

  it("current mode: shows only current provinces", async () => {
    await renderComponent({ mode: "current" })

    // useProvinces called with "current"
    expect(mockUseProvinces).toHaveBeenCalledWith("current")

    // Province options: 34-tỉnh placeholder
    const provinceSelect = screen.getByLabelText(/Tỉnh.*34 tỉnh/)
    expect(provinceSelect).toBeTruthy()
  })

  it("current mode: does NOT fetch districts", async () => {
    await renderComponent({ mode: "current", provinceValue: "Dak Lak" })

    // useDistricts called with enabled=false (isLegacy is false)
    expect(mockUseDistricts).toHaveBeenCalledWith("66", false)
  })

  it("current mode: district combobox is not rendered", async () => {
    await renderComponent({ mode: "current" })

    expect(screen.queryByLabelText("Quận/Huyện")).toBeNull()
  })

  it("current mode: fetches wards with mode=current", async () => {
    await renderComponent({ mode: "current", provinceValue: "Dak Lak" })

    expect(mockUseWards).toHaveBeenCalledWith("66", "current", undefined)
  })

  // -----------------------------------------------------------------
  // MODE: LEGACY
  // -----------------------------------------------------------------

  it("legacy mode: shows all 63 legacy provinces", async () => {
    await renderComponent({ mode: "legacy" })

    expect(mockUseProvinces).toHaveBeenCalledWith("legacy")

    const provinceSelect = screen.getByLabelText(/Tỉnh.*63 tỉnh/)
    expect(provinceSelect).toBeTruthy()
  })

  it("legacy mode: fetches districts for selected province", async () => {
    await renderComponent({ mode: "legacy", provinceValue: "Lao Cai" })

    // Matches code "10" (first match in legacyProvinces)
    expect(mockUseDistricts).toHaveBeenCalledWith("10", true)
  })

  it("legacy mode: district combobox IS rendered", async () => {
    await renderComponent({ mode: "legacy" })

    expect(screen.getByLabelText("Quận/Huyện")).toBeTruthy()
  })

  it("legacy mode: wards fetch requires district", async () => {
    await renderComponent({
      mode: "legacy",
      provinceValue: "Lao Cai",
      districtValue: "Bat Xat",
    })

    expect(mockUseWards).toHaveBeenCalledWith("10", "legacy", "10_001")
  })

  // -----------------------------------------------------------------
  // MODE SWITCHING
  // -----------------------------------------------------------------

  it("switching mode resets province, district, and ward", async () => {
    const { props } = await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
    })

    // Click legacy radio
    const legacyRadio = screen.getByLabelText(/Hộ khẩu cũ/)
    fireEvent.click(legacyRadio)

    await waitFor(() => {
      expect(props.onModeChange).toHaveBeenCalledWith("legacy")
      expect(props.onProvinceChange).toHaveBeenCalledWith("")
      expect(props.onDistrictChange).toHaveBeenCalledWith(null)
      expect(props.onWardChange).toHaveBeenCalledWith("")
    })
  })

  it("switching to current hides district field", async () => {
    // Start in legacy
    const { rerender } = await renderComponent({ mode: "legacy" })
    expect(screen.getByLabelText("Quận/Huyện")).toBeTruthy()

    // Re-render as current
    const { AdaptiveAddressSelect } = await import("./AdaptiveAddressSelect")
    rerender(
      <AdaptiveAddressSelect
        provinceValue=""
        districtValue={null}
        wardValue=""
        mode="current"
        onModeChange={vi.fn()}
        onProvinceChange={vi.fn()}
        onDistrictChange={vi.fn()}
        onWardChange={vi.fn()}
      />,
    )

    expect(screen.queryByLabelText("Quận/Huyện")).toBeNull()
  })

  // -----------------------------------------------------------------
  // PROVINCE SELECTION
  // -----------------------------------------------------------------

  it("selecting a province clears district and ward", async () => {
    const { props } = await renderComponent({ mode: "current" })

    fireEvent.change(screen.getByLabelText(/Tỉnh/), {
      target: { value: "Dak Lak" },
    })

    await waitFor(() => {
      expect(props.onProvinceChange).toHaveBeenCalledWith("Dak Lak")
      expect(props.onDistrictChange).toHaveBeenCalledWith(null)
      expect(props.onWardChange).toHaveBeenCalledWith("")
    })
  })
})
