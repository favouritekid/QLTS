"use client";

import { Suspense } from "react";
import { DrillDownPageShell } from "@/components/officer/drilldown/DrillDownPageShell";
import { drilldownApi } from "@/lib/api/drilldown";

const COLUMNS = [
  { key: "lead_name", label: "Lead" },
  { key: "consultation_date", label: "Ngày tư vấn" },
  { key: "loss_reason_code", label: "Lý do mất" },
  { key: "status", label: "Trạng thái" },
];

function ConsultationsContent() {
  return (
    <DrillDownPageShell
      target="consultations"
      title="Chi tiết tư vấn"
      fetchFn={drilldownApi.getConsultations}
      queryKeyPrefix="drilldown-consultations"
      columns={COLUMNS}
      renderRow={(row: Record<string, unknown>, i: number) => (
        <tr key={String(row.consultation_id ?? i)} className="border-b hover:bg-muted/50">
          <td className="py-2 px-3">{String(row.lead_name ?? "—")}</td>
          <td className="py-2 px-3">{row.consultation_date ? new Date(String(row.consultation_date)).toLocaleDateString("vi-VN") : "—"}</td>
          <td className="py-2 px-3">{String(row.loss_reason_code ?? "—")}</td>
          <td className="py-2 px-3">{String(row.status ?? "—")}</td>
        </tr>
      )}
    />
  );
}

export default function ConsultationsDrillDownPage() {
  return (
    <Suspense fallback={<div className="p-6">Đang tải...</div>}>
      <ConsultationsContent />
    </Suspense>
  );
}
