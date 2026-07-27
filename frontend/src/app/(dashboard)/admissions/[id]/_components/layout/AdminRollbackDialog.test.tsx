/**
 * AdminRollbackDialog — RE-GATE anchor test.
 *
 * Pin: checkbox "Cho phép đổi ngành" KHÔNG được hardcode. Nó phải đến từ
 * capability BE ``permissions.can_request_major_change`` (parent truyền xuống),
 * và mặc định FAIL-CLOSED = false. Hardcode true làm lộ lối vào chết khi feature
 * flag OFF: server trả 400 cho ``allow_major_change=true``, còn người dùng thì
 * tin là chu kỳ đổi ngành đã mở.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { AdminRollbackDialog } from "./AdminRollbackDialog"

vi.mock("@/hooks/admissions", () => ({
  useAdminRollback: () => ({ mutate: vi.fn(), isPending: false }),
}))

// Mock AuditReasonDialog → phơi prop showMajorChangeToggle ra DOM để assert
// pass-through (component thật kéo theo localStorage + Radix Dialog).
vi.mock("@/components/admissions/AuditReasonDialog", () => ({
  AuditReasonDialog: ({
    showMajorChangeToggle,
  }: {
    showMajorChangeToggle?: boolean
  }) => (
    <div
      data-testid="audit-reason-dialog"
      data-major-change-toggle={String(showMajorChangeToggle)}
    />
  ),
  pushRecentReason: vi.fn(),
}))

describe("AdminRollbackDialog — capability gating", () => {
  it("không truyền prop → toggle đổi ngành TẮT (fail-closed)", () => {
    render(
      <AdminRollbackDialog profileId={1} open onOpenChange={vi.fn()} />,
    )
    expect(screen.getByTestId("audit-reason-dialog")).toHaveAttribute(
      "data-major-change-toggle",
      "false",
    )
  })

  it("capability true → toggle đổi ngành BẬT", () => {
    render(
      <AdminRollbackDialog
        profileId={1}
        open
        onOpenChange={vi.fn()}
        showMajorChangeToggle
      />,
    )
    expect(screen.getByTestId("audit-reason-dialog")).toHaveAttribute(
      "data-major-change-toggle",
      "true",
    )
  })
})
