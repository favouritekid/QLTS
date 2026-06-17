import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@/test/utils/test-utils"
import { fireEvent } from "@testing-library/react"
import { AdmissionsStatusTabs } from "./AdmissionsStatusTabs"

const tabs = [
  { key: "all", label: "Tất cả" },
  { key: "pending", label: "Chờ duyệt" },
] as const

describe("AdmissionsStatusTabs", () => {
  it("marks the active tab via aria-selected and shows counts", () => {
    render(
      <AdmissionsStatusTabs
        tabs={tabs}
        activeTab="pending"
        counts={{ all: 10, pending: 3 }}
        onTabClick={vi.fn()}
      />,
    )
    const active = screen.getByRole("tab", { name: /chờ duyệt/i })
    expect(active).toHaveAttribute("aria-selected", "true")
    expect(active).toHaveTextContent("3")
    expect(screen.getByRole("tab", { name: /tất cả/i })).toHaveAttribute("aria-selected", "false")
  })

  it("calls onTabClick with the tab key", () => {
    const onTabClick = vi.fn()
    render(<AdmissionsStatusTabs tabs={tabs} activeTab="all" onTabClick={onTabClick} />)
    fireEvent.click(screen.getByRole("tab", { name: /chờ duyệt/i }))
    expect(onTabClick).toHaveBeenCalledWith("pending")
  })
})
