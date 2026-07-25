import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReportRow } from "@/lib/zod/reports";

import { QuotaRunway } from "./QuotaRunway";

function mkRow(o: {
  id: number;
  name: string;
  code?: string;
  quota?: number | null;
  submitted?: number;
}): ReportRow {
  return {
    group_key: o.id,
    label: o.code ? `${o.name} (${o.code})` : o.name,
    code: o.code ?? null,
    degree_level: null,
    is_bucket: false,
    bucket_kind: null,
    lead: { new_in_week: 0, active_current: 0, consulting_positive_current: 0 },
    admission: {
      profiles_total: 0,
      submitted_in_week: 0,
      admitted_in_week: 0,
      enrolled_in_week: 0,
      submitted_cumulative: o.submitted ?? 0,
      fee_paid_not_submitted: 0,
      admitted_cumulative: 0,
      enrolled_cumulative: 0,
      draft: 0,
      fee_hk1_partial: 0,
      fee_hk1_full: 0,
      quota: o.quota ?? null,
    },
    conversion: { submit_to_admit: null, admit_to_enroll: null },
    finance: {
      gross_in_week: "0",
      refund_in_week: "0",
      net_in_week: "0",
      application_net_in_week: "0",
      tuition_net_in_week: "0",
      net_cumulative: "0",
      profiles_paid: 0,
    },
  };
}

describe("QuotaRunway — thang chỉ tiêu vs số hồ sơ", () => {
  it("ALL có quota → thang chỉ tiêu (còn trống + % chỉ tiêu)", () => {
    render(
      <QuotaRunway
        rows={[
          mkRow({ id: 1, name: "Ngành A", quota: 100, submitted: 40 }),
          mkRow({ id: 2, name: "Ngành B", quota: 50, submitted: 30 }),
        ]}
      />,
    );
    expect(screen.getByText("Còn trống so chỉ tiêu")).toBeTruthy();
    expect(screen.getByText(/Độ dài thanh = chỉ tiêu/)).toBeTruthy();
    expect(screen.getByText("40%")).toBeTruthy(); // A: 40/100
    expect(screen.getByText("60%")).toBeTruthy(); // B: 30/50
  });

  it("NONE có quota → thang số hồ sơ (không nhắc chỉ tiêu)", () => {
    render(
      <QuotaRunway
        rows={[
          mkRow({ id: 1, name: "Ngành A", quota: null, submitted: 40 }),
          mkRow({ id: 2, name: "Ngành B", quota: null, submitted: 30 }),
        ]}
      />,
    );
    expect(screen.getByText("Số hồ sơ (thang tương đối)")).toBeTruthy();
    expect(screen.getByText("Xếp theo số hồ sơ.")).toBeTruthy();
    expect(screen.queryByText("Còn trống so chỉ tiêu")).toBeNull();
  });

  it("MIXED (một số ngành chưa đặt chỉ tiêu) → fallback số hồ sơ, ngành thiếu quota vẫn hiện (không thanh rỗng oan)", () => {
    render(
      <QuotaRunway
        rows={[
          mkRow({ id: 1, name: "Ngành A", quota: 100, submitted: 40 }),
          // ngành B có hồ sơ nhưng CHƯA đặt chỉ tiêu
          mkRow({ id: 2, name: "Ngành B chưa quota", quota: null, submitted: 55 }),
        ]}
      />,
    );
    // every() = false → cả bảng dùng thang số hồ sơ
    expect(screen.getByText("Số hồ sơ (thang tương đối)")).toBeTruthy();
    // ngành thiếu quota VẪN render (trước đây bị ép trackFrac=0 → thanh rỗng)
    expect(screen.getByText("Ngành B chưa quota")).toBeTruthy();
    expect(screen.getByText("Ngành A")).toBeTruthy();
    // hiển thị số hồ sơ tuyệt đối cho MỌI hàng
    expect(screen.getByText("55")).toBeTruthy(); // ngành B
    expect(screen.getByText("40")).toBeTruthy(); // ngành A (số hồ sơ, KHÔNG %)
    // KHÔNG hàng nào phát tín hiệu chỉ tiêu (%, /quota) — kể cả ngành A có quota
    expect(screen.queryByText("40%")).toBeNull();
    expect(screen.queryByText(/\/\s*100/)).toBeNull();
    expect(screen.queryByText(/Độ dài thanh = chỉ tiêu/)).toBeNull();
  });

  it("OVER-quota (vượt chỉ tiêu) → % > 100 + không crash", () => {
    render(
      <QuotaRunway
        rows={[mkRow({ id: 1, name: "Ngành A", quota: 20, submitted: 26 })]}
      />,
    );
    expect(screen.getByText("130%")).toBeTruthy(); // 26/20
    expect(screen.getByText("Ngành A")).toBeTruthy();
  });

  it("rỗng → thông báo không có ngành", () => {
    render(<QuotaRunway rows={[]} />);
    expect(
      screen.getByText(/Chưa có ngành nào phát sinh hồ sơ/),
    ).toBeTruthy();
  });
});
