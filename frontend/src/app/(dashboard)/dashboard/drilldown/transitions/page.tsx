"use client";

import { Suspense } from "react";
import { DrillDownPageShell } from "@/components/officer/drilldown/DrillDownPageShell";
import { drilldownApi } from "@/lib/api/drilldown";

const COLUMNS = [
  { key: "lead_name", label: "Lead" },
  { key: "changed_at", label: "Thời điểm" },
  { key: "old_stage_name", label: "Stage cũ" },
  { key: "new_stage_name", label: "Stage mới" },
  { key: "outcome", label: "Kết quả" },
  { key: "loss_reason_code", label: "Lý do mất" },
];

function TransitionsContent() {
  return (
    <DrillDownPageShell
      title="Chi tiết chuyển đổi"
      fetchFn={drilldownApi.getTransitions}
      queryKeyPrefix="drilldown-transitions"
      columns={COLUMNS}
      renderRow={(row: Record<string, unknown>, i: number) => (
        <tr key={String(row.history_id ?? i)} className="border-b hover:bg-muted/50">
          <td className="py-2 px-3">{String(row.lead_name ?? "—")}</td>
          <td className="py-2 px-3">{row.changed_at ? new Date(String(row.changed_at)).toLocaleDateString("vi-VN") : "—"}</td>
          <td className="py-2 px-3">{String(row.old_stage_name ?? "—")}</td>
          <td className="py-2 px-3">{String(row.new_stage_name ?? "—")}</td>
          <td className="py-2 px-3">{String(row.outcome ?? "—")}</td>
          <td className="py-2 px-3">{String(row.loss_reason_code ?? "—")}</td>
        </tr>
      )}
    />
  );
}

export default function TransitionsDrillDownPage() {
  return (
    <Suspense fallback={<div className="p-6">Đang tải...</div>}>
      <TransitionsContent />
    </Suspense>
  );
}
