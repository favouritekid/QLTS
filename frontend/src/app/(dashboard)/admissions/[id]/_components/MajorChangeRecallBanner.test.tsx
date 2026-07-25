/**
 * MajorChangeRecallBanner — hai GIAI ĐOẠN của chu kỳ đổi ngành.
 *
 * BE chỉ đóng dấu "hết hiệu lực" (supersede) giấy báo hiện hành ở bước reprice,
 * tức SAU khi hồ sơ được nộp lại. Ở giai đoạn 1 (admin vừa cho phép đổi ngành,
 * officer chưa nộp lại) giấy cũ VẪN dùng được, và chu kỳ còn có thể bị bỏ dở.
 * Banner nói "hết hiệu lực" lúc đó là thông tin sai gửi tới cả officer lẫn thí
 * sinh — pin bằng test vì đây là nội dung đối ngoại.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { MajorChangeRecallBanner } from "./MajorChangeRecallBanner"

describe("MajorChangeRecallBanner", () => {
  it("cycleOpen=false: không render gì", () => {
    const { container } = render(
      <MajorChangeRecallBanner cycleOpen={false} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("giai đoạn 1 (chưa reprice): KHÔNG nói hết hiệu lực", () => {
    render(<MajorChangeRecallBanner cycleOpen awaitingConfirmation={false} />)
    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent("vẫn còn hiệu lực")
    expect(alert.textContent).not.toMatch(/đã\s+hết hiệu lực/)
    // Câu mẫu cũng phải ở dạng "chờ", không tuyên bố bỏ bản cũ.
    expect(alert.textContent).not.toMatch(/KHÔNG sử dụng bản cũ/)
  })

  it("giai đoạn 2 (đã reprice, chờ kế toán): tuyên bố hết hiệu lực", () => {
    render(<MajorChangeRecallBanner cycleOpen awaitingConfirmation />)
    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent("hết hiệu lực")
    expect(alert).toHaveTextContent("kế toán xác nhận học phí")
  })

  it("tên thí sinh đi vào câu mẫu (giai đoạn 2)", () => {
    render(
      <MajorChangeRecallBanner
        cycleOpen
        awaitingConfirmation
        candidateName="Nguyễn Văn A"
      />,
    )
    expect(screen.getByRole("button")).toHaveTextContent("Copy câu mẫu")
  })
})
