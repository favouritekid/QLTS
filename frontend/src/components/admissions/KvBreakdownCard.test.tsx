/**
 * KvBreakdownCard tests — Phase E.1 extraction smoke + display states.
 */
import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { KvBreakdownCard } from "./KvBreakdownCard"

describe("KvBreakdownCard", () => {
  // -------------------------------------------------------------------------
  // Display states — frozen vs live preview
  // -------------------------------------------------------------------------

  it("renders 'tạm tính' label when not frozen", () => {
    render(<KvBreakdownCard kv="KV1" frozen={false} />)
    expect(screen.getByText(/tạm tính/i)).toBeInTheDocument()
    expect(screen.queryByText(/đã chốt/i)).not.toBeInTheDocument()
  })

  it("renders 'đã chốt' label + lock icon when frozen", () => {
    render(<KvBreakdownCard kv="KV1" frozen={true} />)
    expect(screen.getByText(/khu vực ưu tiên \(đã chốt\)/i)).toBeInTheDocument()
    // 2 matches expected: header text + "Đã chốt" inline badge — ensure at least one
    expect(screen.getAllByText(/đã chốt/i).length).toBeGreaterThanOrEqual(1)
  })

  // -------------------------------------------------------------------------
  // KV badge rendering — covers KV1/KV2-NT/KV2/KV3
  // -------------------------------------------------------------------------

  it("renders KV1 badge with +0,75đ label", () => {
    render(<KvBreakdownCard kv="KV1" />)
    expect(screen.getByText(/KV1.*0,75đ/)).toBeInTheDocument()
  })

  it("renders KV2-NT badge with +0,50đ label", () => {
    render(<KvBreakdownCard kv="KV2-NT" />)
    expect(screen.getByText(/KV2-NT.*0,50đ/)).toBeInTheDocument()
  })

  it("renders KV2 badge with +0,25đ label", () => {
    render(<KvBreakdownCard kv="KV2" />)
    expect(screen.getByText(/KV2.*0,25đ/)).toBeInTheDocument()
  })

  it("renders KV3 badge with 'không cộng' label", () => {
    render(<KvBreakdownCard kv="KV3" />)
    expect(screen.getByText(/KV3.*không cộng/i)).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Empty / loading states
  // -------------------------------------------------------------------------

  it("shows loading spinner when loading=true and no KV", () => {
    render(<KvBreakdownCard kv={null} loading={true} />)
    expect(screen.getByTestId("kv-breakdown-loading")).toBeInTheDocument()
    expect(screen.getByText(/đang tính/i)).toBeInTheDocument()
  })

  it("shows empty state hint when no KV + not loading", () => {
    render(<KvBreakdownCard kv={null} loading={false} />)
    expect(screen.getByTestId("kv-breakdown-empty")).toBeInTheDocument()
    expect(screen.getByText(/chưa đủ thông tin/i)).toBeInTheDocument()
  })

  it("localizes failure reason via REASON_VI", () => {
    render(<KvBreakdownCard kv={null} reason="cultural_not_set" />)
    expect(screen.getByText(/chưa khai trình độ văn hóa/i)).toBeInTheDocument()
  })

  // Đoàn 3c (24-11) — Codex L5 NỢ-1 (`KvBreakdownCard.tsx:152`): mã dừng L3 của THPT hiện câu, không hiện mã thô.
  it("mã dừng history_entries_inconsistent hiện câu tiếng Việt, không hiện mã", () => {
    render(<KvBreakdownCard kv={null} reason="history_entries_inconsistent" />)
    const o = screen.getByTestId("kv-breakdown-empty")
    expect(o.textContent).toContain("“Lớp cuối” không phải 10, 11 hay 12")
    expect(o.textContent).not.toContain("history_entries_inconsistent")
  })

  it("renders parent-supplied emptyStateHint slot", () => {
    render(
      <KvBreakdownCard
        kv={null}
        emptyStateHint={<p>Custom hint from parent</p>}
      />,
    )
    expect(screen.getByText(/custom hint from parent/i)).toBeInTheDocument()
  })

  it("shows manual override required warning when requiresManual=true", () => {
    render(<KvBreakdownCard kv={null} requiresManual={true} />)
    expect(screen.getByText(/cần cán bộ xem xét/i)).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Pathway + rule labels (localized via PATHWAY_LABEL_VI / RULE_LABEL_VI)
  // -------------------------------------------------------------------------

  it("displays pathway + rule labels in Vietnamese", () => {
    render(
      <KvBreakdownCard
        kv="KV1"
        pathway="thpt_multi_school"
        ruleApplied="longest_duration"
      />,
    )
    expect(screen.getByText(/lịch sử học các trường THPT/i)).toBeInTheDocument()
    expect(screen.getByText(/trường học lâu nhất/i)).toBeInTheDocument()
  })

  // Đoàn 3c (24-11) — Codex L5 NỢ-1 (`KvBreakdownCard.tsx:173,179`): mã đường tính HIỆN HÀNH của máy chủ có nhãn.
  it("mã đường tính hiện hành lich_su_thpt / thuong_tru hiện nhãn tiếng Việt", () => {
    const { rerender } = render(<KvBreakdownCard kv="KV1" pathway="lich_su_thpt" ruleApplied="longest_duration" />)
    expect(screen.getByTestId("kv-breakdown-details").textContent).toContain("Theo lịch sử học các trường THPT")
    rerender(<KvBreakdownCard kv="KV2" pathway="thuong_tru" ruleApplied="commune_lookup" />)
    expect(screen.getByTestId("kv-breakdown-details").textContent).toContain("Theo nơi thường trú")
    expect(screen.getByTestId("kv-breakdown-details").textContent).not.toContain("thuong_tru")
  })

  it("falls back to raw value when pathway not in label map", () => {
    render(
      <KvBreakdownCard
        kv="KV1"
        pathway="future_unknown_pathway"
        ruleApplied="longest_duration"
      />,
    )
    expect(screen.getByText(/future_unknown_pathway/i)).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Manual override audit trail (E.2 prep — Phase E.2 will write these keys)
  // -------------------------------------------------------------------------

  it("renders manual override audit row when ruleApplied='manual_override'", () => {
    render(
      <KvBreakdownCard
        kv="KV1"
        ruleApplied="manual_override"
        manualOverrideReason="Ambiguous tiebreak — sapxep theo grade_to"
        manualOverrideBy="Nguyễn Văn A"
      />,
    )
    expect(screen.getByTestId("kv-breakdown-override")).toBeInTheDocument()
    expect(screen.getByText(/cán bộ ấn định thủ công bởi nguyễn văn a/i)).toBeInTheDocument()
    expect(screen.getByText(/ambiguous tiebreak/i)).toBeInTheDocument()
  })

  it("does NOT render override audit when ruleApplied != 'manual_override'", () => {
    render(
      <KvBreakdownCard
        kv="KV1"
        ruleApplied="longest_duration"
        manualOverrideReason="Should not show"
      />,
    )
    expect(screen.queryByTestId("kv-breakdown-override")).not.toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Breakdown JSON disclosure (officer audit)
  // -------------------------------------------------------------------------

  it("renders breakdown JSON disclosure when breakdown provided", () => {
    render(
      <KvBreakdownCard
        kv="KV1"
        breakdown={{ target_level: "THPT", kv_totals: { KV1: 3 } }}
      />,
    )
    const summary = screen.getByText(/xem chi tiết tính toán/i)
    expect(summary).toBeInTheDocument()
  })

  it("does NOT render breakdown disclosure when no KV resolved", () => {
    render(<KvBreakdownCard kv={null} breakdown={{ foo: "bar" }} />)
    expect(screen.queryByText(/xem chi tiết tính toán/i)).not.toBeInTheDocument()
  })
})
