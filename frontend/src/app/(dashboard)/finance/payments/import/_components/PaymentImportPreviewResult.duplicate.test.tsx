/**
 * Đường thoát cho dòng bị hàng rào nghi trùng giữ lại.
 *
 * Máy chủ cố ý KHÔNG đóng lô khi còn dòng như vậy, để lượt gửi lại kèm xác
 * nhận còn cứu được chúng. Nhưng nếu giao diện không có chỗ bật cờ đó thì cả
 * cơ chế bên máy chủ là vô dụng: lô nằm im ở trạng thái xem trước, còn tiền kế
 * toán đã thu thật thì không có đường nào vào sổ.
 *
 * Ba điều bộ test này khoá:
 *   1. có dòng nghi trùng ⇒ HIỆN nút ghi tiếp;
 *   2. bấm nút ⇒ gửi `confirmDuplicates: true` (không phải một lượt commit thường);
 *   3. dòng hỏng vì lý do khác (số dư đổi) ⇒ KHÔNG hiện nút — chúng ghi lại
 *      cũng vẫn hỏng, mời bấm là mời đâm vào tường.
 */
import { describe, expect, it, vi, beforeEach } from "vitest"
import userEvent from "@testing-library/user-event"
import { render, screen } from "@/test/utils/test-utils"

import { PaymentImportPreviewResult } from "./PaymentImportPreviewResult"
import type {
  PaymentImportCommit,
  PaymentImportPreview,
} from "@/lib/zod/payment-import"

const commitMutate = vi.fn()

vi.mock("@/hooks/finance/usePaymentImport", () => ({
  useCommitPaymentImport: () => ({
    mutate: commitMutate,
    isPending: false,
  }),
  useDownloadPaymentImportResult: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}))

const PREVIEW: PaymentImportPreview = {
  batch_id: 7,
  academic_year: 2026,
  semester_no: 1,
  file_name: "thu.xlsx",
  status: "preview",
  row_count: 2,
  matched_count: 2,
  warned_count: 0,
  failed_count: 0,
  total_amount: "10000000",
  rows: [],
}

/** Kết quả commit có 1 dòng bị hàng rào trùng giữ lại. */
const KET_QUA_CO_NGHI_TRUNG: PaymentImportCommit = {
  batch_id: 7,
  status: "preview",
  committed_count: 1,
  failed_count: 1,
  payment_count: 1,
  total_amount: "5000000",
  rows: [
    {
      row_no: 3,
      status: "error",
      message:
        "nghi trùng với 1 phiếu đã ghi cho cùng khoản phí — cùng số tiền, " +
        "lệch không quá 3 ngày (#41).",
      allocations: [],
    },
  ],
}

/** Kết quả commit chỉ có dòng hỏng thật. */
const KET_QUA_HONG_THAT: PaymentImportCommit = {
  ...KET_QUA_CO_NGHI_TRUNG,
  status: "committed",
  rows: [
    {
      row_no: 3,
      status: "error",
      message: "không còn đợt hóa đơn payable (đã thu đủ / đổi giữa 2 pha)",
      allocations: [],
    },
  ],
}

/** Radix + jsdom: thiếu Pointer Capture thì AlertDialog không mở. */
function installPointerStubs() {
  Element.prototype.scrollIntoView = function scrollIntoView() {}
  Element.prototype.hasPointerCapture = function hasPointerCapture() {
    return false
  }
  Element.prototype.setPointerCapture = function setPointerCapture() {}
  Element.prototype.releasePointerCapture = function releasePointerCapture() {}
}

async function commitRoi(ketQua: PaymentImportCommit) {
  const user = userEvent.setup()
  render(
    <PaymentImportPreviewResult
      preview={PREVIEW}
      onCommitted={vi.fn()}
      onDiscard={vi.fn()}
    />,
  )
  // Nút mở hộp thoại mang kèm số dòng ("Ghi tiền (2 dòng)"); nút xác nhận bên
  // trong hộp thoại chỉ có đúng "Ghi tiền". Phân biệt bằng neo đầu/cuối, không
  // dùng /ghi tiền/i cho cả hai.
  await user.click(screen.getByRole("button", { name: /^ghi tiền \(/i }))
  await user.click(await screen.findByRole("button", { name: /^ghi tiền$/i }))

  // Hook đã bị mock nên không có request thật; lấy callback onSuccess mà
  // component truyền vào rồi gọi tay để dựng màn kết quả.
  const onSuccess = commitMutate.mock.calls.at(-1)?.[1]?.onSuccess
  expect(onSuccess, "component phải truyền onSuccess cho mutate").toBeTypeOf(
    "function",
  )
  onSuccess(ketQua)

  // Chốt rằng màn kết quả ĐÃ dựng. Không có câu này thì ca "không hiện nút"
  // vẫn xanh cả khi component chẳng render gì — tức là xanh vì lý do sai.
  expect(await screen.findByText(/kết quả ghi tiền/i)).toBeInTheDocument()
  return user
}

beforeEach(() => {
  commitMutate.mockClear()
  installPointerStubs()
})

describe("PaymentImportPreviewResult — dòng nghi trùng", () => {
  it("có dòng nghi trùng thì hiện đường ghi tiếp", async () => {
    await commitRoi(KET_QUA_CO_NGHI_TRUNG)
    expect(
      await screen.findByText(/bị giữ lại vì nghi trùng phiếu đã ghi/i),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /đã soát — ghi tiếp/i }),
    ).toBeInTheDocument()
  })

  it("bấm ghi tiếp thì gửi kèm xác nhận, không phải commit thường", async () => {
    const user = await commitRoi(KET_QUA_CO_NGHI_TRUNG)
    commitMutate.mockClear()

    await user.click(screen.getByRole("button", { name: /đã soát — ghi tiếp/i }))

    expect(commitMutate).toHaveBeenCalledTimes(1)
    expect(commitMutate.mock.calls[0][0]).toEqual({
      batchId: 7,
      confirmDuplicates: true,
    })
  })

  it("dòng hỏng vì lý do khác thì KHÔNG mời bấm ghi tiếp", async () => {
    await commitRoi(KET_QUA_HONG_THAT)
    expect(
      screen.queryByText(/bị giữ lại vì nghi trùng phiếu đã ghi/i),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /đã soát — ghi tiếp/i }),
    ).not.toBeInTheDocument()
  })
})
