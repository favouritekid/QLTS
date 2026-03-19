"use client";

import { useMemo } from "react";
import Link from "next/link";
import { AlertTriangle, Clock, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CoverageReport, CoverageWarning } from "@/types/kpi-setup.types";
import { ACTION_HINTS, REASON_CODES } from "@/types/kpi-setup.types";
import type { KpiConfigItem } from "@/types/kpi-setup.types";
import type { MetricCatalogEntry } from "@/lib/api/meta";

interface AggregatedWarningsProps {
  report: CoverageReport;
  configs: KpiConfigItem[];
  catalogMap: Map<string, MetricCatalogEntry>;
  isAdmin: boolean;
  onScrollToUnit: (unitId: number) => void;
  onOpenPlanDialog: (unitId: number, unitName: string) => void;
}

interface WarningItem {
  key: string;
  icon: "alert" | "clock";
  detail: string;
  action: React.ReactNode;
  section: number;
}

function WarningIcon({ type }: { type: "alert" | "clock" }) {
  if (type === "clock") {
    return (
      <Clock
        aria-hidden="true"
        className="h-4 w-4 text-amber-500 shrink-0 mt-0.5"
      />
    );
  }
  return (
    <AlertTriangle
      aria-hidden="true"
      className="h-4 w-4 text-amber-500 shrink-0 mt-0.5"
    />
  );
}

export function AggregatedWarnings({
  report,
  configs,
  catalogMap,
  isAdmin,
  onScrollToUnit,
  onOpenPlanDialog,
}: AggregatedWarningsProps) {
  // Ghost config warnings (period mismatch)
  const ghostCount = useMemo(
    () =>
      configs.filter((c) => {
        const entry = catalogMap.get(c.kpi_code);
        return entry && c.period_type !== entry.period_type;
      }).length,
    [configs, catalogMap],
  );

  const unitNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const u of report.units) {
      map.set(u.unit_id, u.unit_name);
    }
    return map;
  }, [report.units]);

  const warnings: WarningItem[] = useMemo(() => {
    const items: WarningItem[] = [];

    for (const w of report.warnings) {
      const item = buildWarningItem(
        w,
        isAdmin,
        unitNameById,
        onScrollToUnit,
        onOpenPlanDialog,
      );
      if (item) items.push(item);
    }

    // Ghost config warning
    if (ghostCount > 0) {
      items.push({
        key: "ghost-configs",
        icon: "alert",
        detail: `${ghostCount} cấu hình có chu kỳ không khớp catalog — không có tác dụng.`,
        action: (
          <Link
            href="/admin/kpi-config"
            className="text-xs text-primary hover:underline inline-flex items-center gap-1"
          >
            Xem & sửa
            <ExternalLink className="h-3 w-3" />
          </Link>
        ),
        section: 4,
      });
    }

    return items;
  }, [
    report.warnings,
    ghostCount,
    isAdmin,
    unitNameById,
    onScrollToUnit,
    onOpenPlanDialog,
  ]);

  if (warnings.length === 0) {
    return (
      <Card>
        <CardContent className="py-6">
          <p className="text-sm text-center text-muted-foreground">
            Không có cảnh báo. Hệ thống KPI đã sẵn sàng.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Cảnh báo ({warnings.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {warnings.map((w) => (
            <div
              key={w.key}
              className="flex items-start gap-3 rounded-md border p-3"
            >
              <WarningIcon type={w.icon} />
              <div className="flex-1 space-y-1">
                <p className="text-sm">{w.detail}</p>
                {w.action}
              </div>
              <Badge variant="outline" className="text-xs shrink-0">
                Bước {w.section + 1}
              </Badge>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function buildWarningItem(
  w: CoverageWarning,
  isAdmin: boolean,
  unitNameById: Map<number, string>,
  onScrollToUnit: (unitId: number) => void,
  onOpenPlanDialog: (unitId: number, unitName: string) => void,
): WarningItem | null {
  const key = `${w.reason_code}-${w.entity_id ?? "null"}-${w.detail}`;
  const icon: "alert" | "clock" =
    w.reason_code === REASON_CODES.STALE_SYNC ? "clock" : "alert";

  let action: React.ReactNode = null;

  switch (w.action_hint) {
    case ACTION_HINTS.SEED_HOLIDAYS:
      action = (
        <Link
          href="/admin/kpi-planning/holidays"
          className="text-xs text-primary hover:underline inline-flex items-center gap-1"
        >
          {isAdmin ? "Cấu hình lịch nghỉ" : "Xem lịch nghỉ"}
          <ExternalLink className="h-3 w-3" />
        </Link>
      );
      break;

    case ACTION_HINTS.CREATE_PLAN:
      if (w.entity_id != null && isAdmin) {
        const unitName = unitNameById.get(w.entity_id) ?? `Đơn vị #${w.entity_id}`;
        action = (
          <button
            type="button"
            onClick={() => onOpenPlanDialog(w.entity_id!, unitName)}
            className="text-xs text-primary hover:underline"
          >
            Tạo kế hoạch
          </button>
        );
      } else if (w.entity_id != null) {
        action = (
          <button
            type="button"
            onClick={() => onScrollToUnit(w.entity_id!)}
            className="text-xs text-primary hover:underline"
          >
            Xem đơn vị
          </button>
        );
      }
      break;

    case ACTION_HINTS.ASSIGN_TARGET:
    case ACTION_HINTS.REVIEW_TARGETS:
      if (w.entity_id != null) {
        action = (
          <button
            type="button"
            onClick={() => onScrollToUnit(w.entity_id!)}
            className="text-xs text-primary hover:underline"
          >
            {isAdmin ? "Xem & gán chỉ tiêu" : "Xem chỉ tiêu"}
          </button>
        );
      }
      break;

    case ACTION_HINTS.SYNC_YTD:
      action = (
        <span className="text-xs text-muted-foreground">
          Tự động đồng bộ lúc 1:00 AM
        </span>
      );
      break;

    default:
      action = null;
  }

  return { key, icon, detail: w.detail, action, section: w.section };
}
