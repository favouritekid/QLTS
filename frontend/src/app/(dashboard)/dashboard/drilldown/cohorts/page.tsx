"use client";

import { Suspense } from "react";
import { DrillDownPageShell } from "@/components/officer/drilldown/DrillDownPageShell";
import { drilldownApi } from "@/lib/api/drilldown";

const COLUMNS = [
  { key: "lead_name", label: "Lead" },
  { key: "created_at", label: "Ngày tạo" },
  { key: "current_status", label: "Trạng thái" },
  { key: "cohort_result", label: "Kết quả" },
];

function CohortsContent() {
  return (
    <DrillDownPageShell
      title="Chi tiết nhóm leads"
      fetchFn={drilldownApi.getCohorts}
      queryKeyPrefix="drilldown-cohorts"
      columns={COLUMNS}
      renderRow={(row: Record<string, unknown>, i: number) => (
        <tr key={String(row.lead_id ?? i)} className="border-b hover:bg-muted/50">
          <td className="py-2 px-3">{String(row.lead_name ?? "—")}</td>
          <td className="py-2 px-3">{row.created_at ? new Date(String(row.created_at)).toLocaleDateString("vi-VN") : "—"}</td>
          <td className="py-2 px-3">{String(row.current_status ?? "—")}</td>
          <td className="py-2 px-3">{String(row.cohort_result ?? "—")}</td>
        </tr>
      )}
    />
  );
}

export default function CohortsDrillDownPage() {
  return (
    <Suspense fallback={<div className="p-6">Đang tải...</div>}>
      <CohortsContent />
    </Suspense>
  );
}
