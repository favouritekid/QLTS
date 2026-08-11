/**
 * Regression: the record-payment form prefills the payer name + reference from
 * the collection-drawer context (Quick win A) so the accountant confirms instead
 * of re-typing what the system already knows; without a context it stays blank.
 *
 * Và (B1): bảng công nợ trong dialog, đặc biệt dòng "đang chờ duyệt". Tiền chỉ
 * vào sổ khi phiếu được DUYỆT, nên nếu không nói ra thì màn hình hiện y như
 * chưa ai thu và kế toán nhập lại — prod đã có 9 phiếu nghi trùng theo đúng
 * đường đó.
 *
 * Vòng review 04/08 chỉ ra rằng bộ test cũ **không thể đỏ** ở những chỗ quan
 * trọng nhất: mock hook bỏ qua đối số, nên nó xanh y hệt dù dialog hỏi khoản
 * phí nào, và nó chỉ soi cái panel chứ không soi phần còn lại của dialog — nơi
 * con số "còn lại" thứ hai đang sống. Ba lớp được bổ sung ở đây:
 *
 *  - **đối số truyền cho hook** (khoản phí nào, mở hay đóng);
 *  - **lỗi tải phải hiện ra là lỗi**, không được vẽ thành 0 hay thành "không có
 *    phiếu nào chờ" — đó là câu trả lời sai nguy hiểm nhất, vì nó cấp phép cho
 *    lần nhập thứ hai;
 *  - **một con số duy nhất**: chặn theo số máy chủ thì phải HIỆN số máy chủ ở
 *    mọi chỗ, kể cả ô nhập và thông báo lỗi.
 */
// 🔴 Đặt TRƯỚC mọi import — ca "ngày gửi lên" chỉ phân biệt được đúng/sai ở
// múi giờ dương. Ở UTC mặc định của Vitest, bản cũ (`toISOString`) và bản mới
// cho cùng kết quả, nên bài kiểm tra sẽ không thể đỏ. Ca `guard` bên dưới xác
// nhận điều này thay vì tin suông.
const TZ_GOC = process.env.TZ
process.env.TZ = "Asia/Ho_Chi_Minh"

import { afterAll, describe, it, expect, vi, beforeEach } from "vitest"
import userEvent from "@testing-library/user-event"
import { act, render, screen, waitFor, within } from "@/test/utils/test-utils"

import { PaymentRecordDialog } from "./PaymentRecordDialog"

// Trạng thái điều khiển được cho từng ca — khai ở ngoài để `vi.mock` (bị hoist)
// vẫn đọc được giá trị mới nhất.
const state = {
  invoice: {
    total_due: "5000000",
    paid_amount: "1000000",
    remaining_amount: "4000000",
  } as Record<string, string> | undefined,
  invoiceLoading: false,
  invoiceFailed: false,
  pendingItems: [] as Array<{ id: number; amount: string }>,
  pendingTotal: undefined as number | undefined,
  pendingLoading: false,
  pendingFailed: false,
  activeItems: [] as Array<{
    id: number
    amount: string
    status: string
    payment_date: string | null
  }>,
  activeTruncated: false,
  previewFailed: false,
}

/** Đối số THẬT mà dialog truyền cho hook — thứ bộ test cũ không hề nhìn. */
const pendingHookCalls: Array<{ feeId: unknown; options: unknown }> = []
const invoiceHookCalls: Array<{ invoiceId: unknown; options: unknown }> = []
const activeHookCalls: Array<{ input: unknown; options: unknown }> = []
const createPayment = vi.fn()

vi.mock("@/hooks/finance/usePayments", () => ({
  useCreatePayment: () => ({
    mutateAsync: (...args: unknown[]) => createPayment(...args),
    isPending: false,
  }),
  usePendingPaymentsByFee: (feeId: unknown, options: unknown) => {
    pendingHookCalls.push({ feeId, options })
    return {
      data: {
        items: state.pendingItems,
        total: state.pendingTotal ?? state.pendingItems.length,
      },
      isLoading: state.pendingLoading,
      isError: state.pendingFailed,
    }
  },
  // Mô phỏng tối thiểu hành vi máy chủ: chỉ trả lời khi câu hỏi đủ vế, và lọc
  // theo số tiền. Luật thật sống ở máy chủ (test riêng bên backend); ở đây chỉ
  // cần phân biệt "có ứng viên" với "không có".
}))

vi.mock("@/hooks/finance/useInvoices", () => ({
  useInvoiceDetail: (invoiceId: unknown, options: unknown) => {
    invoiceHookCalls.push({ invoiceId, options })
    return {
      data: state.invoiceFailed ? undefined : state.invoice,
      isLoading: state.invoiceLoading,
      isError: state.invoiceFailed,
    }
  },
}))

vi.mock("@/hooks/finance/usePaymentMethods", () => ({
  usePaymentMethods: () => ({
    data: [
      { id: 1, code: "cash", name: "Tiền mặt", is_online: false, is_active: true },
    ],
    isLoading: false,
  }),
}))

/**
 * Radix Select dùng Pointer Capture và `scrollIntoView`, cả hai đều không có
 * trong jsdom. Gán hàm THƯỜNG (không phải `vi.fn`) vì vitest config bật
 * `mockReset`/`restoreMocks`, sẽ xoá sạch thân mock giữa các ca.
 */
function installPointerStubs() {
  Element.prototype.scrollIntoView = function scrollIntoView() {}
  Element.prototype.hasPointerCapture = function hasPointerCapture() {
    return false
  }
  Element.prototype.setPointerCapture = function setPointerCapture() {}
  Element.prototype.releasePointerCapture = function releasePointerCapture() {}
}

// Worker của Vitest được dùng lại giữa các file — trả TZ về nguyên trạng, kẻo
// file chạy sau thừa hưởng múi giờ mà nó không hề khai báo.
afterAll(() => {
  if (TZ_GOC === undefined) delete process.env.TZ
  else process.env.TZ = TZ_GOC
})

beforeEach(() => {
  installPointerStubs()
  pendingHookCalls.length = 0
  invoiceHookCalls.length = 0
  activeHookCalls.length = 0
  state.invoice = {
    total_due: "5000000",
    paid_amount: "1000000",
    remaining_amount: "4000000",
  }
  state.invoiceLoading = false
  state.invoiceFailed = false
  state.pendingItems = []
  state.pendingTotal = undefined
  state.pendingLoading = false
  state.pendingFailed = false
  state.activeItems = []
  state.activeTruncated = false
  state.previewFailed = false
})

describe("PaymentRecordDialog", () => {
  it("prefills payer name + reference from the drawer context", () => {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.200.000 ₫"
        defaultPayerName="Nguyễn Thế Đạt"
        defaultReference="HS-000025"
      />,
    )
    expect(screen.getByLabelText(/tên người nộp/i)).toHaveValue("Nguyễn Thế Đạt")
    expect(screen.getByLabelText(/mã tham chiếu/i)).toHaveValue("HS-000025")
  })

  it("leaves payer + reference blank with no context (e.g. detail page)", () => {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.200.000 ₫"
      />,
    )
    expect(screen.getByLabelText(/tên người nộp/i)).toHaveValue("")
    expect(screen.getByLabelText(/mã tham chiếu/i)).toHaveValue("")
  })
})

describe("PaymentRecordDialog — bảng công nợ", () => {
  it("hiện dòng 'chờ duyệt' kèm SỐ PHIẾU và TỔNG khi có phiếu chưa duyệt", () => {
    state.pendingItems = [
      { id: 1, amount: "2000000" },
      { id: 2, amount: "500000" },
    ]
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    const row = screen.getByTestId("payment-pending-row")
    expect(row).toHaveTextContent(/2 phiếu/)
    // 2.000.000 + 500.000 — cộng ở FE vì API trả từng phiếu, không trả tổng.
    expect(row).toHaveTextContent(/2\D?500\D?000/)
  })

  it("ẨN dòng 'chờ duyệt' khi không có phiếu nào chờ", () => {
    state.pendingItems = []
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    expect(screen.getByTestId("payment-debt-panel")).toBeInTheDocument()
    expect(screen.queryByTestId("payment-pending-row")).not.toBeInTheDocument()
  })

  it("đang tải thì KHÔNG chặn form — vẫn gõ được", () => {
    state.invoiceLoading = true
    state.pendingLoading = true
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    // Panel có mặt (đang ở trạng thái chờ) nhưng các ô nhập vẫn dùng được.
    expect(screen.getByTestId("payment-debt-panel")).toBeInTheDocument()
    expect(screen.queryByTestId("payment-pending-row")).not.toBeInTheDocument()
    expect(screen.getByLabelText(/tên người nộp/i)).toBeEnabled()
    expect(screen.getByLabelText(/mã tham chiếu/i)).toBeEnabled()
  })

  it("hiện ba dòng công nợ lấy từ SỐ THẬT của máy chủ", () => {
    state.invoice = {
      total_due: "5000000",
      paid_amount: "1000000",
      remaining_amount: "4000000",
    }
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        // Prop hiển thị CỐ TÌNH lệch số thật: panel phải bám máy chủ, không
        // bám chuỗi truyền qua prop.
        maxAmount="9.999.999 ₫"
      />,
    )
    const panel = screen.getByTestId("payment-debt-panel")
    expect(panel).toHaveTextContent(/5\D?000\D?000/)
    expect(panel).toHaveTextContent(/1\D?000\D?000/)
    expect(panel).toHaveTextContent(/4\D?000\D?000/)
    expect(panel).not.toHaveTextContent(/9\D?999\D?999/)
  })

  it("nói rõ khi danh sách phiếu chờ bị cắt bớt, không trình bày tổng thiếu như tổng đủ", () => {
    state.pendingItems = [{ id: 1, amount: "2000000" }]
    state.pendingTotal = 120
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    expect(screen.getByTestId("payment-pending-truncated")).toHaveTextContent(/120/)
  })
})

describe("PaymentRecordDialog — hỏi đúng khoản phí, đúng lúc", () => {
  it("truyền feeId của form xuống hook, kèm cờ mở/đóng", () => {
    const { rerender } = render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={77}
        maxAmount="4.000.000 ₫"
      />,
    )
    // Hook phải nhận ĐÚNG khoản phí — không phải invoiceId, không phải
    // undefined. Bộ test cũ mock hook mà bỏ qua đối số nên truyền gì cũng xanh.
    expect(pendingHookCalls.length).toBeGreaterThan(0)
    expect(pendingHookCalls.at(-1)).toEqual({
      feeId: 77,
      options: { enabled: true },
    })

    pendingHookCalls.length = 0
    rerender(
      <PaymentRecordDialog
        open={false}
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={77}
        maxAmount="4.000.000 ₫"
      />,
    )
    // Đóng form thì không được giữ query chạy — và quan trọng hơn, `enabled`
    // đổi theo `open` chính là cơ chế khiến mở lại sẽ hỏi lại máy chủ.
    expect(pendingHookCalls.at(-1)?.options).toEqual({ enabled: false })
  })

  it("bắt hoá đơn phải TƯƠI, không nhận lại bản cache 30 giây của trang cha", () => {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={77}
        maxAmount="4.000.000 ₫"
      />,
    )
    // `enabled: open` một mình KHÔNG đủ: trang cha dùng chung query key với độ
    // tươi mặc định 30 giây, nên mở lại trong 30 giây sẽ đọc đúng bản cache
    // cũ — trong khi hàng đợi chờ duyệt đã tươi. Panel khi ấy nói "không còn
    // phiếu chờ" kèm số dư của lúc trước khi duyệt.
    // (Việc `staleTime: 0` THỰC SỰ ép hỏi lại máy chủ được chứng minh riêng ở
    // `useInvoiceDetail.freshness.test.tsx`; ca này khoá mắt xích nối hai đầu.)
    expect(invoiceHookCalls.at(-1)).toEqual({
      invoiceId: 19,
      options: { enabled: true, staleTime: 0 },
    })
  })
})

describe("PaymentRecordDialog — lỗi tải KHÔNG được vẽ thành số 0", () => {
  it("hỏng hoá đơn thì báo không đối chiếu được, không hiện bảng toàn số 0", () => {
    state.invoiceFailed = true
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    const panel = screen.getByTestId("payment-debt-panel")
    expect(screen.getByTestId("payment-debt-error")).toBeInTheDocument()
    // Ca quyết định: một bảng "Còn phải thu: 0 ₫" trông y hệt "hồ sơ này hết
    // nợ" — kế toán tin là đã đối chiếu xong rồi nhập tiếp.
    expect(panel).not.toHaveTextContent(/Còn phải thu/)
    expect(panel).not.toHaveTextContent(/\b0\s*₫/)
  })

  it("hỏng danh sách phiếu chờ thì NÓI hỏng, không im lặng như 'không có phiếu nào'", () => {
    state.pendingFailed = true
    state.pendingItems = []
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    expect(screen.getByTestId("payment-pending-error")).toBeInTheDocument()
    // Ba dòng công nợ vẫn hiện (hoá đơn tải được) — chỉ phần chờ duyệt là chưa
    // biết, và cái chưa biết phải được nói ra.
    expect(screen.getByTestId("payment-debt-panel")).toHaveTextContent(/Còn phải thu/)
  })
})

describe("PaymentRecordDialog — MỘT con số 'còn lại' duy nhất", () => {
  it("mọi chỗ trong dialog đều dùng số máy chủ, không chỗ nào dùng prop lệch", () => {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="9.999.999 ₫"
      />,
    )
    // Soi TOÀN dialog, không chỉ panel: trước đây tiêu đề và dòng mô tả ô nhập
    // vẫn đọc prop, nên form nói "tối đa 9.999.999" trong khi nó chặn ở
    // 4.000.000.
    const dialog = screen.getByRole("dialog")
    expect(dialog).not.toHaveTextContent(/9\D?999\D?999/)
    expect(within(dialog).getAllByText(/4\D?000\D?000/).length).toBeGreaterThan(1)
  })

  it("chặn số tiền vượt số dư THẬT dù nó nhỏ hơn con số truyền qua prop", async () => {
    const user = userEvent.setup()
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        // Prop nói còn 9.999.999 (ảnh chụp cũ), máy chủ nói còn 4.000.000.
        maxAmount="9.999.999 ₫"
      />,
    )

    await user.click(
      screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
    )
    await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
    await user.type(screen.getByPlaceholderText(/nhập số tiền/i), "5000000")
    await user.click(screen.getByRole("button", { name: /ghi nhận thanh toán/i }))

    // 5.000.000 < prop nhưng > số dư thật ⇒ phải bị chặn TẠI CHỖ, không được
    // gửi lên máy chủ rồi mới bị từ chối.
    await waitFor(() =>
      expect(screen.getByText(/không được vượt quá số dư/i)).toBeInTheDocument(),
    )
    expect(createPayment).not.toHaveBeenCalled()
    // Và câu từ chối phải nêu đúng con số vừa dùng để từ chối.
    expect(screen.getByText(/không được vượt quá số dư/i)).toHaveTextContent(
      /4\D?000\D?000/,
    )
  })

  it("guard: bộ test chạy ở múi giờ Việt Nam (dùng chung cho nhóm dưới)", () => {
    // -420 phút = UTC+7. Ở UTC (0) thì ca ngày bên dưới mất khả năng phân biệt
    // bản cũ với bản mới.
    expect(new Date(2026, 7, 5).getTimezoneOffset()).toBe(-420)
  })

  it("gửi được số tiền nằm trong số dư thật", async () => {
    const user = userEvent.setup()
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="9.999.999 ₫"
      />,
    )

    await user.click(
      screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
    )
    await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
    await user.type(screen.getByPlaceholderText(/nhập số tiền/i), "3000000")
    await user.click(screen.getByRole("button", { name: /ghi nhận thanh toán/i }))

    // Đối chứng cho ca trên: nếu ca này cũng bị chặn thì phép chặn đang sai
    // chiều chứ không phải đang bảo vệ ai.
    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))
    expect(createPayment.mock.calls[0][0]).toMatchObject({
      invoiceId: 19,
      feeId: 7,
      data: expect.objectContaining({ invoice_id: 19, amount: "3000000" }),
    })
  })

  it("BẤM một ngày trong lịch thì gửi đúng ngày đó, không lùi một ngày", async () => {
    // Đồng hồ cố định để "tháng đang mở" của lịch là 08/2026 và ca này không
    // phụ thuộc lúc chạy thật.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date("2026-08-12T09:00:00+07:00"))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    try {
      render(
        <PaymentRecordDialog
          open
          onOpenChange={vi.fn()}
          invoiceId={19}
          feeId={7}
          maxAmount="9.999.999 ₫"
        />,
      )

      await user.click(
        screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
      )
      await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
      await user.type(screen.getByPlaceholderText(/nhập số tiền/i), "1000000")

      // Mở lịch và bấm ngày 05 — thao tác thật của kế toán ghi một khoản thu
      // mấy hôm trước. Đây là đường sinh ra lỗi: `react-day-picker` trả
      // `Date` 00:00 GIỜ ĐỊA PHƯƠNG, và lỗi lùi ngày ở đường này KHÔNG phụ
      // thuộc giờ trong ngày (khác với ca để nguyên mặc định).
      // Nút mở lịch là combobox thứ hai (thứ nhất là phương thức thanh toán).
      // Khẳng định nhãn của nó trước khi bấm: form phải đang hiển thị đúng
      // ngày mặc định, nếu không thì ca này đang đo một màn hình khác.
      const nutLich = screen.getAllByRole("combobox")[1]
      expect(nutLich).toHaveTextContent("12/08/2026")
      await user.click(nutLich)
      const lich = await screen.findByRole("grid")
      // Lịch còn hiển thị ngày của tháng liền kề nên tìm theo chữ số "5" sẽ
      // dính nhiều ô. `data-day` là khoá ngày do react-day-picker gắn sẵn —
      // xác định và không phụ thuộc cách nó dựng nhãn tiếng Việt.
      const oNgay5 = lich.querySelector<HTMLElement>('[data-day="2026-08-05"] button')
      expect(oNgay5).not.toBeNull()
      await user.click(oNgay5!)

      await user.click(screen.getByRole("button", { name: /ghi nhận thanh toán/i }))
      await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))

      expect(createPayment.mock.calls[0][0].data.payment_date).toBe("2026-08-05")
    } finally {
      vi.useRealTimers()
    }
  })
})

describe("PaymentRecordDialog — vòng xác nhận nghi trùng", () => {
  const nutLuu = () => screen.getByRole("button", { name: /ghi nhận thanh toán/i })

  async function dienForm(user: ReturnType<typeof userEvent.setup>, soTien: string) {
    await user.click(
      screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
    )
    await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
    await user.type(screen.getByPlaceholderText(/nhập số tiền/i), soTien)
  }

  function than409(over: Record<string, unknown> = {}) {
    return {
      response: {
        status: 409,
        data: {
          detail: "trùng",
          error_code: "PAYMENT_DUPLICATE_SUSPECTED",
          duplicates: [
            {
              payment_id: 91,
              amount: "1000000",
              payment_date: "2026-08-05T03:00:00+00:00",
              status: "pending",
              invoice_number: "INV-A",
            },
          ],
          duplicates_truncated: false,
          duplicates_total: 1,
          review_token: "phieu.mot",
          ...over,
        },
      },
    }
  }

  function moForm() {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="9.999.999 ₫"
      />,
    )
  }

  it("gửi → 409 thật → xác nhận → request THỨ HAI mang đúng phiếu", async () => {
    // Ca duy nhất chứng minh tính năng dùng được. Reducer xanh không đủ: nó
    // không nói gì về việc handler có thật sự đọc phiếu ra khỏi trạng thái rồi
    // đính vào payload hay không — đúng lớp lỗi đã xảy ra một lần rồi (giao
    // diện thiếu một trường bắt buộc mà ca ở tầng dưới vẫn xanh).
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce(than409())
    createPayment.mockResolvedValueOnce({ id: 1 })
    moForm()
    await dienForm(user, "1000000")
    await user.click(nutLuu())

    await screen.findByTestId("payment-duplicate-warning")
    expect(createPayment.mock.calls[0][0].data.review_token).toBeUndefined()

    await user.click(screen.getByTestId("payment-duplicate-confirm"))
    await user.click(nutLuu())

    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(2))
    expect(createPayment.mock.calls[1][0].data.review_token).toBe("phieu.mot")
  })

  it("sửa số tiền sau 409 ⇒ cảnh báo biến mất, lượt sau KHÔNG mang phiếu", async () => {
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce(than409())
    createPayment.mockResolvedValueOnce({ id: 1 })
    moForm()
    const oSoTien = screen.getByPlaceholderText(/nhập số tiền/i)
    await dienForm(user, "1000000")
    await user.click(nutLuu())
    await screen.findByTestId("payment-duplicate-warning")
    await user.click(screen.getByTestId("payment-duplicate-confirm"))

    await user.clear(oSoTien)
    await user.type(oSoTien, "1500000")
    await waitFor(() =>
      expect(screen.queryByTestId("payment-duplicate-warning")).not.toBeInTheDocument(),
    )

    await user.click(nutLuu())
    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(2))
    expect(
      createPayment.mock.calls[1][0].data.review_token,
      "phiếu nói về số tiền cũ — mang nó theo số tiền mới là xin xác nhận cho " +
        "một tập ứng viên người dùng chưa từng xem",
    ).toBeUndefined()
  })

  it("sửa GHI CHÚ sau 409 ⇒ giữ nguyên lượt xác nhận", async () => {
    // Ghi chú KHÔNG nằm trong những trường phiếu ràng buộc vào. Huỷ xác nhận vì
    // nó là bắt người dùng tick lại vì một thay đổi không liên quan — cách
    // nhanh nhất khiến họ bấm qua cảnh báo mà không đọc.
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce(than409())
    moForm()
    await dienForm(user, "1000000")
    await user.click(nutLuu())
    await screen.findByTestId("payment-duplicate-warning")
    await user.click(screen.getByTestId("payment-duplicate-confirm"))

    await user.type(screen.getByPlaceholderText(/ghi chú thêm/i), "thu hộ")

    expect(screen.getByTestId("payment-duplicate-warning")).toBeInTheDocument()
    expect(screen.getByTestId("payment-duplicate-confirm")).toBeChecked()
  })

  it("xác nhận gặp 409 MỚI ⇒ thay nguyên khối và bỏ tick", async () => {
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce(than409())
    createPayment.mockRejectedValueOnce(
      than409({
        duplicates: [
          {
            payment_id: 92,
            amount: "1000000",
            payment_date: null,
            status: "verified",
            invoice_number: "INV-B",
          },
        ],
        review_token: "phieu.hai",
      }),
    )
    moForm()
    await dienForm(user, "1000000")
    await user.click(nutLuu())
    await screen.findByTestId("payment-duplicate-warning")
    await user.click(screen.getByTestId("payment-duplicate-confirm"))
    await user.click(nutLuu())

    await waitFor(() =>
      expect(screen.getByTestId("payment-duplicate-warning")).toHaveTextContent(/INV-B/),
    )
    expect(screen.getByTestId("payment-duplicate-warning")).not.toHaveTextContent(/INV-A/)
    expect(
      screen.getByTestId("payment-duplicate-confirm"),
      "tập ứng viên đã đổi ⇒ tick cũ nói về thứ khác",
    ).not.toBeChecked()
    expect(nutLuu()).toBeDisabled()
  })

  it("409 MÉO (thiếu phiếu) ⇒ KHÔNG có khối xác nhận", async () => {
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce(than409({ review_token: undefined }))
    moForm()
    await dienForm(user, "1000000")
    await user.click(nutLuu())

    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))
    expect(
      screen.queryByTestId("payment-duplicate-warning"),
      "không có phiếu thì không có gì để xác nhận — một nút bấm vô hiệu còn tệ " +
        "hơn một thông báo lỗi thẳng thắn",
    ).not.toBeInTheDocument()
  })

  it("lỗi KHÔNG phải trùng ⇒ thoát trạng thái gửi, không giữ phiếu", async () => {
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce({ response: { status: 500, data: {} } })
    createPayment.mockResolvedValueOnce({ id: 1 })
    moForm()
    await dienForm(user, "1000000")
    await user.click(nutLuu())

    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))
    // Kẹt ở `submitting` thì nút Lưu khoá vĩnh viễn và người ghi mất đường.
    await waitFor(() => expect(nutLuu()).toBeEnabled())
    await user.click(nutLuu())
    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(2))
    expect(createPayment.mock.calls[1][0].data.review_token).toBeUndefined()
  })

  it("bấm Lưu HAI LẦN liên tiếp ⇒ chỉ MỘT lượt gửi", async () => {
    // Phải chạy ở tầng dialog: reducer chặn được lượt thứ hai, nhưng chỉ SAU
    // khi React render lại — còn hai cú bấm liền nhau cùng chạy trên một bản
    // trạng thái. Hàng rào thật nằm trong handler.
    const user = userEvent.setup()
    let goCua: (v: unknown) => void = () => {}
    createPayment.mockReturnValueOnce(
      new Promise((res) => {
        goCua = res
      }),
    )
    moForm()
    await dienForm(user, "1000000")
    const nut = nutLuu()
    await user.click(nut)
    await user.click(nut)

    expect(createPayment).toHaveBeenCalledTimes(1)
    goCua({ id: 1 })
  })

  it("bấm HAI LẦN ở lượt gửi KÈM PHIẾU ⇒ cũng chỉ một lượt", async () => {
    const user = userEvent.setup()
    createPayment.mockRejectedValueOnce(than409())
    let goCua: (v: unknown) => void = () => {}
    createPayment.mockReturnValueOnce(
      new Promise((res) => {
        goCua = res
      }),
    )
    moForm()
    await dienForm(user, "1000000")
    await user.click(nutLuu())
    await screen.findByTestId("payment-duplicate-warning")
    await user.click(screen.getByTestId("payment-duplicate-confirm"))
    const nut = nutLuu()
    await user.click(nut)
    await user.click(nut)

    // 1 lượt đầu (bị 409) + 1 lượt kèm phiếu = 2. Không phải 3.
    expect(createPayment).toHaveBeenCalledTimes(2)
    goCua({ id: 1 })
  })
  it("đang gửi ⇒ KHOÁ ba trường mà phiếu ràng buộc vào", async () => {
    // Sửa được giữa lúc request đang bay thì ảnh chụp giữ ý định CŨ trong khi
    // form đã hiện giá trị mới. Máy chủ vẫn fail-closed, nhưng màn hình nói một
    // đằng và lượt sau ăn thêm một vòng 409 không cần thiết.
    const user = userEvent.setup()
    let goCua: (v: unknown) => void = () => {}
    createPayment.mockReturnValueOnce(
      new Promise((res) => {
        goCua = res
      }),
    )
    moForm()
    await dienForm(user, "1000000")
    await user.click(nutLuu())

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/nhập số tiền/i)).toBeDisabled(),
    )
    expect(
      screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
    ).toBeDisabled()
    // Ô ngày là một nút mở lịch, nhãn của nó là chính ngày đang chọn nên
    // không có tên ổn định để tìm. Khoá nó bằng cách khác: MỌI nút trong form
    // phải disabled khi đang gửi, trừ nút Huỷ (người dùng luôn phải thoát
    // được). Phép đếm này còn bắt được cả những nút thêm vào sau này mà ai đó
    // quên khoá.
    const nutConMo = screen
      .getAllByRole("button")
      .filter((b) => !(b as HTMLButtonElement).disabled)
      .map((b) => b.textContent?.trim())
    expect(nutConMo.every((t) => /h[uủ][yỷ]|đóng|close/i.test(t ?? ""))).toBe(true)

    goCua({ id: 1 })
  })
})
