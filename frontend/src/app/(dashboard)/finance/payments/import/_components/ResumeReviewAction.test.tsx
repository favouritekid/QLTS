/**
 * Đường thoát cho lô mắc kẹt: LỊCH SỬ → mở lô → detail TƯƠI → ghi tiếp.
 *
 * Trước khi có đường này, đường ghi tiếp chỉ tồn tại trên màn kết quả ngay sau
 * commit. Refresh hay đóng tab là lô kẹt: backend vẫn nhận `confirmed_rows`
 * nhưng giao diện không còn chỗ nào gửi chúng.
 *
 * Ca ở đây canh bốn tính chất mà một bản vá "cho có" sẽ làm hỏng đúng theo thứ
 * tự đó:
 *
 * 1. phiếu lấy bằng lời gọi API TRỰC TIẾP mỗi lần mở, không qua cache;
 * 2. thiếu phiếu ⇒ fail-closed, KHÔNG gửi phần còn lại;
 * 3. double-click chỉ sinh MỘT request;
 * 4. gửi đúng phiếu theo từng `row_no`, không phải một cờ cho cả lô.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import userEvent from "@testing-library/user-event"
import { act, render, screen, waitFor } from "@/test/utils/test-utils"

import { ResumeReviewAction } from "./ResumeReviewAction"

const getBatchDetail = vi.fn()
const commitMutate = vi.fn()

vi.mock("@/lib/api/payment-import", () => ({
  paymentImportApi: {
    getBatchDetail: (...a: unknown[]) => getBatchDetail(...a),
  },
}))

vi.mock("@/hooks/finance/usePaymentImport", () => ({
  useCommitPaymentImport: () => ({
    mutate: commitMutate,
    isPending: false,
  }),
}))

vi.mock("./ImportRowsTable", () => ({
  ImportRowsTable: ({ rows }: { rows: Array<{ row_no: number }> }) => (
    <div data-testid="rows">{rows.map((r) => r.row_no).join(",")}</div>
  ),
}))

const toastError = vi.fn()
const toastInfo = vi.fn()
vi.mock("sonner", () => ({
  toast: {
    error: (...a: unknown[]) => toastError(...a),
    info: (...a: unknown[]) => toastInfo(...a),
    success: vi.fn(),
  },
}))

function dongChoSoat(row_no: number, token: string | null) {
  return {
    row_no,
    validation_status: "warned",
    commit_status: "duplicate_review_required",
    review_token: token,
    amount: "1500000.00",
    message: null,
    payment_ids: [],
  }
}

beforeEach(() => {
  getBatchDetail.mockReset()
  commitMutate.mockReset()
  toastError.mockReset()
  toastInfo.mockReset()
})

describe("ResumeReviewAction", () => {
  it("mở lô → gọi detail TRỰC TIẾP rồi gửi đúng phiếu theo từng row_no", async () => {
    getBatchDetail.mockResolvedValue({
      rows: [dongChoSoat(2, "tok-2"), dongChoSoat(5, "tok-5")],
    })
    const user = userEvent.setup()
    render(<ResumeReviewAction batchId={10} reviewRequiredCount={2} />)

    await user.click(screen.getByRole("button", { name: /Ghi tiếp 2 dòng/i }))

    // Phiếu đến từ một lời gọi API mới, KHÔNG từ cache: mỗi lần mở là một lần
    // hỏi lại máy chủ.
    await waitFor(() => expect(getBatchDetail).toHaveBeenCalledWith(10))
    expect(await screen.findByTestId("rows")).toHaveTextContent("2,5")

    await user.click(screen.getByRole("button", { name: /Đã soát — ghi tiếp/i }))

    expect(commitMutate).toHaveBeenCalledTimes(1)
    expect(commitMutate.mock.calls[0][0]).toEqual({
      batchId: 10,
      confirmedRows: [
        { row_no: 2, review_token: "tok-2" },
        { row_no: 5, review_token: "tok-5" },
      ],
    })
  })

  it("một dòng thiếu phiếu ⇒ FAIL-CLOSED, không mở và không gửi phần còn lại", async () => {
    // Đây là chỗ dễ đi sai nhất: lọc bỏ dòng hỏng rồi gửi những dòng còn lại
    // trông như "xử lý được bao nhiêu hay bấy nhiêu", nhưng thực chất là âm
    // thầm bỏ qua đúng dòng người dùng định xử lý.
    getBatchDetail.mockResolvedValue({
      rows: [dongChoSoat(2, "tok-2"), dongChoSoat(5, null)],
    })
    const user = userEvent.setup()
    render(<ResumeReviewAction batchId={11} reviewRequiredCount={2} />)

    await user.click(screen.getByRole("button", { name: /Ghi tiếp 2 dòng/i }))

    await waitFor(() => expect(toastError).toHaveBeenCalled())
    expect(screen.queryByTestId("rows")).not.toBeInTheDocument()
    expect(commitMutate).not.toHaveBeenCalled()
  })

  it("lô không còn dòng chờ soát ⇒ báo và không mở hộp thoại", async () => {
    getBatchDetail.mockResolvedValue({
      rows: [{ ...dongChoSoat(2, "tok-2"), commit_status: "committed" }],
    })
    const user = userEvent.setup()
    render(<ResumeReviewAction batchId={12} reviewRequiredCount={1} />)

    await user.click(screen.getByRole("button", { name: /Ghi tiếp 1 dòng/i }))

    await waitFor(() => expect(toastInfo).toHaveBeenCalled())
    expect(commitMutate).not.toHaveBeenCalled()
  })

  it("double-click lúc đang tải detail chỉ sinh MỘT request", async () => {
    let giai!: (v: unknown) => void
    getBatchDetail.mockReturnValue(new Promise((res) => (giai = res)))
    const user = userEvent.setup()
    render(<ResumeReviewAction batchId={13} reviewRequiredCount={1} />)

    const nut = screen.getByRole("button", { name: /Ghi tiếp 1 dòng/i })
    await user.click(nut)

    // Hàng rào ngăn cú thứ hai là `disabled` trên nút: React đã render lại
    // với `dangTai = true` trước khi cú click sau kịp tới, nên trình duyệt
    // không giao sự kiện cho handler nữa. Khẳng định nó ở đây để ca ĐỎ khi ai
    // đó gỡ `disabled` — nếu chỉ đếm số request thì gỡ hàng rào vẫn xanh.
    //
    // `if (dangBan) return` trong `moVaNapPhieu` là lớp hai và KHÔNG quan sát
    // được từ giao diện; nó cũng không cứu được hai click rơi vào cùng một
    // batch render, vì handler đóng bao trên `dangBan` của lần render trước.
    expect(nut).toBeDisabled()

    await user.click(nut)

    // Giải quyết phiếu BÊN TRONG act: nếu để promise chín sau khi ca kết thúc
    // thì mọi khẳng định dưới đây nói về một lượt tải còn dang dở, và các
    // setState muộn sẽ rơi sang ca kế tiếp.
    await act(async () => {
      giai({ rows: [dongChoSoat(2, "tok-2")] })
    })

    // Chờ UI đạt TRẠNG THÁI CUỐI, không dừng ở giữa vòng đời: hộp thoại đã mở
    // với đúng dòng, và nút đã hết bận (`dangTai` về false ở nhánh finally).
    expect(await screen.findByTestId("rows")).toHaveTextContent("2")
    await waitFor(() => expect(nut).toBeEnabled())

    // Chỉ đến đây "một request" mới là kết luận về TRỌN luồng async.
    expect(getBatchDetail).toHaveBeenCalledTimes(1)
  })

  it("detail lỗi ⇒ báo lỗi, không mở hộp thoại", async () => {
    getBatchDetail.mockRejectedValue(new Error("boom"))
    const user = userEvent.setup()
    render(<ResumeReviewAction batchId={14} reviewRequiredCount={1} />)

    await user.click(screen.getByRole("button", { name: /Ghi tiếp 1 dòng/i }))

    await waitFor(() => expect(toastError).toHaveBeenCalled())
    expect(screen.queryByTestId("rows")).not.toBeInTheDocument()
    expect(commitMutate).not.toHaveBeenCalled()
  })

  it("mở LẠI sau khi đóng phải nạp phiếu MỚI, không dùng phiếu lần trước", async () => {
    // Phiếu nói về một tập ứng viên tại một thời điểm. Giữ lại qua lần mở sau
    // là xin xác nhận cho một câu hỏi khác.
    getBatchDetail
      .mockResolvedValueOnce({ rows: [dongChoSoat(2, "tok-cu")] })
      .mockResolvedValueOnce({ rows: [dongChoSoat(2, "tok-moi")] })
    const user = userEvent.setup()
    render(<ResumeReviewAction batchId={15} reviewRequiredCount={1} />)

    await user.click(screen.getByRole("button", { name: /Ghi tiếp 1 dòng/i }))
    await screen.findByTestId("rows")
    await user.click(screen.getByRole("button", { name: /Để sau/i }))

    await user.click(screen.getByRole("button", { name: /Ghi tiếp 1 dòng/i }))
    await screen.findByTestId("rows")
    await user.click(screen.getByRole("button", { name: /Đã soát — ghi tiếp/i }))

    expect(getBatchDetail).toHaveBeenCalledTimes(2)
    expect(commitMutate.mock.calls[0][0].confirmedRows).toEqual([
      { row_no: 2, review_token: "tok-moi" },
    ])
  })
})
