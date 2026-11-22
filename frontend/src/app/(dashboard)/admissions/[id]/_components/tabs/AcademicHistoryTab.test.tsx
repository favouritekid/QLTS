/**
 * AcademicHistoryTab — Commit 5 fast-entry anchors.
 *
 * Pin:
 *   - Thêm nhanh THPT / THCS từ NĂM BẮT ĐẦU lớp đầu cấp (owner 22-11): mỗi lớp
 *     một dòng Y→Y+1, xem trước "Tốt nghiệp năm …", không tự lấy năm nay.
 *   - Nhắc nhẹ: dòng 0 năm học, hai dòng trùng năm học, hở năm học.
 *   - Free-text school warning render khi nhập school_name không qua picker.
 */

import { afterEach, describe, it, expect, vi } from "vitest"
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
import type { AdmissionProfileUpdateInput, AcademicRecord } from "@/lib/zod/admissions"

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

// CẶP FE ↔ backend (owner 22-11 mục C): gõ 2022 ⇒ nút sinh đúng 3 dòng; sau khi chọn
// trường từ danh mục (mock: school_id 42, level THPT) ra ĐÚNG dữ liệu dưới đây.
// Backend chép NGUYÊN dữ liệu này ở `Backend_FastAPI/tests/unit/test_priority_kv_lien_cap_g5.py`
// (`CAP_FE_NUT_THEM_NHANH_2022`) và khoá phía tính tra đúng năm học 2022, 2023, 2024.
// ĐỔI một bên thì đổi cả hai.
const CAP_FE_NUT_THEM_NHANH_2022 = [
  { school_id: 42, school_name: "THPT Chuyên Nguyễn Du", level: "THPT", year_from: 2022, year_to: 2023, grade_to: 10, gpa: null, graduation_type: "THPT" },
  { school_id: 42, school_name: "THPT Chuyên Nguyễn Du", level: "THPT", year_from: 2023, year_to: 2024, grade_to: 11, gpa: null, graduation_type: "THPT" },
  { school_id: 42, school_name: "THPT Chuyên Nguyễn Du", level: "THPT", year_from: 2024, year_to: 2025, grade_to: 12, gpa: null, graduation_type: "THPT" },
]

function typeYear(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } })
}

describe("AcademicHistoryTab — thêm nhanh 3 năm THPT từ năm bắt đầu lớp 10 (owner 22-11)", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it("nút và ô năm hiện khi isEditable=true", () => {
    renderTab({ isEditable: true })
    expect(screen.getByTestId("academic-quick-add-thpt")).toBeInTheDocument()
    expect(screen.getByLabelText("Năm bắt đầu lớp 10")).toBeInTheDocument()
  })

  it("nút KHÔNG hiện khi isEditable=false", () => {
    renderTab({ isEditable: false })
    expect(screen.queryByTestId("academic-quick-add-thpt")).not.toBeInTheDocument()
  })

  it("KHÔNG tự lấy năm nay: chưa gõ năm thì nút khoá, gõ 2022 thì sinh 2022–2025 dù đồng hồ ở năm khác", () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date("2031-03-01T00:00:00Z"))
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({ isEditable: true, exposeForm: (f) => { capturedForm = f } })

    expect(screen.getByTestId("academic-quick-add-thpt")).toBeDisabled()
    fireEvent.click(screen.getByTestId("academic-quick-add-thpt"))
    expect(capturedForm!.getValues("academic_history")).toHaveLength(0)

    typeYear("academic-quick-add-thpt-start", "2022")
    fireEvent.click(screen.getByTestId("academic-quick-add-thpt"))
    expect((capturedForm!.getValues("academic_history") ?? []).map((h) => [h.year_from, h.year_to])).toEqual([
      [2022, 2023],
      [2023, 2024],
      [2024, 2025],
    ])
  })

  it("gõ 2022 ⇒ xem trước từng năm học + 'Tốt nghiệp năm 2025'; bấm ⇒ đúng 3 dòng Y→Y+1 lớp 10/11/12, ô năm được xoá", () => {
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({ isEditable: true, exposeForm: (f) => { capturedForm = f } })

    typeYear("academic-quick-add-thpt-start", "2022")
    expect(screen.getByTestId("academic-quick-add-thpt-preview")).toHaveTextContent(
      "Lớp 10: 2022–2023, lớp 11: 2023–2024, lớp 12: 2024–2025. Tốt nghiệp năm 2025.",
    )
    fireEvent.click(screen.getByTestId("academic-quick-add-thpt"))

    expect(capturedForm!.getValues("academic_history")).toEqual([
      { school_id: null, school_name: "", level: null, year_from: 2022, year_to: 2023, grade_to: 10, gpa: null, graduation_type: "THPT" },
      { school_id: null, school_name: "", level: null, year_from: 2023, year_to: 2024, grade_to: 11, gpa: null, graduation_type: "THPT" },
      { school_id: null, school_name: "", level: null, year_from: 2024, year_to: 2025, grade_to: 12, gpa: null, graduation_type: "THPT" },
    ])
    expect(screen.getByTestId("academic-quick-add-thpt-start")).toHaveValue(null)
    expect(screen.queryByTestId("academic-quick-add-thpt-preview")).not.toBeInTheDocument()
    // Dòng liền mạch: không nhắc 0 năm / trùng / hở.
    expect(screen.queryByTestId("academic-notices")).not.toBeInTheDocument()
  })

  it("CẶP với backend: gõ 2022, chọn trường từ danh mục cho cả 3 dòng ⇒ đúng dữ liệu CAP_FE_NUT_THEM_NHANH_2022", () => {
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({ isEditable: true, exposeForm: (f) => { capturedForm = f } })

    typeYear("academic-quick-add-thpt-start", "2022")
    fireEvent.click(screen.getByTestId("academic-quick-add-thpt"))
    screen.getAllByTestId("mock-pick-real-school").forEach((b) => fireEvent.click(b))

    expect(capturedForm!.getValues("academic_history")).toEqual(CAP_FE_NUT_THEM_NHANH_2022)
  })

  it("năm sai ⇒ báo 'Năm không hợp lệ', nút khoá", () => {
    renderTab({ isEditable: true })
    typeYear("academic-quick-add-thpt-start", "22")
    expect(screen.getByTestId("academic-quick-add-thpt-invalid")).toHaveTextContent("Năm không hợp lệ")
    expect(screen.getByTestId("academic-quick-add-thpt")).toBeDisabled()
    typeYear("academic-quick-add-thpt-start", "2098") // lớp 12 sẽ tới 2101 > 2100
    expect(screen.getByTestId("academic-quick-add-thpt")).toBeDisabled()
  })

  it("dòng sinh ra vẫn sửa được (lưu ban lớp 10: 2022→2024) và khi ấy nhắc trùng năm học", () => {
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({ isEditable: true, exposeForm: (f) => { capturedForm = f } })

    typeYear("academic-quick-add-thpt-start", "2022")
    fireEvent.click(screen.getByTestId("academic-quick-add-thpt"))
    fireEvent.change(screen.getAllByLabelText("Đến năm")[0], { target: { value: "2024" } })

    expect(capturedForm!.getValues("academic_history.0.year_to")).toBe(2024)
    expect(screen.getByText(/Trường #1 và #2 cùng có năm học 2023–2024/)).toBeInTheDocument()
  })
})

describe("AcademicHistoryTab — thêm nhanh 4 năm THCS từ năm bắt đầu lớp 6", () => {
  it("nút hiện khi isEditable=true", () => {
    renderTab({ isEditable: true })
    expect(screen.getByTestId("academic-quick-add-thcs")).toBeInTheDocument()
  })

  it("nút KHÔNG hiện khi isEditable=false", () => {
    renderTab({ isEditable: false })
    expect(screen.queryByTestId("academic-quick-add-thcs")).not.toBeInTheDocument()
  })

  it("chưa có THPT ⇒ không gợi ý; gõ 2018 ⇒ 4 dòng 2018→2019 … 2021→2022 lớp 6–9, 'Tốt nghiệp THCS năm 2022'", () => {
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({ isEditable: true, exposeForm: (f) => { capturedForm = f } })

    expect(screen.queryByTestId("academic-quick-add-thcs-suggest")).not.toBeInTheDocument()
    expect(screen.getByTestId("academic-quick-add-thcs")).toBeDisabled()
    typeYear("academic-quick-add-thcs-start", "2018")
    expect(screen.getByTestId("academic-quick-add-thcs-preview")).toHaveTextContent(
      "Lớp 6: 2018–2019, lớp 7: 2019–2020, lớp 8: 2020–2021, lớp 9: 2021–2022. Tốt nghiệp THCS năm 2022.",
    )
    fireEvent.click(screen.getByTestId("academic-quick-add-thcs"))

    const history = capturedForm!.getValues("academic_history") ?? []
    expect(history.map((h) => [h.grade_to, h.year_from, h.year_to])).toEqual([
      [6, 2018, 2019],
      [7, 2019, 2020],
      [8, 2020, 2021],
      [9, 2021, 2022],
    ])
    expect((history as Array<{ graduation_type?: string | null }>).map((h) => h.graduation_type)).toEqual([
      "THCS",
      "THCS",
      "THCS",
      "THCS",
    ])
  })

  it("đã có THPT bắt đầu 2022 ⇒ gợi ý lớp 6 = 2018 (lớp 10 − 4); dùng gợi ý ⇒ nối liền lớp 9 → lớp 10, không nhắc hở", () => {
    let capturedForm: UseFormReturn<AdmissionProfileUpdateInput> | null = null
    renderTab({ isEditable: true, exposeForm: (f) => { capturedForm = f } })

    typeYear("academic-quick-add-thpt-start", "2022")
    fireEvent.click(screen.getByTestId("academic-quick-add-thpt"))
    expect(screen.getByTestId("academic-quick-add-thcs-suggest")).toHaveTextContent("Gợi ý: 2018 (lớp 10 − 4)")
    fireEvent.click(screen.getByTestId("academic-quick-add-thcs-suggest"))
    expect(screen.getByTestId("academic-quick-add-thcs-start")).toHaveValue(2018)
    fireEvent.click(screen.getByTestId("academic-quick-add-thcs"))

    const history = capturedForm!.getValues("academic_history") ?? []
    expect(history.map((h) => [h.grade_to, h.year_from, h.year_to])).toEqual([
      [10, 2022, 2023],
      [11, 2023, 2024],
      [12, 2024, 2025],
      [6, 2018, 2019],
      [7, 2019, 2020],
      [8, 2020, 2021],
      [9, 2021, 2022],
    ])
    expect(screen.queryByText(/Hở năm học/)).not.toBeInTheDocument()
    expect(screen.queryByText(/cùng có năm học/)).not.toBeInTheDocument()
  })
})

describe("AcademicHistoryTab — soft data-quality notices (Tầng 2/3)", () => {
  const rec = (over: Partial<AcademicRecord>): AcademicRecord => ({
    school_id: 1,
    school_name: "Trường X",
    level: "THPT",
    year_from: 2020,
    year_to: 2021,
    grade_to: 12,
    gpa: null,
    ...over,
  })

  it("cảnh báo trùng lớp khi 2 entry cùng grade_to", () => {
    renderTab({
      defaults: {
        academic_history: [
          rec({ school_id: 1, grade_to: 12, year_from: 2020, year_to: 2021 }),
          rec({ school_id: 2, grade_to: 12, year_from: 2021, year_to: 2022 }),
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.getByText(/Lớp 12 xuất hiện nhiều lần/i)).toBeInTheDocument()
  })

  it("cảnh báo khi > 3 năm THPT (cho phép, không chặn)", () => {
    renderTab({
      defaults: {
        academic_history: [
          rec({ school_id: 1, grade_to: 10 }),
          rec({ school_id: 2, grade_to: 11 }),
          rec({ school_id: 3, grade_to: 12 }),
          rec({ school_id: 4, grade_to: 11 }),
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.getByText(/Đang có 4 năm THPT/i)).toBeInTheDocument()
  })

  it("cảnh báo năm kết thúc ở tương lai", () => {
    const future = new Date().getFullYear() + 5
    renderTab({
      defaults: {
        academic_history: [rec({ year_from: future, year_to: future, grade_to: 12 })],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.getByText(/kiểm tra lại năm học/i)).toBeInTheDocument()
  })

  it("hiện gợi ý KV khi có dòng THPT nhưng chưa chọn trường từ danh mục", () => {
    renderTab({
      defaults: {
        academic_history: [rec({ school_id: null, school_name: "THPT gõ tay", grade_to: 12 })],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.getByTestId("academic-kv-hint")).toBeInTheDocument()
  })

  it("ẩn gợi ý KV khi đã chọn ít nhất 1 trường THPT từ danh mục", () => {
    renderTab({
      defaults: {
        academic_history: [rec({ school_id: 42, grade_to: 12 })],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.queryByTestId("academic-kv-hint")).not.toBeInTheDocument()
  })

  it("KHÔNG có notice nào khi nhập chuẩn 3 THPT + 4 THCS đã chọn trường", () => {
    // Mỗi lớp một năm học liền nhau (2015–2016 … 2021–2022): không 0 năm, không trùng, không hở.
    renderTab({
      defaults: {
        academic_history: [
          rec({ school_id: 1, level: "THCS", grade_to: 6, year_from: 2015, year_to: 2016 }),
          rec({ school_id: 1, level: "THCS", grade_to: 7, year_from: 2016, year_to: 2017 }),
          rec({ school_id: 1, level: "THCS", grade_to: 8, year_from: 2017, year_to: 2018 }),
          rec({ school_id: 1, level: "THCS", grade_to: 9, year_from: 2018, year_to: 2019 }),
          rec({ school_id: 2, grade_to: 10, year_from: 2019, year_to: 2020 }),
          rec({ school_id: 2, grade_to: 11, year_from: 2020, year_to: 2021 }),
          rec({ school_id: 2, grade_to: 12, year_from: 2021, year_to: 2022 }),
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.queryByTestId("academic-notices")).not.toBeInTheDocument()
  })

  it("nhắc dòng có hai năm bằng nhau (dữ liệu nút thêm nhanh cũ 2025→2025)", () => {
    renderTab({
      defaults: {
        academic_history: [rec({ year_from: 2025, year_to: 2025, grade_to: 12 })],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(
      screen.getByText(
        'Trường #1: "Từ năm" và "Đến năm" đều là 2025, chưa có năm học nào. Một năm học ghi hai năm liền nhau, vd năm học 2024–2025 ghi 2024 → 2025; đối chiếu học bạ.',
      ),
    ).toBeInTheDocument()
  })

  it("nhắc hai dòng trùng năm học (khoá năm bắt đầu: 2020→2023 và 2022→2023 trùng 2022–2023)", () => {
    renderTab({
      defaults: {
        academic_history: [
          rec({ school_id: 1, grade_to: 11, year_from: 2020, year_to: 2023 }),
          rec({ school_id: 2, grade_to: 12, year_from: 2022, year_to: 2023 }),
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.getByText(/Trường #1 và #2 cùng có năm học 2022–2023 —/)).toBeInTheDocument()
  })

  it("KHÔNG nhắc trùng khi hai dòng chỉ chạm nhau ở năm chuyển trường (2020→2022 rồi 2022→2023)", () => {
    renderTab({
      defaults: {
        academic_history: [
          rec({ school_id: 1, grade_to: 11, year_from: 2020, year_to: 2022 }),
          rec({ school_id: 2, grade_to: 12, year_from: 2022, year_to: 2023 }),
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.queryByTestId("academic-notices")).not.toBeInTheDocument()
  })

  it("nhắc hở một năm học và hở nhiều năm học", () => {
    renderTab({
      defaults: {
        academic_history: [
          rec({ school_id: 1, level: "THCS", grade_to: 9, year_from: 2017, year_to: 2021 }),
          rec({ school_id: 2, grade_to: 12, year_from: 2022, year_to: 2025 }),
          rec({ school_id: 3, grade_to: 12, year_from: 2027, year_to: 2028 }),
        ],
      } as Partial<AdmissionProfileUpdateInput>,
    })
    expect(screen.getByText(/Hở năm học 2021–2022 \(giữa Trường #1 và #2\)/)).toBeInTheDocument()
    expect(screen.getByText(/Hở năm học 2025–2026 đến 2026–2027 \(giữa Trường #2 và #3\)/)).toBeInTheDocument()
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
