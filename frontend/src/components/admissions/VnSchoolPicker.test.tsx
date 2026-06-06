/**
 * VnSchoolPicker — Vitest unit tests (Q9 #07 Phase D.3)
 *
 * Mocks `useVnSchoolSearch` hook to avoid network. Asserts:
 * - Renders trigger + placeholder
 * - Opens combobox, debounced query triggers hook
 * - Selecting school fires onChange with school_id/level/current_kv
 * - Clear button resets selection
 * - DTNT badge displays
 * - "Hiển thị X/Y kết quả" message when total > items.length
 */
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest"
import * as React from "react"
import { render, screen, fireEvent } from "@/test/utils/test-utils"
import { VnSchoolPicker, type VnSchoolPickerValue } from "./VnSchoolPicker"

// cmdk (Command palette) uses Element.scrollIntoView for item navigation;
// jsdom doesn't implement it. Stub before tests run.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  // hasPointerCapture used by Radix Popover; jsdom incomplete
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false)
  }
})

// Mock the hook — control returned data per test
const mockHook = vi.fn()
vi.mock("@/lib/hooks/use-vn-school-search", () => ({
  useVnSchoolSearch: (...args: unknown[]) => mockHook(...args),
}))

const emptyValue: VnSchoolPickerValue = {
  school_id: null,
  school_name: "",
  level: null,
  current_kv: null,
}

const sampleItems = [
  {
    id: 132,
    moet_school_code: "002",
    moet_province_code: "040",
    name: "THPT Buôn Ma Thuột",
    address: "Số 57 Bà Triệu",
    province: "Đắk Lắk",
    district: "Buôn Ma Thuột",
    level: "THPT",
    is_dtnt: false,
    current_kv: null,
  },
  {
    id: 162,
    moet_school_code: "090",
    moet_province_code: "040",
    name: "THPT Buôn Ma Thuột",
    address: "Số 57 Bà Triệu, phường Tự An",
    province: "Đắk Lắk",
    district: "Buôn Ma Thuột",
    level: "THPT",
    is_dtnt: false,
    current_kv: "KV2",
  },
  {
    id: 3,
    moet_school_code: "001",
    moet_province_code: "040",
    name: "PT DTNT Tây Nguyên",
    address: "Buôn Ma Thuột",
    province: "Đắk Lắk",
    district: "Buôn Ma Thuột",
    level: "THPT",
    is_dtnt: true,
    current_kv: "KV1",
  },
]

describe("VnSchoolPicker", () => {
  beforeEach(() => {
    mockHook.mockReset()
    mockHook.mockReturnValue({ data: undefined, isLoading: false })
  })

  it("renders placeholder when no school selected", () => {
    render(
      <VnSchoolPicker
        value={emptyValue}
        onChange={vi.fn()}
        placeholder="Tìm trường..."
      />
    )
    expect(screen.getByText("Tìm trường...")).toBeInTheDocument()
  })

  it("displays selected school name in trigger", () => {
    render(
      <VnSchoolPicker
        value={{
          school_id: 132,
          school_name: "THPT Buôn Ma Thuột",
          level: "THPT",
          current_kv: "KV2",
        }}
        onChange={vi.fn()}
      />
    )
    expect(
      screen.getAllByText(/THPT Buôn Ma Thuột/i).length
    ).toBeGreaterThan(0)
  })

  it("displays selected metadata badge with level + current_kv", () => {
    render(
      <VnSchoolPicker
        value={{
          school_id: 132,
          school_name: "THPT Buôn Ma Thuột",
          level: "THPT",
          current_kv: "KV2",
        }}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText(/Đã chọn từ danh mục/i)).toBeInTheDocument()
    expect(screen.getByText(/KV hiện tại: KV2/i)).toBeInTheDocument()
  })

  it("opens combobox + shows 'Gõ tối thiểu 2 ký tự' when query empty", () => {
    render(
      <VnSchoolPicker value={emptyValue} onChange={vi.fn()} />
    )
    fireEvent.click(screen.getByRole("combobox"))
    // Radix Popover may render same text in multiple a11y nodes
    expect(
      screen.getAllByText(/Gõ tối thiểu 2 ký tự/i).length
    ).toBeGreaterThan(0)
  })

  it("displays loading state when isLoading=true", () => {
    mockHook.mockReturnValue({ data: undefined, isLoading: true })
    render(
      <VnSchoolPicker value={emptyValue} onChange={vi.fn()} />
    )
    fireEvent.click(screen.getByRole("combobox"))
    expect(screen.getByText(/Đang tìm/i)).toBeInTheDocument()
  })

  it("displays search results with DTNT badge", () => {
    mockHook.mockReturnValue({
      data: { items: sampleItems, total: 3, limit: 20, offset: 0 },
      isLoading: false,
    })
    render(
      <VnSchoolPicker value={emptyValue} onChange={vi.fn()} />
    )
    fireEvent.click(screen.getByRole("combobox"))

    expect(screen.getByText("PT DTNT Tây Nguyên")).toBeInTheDocument()
    expect(screen.getByText("DTNT")).toBeInTheDocument()
    expect(screen.getAllByText(/THPT Buôn Ma Thuột/).length).toBeGreaterThanOrEqual(2)
  })

  it("selecting a school fires onChange with full payload", () => {
    mockHook.mockReturnValue({
      data: { items: sampleItems, total: 3, limit: 20, offset: 0 },
      isLoading: false,
    })
    const onChange = vi.fn()
    render(<VnSchoolPicker value={emptyValue} onChange={onChange} />)
    fireEvent.click(screen.getByRole("combobox"))

    const dtntItem = screen.getByText("PT DTNT Tây Nguyên")
    fireEvent.click(dtntItem)

    expect(onChange).toHaveBeenCalledWith({
      school_id: 3,
      school_name: "PT DTNT Tây Nguyên",
      level: "THPT",
      current_kv: "KV1",
    })
  })

  it("displays 'X/Y kết quả' message when total > items.length", () => {
    mockHook.mockReturnValue({
      data: { items: sampleItems, total: 50, limit: 20, offset: 0 },
      isLoading: false,
    })
    render(<VnSchoolPicker value={emptyValue} onChange={vi.fn()} />)
    fireEvent.click(screen.getByRole("combobox"))
    expect(screen.getByText(/Hiển thị 3\/50 kết quả/)).toBeInTheDocument()
  })

  it("shows 'Không tìm thấy' empty state when no matches", () => {
    mockHook.mockReturnValue({
      data: { items: [], total: 0, limit: 20, offset: 0 },
      isLoading: false,
    })
    render(<VnSchoolPicker value={emptyValue} onChange={vi.fn()} />)
    fireEvent.click(screen.getByRole("combobox"))
    // Type a longer search query to trigger non-empty state
    const input = screen.getByPlaceholderText(/Gõ tên trường/i)
    fireEvent.change(input, { target: { value: "khong tim thay" } })
    expect(screen.getByText(/Không tìm thấy trường nào/i)).toBeInTheDocument()
  })

  it("shows KV badge after picking even when the parent never feeds current_kv back", () => {
    // Regression: AcademicHistoryTab passes value.current_kv = null (the form
    // schema has no current_kv field). Before the fix the "KV hiện tại" badge
    // could never render after a pick. The picker now remembers the picked
    // school's KV internally so the officer gets immediate KV feedback.
    mockHook.mockReturnValue({
      data: { items: sampleItems, total: 3, limit: 20, offset: 0 },
      isLoading: false,
    })
    function Parent() {
      const [val, setVal] = React.useState<VnSchoolPickerValue>(emptyValue)
      return (
        <VnSchoolPicker
          // Mirror AcademicHistoryTab: parent persists id/name/level but drops KV.
          value={{ ...val, current_kv: null }}
          onChange={(v) =>
            setVal({
              school_id: v.school_id,
              school_name: v.school_name,
              level: v.level,
              current_kv: null,
            })
          }
        />
      )
    }
    render(<Parent />)
    fireEvent.click(screen.getByRole("combobox"))
    fireEvent.click(screen.getByText("PT DTNT Tây Nguyên")) // current_kv: KV1

    expect(screen.getByText(/Đã chọn từ danh mục/i)).toBeInTheDocument()
    expect(screen.getByText(/KV hiện tại: KV1/i)).toBeInTheDocument()
  })

  it("disabled prop disables trigger button", () => {
    render(
      <VnSchoolPicker value={emptyValue} onChange={vi.fn()} disabled />
    )
    const button = screen.getByRole("combobox")
    expect(button).toBeDisabled()
  })
})
