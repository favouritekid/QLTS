"use client";

import * as React from "react";
import type { AxiosError } from "axios";
import { BarChart3, ChevronLeft, ChevronRight, Download } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { exportAdmissionSummary } from "@/lib/api/reports";
import { useReportFilters, useWeeklyReport } from "@/hooks/reports/useWeeklyReport";
import { cn } from "@/lib/utils";
import { blobErrorMessage, downloadBlob } from "@/lib/utils/download-blob";
import { subDaysVN } from "@/lib/utils/vn-date";
import type { ReportGroupBy } from "@/lib/zod/reports";

import { rankByQuotaGap } from "./cockpit-rank";
import { SummaryBand } from "./SummaryBand";
import { WeeklyReportTable, type Period } from "./WeeklyReportTable";

const CURRENT_YEAR = new Date().getFullYear();
const ALL_ROUNDS = "__all__";

const dm = (s: string) => `${s.slice(8, 10)}/${s.slice(5, 7)}`;

/** Friendly message instead of dumping a raw AxiosError / ZodError. */
function errMessage(err: unknown): string {
  const status = (err as { response?: { status?: number } })?.response?.status;
  if (status === 403) return "Bạn không có quyền xem báo cáo này.";
  if (status === 404) return "Không tìm thấy đơn vị/đợt đã chọn.";
  if (status === 400 || status === 422) return "Tham số không hợp lệ (năm/tuần/đợt).";
  return "Không tải được báo cáo. Vui lòng thử lại.";
}

export function AdmissionsWeeklyClient() {
  const [year, setYear] = React.useState(CURRENT_YEAR);
  const [round, setRound] = React.useState<string>(ALL_ROUNDS);
  const [groupBy, setGroupBy] = React.useState<ReportGroupBy>("major");
  const [period, setPeriod] = React.useState<Period>("ytd");
  const [weekStart, setWeekStart] = React.useState<string | undefined>(undefined);
  const [exporting, setExporting] = React.useState(false);
  // Guard the post-await setState if the user navigates away mid-export.
  const mountedRef = React.useRef(true);
  React.useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );

  // Filter options (năm config ∪ data + đợt) — admin & manager, same gate as report.
  const { data: filters } = useReportFilters(year);
  const yearOptions = React.useMemo(
    () =>
      Array.from(
        new Set([...(filters?.academic_years ?? []), CURRENT_YEAR]),
      ).sort((a, b) => b - a),
    [filters],
  );
  const roundCodes = filters?.rounds ?? [];

  const { data, isLoading, isError, error, isFetching } = useWeeklyReport({
    academic_year: year,
    group_by: groupBy,
    round_code: round === ALL_ROUNDS ? undefined : round,
    week_start: weekStart,
  });

  // Trust the response only once it matches the selected year: placeholderData
  // keeps the PREVIOUS year's payload during a switch, and navigating off its
  // stale week could POST a week the new academic_year rejects (422).
  const synced = data && data.academic_year === year ? data : undefined;
  const week = synced?.week;
  // Anchor prev/next on the locally-chosen week (rapid clicks aren't swallowed by
  // placeholder lag); fall back to the synced response's week.
  const navAnchor = weekStart ?? week?.week_start;

  // Cockpit (lũy kế + ngành): rank by % chỉ tiêu ascending so the most-behind
  // ngành surface first; buckets and no-target ngành sink to the bottom.
  const cockpitRows = React.useMemo(() => {
    if (!synced) return [];
    if (period !== "ytd" || groupBy !== "major") return synced.rows;
    return rankByQuotaGap(synced.rows);
  }, [synced, period, groupBy]);

  const onYearChange = (next: number) => {
    setYear(next);
    // dependent filters may be invalid for the new year → reset both.
    setWeekStart(undefined);
    setRound(ALL_ROUNDS);
  };

  // Xuất báo cáo "số liệu tổng" (snapshot cả năm) — KHÁC bảng tuần đang hiển thị.
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
      {/* Header + filters */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <BarChart3 className="size-6 text-primary" /> Báo cáo tuyển sinh
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Phễu lead → hồ sơ → tài chính theo{" "}
            {groupBy === "major" ? "ngành" : "cán bộ"}, theo tuần &amp; lũy kế.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Năm</label>
            <Select value={year.toString()} onValueChange={(v) => onYearChange(Number(v))}>
              <SelectTrigger className="w-24" aria-label="Năm">
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
            <label className="text-xs text-muted-foreground">Tuần</label>
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
                {week ? (
                  <>
                    <span className="font-medium">Tuần {week.iso_week}</span>
                    <span className="block text-xs text-muted-foreground">
                      {dm(week.week_start)} – {dm(week.week_end)}
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
      </div>

      {/* Toggles */}
      <div className="flex flex-wrap items-center justify-between gap-3">
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
      </div>

      {/* Body */}
      {isError ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {errMessage(error)}
        </div>
      ) : isLoading || !synced ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <div className={cn("space-y-4", isFetching && "opacity-60 transition-opacity")}>
          <SummaryBand
            rows={synced.rows}
            totals={synced.totals}
            groupBy={synced.group_by}
          />
          <WeeklyReportTable
            rows={cockpitRows}
            totals={synced.totals}
            groupBy={synced.group_by}
            period={period}
            // Nháp/HK1 (snapshot) chỉ hợp lệ ở lát cắt hiện tại; lùi tuần → ẩn.
            snapshotAsOfNow={weekStart == null}
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
            <span>
              Số liệu tính lại theo phân bổ hiện tại — tuần đã qua có thể đổi sau khi
              công bố kết quả.
            </span>
            {synced.data_quality.ambiguous_profiles > 0 && (
              <span>· Nhiều NV trúng: {synced.data_quality.ambiguous_profiles}</span>
            )}
            {synced.data_quality.unresolved_profiles > 0 && (
              <span>· Chưa phân loại ngành: {synced.data_quality.unresolved_profiles}</span>
            )}
            {groupBy === "officer" && synced.data_quality.unassigned_profiles > 0 && (
              <span>· Chưa gán cán bộ: {synced.data_quality.unassigned_profiles}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
