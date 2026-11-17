/**
 * GĐ1b §4.7 / §7 — nút theo CỜ MÁY CHỦ: mỗi nút hiện khi và chỉ khi đúng cờ của nó bật; thiếu định danh / phiên bản ⇒
 * không nút nào (fail-closed). Không suy theo vai (quét tĩnh khoá thêm).
 */
import { describe, expect, it } from "vitest"
import { screen } from "@testing-library/react"

import { DocumentReviewActions } from "./DocumentReviewActions"
import { giayGia, renderWithClient } from "./test-helpers"

const NUT = {
  can_verify: /^Duyệt giấy/,
  can_reject: /^Từ chối giấy/,
  can_reset: /^Đặt lại giấy/,
  can_view_history: /^Lịch sử giấy/,
} as const

function nutDangHien(): string[] {
  return (Object.keys(NUT) as (keyof typeof NUT)[]).filter((k) => screen.queryByRole("button", { name: NUT[k] }) !== null)
}

describe("DocumentReviewActions — nút theo cờ máy chủ", () => {
  it("mọi cờ tắt ⇒ không có nút nào", () => {
    renderWithClient(<DocumentReviewActions profileId={5} document={giayGia()} />)
    expect(screen.queryAllByRole("button")).toHaveLength(0)
  })

  it.each(Object.keys(NUT) as (keyof typeof NUT)[])("chỉ bật %s ⇒ chỉ đúng nút đó", (co) => {
    renderWithClient(<DocumentReviewActions profileId={5} document={giayGia({ [co]: true })} />)
    expect(nutDangHien()).toEqual([co])
  })

  it("requires_ack ⇒ nút ghi 'Duyệt (cam kết)'", () => {
    renderWithClient(<DocumentReviewActions profileId={5} document={giayGia({ can_verify: true, requires_ack: true })} />)
    expect(screen.getByRole("button", { name: /^Duyệt giấy/ })).toHaveTextContent("Duyệt (cam kết)")
  })

  it("verify_block_reason own_submission ⇒ hiện lý do khoá, không nút Duyệt", () => {
    renderWithClient(
      <DocumentReviewActions profileId={5} document={giayGia({ verify_block_reason: "own_submission" })} />,
    )
    expect(screen.getByTestId("ly-do-khoa-duyet")).toHaveTextContent("không tự duyệt")
    expect(screen.queryByRole("button", { name: /^Duyệt giấy/ })).toBeNull()
  })

  it("verify_block_reason not_permitted ⇒ không nói gì trên từng giấy", () => {
    renderWithClient(<DocumentReviewActions profileId={5} document={giayGia({ verify_block_reason: "not_permitted" })} />)
    expect(screen.queryByTestId("ly-do-khoa-duyet")).toBeNull()
  })

  it("cờ bật nhưng thiếu row_version ⇒ KHÔNG nút nào + báo thiếu định danh", () => {
    const g = giayGia({ can_verify: true, can_reset: true, can_view_history: true })
    delete g.row_version
    renderWithClient(<DocumentReviewActions profileId={5} document={g} />)
    expect(screen.queryAllByRole("button")).toHaveLength(0)
    expect(screen.getByTestId("giay-thieu-dinh-danh")).toBeInTheDocument()
  })

  it("giấy chưa có dòng (định danh null, mọi cờ tắt) ⇒ im lặng", () => {
    const { container } = renderWithClient(
      <DocumentReviewActions profileId={5} document={giayGia({ document_row_id: null, row_version: null })} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
