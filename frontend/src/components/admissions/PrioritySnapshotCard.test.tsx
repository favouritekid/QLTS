/**
 * PrioritySnapshotCard tests — Phase E wireframe combined KV+UT+TOTAL layout.
 *
 * Covers:
 * - Frozen vs live preview header text
 * - KV badge rendering (KV1/KV2-NT/KV2/KV3)
 * - Combined "KV + UT = TỔNG" badge layout
 * - Inline summary rows (Cách tính KV / Quy tắc / UT áp dụng) always visible
 * - Frozen footer (✅ Đã chốt + ℹ️ Không thể thay đổi) — universal, not just override
 * - Manual override audit row (E.2 hook ready)
 * - Empty state + loading
 * - UT verification status badge (potential vs verified)
 * - formatBonus helper edge cases
 */
import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { PrioritySnapshotCard, formatBonus } from "./PrioritySnapshotCard"
import type { UtBreakdown } from "@/lib/api/priority-kv"

describe("formatBonus", () => {
  it("formats positive value with explicit + and Vietnamese comma", () => {
    expect(formatBonus(0.75)).toBe("+0,75đ")
    expect(formatBonus(1)).toBe("+1,00đ")
    expect(formatBonus(2)).toBe("+2,00đ")
  })

  it("returns '0đ' for zero", () => {
    expect(formatBonus(0)).toBe("0đ")
  })

  it("returns em-dash for null/undefined", () => {
    expect(formatBonus(null)).toBe("—")
    expect(formatBonus(undefined)).toBe("—")
  })

  it("handles negative values", () => {
    expect(formatBonus(-0.25)).toBe("-0,25đ")
  })
})

describe("PrioritySnapshotCard — header state", () => {
  it("renders 'tạm tính' header when not frozen", () => {
    render(<PrioritySnapshotCard kv="KV1" frozen={false} />)
    expect(screen.getByText(/Điểm cộng ưu tiên \(tạm tính\)/i)).toBeInTheDocument()
  })

  it("renders 'đã chốt' header when frozen", () => {
    render(<PrioritySnapshotCard kv="KV1" frozen={true} />)
    expect(screen.getByText(/Điểm cộng ưu tiên \(đã chốt\)/i)).toBeInTheDocument()
  })
})

describe("PrioritySnapshotCard — KV badges", () => {
  it("renders KV1 badge with +0,75đ", () => {
    render(<PrioritySnapshotCard kv="KV1" />)
    expect(screen.getByTestId("priority-snapshot-kv-badge")).toHaveTextContent(/KV1.*0,75đ/)
  })

  it("renders KV2-NT badge with +0,50đ", () => {
    render(<PrioritySnapshotCard kv="KV2-NT" />)
    expect(screen.getByTestId("priority-snapshot-kv-badge")).toHaveTextContent(/KV2-NT.*0,50đ/)
  })

  it("renders KV3 badge with 'không cộng'", () => {
    render(<PrioritySnapshotCard kv="KV3" />)
    expect(screen.getByTestId("priority-snapshot-kv-badge")).toHaveTextContent(/KV3.*không cộng/i)
  })

  it("shows 'khu vực' subtitle under KV badge", () => {
    render(<PrioritySnapshotCard kv="KV1" />)
    expect(screen.getByText(/khu vực/)).toBeInTheDocument()
  })
})

describe("PrioritySnapshotCard — UT + TOTAL combined layout", () => {
  const utBreakdown: UtBreakdown = {
    codes_submitted: ["04"],
    applied_code_potential: "04",
    applied_rate_potential: "1.00",
    verified_codes: ["04"],
    applied_code_verified: "04",
    applied_rate_verified: "1.00",
  }

  it("renders UT badge when codes submitted", () => {
    render(
      <PrioritySnapshotCard
        kv="KV1"
        utBreakdown={utBreakdown}
        objectBonusPotential={1.0}
        totalBonusPotential={1.75}
      />,
    )
    expect(screen.getByTestId("priority-snapshot-ut-badge")).toHaveTextContent(/UT04.*\+1,00đ/)
    expect(screen.getByText(/đối tượng/i)).toBeInTheDocument()
  })

  it("renders TỔNG badge when KV + UT both present", () => {
    render(
      <PrioritySnapshotCard
        kv="KV1"
        utBreakdown={utBreakdown}
        objectBonusPotential={1.0}
        totalBonusPotential={1.75}
      />,
    )
    expect(screen.getByTestId("priority-snapshot-total-badge")).toHaveTextContent(/TỔNG.*\+1,75đ/)
  })

  it("does NOT render TỔNG badge when only KV (no UT)", () => {
    render(<PrioritySnapshotCard kv="KV1" />)
    expect(screen.queryByTestId("priority-snapshot-total-badge")).not.toBeInTheDocument()
  })

  it("shows verified status badge when all UT codes verified", () => {
    render(
      <PrioritySnapshotCard
        kv="KV1"
        utBreakdown={utBreakdown}
      />,
    )
    expect(screen.getByText(/Tất cả diện đã xác minh/i)).toBeInTheDocument()
  })

  it("shows pending status when no UT codes verified", () => {
    const pendingBreakdown: UtBreakdown = {
      ...utBreakdown,
      verified_codes: [],
      applied_code_verified: null,
      applied_rate_verified: null,
    }
    render(
      <PrioritySnapshotCard
        kv="KV1"
        utBreakdown={pendingBreakdown}
      />,
    )
    expect(screen.getByText(/1 diện chờ xác minh/i)).toBeInTheDocument()
  })

  it("shows partial verified ratio", () => {
    const partialBreakdown: UtBreakdown = {
      codes_submitted: ["04", "06"],
      applied_code_potential: "04",
      applied_rate_potential: "1.00",
      verified_codes: ["04"],
      applied_code_verified: "04",
      applied_rate_verified: "1.00",
    }
    render(
      <PrioritySnapshotCard
        kv="KV1"
        utBreakdown={partialBreakdown}
      />,
    )
    expect(screen.getByText(/1\/2 diện đã xác minh/i)).toBeInTheDocument()
  })
})

describe("PrioritySnapshotCard — inline summary rows (always visible)", () => {
  it("renders Cách tính KV row when pathway present", () => {
    render(
      <PrioritySnapshotCard kv="KV1" pathway="thpt_multi_school" />,
    )
    expect(screen.getByTestId("priority-snapshot-summary")).toHaveTextContent(
      /Cách tính KV.*Theo lịch sử học các trường THPT/i,
    )
  })

  it("renders Quy tắc row when ruleApplied present", () => {
    render(
      <PrioritySnapshotCard kv="KV1" ruleApplied="longest_duration" />,
    )
    expect(screen.getByTestId("priority-snapshot-summary")).toHaveTextContent(
      /Quy tắc.*Trường học lâu nhất/i,
    )
  })

  it("renders UT áp dụng row when UT codes present", () => {
    const utBreakdown: UtBreakdown = {
      codes_submitted: ["04", "06"],
      applied_code_potential: "04",
      applied_rate_potential: "1.00",
      verified_codes: [],
      applied_code_verified: null,
      applied_rate_verified: null,
    }
    render(
      <PrioritySnapshotCard
        kv="KV1"
        utBreakdown={utBreakdown}
      />,
    )
    expect(screen.getByTestId("priority-snapshot-summary")).toHaveTextContent(
      /UT áp dụng.*UT04.*chọn diện CAO NHẤT trong 2 diện/i,
    )
  })
})

describe("PrioritySnapshotCard — frozen footer (universal)", () => {
  it("shows ✅ Đã chốt + ℹ️ Không thể thay đổi when frozen with metadata", () => {
    render(
      <PrioritySnapshotCard
        kv="KV1"
        frozen={true}
        frozenAt="2026-05-19T02:15:00Z"
        resolvedBy="@candidate"
      />,
    )
    const footer = screen.getByTestId("priority-snapshot-frozen-footer")
    expect(footer).toHaveTextContent(/Đã chốt khi nộp hồ sơ.*@candidate/i)
    expect(footer).toHaveTextContent(
      /Không thể thay đổi.*chỉ admin có thể override/i,
    )
  })

  it("does NOT show frozen footer when not frozen", () => {
    render(<PrioritySnapshotCard kv="KV1" frozen={false} />)
    expect(
      screen.queryByTestId("priority-snapshot-frozen-footer"),
    ).not.toBeInTheDocument()
  })
})

describe("PrioritySnapshotCard — manual override audit (E.2)", () => {
  it("renders override audit when ruleApplied='manual_override'", () => {
    render(
      <PrioritySnapshotCard
        kv="KV2-NT"
        ruleApplied="manual_override"
        manualOverrideBy="@admin1"
        manualOverrideAt="2026-05-19T07:32:00Z"
        manualOverrideReason="Hồ sơ cư trú thực tế tại P. Giảng Võ"
      />,
    )
    const override = screen.getByTestId("priority-snapshot-override")
    expect(override).toHaveTextContent(/Cán bộ ấn định thủ công.*@admin1/i)
    expect(override).toHaveTextContent(/Hồ sơ cư trú thực tế/i)
  })

  it("does NOT show override audit when ruleApplied != 'manual_override'", () => {
    render(
      <PrioritySnapshotCard
        kv="KV1"
        ruleApplied="longest_duration"
        manualOverrideBy="@admin1"
      />,
    )
    expect(
      screen.queryByTestId("priority-snapshot-override"),
    ).not.toBeInTheDocument()
  })
})

describe("PrioritySnapshotCard — empty / loading", () => {
  it("shows spinner when loading + no KV + not frozen", () => {
    render(<PrioritySnapshotCard kv={null} loading={true} />)
    expect(screen.getByTestId("priority-snapshot-loading")).toBeInTheDocument()
  })

  it("shows empty state when no KV + not loading", () => {
    render(<PrioritySnapshotCard kv={null} loading={false} />)
    expect(screen.getByTestId("priority-snapshot-empty")).toBeInTheDocument()
    expect(screen.getByText(/Chưa đủ thông tin để tính điểm ưu tiên/i)).toBeInTheDocument()
  })

  it("localizes failure reason", () => {
    render(<PrioritySnapshotCard kv={null} reason="cultural_not_set" />)
    expect(screen.getByText(/Chưa khai trình độ văn hóa/i)).toBeInTheDocument()
  })
})

describe("PrioritySnapshotCard — JSONB breakdown disclosure", () => {
  it("renders breakdown disclosure when breakdown + kv present", () => {
    render(
      <PrioritySnapshotCard
        kv="KV1"
        breakdown={{ matched_school: "THPT Buôn Ma Thuột" }}
      />,
    )
    expect(screen.getByTestId("priority-snapshot-json")).toBeInTheDocument()
  })

  it("hides breakdown disclosure when no kv", () => {
    render(
      <PrioritySnapshotCard
        kv={null}
        breakdown={{ matched_school: "X" }}
      />,
    )
    expect(screen.queryByTestId("priority-snapshot-json")).not.toBeInTheDocument()
  })
})
