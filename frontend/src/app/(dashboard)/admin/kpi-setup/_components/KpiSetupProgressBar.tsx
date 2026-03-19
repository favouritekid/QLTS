"use client";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { CoverageReport } from "@/types/kpi-setup.types";

interface Props {
  report: CoverageReport;
  onIndicatorClick?: (sectionId: string) => void;
}

export function KpiSetupProgressBar({ report, onIndicatorClick }: Props) {
  const { holiday_status, summary, warnings } = report;

  // Weighted completion score
  const holidayScore = holiday_status.is_complete ? 15 : 0;
  const unitScore =
    summary.total_units > 0
      ? (summary.units_with_plan / summary.total_units) * 35
      : 0;
  const officerScore =
    summary.total_officers > 0
      ? (summary.officers_with_target / summary.total_officers) * 35
      : 0;
  const syncScore = warnings.every((w) => w.reason_code !== "stale_sync")
    ? 15
    : 0;

  const total = Math.round(holidayScore + unitScore + officerScore + syncScore);

  const indicators = [
    {
      label: "Lịch nghỉ",
      ok: holiday_status.is_complete,
      sectionId: "holiday-section",
    },
    {
      label: "Kế hoạch đơn vị",
      ok: summary.total_units > 0 && summary.units_with_plan === summary.total_units,
      sectionId: "unit-coverage-section",
    },
    {
      label: "Chỉ tiêu officer",
      ok:
        summary.total_officers > 0 &&
        summary.officers_with_target === summary.total_officers,
      sectionId: "unit-coverage-section",
    },
    {
      label: "Đồng bộ YTD",
      ok: warnings.every((w) => w.reason_code !== "stale_sync"),
      sectionId: "unit-coverage-section",
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Progress value={total} className="flex-1 h-3" />
        <span className="text-sm font-medium tabular-nums w-12 text-right">
          {total}%
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {indicators.map((ind) => {
          const badge = (
            <Badge
              key={ind.label}
              variant={ind.ok ? "default" : "outline"}
              className={`text-xs${onIndicatorClick ? " cursor-pointer hover:opacity-80" : ""}`}
            >
              {ind.ok ? "✓" : "○"} {ind.label}
            </Badge>
          );

          if (onIndicatorClick) {
            return (
              <button
                key={ind.label}
                type="button"
                onClick={() => onIndicatorClick(ind.sectionId)}
              >
                {badge}
              </button>
            );
          }

          return badge;
        })}
      </div>
    </div>
  );
}
