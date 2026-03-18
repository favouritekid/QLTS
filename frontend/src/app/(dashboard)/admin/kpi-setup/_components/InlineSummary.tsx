"use client";

import { AlertTriangle, Clock, Target, TrendingUp, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { CoverageReport, CoverageWarning } from "@/types/kpi-setup.types";
import { ACTION_HINTS, REASON_CODES } from "@/types/kpi-setup.types";

interface Props {
  report: CoverageReport;
  isAdmin?: boolean;
}

function WarningIcon({ code }: { code: string }) {
  if (code === REASON_CODES.STALE_SYNC) {
    return <Clock aria-hidden="true" className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />;
  }
  return <AlertTriangle aria-hidden="true" className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />;
}

function actionLabel(hint: string, admin: boolean): string {
  switch (hint) {
    case ACTION_HINTS.SEED_HOLIDAYS:
      return admin ? "Cấu hình lịch nghỉ" : "Xem lịch nghỉ";
    case ACTION_HINTS.CREATE_PLAN:
      return admin ? "Tạo kế hoạch" : "Xem kế hoạch";
    case ACTION_HINTS.ASSIGN_TARGET:
      return admin ? "Gán chỉ tiêu" : "Xem chỉ tiêu";
    case ACTION_HINTS.REVIEW_TARGETS:
      return "Xem chỉ tiêu";
    case ACTION_HINTS.SYNC_YTD:
      return "Đồng bộ YTD";
    default:
      return hint;
  }
}

function scrollToElement(warning: CoverageWarning) {
  let targetId: string | null = null;

  switch (warning.action_hint) {
    case ACTION_HINTS.SEED_HOLIDAYS:
      targetId = "holiday-section";
      break;
    case ACTION_HINTS.CREATE_PLAN:
      if (warning.entity_id != null) {
        targetId = `unit-${warning.entity_id}`;
      }
      break;
    case ACTION_HINTS.ASSIGN_TARGET:
    case ACTION_HINTS.REVIEW_TARGETS:
      if (warning.entity_id != null) {
        targetId = `unit-${warning.entity_id}`;
      }
      break;
    default:
      break;
  }

  if (targetId) {
    document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

export function InlineSummary({ report, isAdmin = false }: Props) {
  const { summary, warnings } = report;

  const atRiskCount = report.units.reduce(
    (sum, u) =>
      sum + u.officers.filter((o) => o.status === "at_risk" || o.status === "overdue").length,
    0,
  );

  const summaryCards = [
    {
      title: "Tổng chỉ tiêu",
      value: summary.total_annual_target,
      icon: Target,
    },
    {
      title: "Đã đạt YTD",
      value: summary.total_achieved_ytd,
      icon: TrendingUp,
    },
    {
      title: "Tiến độ",
      value: `${summary.progress_pct}%`,
      icon: TrendingUp,
    },
    {
      title: "Cán bộ có nguy cơ",
      value: atRiskCount,
      icon: Users,
      highlight: atRiskCount > 0,
    },
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summaryCards.map((card) => (
          <Card key={card.title}>
            <CardContent className="pt-6">
              <div className="flex items-center gap-3">
                <card.icon
                  aria-hidden="true"
                  className={`h-5 w-5 ${card.highlight ? "text-destructive" : "text-muted-foreground"}`}
                />
                <div>
                  <p className="text-sm text-muted-foreground">{card.title}</p>
                  <p
                    className={`text-2xl font-semibold tabular-nums ${card.highlight ? "text-destructive" : ""}`}
                  >
                    {card.value}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {warnings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cảnh báo</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {warnings.map((warning, idx) => (
                <div
                  key={`${warning.reason_code}-${warning.entity_id ?? "null"}-${idx}`}
                  className="flex items-start gap-3 rounded-md border p-3"
                >
                  <WarningIcon code={warning.reason_code} />
                  <div className="flex-1 space-y-1">
                    <p className="text-sm">{warning.detail}</p>
                    <button
                      type="button"
                      onClick={() => scrollToElement(warning)}
                      className="text-xs text-primary hover:underline"
                    >
                      {actionLabel(warning.action_hint, isAdmin)}
                    </button>
                  </div>
                  <Badge variant="outline" className="text-xs shrink-0">
                    Bước {warning.section + 1}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
