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
  wardCodeValue?: string | null
  mode?: AddressMode
  onProvinceChange?: (v: string) => void
  onDistrictChange?: (v: string | null) => void
  onWardChange?: (v: string) => void
  onWardCodeChange?: (code: string | null) => void
  onModeChange?: (m: AddressMode) => void
}

async function renderComponent(overrides: Props = {}) {
  const { AdaptiveAddressSelect } = await import("./AdaptiveAddressSelect")
  const props = {
    provinceValue: "",
    districtValue: null,
    wardValue: "",
    wardCodeValue: null as string | null,
    mode: "current" as AddressMode,
    onProvinceChange: vi.fn(),
    onDistrictChange: vi.fn(),
    onWardChange: vi.fn(),
    onWardCodeChange: vi.fn(),
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

  it("switching mode with existing data asks before resetting address", async () => {
    const { props } = await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
      wardValue: "Xa Ea Kao",
      wardCodeValue: "66_002",
    })

    const legacyRadio = screen.getByLabelText(/Hộ khẩu cũ/)
    fireEvent.click(legacyRadio)

    expect(screen.getByText("Đổi chế độ địa chỉ?")).toBeInTheDocument()
    expect(props.onModeChange).not.toHaveBeenCalled()
    expect(props.onProvinceChange).not.toHaveBeenCalled()
    expect(props.onWardChange).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole("button", { name: "Đổi và xóa địa chỉ" }))

    await waitFor(() => {
      expect(props.onModeChange).toHaveBeenCalledWith("legacy")
      expect(props.onProvinceChange).toHaveBeenCalledWith("")
      expect(props.onDistrictChange).toHaveBeenCalledWith(null)
      expect(props.onWardChange).toHaveBeenCalledWith("")
      expect(props.onWardCodeChange).toHaveBeenCalledWith(null)
    })
  })

  it("cancelling mode switch preserves the current address", async () => {
    const { props } = await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
      wardValue: "Xa Ea Kao",
      wardCodeValue: "66_002",
    })

    fireEvent.click(screen.getByLabelText(/Hộ khẩu cũ/))
    fireEvent.click(screen.getByRole("button", { name: "Giữ địa chỉ hiện tại" }))

    await waitFor(() => {
      expect(screen.queryByText("Đổi chế độ địa chỉ?")).not.toBeInTheDocument()
    })
    expect(props.onModeChange).not.toHaveBeenCalled()
    expect(props.onProvinceChange).not.toHaveBeenCalled()
    expect(props.onDistrictChange).not.toHaveBeenCalled()
    expect(props.onWardChange).not.toHaveBeenCalled()
    expect(props.onWardCodeChange).not.toHaveBeenCalled()
  })

  it("switching mode without address data applies immediately", async () => {
    const { props } = await renderComponent({ mode: "current" })

    fireEvent.click(screen.getByLabelText(/Hộ khẩu cũ/))

    await waitFor(() => {
      expect(props.onModeChange).toHaveBeenCalledWith("legacy")
      expect(props.onProvinceChange).toHaveBeenCalledWith("")
      expect(props.onWardChange).toHaveBeenCalledWith("")
    })
    expect(screen.queryByText("Đổi chế độ địa chỉ?")).not.toBeInTheDocument()
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

  // -----------------------------------------------------------------
  // Phase E.4 KV BRIDGE — ward code expose
  // -----------------------------------------------------------------

  it("ward combobox dùng ward.code làm option value (canonical key)", async () => {
    mockUseWards.mockReturnValue({
      data: [
        { code: "66_001", name: "Phường Tân An", province_code: "66", district_code: null },
        { code: "66_002", name: "Xã Ea Kao", province_code: "66", district_code: null },
      ],
      isLoading: false,
    })

    await renderComponent({ mode: "current", provinceValue: "Dak Lak" })

    const wardSelect = screen.getByLabelText("Phường/Xã") as HTMLSelectElement
    const optionValues = Array.from(wardSelect.options).map((o) => o.value)
    expect(optionValues).toContain("66_001")
    expect(optionValues).toContain("66_002")
    // Không còn dùng ward.name làm value
    expect(optionValues).not.toContain("Phường Tân An")
    expect(optionValues).not.toContain("Xã Ea Kao")
  })

  it("selecting ward (by code) fires onWardChange(name) + onWardCodeChange(code)", async () => {
    mockUseWards.mockReturnValue({
      data: [
        { code: "66_001", name: "Phường Tân An", province_code: "66", district_code: null },
        { code: "66_002", name: "Xã Ea Kao", province_code: "66", district_code: null },
      ],
      isLoading: false,
    })

    const { props } = await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
    })

    // Combobox value đổi sang ward.code (canonical primary key)
    fireEvent.change(screen.getByLabelText("Phường/Xã"), {
      target: { value: "66_002" },
    })

    await waitFor(() => {
      expect(props.onWardChange).toHaveBeenCalledWith("Xã Ea Kao")
      expect(props.onWardCodeChange).toHaveBeenCalledWith("66_002")
    })
  })

  it("ward selection cleared (empty string) emits empty name + null commune code", async () => {
    mockUseWards.mockReturnValue({
      data: [{ code: "66_001", name: "Phường Tân An", province_code: "66", district_code: null }],
      isLoading: false,
    })

    const { props } = await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
      wardValue: "Phường Tân An",
      wardCodeValue: "66_001",
    })

    fireEvent.change(screen.getByLabelText("Phường/Xã"), { target: { value: "" } })

    await waitFor(() => {
      expect(props.onWardChange).toHaveBeenCalledWith("")
      expect(props.onWardCodeChange).toHaveBeenCalledWith(null)
    })
  })

  it("wardCodeValue prop sets combobox internal selection (hydration)", async () => {
    mockUseWards.mockReturnValue({
      data: [
        { code: "66_001", name: "Phường Tân An", province_code: "66", district_code: null },
        { code: "66_002", name: "Xã Ea Kao", province_code: "66", district_code: null },
      ],
      isLoading: false,
    })

    await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
      wardCodeValue: "66_002",
    })

    expect((screen.getByLabelText("Phường/Xã") as HTMLSelectElement).value).toBe(
      "66_002",
    )
  })

  it("fallback hydration từ wardValue (name) khi wardCodeValue chưa có (legacy profile)", async () => {
    mockUseWards.mockReturnValue({
      data: [
        { code: "66_001", name: "Phường Tân An", province_code: "66", district_code: null },
      ],
      isLoading: false,
    })

    await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
      wardValue: "Phường Tân An",
      // wardCodeValue undefined — legacy profile chỉ có name
    })

    // Component lookup ngược name → code để select đúng option
    expect((screen.getByLabelText("Phường/Xã") as HTMLSelectElement).value).toBe(
      "66_001",
    )
  })

  it("legacy mode: hiển thị xã theo TÊN — KHÔNG nhảy khi commune_code đã canonicalize trùng mã legacy khác", async () => {
    // Regression (bug "Xã Nam Bình → Thị trấn Đức An"): mã GSO 24717 bị tái dùng
    // 2 thời kỳ — legacy = "Thị trấn Đức An", đồng thời là successor của legacy
    // "Xã Nam Bình" (24721). Sau khi BE canonicalize lúc lưu, wardCodeValue=24717.
    // Combobox legacy PHẢI khớp theo name → "Xã Nam Bình" (24721), KHÔNG được khớp
    // theo code → "Thị trấn Đức An" (24717).
    mockUseWards.mockReturnValue({
      data: [
        { code: "24717", name: "Thị trấn Đức An", province_code: "10", district_code: "10_001" },
        { code: "24721", name: "Xã Nam Bình", province_code: "10", district_code: "10_001" },
      ],
      isLoading: false,
    })

    await renderComponent({
      mode: "legacy",
      provinceValue: "Lao Cai",
      districtValue: "Bat Xat",
      wardValue: "Xã Nam Bình",
      wardCodeValue: "24717", // mã hiện hành đã canonicalize (trùng mã legacy của xã khác)
    })

    const wardSelect = screen.getByLabelText("Phường/Xã") as HTMLSelectElement
    // Khớp theo name → 24721 (Xã Nam Bình), KHÔNG phải 24717 (Thị trấn Đức An)
    expect(wardSelect.value).toBe("24721")
  })

  it("province change clears commune code along with ward/district", async () => {
    const { props } = await renderComponent({ mode: "current" })

    fireEvent.change(screen.getByLabelText(/Tỉnh/), {
      target: { value: "Dak Lak" },
    })

    await waitFor(() => {
      expect(props.onWardCodeChange).toHaveBeenCalledWith(null)
    })
  })

  it("mode switch clears commune code", async () => {
    const { props } = await renderComponent({
      mode: "current",
      provinceValue: "Dak Lak",
    })

    fireEvent.click(screen.getByLabelText(/Hộ khẩu cũ/))
    fireEvent.click(screen.getByRole("button", { name: "Đổi và xóa địa chỉ" }))

    await waitFor(() => {
      expect(props.onWardCodeChange).toHaveBeenCalledWith(null)
    })
  })

  it("district change (legacy mode) clears commune code", async () => {
    const { props } = await renderComponent({
      mode: "legacy",
      provinceValue: "Lao Cai",
    })

    fireEvent.change(screen.getByLabelText("Quận/Huyện"), {
      target: { value: "Bat Xat" },
    })

    await waitFor(() => {
      expect(props.onWardCodeChange).toHaveBeenCalledWith(null)
    })
  })
})
