"use client";

import type {
  CoverageReport,
  OfficerCoverage,
  UnitCoverage,
} from "@/types/kpi-setup.types";
import {
  STATUS_CONFIG,
  TARGET_SOURCE_CONFIG,
} from "@/types/kpi-setup.types";

export type DashboardTone = "success" | "neutral" | "warning" | "danger";
export type TrendDirection = "up" | "flat" | "down";

export interface UnitInsight {
  unitId: number;
  unitName: string;
  annualTarget: number;
  achievedYtd: number;
  progressPct: number;
  expectedProgressPct: number;
  expectedTargetToDate: number;
  forecastFinal: number;
  totalOfficers: number;
  missingTargets: number;
  riskOfficers: number;
  completedOfficers: number;
  targetGap: number;
  hasPlan: boolean;
  tone: DashboardTone;
  trend: TrendDirection;
  severity: number;
  statusLabel: string;
  summaryLabel: string;
}

export interface OfficerInsight {
  rank: number;
  unitId: number;
  unitName: string;
  officerId: number;
  officerName: string;
  annualTarget: number;
  achievedYtd: number;
  progressPct: number;
  expectedProgressPct: number;
  paceDeltaPct: number;
  tone: DashboardTone;
  trend: TrendDirection;
  status: OfficerCoverage["status"];
  statusLabel: string;
  targetSource: OfficerCoverage["target_source"];
  targetSourceLabel: string;
  planId: number | null;
}

export interface AlertGroup {
  key: string;
  title: string;
  description: string;
  count: number;
  items: string[];
  tone: DashboardTone;
  actionLabel: string;
  targetId: string;
}

export interface DashboardAnalytics {
  overallTone: DashboardTone;
  overallTrend: TrendDirection;
  overallPaceDeltaPct: number;
  expectedProgressPct: number;
  expectedYtdTarget: number;
  forecastFinal: number;
  unitsWithPlanCount: number;
  unitsRunningWellCount: number;
  missingPlanCount: number;
  officersMissingCount: number;
  riskUnitCount: number;
  alertGroups: AlertGroup[];
  unitInsights: UnitInsight[];
  officerInsights: OfficerInsight[];
  topPerformers: OfficerInsight[];
  atRiskUnits: UnitInsight[];
  timelineWeights: number[];
}

export const MONTH_LABELS_SHORT = [
  "T1",
  "T2",
  "T3",
  "T4",
  "T5",
  "T6",
  "T7",
  "T8",
  "T9",
  "T10",
  "T11",
  "T12",
];

const DEFAULT_SEASONAL_WEIGHTS = [
  0.04,
  0.033,
  0.05,
  0.06,
  0.073,
  0.127,
  0.153,
  0.16,
  0.133,
  0.093,
  0.043,
  0.033,
];

const numberFormatter = new Intl.NumberFormat("vi-VN");
const percentFormatter = new Intl.NumberFormat("vi-VN", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 0,
});

export const DASHBOARD_TONE_STYLES: Record<
  DashboardTone,
  {
    badge: string;
    border: string;
    progress: string;
    soft: string;
    text: string;
  }
> = {
  success: {
    badge: "bg-emerald-600 text-white",
    border: "border-emerald-200",
    progress: "bg-emerald-500",
    soft: "border-emerald-200 bg-emerald-50/80 text-emerald-950",
    text: "text-emerald-700",
  },
  neutral: {
    badge: "bg-sky-600 text-white",
    border: "border-sky-200",
    progress: "bg-sky-500",
    soft: "border-sky-200 bg-sky-50/80 text-sky-950",
    text: "text-sky-700",
  },
  warning: {
    badge: "bg-amber-500 text-amber-950",
    border: "border-amber-200",
    progress: "bg-amber-500",
    soft: "border-amber-200 bg-amber-50/80 text-amber-950",
    text: "text-amber-700",
  },
  danger: {
    badge: "bg-rose-600 text-white",
    border: "border-rose-200",
    progress: "bg-rose-500",
    soft: "border-rose-200 bg-rose-50/80 text-rose-950",
    text: "text-rose-700",
  },
};

function roundOne(value: number) {
  return Math.round(value * 10) / 10;
}

export function formatNumber(value: number) {
  return numberFormatter.format(Math.round(value));
}

export function formatPercent(value: number) {
  return `${percentFormatter.format(roundOne(value))}%`;
}

function normalizeWeights(weights?: number[] | null) {
  if (!weights || weights.length !== 12) {
    return [...DEFAULT_SEASONAL_WEIGHTS];
  }

  const total = weights.reduce((sum, weight) => sum + weight, 0);
  if (total <= 0) {
    return [...DEFAULT_SEASONAL_WEIGHTS];
  }

  return weights.map((weight) => weight / total);
}

function getElapsedMonthCount(fiscalYear: number, today = new Date()) {
  const currentYear = today.getFullYear();
  if (fiscalYear < currentYear) return 12;
  if (fiscalYear > currentYear) return 0;
  return today.getMonth() + 1;
}

function getExpectedProgressRatio(
  weights: number[] | null | undefined,
  fiscalYear: number,
  today = new Date(),
) {
  const elapsedMonths = getElapsedMonthCount(fiscalYear, today);
  if (elapsedMonths <= 0) return 0;
  return normalizeWeights(weights)
    .slice(0, elapsedMonths)
    .reduce((sum, weight) => sum + weight, 0);
}

function getUnitAnnualTarget(unit: UnitCoverage) {
  if (unit.annual_target != null && unit.annual_target > 0) {
    return unit.annual_target;
  }
  return unit.officers.reduce((sum, officer) => sum + officer.annual_target, 0);
}

function getUnitAchievedYtd(unit: UnitCoverage) {
  return unit.officers.reduce((sum, officer) => sum + officer.achieved_ytd, 0);
}

function getTrendDirection(progressPct: number, expectedProgressPct: number) {
  const delta = progressPct - expectedProgressPct;
  if (delta >= 4) return "up";
  if (delta <= -4) return "down";
  return "flat";
}

function getOfficerTone(
  officer: OfficerCoverage,
  expectedProgressPct: number,
): DashboardTone {
  if (officer.target_source === "none" || officer.status === "overdue") {
    return "danger";
  }
  if (officer.status === "at_risk") {
    return "warning";
  }
  if (officer.status === "completed") {
    return "success";
  }

  const delta = officer.progress_pct - expectedProgressPct;
  if (delta >= 5) return "success";
  if (delta <= -10) return "danger";
  if (delta <= -3 || officer.status === "not_started") return "warning";
  return "neutral";
}

function getUnitTone(params: {
  hasPlan: boolean;
  missingTargets: number;
  riskOfficers: number;
  targetGap: number;
  paceDeltaPct: number;
  severity: number;
}) {
  const {
    hasPlan,
    missingTargets,
    riskOfficers,
    targetGap,
    paceDeltaPct,
    severity,
  } = params;

  if (!hasPlan || severity >= 34) return "danger";
  if (severity >= 14) return "warning";
  if (
    paceDeltaPct >= 4 &&
    missingTargets === 0 &&
    riskOfficers === 0 &&
    targetGap === 0
  ) {
    return "success";
  }
  return "neutral";
}

function getUnitStatusLabel(
  tone: DashboardTone,
  hasPlan: boolean,
  riskOfficers: number,
  missingTargets: number,
  targetGap: number,
) {
  if (!hasPlan) return "Thiếu KPI Plan";
  if (tone === "danger") return "Nguy cơ trượt";
  if (tone === "warning") {
    if (missingTargets > 0) return "Thiếu KPI cán bộ";
    if (targetGap !== 0) return "Lệch phân bổ";
    if (riskOfficers > 0) return "Cần theo dõi";
  }
  if (tone === "success") return "Đang chạy tốt";
  return "Ổn định";
}

function getUnitSummaryLabel(params: {
  hasPlan: boolean;
  riskOfficers: number;
  missingTargets: number;
  targetGap: number;
  paceDeltaPct: number;
}) {
  const { hasPlan, riskOfficers, missingTargets, targetGap, paceDeltaPct } = params;

  if (!hasPlan) return "Tạo plan để mở phân bổ KPI cho đơn vị.";
  if (missingTargets > 0) {
    return `${missingTargets} cán bộ chưa có KPI cá nhân.`;
  }
  if (targetGap !== 0) {
    const prefix = targetGap > 0 ? "Thiếu phân bổ" : "Vượt phân bổ";
    return `${prefix} ${formatNumber(Math.abs(targetGap))} KPI so với plan đơn vị.`;
  }
  if (riskOfficers > 0) {
    return `${riskOfficers} cán bộ đang chậm nhịp so với kế hoạch.`;
  }
  if (paceDeltaPct >= 4) {
    return "Đơn vị đang vượt nhịp kỳ vọng theo mùa tuyển sinh.";
  }
  if (paceDeltaPct <= -4) {
    return "Đơn vị đang dưới nhịp kỳ vọng, cần bám sát hơn.";
  }
  return "Đơn vị đang bám kế hoạch ổn định.";
}

export function buildUnitInsight(unit: UnitCoverage, fiscalYear: number): UnitInsight {
  const annualTarget = getUnitAnnualTarget(unit);
  const achievedYtd = getUnitAchievedYtd(unit);
  const expectedRatio = getExpectedProgressRatio(unit.seasonal_weights, fiscalYear);
  const expectedProgressPct = roundOne(expectedRatio * 100);
  const progressPct =
    annualTarget > 0 ? roundOne((achievedYtd / annualTarget) * 100) : 0;
  const paceDeltaPct = progressPct - expectedProgressPct;
  const missingTargets = unit.officers.filter((officer) => officer.target_source === "none").length;
  const riskOfficers = unit.officers.filter(
    (officer) => officer.status === "at_risk" || officer.status === "overdue",
  ).length;
  const completedOfficers = unit.officers.filter(
    (officer) => officer.status === "completed",
  ).length;

  let severity = 0;
  if (!unit.plan_id) severity += 40;
  severity += missingTargets * 10;
  severity += riskOfficers * 8;
  if (unit.target_gap !== 0) severity += 12;
  if (paceDeltaPct <= -10) severity += 18;
  else if (paceDeltaPct <= -4) severity += 8;
  if (expectedRatio > 0 && annualTarget > 0) {
    const forecastFinal = achievedYtd / expectedRatio;
    if (forecastFinal < annualTarget * 0.85) {
      severity += 8;
    }
  }
  if (completedOfficers > 0 && paceDeltaPct >= 4) {
    severity = Math.max(0, severity - 3);
  }

  const tone = getUnitTone({
    hasPlan: unit.plan_id != null,
    missingTargets,
    riskOfficers,
    targetGap: unit.target_gap,
    paceDeltaPct,
    severity,
  });
  const forecastFinal =
    expectedRatio > 0 ? Math.round(achievedYtd / expectedRatio) : 0;

  return {
    unitId: unit.unit_id,
    unitName: unit.unit_name,
    annualTarget,
    achievedYtd,
    progressPct,
    expectedProgressPct,
    expectedTargetToDate: Math.round(annualTarget * expectedRatio),
    forecastFinal,
    totalOfficers: unit.officers.length,
    missingTargets,
    riskOfficers,
    completedOfficers,
    targetGap: unit.target_gap,
    hasPlan: unit.plan_id != null,
    tone,
    trend: getTrendDirection(progressPct, expectedProgressPct),
    severity,
    statusLabel: getUnitStatusLabel(
      tone,
      unit.plan_id != null,
      riskOfficers,
      missingTargets,
      unit.target_gap,
    ),
    summaryLabel: getUnitSummaryLabel({
      hasPlan: unit.plan_id != null,
      riskOfficers,
      missingTargets,
      targetGap: unit.target_gap,
      paceDeltaPct,
    }),
  };
}

export function buildOfficerInsight(
  officer: OfficerCoverage,
  unit: UnitCoverage,
  fiscalYear: number,
  rank = 0,
): OfficerInsight {
  const expectedProgressPct = roundOne(
    getExpectedProgressRatio(unit.seasonal_weights, fiscalYear) * 100,
  );
  const tone = getOfficerTone(officer, expectedProgressPct);

  return {
    rank,
    unitId: unit.unit_id,
    unitName: unit.unit_name,
    officerId: officer.officer_id,
    officerName: officer.officer_name,
    annualTarget: officer.annual_target,
    achievedYtd: officer.achieved_ytd,
    progressPct: officer.progress_pct,
    expectedProgressPct,
    paceDeltaPct: roundOne(officer.progress_pct - expectedProgressPct),
    tone,
    trend: getTrendDirection(officer.progress_pct, expectedProgressPct),
    status: officer.status,
    statusLabel: STATUS_CONFIG[officer.status].label,
    targetSource: officer.target_source,
    targetSourceLabel: TARGET_SOURCE_CONFIG[officer.target_source].label,
    planId: officer.plan_id,
  };
}

function buildAlertGroups(
  report: CoverageReport,
  unitInsights: UnitInsight[],
  officerInsights: OfficerInsight[],
) {
  const groups: AlertGroup[] = [];

  const missingPlanUnits = unitInsights
    .filter((unit) => !unit.hasPlan)
    .map((unit) => unit.unitName);
  if (missingPlanUnits.length > 0) {
    groups.push({
      key: "missing-plan",
      title: `${missingPlanUnits.length} đơn vị chưa tạo KPI Plan`,
      description: "Ưu tiên tạo plan để đơn vị có thể phân bổ chỉ tiêu ngay.",
      count: missingPlanUnits.length,
      items: missingPlanUnits,
      tone: "danger",
      actionLabel: "Tạo kế hoạch ngay",
      targetId: "unit-dashboard",
    });
  }

  const officersMissingTargets = officerInsights
    .filter((officer) => officer.targetSource === "none")
    .map((officer) => `${officer.officerName} - ${officer.unitName}`);
  if (officersMissingTargets.length > 0) {
    groups.push({
      key: "missing-kpi",
      title: `${officersMissingTargets.length} cán bộ chưa có KPI`,
      description: "Các cán bộ này chưa có chỉ tiêu nên không thể theo dõi đúng nhịp.",
      count: officersMissingTargets.length,
      items: officersMissingTargets,
      tone: "danger",
      actionLabel: "Gán KPI",
      targetId: "officer-kpi",
    });
  }

  const targetGapUnits = unitInsights
    .filter((unit) => unit.targetGap !== 0)
    .map(
      (unit) =>
        `${unit.unitName} (${unit.targetGap > 0 ? "+" : ""}${formatNumber(unit.targetGap)})`,
    );
  if (targetGapUnits.length > 0) {
    groups.push({
      key: "allocation-gap",
      title: `${targetGapUnits.length} đơn vị lệch phân bổ`,
      description: "Tổng KPI cán bộ chưa khớp với plan đơn vị, cần rà soát lại quota.",
      count: targetGapUnits.length,
      items: targetGapUnits,
      tone: "warning",
      actionLabel: "Rà soát phân bổ",
      targetId: "unit-dashboard",
    });
  }

  if (!report.holiday_status.is_complete) {
    groups.push({
      key: "holiday",
      title: "Lịch nghỉ chưa hoàn tất",
      description: "Thiếu lịch nghỉ sẽ làm sai nhịp tính KPI theo tháng và ngày làm việc.",
      count: 1,
      items: [`Năm ${report.fiscal_year} mới có ${report.holiday_status.total_holidays} ngày nghỉ.`],
      tone: "warning",
      actionLabel: "Cấu hình lịch nghỉ",
      targetId: "holiday-section",
    });
  }

  if (report.warnings.some((warning) => warning.reason_code === "stale_sync")) {
    groups.push({
      key: "stale-sync",
      title: "YTD chưa đồng bộ gần đây",
      description: "Số liệu thực tế có thể đang chậm hơn 24h, nên kiểm tra trước khi ra quyết định.",
      count: 1,
      items: ["Có bản ghi KPI chưa được sync trong 24h gần nhất."],
      tone: "warning",
      actionLabel: "Mở phần chi tiết",
      targetId: "detail-section",
    });
  }

  return groups;
}

function aggregateTimelineWeights(report: CoverageReport) {
  const bucket = Array.from({ length: 12 }, () => 0);
  let totalTarget = 0;

  for (const unit of report.units) {
    const unitTarget = getUnitAnnualTarget(unit);
    if (unitTarget <= 0) continue;

    const weights = normalizeWeights(unit.seasonal_weights);
    weights.forEach((weight, index) => {
      bucket[index] += weight * unitTarget;
    });
    totalTarget += unitTarget;
  }

  if (totalTarget <= 0) {
    return normalizeWeights(null);
  }

  return bucket.map((weight) => weight / totalTarget);
}

export function buildDashboardAnalytics(report: CoverageReport): DashboardAnalytics {
  const unitInsights = report.units
    .map((unit) => buildUnitInsight(unit, report.fiscal_year))
    .sort((left, right) => {
      if (right.severity !== left.severity) {
        return right.severity - left.severity;
      }
      return right.progressPct - left.progressPct;
    });

  const officerInsights = report.units
    .flatMap((unit) =>
      unit.officers.map((officer) => buildOfficerInsight(officer, unit, report.fiscal_year)),
    )
    .sort((left, right) => {
      if (right.progressPct !== left.progressPct) {
        return right.progressPct - left.progressPct;
      }
      if (right.achievedYtd !== left.achievedYtd) {
        return right.achievedYtd - left.achievedYtd;
      }
      return left.officerName.localeCompare(right.officerName, "vi");
    })
    .map((officer, index) => ({ ...officer, rank: index + 1 }));

  const timelineWeights = aggregateTimelineWeights(report);
  const expectedProgressPct = roundOne(
    getExpectedProgressRatio(timelineWeights, report.fiscal_year) * 100,
  );
  const overallPaceDeltaPct = roundOne(report.summary.progress_pct - expectedProgressPct);
  const unitsRunningWellCount = unitInsights.filter(
    (unit) => unit.tone === "success" || unit.tone === "neutral",
  ).length;
  const riskUnitCount = unitInsights.filter(
    (unit) => unit.tone === "danger" || unit.tone === "warning",
  ).length;

  let overallTone: DashboardTone = "neutral";
  if (
    riskUnitCount >= Math.max(2, Math.ceil(report.summary.total_units / 3)) ||
    overallPaceDeltaPct <= -8
  ) {
    overallTone = "danger";
  } else if (riskUnitCount > 0 || overallPaceDeltaPct <= -4) {
    overallTone = "warning";
  } else if (overallPaceDeltaPct >= 4) {
    overallTone = "success";
  }

  const expectedRatio = expectedProgressPct / 100;
  const forecastFinal =
    expectedRatio > 0 ? Math.round(report.summary.total_achieved_ytd / expectedRatio) : 0;

  return {
    overallTone,
    overallTrend: getTrendDirection(report.summary.progress_pct, expectedProgressPct),
    overallPaceDeltaPct,
    expectedProgressPct,
    expectedYtdTarget: Math.round(report.summary.total_annual_target * expectedRatio),
    forecastFinal,
    unitsWithPlanCount: unitInsights.filter((unit) => unit.hasPlan).length,
    unitsRunningWellCount,
    missingPlanCount: unitInsights.filter((unit) => !unit.hasPlan).length,
    officersMissingCount: officerInsights.filter(
      (officer) => officer.targetSource === "none",
    ).length,
    riskUnitCount,
    alertGroups: buildAlertGroups(report, unitInsights, officerInsights),
    unitInsights,
    officerInsights,
    topPerformers: officerInsights.filter((officer) => officer.annualTarget > 0).slice(0, 5),
    atRiskUnits: [...unitInsights]
      .filter((unit) => unit.tone === "danger" || unit.tone === "warning")
      .sort((left, right) => right.severity - left.severity)
      .slice(0, 5),
    timelineWeights,
  };
}

