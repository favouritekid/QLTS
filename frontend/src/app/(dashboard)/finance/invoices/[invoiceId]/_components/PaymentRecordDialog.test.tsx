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
  useDuplicatePreview: (
    input: { feeId?: number; amount: number | null; paymentDate: string | null },
    options: { enabled?: boolean },
  ) => {
    activeHookCalls.push({ input, options })
    const duCanCu =
      (options?.enabled ?? true) &&
      !!input.feeId &&
      input.amount != null &&
      input.amount > 0 &&
      !!input.paymentDate
    if (!duCanCu) return { data: undefined }
    const items = state.activeItems.filter(
      (p) => Number(p.amount) === input.amount,
    )
    return {
      data: { items, total: items.length + (state.activeTruncated ? 1 : 0) },
    }
  },
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

describe("PaymentRecordDialog — cảnh báo ghi trùng", () => {
  /** Điền phương thức + số tiền. */
  async function dienForm(user: ReturnType<typeof userEvent.setup>, soTien: string) {
    await user.click(
      screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
    )
    await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
    await user.type(screen.getByPlaceholderText(/nhập số tiền/i), soTien)
  }

  const nutLuu = () => screen.getByRole("button", { name: /ghi nhận thanh toán/i })

  function phieuDaCo(over: Partial<(typeof state.activeItems)[number]> = {}) {
    return {
      id: 5,
      amount: "1000000",
      status: "pending",
      payment_date: new Date().toISOString(),
      ...over,
    }
  }

  it("gõ số tiền trùng một phiếu đã có thì cảnh báo SỚM và chặn Lưu", async () => {
    const user = userEvent.setup()
    state.activeItems = [phieuDaCo()]
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    expect(screen.queryByTestId("payment-duplicate-warning")).not.toBeInTheDocument()

    await dienForm(user, "1000000")

    // Hiện TRƯỚC khi bấm Lưu — người ghi không phải gửi đi rồi mới biết.
    expect(await screen.findByTestId("payment-duplicate-warning")).toBeInTheDocument()
    expect(nutLuu()).toBeDisabled()
    expect(createPayment).not.toHaveBeenCalled()
  })

  it("tick xác nhận rồi bấm Lưu thì gửi confirm_duplicate=true, KHÔNG tự gửi lại", async () => {
    const user = userEvent.setup()
    state.activeItems = [phieuDaCo({ status: "verified" })]
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    await dienForm(user, "1000000")
    await screen.findByTestId("payment-duplicate-warning")

    await user.click(screen.getByTestId("payment-duplicate-confirm"))
    // Tick KHÔNG được tự gửi: hành động cuối vẫn phải là một quyết định.
    expect(createPayment).not.toHaveBeenCalled()

    await user.click(nutLuu())
    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))
    expect(createPayment.mock.calls[0][0].data.confirm_duplicate).toBe(true)
  })

  it("đổi số tiền sau khi đã tick thì xác nhận hết hiệu lực", async () => {
    const user = userEvent.setup()
    state.activeItems = [phieuDaCo(), phieuDaCo({ id: 6, amount: "2000000" })]
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    const oSoTien = screen.getByPlaceholderText(/nhập số tiền/i)
    await dienForm(user, "1000000")
    await screen.findByTestId("payment-duplicate-warning")
    await user.click(screen.getByTestId("payment-duplicate-confirm"))
    expect(nutLuu()).toBeEnabled()

    // Tick được cấp cho 1.000.000. Mang nó sang 2.000.000 là bỏ qua cảnh báo
    // cho một số tiền chưa ai xem.
    await user.clear(oSoTien)
    await user.type(oSoTien, "2000000")

    await waitFor(() => expect(nutLuu()).toBeDisabled())
    expect(screen.getByTestId("payment-duplicate-confirm")).not.toBeChecked()
  })

  it("số tiền không trùng phiếu nào thì không cảnh báo, gửi confirm_duplicate=false", async () => {
    const user = userEvent.setup()
    state.activeItems = [phieuDaCo()]
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    await dienForm(user, "500000")
    expect(screen.queryByTestId("payment-duplicate-warning")).not.toBeInTheDocument()

    await user.click(nutLuu())
    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))
    expect(createPayment.mock.calls[0][0].data.confirm_duplicate).toBe(false)
  })

  it("cảnh báo SỚM bị cắt cũng phải nói ra", async () => {
    // Hai nguồn (xem trước và 409) đếm "còn nữa" bằng hai cách khác nhau. Đọc
    // nhầm nguồn là im lặng đúng lúc cần nói: người ghi thấy 20 phiếu và tưởng
    // đó là tất cả.
    const user = userEvent.setup()
    state.activeItems = Array.from({ length: 20 }, (_, i) => phieuDaCo({ id: i + 1 }))
    state.activeTruncated = true
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    await dienForm(user, "1000000")
    await screen.findByTestId("payment-duplicate-warning")
    expect(screen.getByTestId("payment-duplicate-truncated")).toBeInTheDocument()
  })

  it("cảnh báo SỚM chưa bị cắt thì KHÔNG nói thừa", async () => {
    const user = userEvent.setup()
    state.activeItems = [phieuDaCo()]
    state.activeTruncated = false
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    await dienForm(user, "1000000")
    await screen.findByTestId("payment-duplicate-warning")
    expect(screen.queryByTestId("payment-duplicate-truncated")).not.toBeInTheDocument()
  })

  it("máy chủ trả 409 thì hiện danh sách của máy chủ, kèm ghi chú khi bị cắt", async () => {
    const user = userEvent.setup()
    // Giao diện KHÔNG thấy gì — máy chủ vẫn là nơi quyết định cuối.
    state.activeItems = []
    createPayment.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: "Đã có nhiều phiếu thu cùng số tiền",
          error_code: "PAYMENT_DUPLICATE_SUSPECTED",
          duplicates: [
            {
              payment_id: 91,
              amount: "1000000",
              payment_date: "2026-08-05T03:00:00+00:00",
              status: "verified",
              invoice_number: "INV-XYZ",
            },
          ],
          duplicates_truncated: true,
        },
      },
    })
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    await dienForm(user, "1000000")
    expect(screen.queryByTestId("payment-duplicate-warning")).not.toBeInTheDocument()

    await user.click(nutLuu())

    const khoi = await screen.findByTestId("payment-duplicate-warning")
    expect(khoi).toHaveTextContent("INV-XYZ")
    expect(screen.getByTestId("payment-duplicate-truncated")).toBeInTheDocument()
    expect(nutLuu()).toBeDisabled()
  })

  it("409 rồi đổi số tiền thì danh sách của máy chủ không còn hiện", async () => {
    const user = userEvent.setup()
    state.activeItems = []
    createPayment.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: "trùng",
          error_code: "PAYMENT_DUPLICATE_SUSPECTED",
          duplicates: [
            {
              payment_id: 91,
              amount: "1000000",
              payment_date: null,
              status: "pending",
              invoice_number: "INV-XYZ",
            },
          ],
          duplicates_truncated: false,
        },
      },
    })
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    const oSoTien = screen.getByPlaceholderText(/nhập số tiền/i)
    await dienForm(user, "1000000")
    await user.click(nutLuu())
    await screen.findByTestId("payment-duplicate-warning")

    // Cảnh báo nói về 1.000.000. Đổi số tiền thì nó phải biến mất — hiện danh
    // sách của một số tiền khác với số đang trên màn hình là nói dối.
    await user.clear(oSoTien)
    await user.type(oSoTien, "1500000")
    await waitFor(() =>
      expect(screen.queryByTestId("payment-duplicate-warning")).not.toBeInTheDocument(),
    )
    expect(nutLuu()).toBeEnabled()
  })

  it("409 với payload MÉO thì không hiện khối cảnh báo (rơi về lỗi chung)", async () => {
    const user = userEvent.setup()
    state.activeItems = []
    createPayment.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: "trùng",
          error_code: "PAYMENT_DUPLICATE_SUSPECTED",
          duplicates: [{ payment_id: 91 }], // thiếu trường
          duplicates_truncated: false,
        },
      },
    })
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    await dienForm(user, "1000000")
    await user.click(nutLuu())
    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))

    // Không dựng khối cảnh báo từ dữ liệu không đọc được: người dùng thấy
    // thông báo lỗi chung (hook bắn), form không giả vờ hiểu.
    expect(screen.queryByTestId("payment-duplicate-warning")).not.toBeInTheDocument()
  })

  it("hỏi hook nguồn RIÊNG cho cảnh báo trùng, không mượn ô chờ duyệt", () => {
    render(
      <PaymentRecordDialog
        open
        onOpenChange={vi.fn()}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    // Hai nguồn tách bạch: ô "đang chờ duyệt" hỏi hàng đợi maker-checker; cảnh
    // báo trùng hỏi CHÍNH luật của máy chủ bằng bộ ba fee + tiền + ngày.
    expect(activeHookCalls.at(-1)?.options).toEqual({ enabled: true })
    expect(activeHookCalls.at(-1)?.input).toMatchObject({ feeId: 7 })
    expect(pendingHookCalls.at(-1)).toEqual({ feeId: 7, options: { enabled: true } })
  })
})

describe("PaymentRecordDialog — phản hồi của phiên trước không sống lại", () => {
  it("đóng form khi request đang bay, mở lại cùng dữ liệu ⇒ không thấy cảnh báo cũ", async () => {
    const user = userEvent.setup()
    state.activeItems = []

    // Giữ phản hồi lại: mô phỏng người dùng bấm X trong lúc máy chủ chưa trả
    // lời. Hiệu ứng dọn dẹp chạy trước, rồi `catch` của request cũ mới chạy —
    // nếu nó ghi state vô điều kiện thì danh sách của phiên trước sẽ nằm sẵn ở
    // đó chờ phiên sau.
    let tuChoi: (e: unknown) => void = () => {}
    createPayment.mockImplementationOnce(
      () => new Promise((_, reject) => { tuChoi = reject }),
    )

    const onOpenChange = vi.fn()
    const { rerender } = render(
      <PaymentRecordDialog
        open
        onOpenChange={onOpenChange}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )

    await user.click(
      screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
    )
    await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
    await user.type(screen.getByPlaceholderText(/nhập số tiền/i), "1000000")
    await user.click(screen.getByRole("button", { name: /ghi nhận thanh toán/i }))
    await waitFor(() => expect(createPayment).toHaveBeenCalledTimes(1))

    // Người dùng đóng form trong lúc chờ.
    rerender(
      <PaymentRecordDialog
        open={false}
        onOpenChange={onOpenChange}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )

    // Máy chủ trả lời MUỘN, sau khi form đã đóng. Bọc `act` vì lời từ chối này
    // kích hoạt `setState` bên trong component — không bọc thì React cảnh báo
    // và ta đang đo một cây giao diện chưa ổn định.
    await act(async () => {
      tuChoi({
        response: {
          status: 409,
          data: {
            detail: "trùng",
            error_code: "PAYMENT_DUPLICATE_SUSPECTED",
            duplicates: [
              {
                payment_id: 91,
                amount: "1000000",
                payment_date: null,
                status: "pending",
                invoice_number: "INV-PHIEN-TRUOC",
              },
            ],
            duplicates_truncated: false,
          },
        },
      })
      await Promise.resolve()
    })

    // Mở lại và nhập ĐÚNG dữ liệu cũ.
    rerender(
      <PaymentRecordDialog
        open
        onOpenChange={onOpenChange}
        invoiceId={19}
        feeId={7}
        maxAmount="4.000.000 ₫"
      />,
    )
    await user.click(
      screen.getByRole("combobox", { name: /phương thức thanh toán/i }),
    )
    await user.click(await screen.findByRole("option", { name: "Tiền mặt" }))
    await user.type(screen.getByPlaceholderText(/nhập số tiền/i), "1000000")

    // Cảnh báo của phiên trước KHÔNG được sống dậy: lần này chưa ai hỏi máy
    // chủ, nên hiện một danh sách cũ là nói về dữ liệu không còn ai bảo đảm.
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.queryByText(/INV-PHIEN-TRUOC/)).not.toBeInTheDocument()
  })
})
