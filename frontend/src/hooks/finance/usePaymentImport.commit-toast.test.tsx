/**
 * Lượt ghi tiền lô trả **200** cho ba kết cục khác hẳn nhau, và trước đây cả ba
 * đi chung một `toast.success`. Bộ này khoá việc mỗi kết cục nói đúng nghĩa của
 * nó:
 *
 *   1. ghi trọn                    → thành công (dấu ✓ xanh);
 *   2. còn dòng chờ xác nhận       → CẢNH BÁO, việc chưa xong;
 *   3. phiếu vừa gửi bị từ chối    → CẢNH BÁO nêu SỐ dòng chưa ghi được,
 *                                    kèm phần đã vào sổ của chính lượt ấy.
 *
 * Ca 3 là ca đã gặp thật khi smoke: người dùng bấm "Đã soát — ghi tiếp", không
 * đồng nào vào sổ, mà màn hình hiện dấu tích xanh "Đã ghi 0 dòng".
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { QueryClientProvider } from "@tanstack/react-query"

import { createTestQueryClient } from "@/test/utils/test-utils"
import { useCommitPaymentImport } from "./usePaymentImport"

const commitApi = vi.fn()
vi.mock("@/lib/api/payment-import", () => ({
  paymentImportApi: {
    commit: (...a: unknown[]) => commitApi(...a),
  },
}))

const toastSuccess = vi.fn()
const toastWarning = vi.fn()
const toastError = vi.fn()
vi.mock("sonner", () => ({
  toast: {
    success: (...a: unknown[]) => toastSuccess(...a),
    warning: (...a: unknown[]) => toastWarning(...a),
    error: (...a: unknown[]) => toastError(...a),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={createTestQueryClient()}>
      {children}
    </QueryClientProvider>
  )
}

function ketQua(over: Record<string, unknown> = {}) {
  return {
    batch_id: 7,
    status: "preview",
    committed_count: 0,
    failed_count: 0,
    review_required_count: 0,
    payment_count: 0,
    total_amount: "0",
    rows: [],
    ...over,
  }
}

function dongChoSoat(row_no: number, token: string) {
  return {
    row_no,
    validation_status: "warned",
    commit_status: "duplicate_review_required",
    review_token: token,
    allocations: [],
  }
}

beforeEach(() => {
  commitApi.mockReset()
  toastSuccess.mockReset()
  toastWarning.mockReset()
  toastError.mockReset()
})

describe("useCommitPaymentImport — toast nói đúng nghĩa từng kết cục", () => {
  it("ghi trọn ⇒ báo thành công", async () => {
    commitApi.mockResolvedValue(
      ketQua({ status: "committed", committed_count: 2, payment_count: 2 }),
    )
    const { result } = renderHook(() => useCommitPaymentImport(), { wrapper })

    result.current.mutate({ batchId: 7 })

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledTimes(1))
    expect(toastWarning).not.toHaveBeenCalled()
  })

  it("còn dòng chờ xác nhận ⇒ CẢNH BÁO, không phải thành công", async () => {
    commitApi.mockResolvedValue(
      ketQua({
        committed_count: 1,
        payment_count: 1,
        review_required_count: 1,
        rows: [dongChoSoat(3, "phieu")],
      }),
    )
    const { result } = renderHook(() => useCommitPaymentImport(), { wrapper })

    result.current.mutate({ batchId: 7 })

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1))
    expect(
      toastSuccess,
      "việc chưa xong thì không được mang dấu ✓ xanh",
    ).not.toHaveBeenCalled()
  })

  it("gửi phiếu mà dòng VẪN bị giữ ⇒ cảnh báo nêu rõ tập đã đổi", async () => {
    // 0 dòng vào sổ, và dòng vừa xác nhận vẫn nằm nguyên ở trạng thái chờ.
    commitApi.mockResolvedValue(
      ketQua({
        review_required_count: 1,
        rows: [dongChoSoat(3, "phieu-moi")],
      }),
    )
    const { result } = renderHook(() => useCommitPaymentImport(), { wrapper })

    result.current.mutate({
      batchId: 7,
      confirmedRows: [{ row_no: 3, review_token: "phieu-cu" }],
    })

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1))
    expect(toastWarning.mock.calls[0][0]).toMatch(
      /1 dòng vừa xác nhận chưa được ghi vì phiếu xác nhận không còn hiệu lực/i,
    )
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it("dòng chờ soát KHÁC dòng vừa gửi phiếu ⇒ vẫn chỉ là cảnh báo thường", async () => {
    // Phiếu của dòng 3 ghi được; dòng 5 là dòng khác, chưa ai xác nhận. Đây
    // KHÔNG phải ca tập đã đổi — nói vậy là dạy người dùng bỏ qua câu cảnh báo
    // thật ở ca kia.
    commitApi.mockResolvedValue(
      ketQua({
        committed_count: 1,
        payment_count: 1,
        review_required_count: 1,
        rows: [dongChoSoat(5, "phieu-dong-5")],
      }),
    )
    const { result } = renderHook(() => useCommitPaymentImport(), { wrapper })

    result.current.mutate({
      batchId: 7,
      confirmedRows: [{ row_no: 3, review_token: "phieu-dong-3" }],
    })

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1))
    expect(toastWarning.mock.calls[0][0]).not.toMatch(/không còn hiệu lực/i)
    expect(toastSuccess).not.toHaveBeenCalled()
  })

  it("HỖN HỢP: một dòng ghi được + một phiếu bị từ chối ⇒ nói cả hai con số", async () => {
    // `committed_count` đếm riêng LƯỢT này, nên một lần gửi hai phiếu có thể
    // ghi được dòng 3 và từ chối phiếu cũ của dòng 5. Câu "chưa dòng nào được
    // ghi" ở bản trước tự mâu thuẫn với chính "Đã ghi 1 dòng" ngay sau nó.
    commitApi.mockResolvedValue(
      ketQua({
        committed_count: 1,
        payment_count: 1,
        review_required_count: 1,
        rows: [
          { row_no: 3, validation_status: "warned", commit_status: "committed" },
          dongChoSoat(5, "phieu-moi-dong-5"),
        ],
      }),
    )
    const { result } = renderHook(() => useCommitPaymentImport(), { wrapper })

    result.current.mutate({
      batchId: 7,
      confirmedRows: [
        { row_no: 3, review_token: "phieu-dong-3" },
        { row_no: 5, review_token: "phieu-cu-dong-5" },
      ],
    })

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1))
    const cau = toastWarning.mock.calls[0][0] as string

    // Đúng MỘT dòng bị từ chối — không phải cả hai dòng vừa gửi.
    expect(cau).toMatch(/^1 dòng vừa xác nhận chưa được ghi/i)
    // Và phải nói ra phần đã vào sổ: giấu nó đi là để kế toán tưởng lượt này
    // trắng tay rồi gửi lại lần nữa.
    expect(cau).toMatch(/Đã ghi 1 dòng/i)
    expect(cau).toMatch(/1 dòng chờ xác nhận trùng/i)
    expect(cau, "không được nói trống 'chưa dòng nào'").not.toMatch(
      /chưa dòng nào/i,
    )
    expect(toastSuccess).not.toHaveBeenCalled()
  })
})
