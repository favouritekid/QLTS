"use client";

import * as React from "react";
import type { AxiosError } from "axios";
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Download,
  LayoutDashboard,
} from "lucide-react";
import { toast } from "sonner";

import { rankByQuotaGap } from "@/app/(dashboard)/reports/admissions-weekly/_components/cockpit-rank";
import { SummaryBand } from "@/app/(dashboard)/reports/admissions-weekly/_components/SummaryBand";
import {
  WeeklyReportTable,
  type Period,
} from "@/app/(dashboard)/reports/admissions-weekly/_components/WeeklyReportTable";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDebtReport } from "@/hooks/finance/useDebtReport";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import {
  useAdmissionTrend,
  useOfficerMajorMatrix,
  usePipelineFunnel,
} from "@/hooks/reports/useAdmissionOverview";
import { useReportFilters, useWeeklyReport } from "@/hooks/reports/useWeeklyReport";
import { exportAdmissionSummary } from "@/lib/api/reports";
import { cn } from "@/lib/utils";
import { blobErrorMessage, downloadBlob } from "@/lib/utils/download-blob";
import { subDaysVN } from "@/lib/utils/vn-date";
import type { ReportGroupBy } from "@/lib/zod/reports";

import { DebtPanel } from "./DebtPanel";
import { OfficerMajorHeatmap } from "./OfficerMajorHeatmap";
import { OverviewFunnel } from "./OverviewFunnel";
import { OverviewTrend } from "./OverviewTrend";
import { QuotaRunway } from "./QuotaRunway";

const CURRENT_YEAR = new Date().getFullYear();
const ALL_ROUNDS = "__all__";
const ALL_UNITS = "__all__";

const dm = (s: string) => `${s.slice(8, 10)}/${s.slice(5, 7)}`;

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

type TabKey = "visual" | "table";

export function AdmissionOverviewClient() {
  const [year, setYear] = React.useState(CURRENT_YEAR);
  const [round, setRound] = React.useState<string>(ALL_ROUNDS);
  const [unit, setUnit] = React.useState<string>(ALL_UNITS);
  const [tab, setTab] = React.useState<TabKey>("visual");
  // Bảng chi tiết controls (cũng lái KPI band — user chốt "theo toggle bảng").
  const [groupBy, setGroupBy] = React.useState<ReportGroupBy>("major");
  const [period, setPeriod] = React.useState<Period>("ytd");
  const [weekStart, setWeekStart] = React.useState<string | undefined>(undefined);
  const [exporting, setExporting] = React.useState(false);
  const mountedRef = React.useRef(true);
  React.useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );

  const roundCode = round === ALL_ROUNDS ? undefined : round;
  const unitId = unit === ALL_UNITS ? undefined : Number(unit);

  // Filter option sources.
  const { data: filters } = useReportFilters(year);
  const { data: orgUnits = [] } = useOrganizationUnits();
  const yearOptions = React.useMemo(
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

  // KPI band + bảng chi tiết — theo toggle (group_by · period/week).
  const weeklyDetail = useWeeklyReport({
    academic_year: year,
    group_by: groupBy,
    round_code: roundCode,
    unit_id: unitId,
    week_start: weekStart,
  });
  // Đường băng chỉ tiêu cần ngành + LŨY KẾ (chỉ tiêu theo ngành, năm) — độc lập
  // toggle bảng. Khi toggle = major + lũy kế thì trùng key với weeklyDetail → dedup.
  const weeklyMajor = useWeeklyReport({
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

  const syncedDetail =
    weeklyDetail.data && weeklyDetail.data.academic_year === year
      ? weeklyDetail.data
      : undefined;
  const syncedMajor =
    weeklyMajor.data && weeklyMajor.data.academic_year === year
      ? weeklyMajor.data
      : undefined;
  const weekMeta = syncedDetail?.week;
  const navAnchor = weekStart ?? weekMeta?.week_start;

  const anyFetching =
    weeklyDetail.isFetching ||
    weeklyMajor.isFetching ||
    funnel.isFetching ||
    trend.isFetching ||
    matrix.isFetching;

  // Cockpit (lũy kế + ngành): rank ngành theo % chỉ tiêu tăng dần (nguy cơ đầu).
  const cockpitRows = React.useMemo(() => {
    if (!syncedDetail) return [];
    if (period !== "ytd" || groupBy !== "major") return syncedDetail.rows;
    return rankByQuotaGap(syncedDetail.rows);
  }, [syncedDetail, period, groupBy]);

  // Enforced unit scope (thin-client, pure derivation). Đọc scope_unit_id off
  // weeklyMajor (luôn fetch, ổn định) → manager bị khóa về đơn vị của mình.
  const enforcedUnit = weeklyMajor.data?.scope_unit_id ?? null;
  const scopeDetermined = weeklyMajor.data !== undefined;
  const isUnitScoped = scopeDetermined && unit === ALL_UNITS && enforcedUnit != null;
  const unitPickerDisabled = !scopeDetermined || isUnitScoped;
  const unitValue = isUnitScoped ? String(enforcedUnit) : unit;
  const enforcedUnitName = isUnitScoped
    ? flatUnits.find((u) => u.id === enforcedUnit)?.name
    : undefined;

  const onYearChange = (next: number) => {
    setYear(next);
    setRound(ALL_ROUNDS); // dependent filter may be invalid for the new year
    setWeekStart(undefined);
  };

  const onExport = async () => {
    setExporting(true);
    try {
      const { blob, filename } = await exportAdmissionSummary(year);
      downloadBlob(blob, filename);
      toast.success("Đã xuất báo cáo Excel");
    } catch (err) {
      toast.error(
        await blobErrorMessage(err as AxiosError, "Không xuất được báo cáo."),
      );
    } finally {
      if (mountedRef.current) setExporting(false);
    }
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
            Phễu · chỉ tiêu · tài chính · tải cán bộ — trực quan để nắm nhanh,
            bảng chi tiết để tra cứu &amp; xuất Excel.
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
        {/* KPI band ĐIỀU HÀNH — ỔN ĐỊNH (ngành · lũy kế năm), KHÔNG đổi theo toggle
            ẩn ở tab Bảng chi tiết (tránh KPI đổi mà control lại không nhìn thấy). */}
        <PanelState
          query={{
            isError: weeklyMajor.isError,
            error: weeklyMajor.error,
            data: syncedMajor,
          }}
          skeleton="h-24 w-full"
        >
          {syncedMajor && (
            <SummaryBand
              rows={syncedMajor.rows}
              totals={syncedMajor.totals}
              groupBy={syncedMajor.group_by}
            />
          )}
        </PanelState>

        <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
          <TabsList>
            <TabsTrigger value="visual" className="gap-1.5">
              <LayoutDashboard className="size-4" /> Trực quan
            </TabsTrigger>
            <TabsTrigger value="table" className="gap-1.5">
              <BarChart3 className="size-4" /> Bảng chi tiết
            </TabsTrigger>
          </TabsList>

          {/* ---- TAB TRỰC QUAN ---- */}
          <TabsContent value="visual" className="mt-4 space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Phễu LEAD theo giai đoạn">
                <p className="mb-3 -mt-1 text-xs text-muted-foreground">
                  Đếm <strong>LEAD</strong> đi tới từng bước pipeline (cohort đợt,
                  gồm khách vãng lai) — <em>khác</em> KPI “Hồ sơ đã nộp” (đếm theo
                  hồ sơ). Không so trực tiếp hai con số.
                </p>
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

            {/* Hồ sơ nộp / chỉ tiêu — tử số là HỒ SƠ NỘP (không phải nhập học);
                dùng weeklyMajor (ngành · lũy kế) độc lập toggle */}
            <Panel title="Hồ sơ nộp / chỉ tiêu — theo ngành">
              <p className="mb-3 -mt-1 text-xs text-muted-foreground">
                Mẫu số = <strong>chỉ tiêu</strong>; độ dài thanh = <strong>hồ sơ
                đã nộp</strong>/chỉ tiêu (KHÔNG phải nhập học). Trong đó hổ phách =
                đã đóng học phí HK1, xanh = đã nộp chưa đóng, phần trống = còn
                thiếu. Ngành nguy cơ (đầy thấp) hiện đầu.
              </p>
              <PanelState
                query={{
                  isError: weeklyMajor.isError,
                  error: weeklyMajor.error,
                  data: syncedMajor,
                }}
                skeleton="h-56 w-full"
              >
                {syncedMajor && (
                  <QuotaRunway rows={syncedMajor.rows} matrix={matrix.data} />
                )}
              </PanelState>
            </Panel>

            <Panel title="Tải hồ sơ theo ngành × cán bộ" caption="officer-major-matrix">
              <PanelState query={matrix} skeleton="h-56 w-full">
                {matrix.data && <OfficerMajorHeatmap matrix={matrix.data} />}
              </PanelState>
            </Panel>

            <Panel title="Công nợ học phí" caption="debt-report">
              <p className="mb-3 -mt-1 text-xs text-muted-foreground">
                Toàn bộ học phí còn nợ (mọi kỳ) · theo năm học và đơn vị — chưa lọc
                theo đợt. “Đã thu” ở đây = đã thu trên hoá đơn CÒN NỢ (khác dải KPI
                “Đã thu” tổng cash mọi phí).
              </p>
              <DebtPanel summary={debt.data?.summary} isLoading={debt.isLoading} />
            </Panel>

            <p className="text-xs text-muted-foreground">
              Số liệu tính lại theo phân bổ hiện tại — tuần đã qua có thể đổi sau
              khi công bố kết quả. <strong>Phễu</strong> đếm LEAD theo cohort đợt
              (gồm khách vãng lai) nên bậc “Đã nộp hồ sơ” có thể lệch nhẹ so với
              dải KPI “Hồ sơ nộp” (đếm theo mốc hồ sơ). KPI · đường băng chỉ tiêu ·
              heatmap · trend dùng chung một nguồn milestone.
            </p>
          </TabsContent>

          {/* ---- TAB BẢNG CHI TIẾT ---- */}
          <TabsContent value="table" className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <Tabs value={groupBy} onValueChange={(v) => setGroupBy(v as ReportGroupBy)}>
                  <TabsList>
                    <TabsTrigger value="major">Theo ngành</TabsTrigger>
                    <TabsTrigger value="officer">Theo nhân viên</TabsTrigger>
                  </TabsList>
                </Tabs>
                <Tabs value={period} onValueChange={(v) => setPeriod(v as Period)}>
                  <TabsList>
                    <TabsTrigger value="week">Tuần này</TabsTrigger>
                    <TabsTrigger value="ytd">Lũy kế năm</TabsTrigger>
                  </TabsList>
                </Tabs>
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label="Tuần trước"
                    disabled={!navAnchor}
                    onClick={() => navAnchor && setWeekStart(subDaysVN(navAnchor, 7))}
                  >
                    <ChevronLeft />
                  </Button>
                  <div className="min-w-[140px] rounded-md border px-3 py-1.5 text-center text-sm">
                    {weekMeta ? (
                      <>
                        <span className="font-medium">Tuần {weekMeta.iso_week}</span>
                        <span className="block text-xs text-muted-foreground">
                          {dm(weekMeta.week_start)} – {dm(weekMeta.week_end)}
                        </span>
                      </>
                    ) : (
                      <Skeleton className="h-8 w-full" />
                    )}
                  </div>
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label="Tuần sau"
                    disabled={!navAnchor}
                    onClick={() => navAnchor && setWeekStart(subDaysVN(navAnchor, -7))}
                  >
                    <ChevronRight />
                  </Button>
                  {weekStart && (
                    <Button variant="ghost" size="sm" onClick={() => setWeekStart(undefined)}>
                      Tuần này
                    </Button>
                  )}
                </div>
              </div>
              <Button
                variant="outline"
                onClick={onExport}
                disabled={exporting}
                title="Xuất số liệu tuyển sinh cả năm ra Excel (3 sheet: số liệu chung · chia theo nhân viên · quy ước)"
              >
                <Download className="mr-2 size-4" />
                {exporting ? "Đang xuất…" : "Xuất Excel"}
              </Button>
            </div>

            <PanelState
              query={{
                isError: weeklyDetail.isError,
                error: weeklyDetail.error,
                data: syncedDetail,
              }}
              skeleton="h-96 w-full"
            >
              {syncedDetail && (
                <>
                  <WeeklyReportTable
                    rows={cockpitRows}
                    totals={syncedDetail.totals}
                    groupBy={syncedDetail.group_by}
                    period={period}
                  />
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    {period === "ytd" && groupBy === "major" && round === ALL_ROUNDS && (
                      <span className="flex items-center gap-2">
                        Chỉ tiêu:
                        <span className="flex items-center gap-1">
                          <span className="size-2 rounded-full bg-rose-500" />&lt;50%
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="size-2 rounded-full bg-amber-500" />50–90%
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="size-2 rounded-full bg-emerald-500" />≥90%
                        </span>
                      </span>
                    )}
                    {period === "ytd" && groupBy === "major" && round !== ALL_ROUNDS && (
                      <span>Đang lọc đợt — tiến độ chỉ tiêu (theo cả năm) tạm ẩn.</span>
                    )}
                    {syncedDetail.data_quality.ambiguous_profiles > 0 && (
                      <span>· Nhiều NV trúng: {syncedDetail.data_quality.ambiguous_profiles}</span>
                    )}
                    {syncedDetail.data_quality.unresolved_profiles > 0 && (
                      <span>· Chưa phân loại ngành: {syncedDetail.data_quality.unresolved_profiles}</span>
                    )}
                    {groupBy === "officer" && syncedDetail.data_quality.unassigned_profiles > 0 && (
                      <span>· Chưa gán cán bộ: {syncedDetail.data_quality.unassigned_profiles}</span>
                    )}
                  </div>
                </>
              )}
            </PanelState>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
