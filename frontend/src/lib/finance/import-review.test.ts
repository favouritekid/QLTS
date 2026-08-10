/**
 * Phép đo "phiếu vừa gửi có bị từ chối không" — ba nơi dùng chung nó (hook
 * toast, màn kết quả, đường mở lại từ Lịch sử lô), nên nó phải đọc theo
 * `row_no` của chính lượt gửi chứ không theo con số đếm.
 */
import { describe, it, expect } from "vitest"

import { coPhieuHetHieuLuc, dongPhieuHetHieuLuc } from "./import-review"

const cho = (row_no: number) => ({
  row_no,
  commit_status: "duplicate_review_required",
})
const xong = (row_no: number) => ({ row_no, commit_status: "committed" })

describe("dongPhieuHetHieuLuc", () => {
  it("dòng đã gửi phiếu mà vẫn bị giữ ⇒ nêu đúng dòng đó", () => {
    expect(dongPhieuHetHieuLuc([{ row_no: 3 }], [cho(3)])).toEqual([3])
  })

  it("dòng đã gửi phiếu và vào sổ ⇒ rỗng", () => {
    expect(dongPhieuHetHieuLuc([{ row_no: 3 }], [xong(3)])).toEqual([])
  })

  it("KHÔNG gửi phiếu nào ⇒ rỗng, dù lô còn dòng chờ soát", () => {
    // Lượt commit đầu tiên có dòng bị giữ là chuyện bình thường — gọi nó là
    // "phiếu hết hiệu lực" thì mọi lô nghi trùng đều hiện cảnh báo sai.
    expect(dongPhieuHetHieuLuc(undefined, [cho(3)])).toEqual([])
    expect(dongPhieuHetHieuLuc([], [cho(3)])).toEqual([])
  })

  it("dòng chờ soát KHÁC dòng vừa gửi ⇒ rỗng", () => {
    expect(dongPhieuHetHieuLuc([{ row_no: 3 }], [xong(3), cho(5)])).toEqual([])
  })

  it("nhiều dòng bị từ chối ⇒ nêu đủ, theo thứ tự dòng", () => {
    expect(
      dongPhieuHetHieuLuc([{ row_no: 5 }, { row_no: 2 }], [cho(5), cho(2)]),
    ).toEqual([2, 5])
  })

  it("rows rỗng/thiếu ⇒ rỗng, không ném", () => {
    expect(dongPhieuHetHieuLuc([{ row_no: 3 }], [])).toEqual([])
    expect(dongPhieuHetHieuLuc([{ row_no: 3 }], undefined)).toEqual([])
  })
})

describe("coPhieuHetHieuLuc", () => {
  it("là vị từ của cùng phép đo", () => {
    expect(coPhieuHetHieuLuc([{ row_no: 3 }], [cho(3)])).toBe(true)
    expect(coPhieuHetHieuLuc([{ row_no: 3 }], [xong(3)])).toBe(false)
    expect(coPhieuHetHieuLuc(undefined, [cho(3)])).toBe(false)
  })
})
