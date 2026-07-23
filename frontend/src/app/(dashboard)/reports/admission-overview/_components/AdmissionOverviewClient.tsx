"use client";

import * as React from "react";
import { LayoutDashboard } from "lucide-react";

import { SummaryBand } from "@/app/(dashboard)/reports/admissions-weekly/_components/SummaryBand";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebtReport } from "@/hooks/finance/useDebtReport";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import {
  useAdmissionTrend,
  useOfficerMajorMatrix,
  usePipelineFunnel,
} from "@/hooks/reports/useAdmissionOverview";
import { useReportFilters, useWeeklyReport } from "@/hooks/reports/useWeeklyReport";
import { cn } from "@/lib/utils";

import { DebtPanel } from "./DebtPanel";
import { OfficerMajorHeatmap } from "./OfficerMajorHeatmap";
import { OverviewFunnel } from "./OverviewFunnel";
import { OverviewTrend } from "./OverviewTrend";
import { QuotaRunway } from "./QuotaRunway";

const CURRENT_YEAR = new Date().getFullYear();
const ALL_ROUNDS = "__all__";
const ALL_UNITS = "__all__";

function errMessage(err: unknown): string {
  const e = err as {
    response?: { status?: number; data?: { detail?: string } };
  };
  const status = e?.response?.status;
  if (status === 403) return "Bạn không có quyền xem báo cáo này.";
  if (status === 404) return "Không tìm thấy đơn vị/đợt đã chọn.";
  if (status === 400) {
    // BusinessRuleViolation (vd đợt thiếu ngày bắt đầu/kết thúc) — nêu đúng lý do
    // để người dùng biết cách xử lý, thay vì thông báo chung chung.
    const detail = e?.response?.data?.detail;
    return typeof detail === "string" && detail ? detail : "Tham số không hợp lệ.";
  }
  if (status === 422) return "Tham số không hợp lệ.";
  return "Không tải được báo cáo. Vui lòng thử lại.";
}

function Panel({
  title,
  caption,
  children,
  className,
}: {
  title: string;
  caption?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border bg-card p-4 shadow-sm", className)}>
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {caption && (
          <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
            {caption}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

/** Panel body state: error note (not a stuck skeleton), else data, else skeleton. */
function PanelState({
  query,
  skeleton,
  children,
}: {
  query: { isError: boolean; error: unknown; data: unknown };
  skeleton: string;
  children: React.ReactNode;
}) {
  if (query.isError) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        {errMessage(query.error)}
      </div>
    );
  }
  if (query.data) return <>{children}</>;
  return <Skeleton className={skeleton} />;
}

interface FlatUnit {
  id: number;
  name: string;
  depth: number;
}

export function AdmissionOverviewClient() {
  const [year, setYear] = React.useState(CURRENT_YEAR);
  const [round, setRound] = React.useState<string>(ALL_ROUNDS);
  const [unit, setUnit] = React.useState<string>(ALL_UNITS);

  const roundCode = round === ALL_ROUNDS ? undefined : round;
  const unitId = unit === ALL_UNITS ? undefined : Number(unit);

  // Filter option sources.
  const { data: filters } = useReportFilters(year);
  const { data: orgUnits = [] } = useOrganizationUnits();
  const yearOptions = React.useMemo(
    // include the selected `year` so its <SelectItem> always exists (the Năm
    // trigger never blanks while useReportFilters refetches on a year switch).
    () =>
      Array.from(
        new Set([...(filters?.academic_years ?? []), CURRENT_YEAR, year]),
      ).sort((a, b) => b - a),
    [filters, year],
  );
  const roundCodes = filters?.rounds ?? [];
  const flatUnits = React.useMemo(() => {
    const out: FlatUnit[] = [];
    const walk = (units: typeof orgUnits, depth: number) => {
      for (const u of units) {
        out.push({ id: u.id, name: u.name, depth });
        if (u.children?.length) walk(u.children, depth + 1);
      }
    };
    walk(orgUnits, 0);
    return out;
  }, [orgUnits]);

  const scope = { academic_year: year, round_code: roundCode, unit_id: unitId };

  // Primary query (KPI band + runway) + the three overview panels + debt.
  const weekly = useWeeklyReport({
    academic_year: year,
    group_by: "major",
    round_code: roundCode,
    unit_id: unitId,
  });
  const funnel = usePipelineFunnel(scope);
  const trend = useAdmissionTrend(scope);
  const matrix = useOfficerMajorMatrix(scope);
  const debt = useDebtReport({
    academic_year: year,
    unit_id: unitId,
    fee_type: "tuition",
  });

  const synced =
    weekly.data && weekly.data.academic_year === year ? weekly.data : undefined;
  const anyFetching =
    weekly.isFetching || funnel.isFetching || trend.isFetching || matrix.isFetching;

  // Enforced unit scope (thin-client, pure derivation — no ref/effect). The picker
  // stays LOCKED until the first report response arrives (scope determined), so a
  // manager can't pick a foreign unit before we know the scope and 404. A unit-scoped
  // user (manager) keeps "Toàn trường" selected while the backend returns their own
  // unit as scope_unit_id → we show that unit and keep it locked (never diverges from
  // ALL_UNITS → the check stays valid). scope_unit_id is year-independent, so read it
  // off weekly.data (survives placeholder during a year switch). Admin → null → free.
  const enforcedUnit = weekly.data?.scope_unit_id ?? null;
  const scopeDetermined = weekly.data !== undefined;
  const isUnitScoped = scopeDetermined && unit === ALL_UNITS && enforcedUnit != null;
  const unitPickerDisabled = !scopeDetermined || isUnitScoped;
  const unitValue = isUnitScoped ? String(enforcedUnit) : unit;
  const enforcedUnitName = isUnitScoped
    ? flatUnits.find((u) => u.id === enforcedUnit)?.name
    : undefined;

  const onYearChange = (next: number) => {
    setYear(next);
    setRound(ALL_ROUNDS); // dependent filter may be invalid for the new year
  };

  return (
    <div className="flex h-full flex-col space-y-5 p-4 sm:p-6">
      {/* Header + filters (scope cả trang) */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <LayoutDashboard className="size-6 text-primary" /> Tổng quan tuyển sinh
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Phễu · chỉ tiêu · tài chính · tải cán bộ — một màn hình để nắm nhanh và
            can thiệp đúng chỗ.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Năm học</label>
            <Select value={year.toString()} onValueChange={(v) => onYearChange(Number(v))}>
              <SelectTrigger className="w-24" aria-label="Năm học">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {yearOptions.map((y) => (
                  <SelectItem key={y} value={y.toString()}>
                    {y}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Đợt</label>
            <Select value={round} onValueChange={setRound}>
              <SelectTrigger className="w-32" aria-label="Đợt">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_ROUNDS}>Tất cả đợt</SelectItem>
                {roundCodes.map((rc) => (
                  <SelectItem key={rc} value={rc}>
                    {rc}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Đơn vị</label>
            <Select
              value={unitValue}
              onValueChange={setUnit}
              disabled={unitPickerDisabled}
            >
              <SelectTrigger className="w-44" aria-label="Đơn vị">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_UNITS}>Toàn trường</SelectItem>
                {/* enforced unit may not be in the tree yet (still loading) — keep an
                    item so the locked value always displays a name */}
                {isUnitScoped &&
                  !flatUnits.some((u) => u.id === enforcedUnit) && (
                    <SelectItem value={String(enforcedUnit)}>
                      {enforcedUnitName ?? `Đơn vị #${enforcedUnit}`}
                    </SelectItem>
                  )}
                {flatUnits.map((u) => (
                  <SelectItem key={u.id} value={u.id.toString()}>
                    <span style={u.depth > 0 ? { paddingLeft: u.depth * 10 } : undefined}>
                      {u.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Mỗi panel TỰ quản trạng thái → weekly lỗi (vd đợt thiếu ngày) KHÔNG che
          phễu/trend/matrix/công nợ (fetch độc lập, funnel cố ý skip_undated). */}
      <div className={cn("space-y-4", anyFetching && "opacity-60 transition-opacity")}>
        {/* KPI band (tái dùng SummaryBand) — phụ thuộc weekly, trạng thái riêng */}
        <PanelState
          query={{ isError: weekly.isError, error: weekly.error, data: synced }}
          skeleton="h-24 w-full"
        >
          {synced && (
            <SummaryBand
              rows={synced.rows}
              totals={synced.totals}
              groupBy={synced.group_by}
            />
          )}
        </PanelState>

        {/* Phễu + Xu hướng (độc lập) */}
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Dòng chảy mùa tuyển sinh" caption="pipeline_stage">
            <PanelState query={funnel} skeleton="h-64 w-full">
              {funnel.data && <OverviewFunnel funnel={funnel.data} />}
            </PanelState>
          </Panel>
          <Panel title="Nhịp tích luỹ 8 tuần" caption="cumulative">
            <PanelState query={trend} skeleton="h-64 w-full">
              {trend.data && <OverviewTrend trend={trend.data} />}
            </PanelState>
          </Panel>
        </div>

        {/* Độ đầy chỉ tiêu theo ngành — phụ thuộc weekly, trạng thái riêng */}
        <Panel title="Độ đầy chỉ tiêu — theo ngành" caption="admission-weekly">
          <p className="mb-3 -mt-1 text-xs text-muted-foreground">
            Mỗi thanh = chỉ tiêu; hổ phách = đã đóng học phí HK1, xanh = đã nộp
            chưa đóng, phần trống = còn thiếu so chỉ tiêu. Ngành nguy cơ (đầy
            thấp) hiện đầu.
          </p>
          <PanelState
            query={{ isError: weekly.isError, error: weekly.error, data: synced }}
            skeleton="h-56 w-full"
          >
            {synced && <QuotaRunway rows={synced.rows} matrix={matrix.data} />}
          </PanelState>
        </Panel>

        {/* Heatmap ngành × cán bộ (độc lập) */}
        <Panel title="Tải hồ sơ theo ngành × cán bộ" caption="officer-major-matrix">
          <PanelState query={matrix} skeleton="h-56 w-full">
            {matrix.data && <OfficerMajorHeatmap matrix={matrix.data} />}
          </PanelState>
        </Panel>

        {/* Công nợ học phí (độc lập; mọi kỳ — endpoint không tách semester) */}
        <Panel title="Công nợ học phí" caption="debt-report">
          <p className="mb-3 -mt-1 text-xs text-muted-foreground">
            Toàn bộ học phí còn nợ (mọi kỳ) · theo năm học và đơn vị — chưa lọc
            theo đợt.
          </p>
          <DebtPanel summary={debt.data?.summary} isLoading={debt.isLoading} />
        </Panel>

        <p className="text-xs text-muted-foreground">
          Số liệu tính lại theo phân bổ hiện tại — tuần đã qua có thể đổi sau khi
          công bố kết quả. <strong>Phễu</strong> đếm LEAD theo cohort đợt (gồm
          khách vãng lai) nên bậc “Đã nộp hồ sơ” có thể lệch nhẹ so với dải KPI
          “Hồ sơ nộp” (đếm theo mốc hồ sơ). KPI · đường băng chỉ tiêu · heatmap ·
          trend dùng chung một nguồn milestone → nhất quán với Báo cáo tuyển sinh.
        </p>
      </div>
    </div>
  );
}
