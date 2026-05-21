/**
 * Combobox — Commit 5 ariaLabel prop anchor.
 *
 * Pin: trigger button có aria-label rõ ràng để screen reader đọc đúng
 * khi placeholder không đủ context (vd 3 combobox tỉnh/quận/xã trên
 * cùng form).
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"

import { Combobox } from "./combobox"

describe("Combobox — accessible name (Commit 5)", () => {
  it("uses ariaLabel prop khi truyền", () => {
    render(
      <Combobox
        value=""
        onChange={vi.fn()}
        options={[{ value: "VN", label: "Việt Nam" }]}
        placeholder="Chọn..."
        ariaLabel="Chọn quốc tịch"
      />
    )
    expect(screen.getByRole("combobox", { name: "Chọn quốc tịch" })).toBeInTheDocument()
  })

  it("fallback placeholder làm aria-label khi không truyền ariaLabel", () => {
    render(
      <Combobox
        value=""
        onChange={vi.fn()}
        options={[{ value: "VN", label: "Việt Nam" }]}
        placeholder="Chọn quốc tịch (fallback)"
      />
    )
    expect(
      screen.getByRole("combobox", { name: "Chọn quốc tịch (fallback)" })
    ).toBeInTheDocument()
  })
})
