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
  useAdmissionWow,
  useOfficerMajorMatrix,
  usePipelineFunnel,
} from "@/hooks/reports/useAdmissionOverview";
import { useReportFilters, useWeeklyReport } from "@/hooks/reports/useWeeklyReport";
import { exportAdmissionSummary } from "@/lib/api/reports";
import { cn } from "@/lib/utils";
import { blobErrorMessage, downloadBlob } from "@/lib/utils/download-blob";
import { dmVN, isoWeekYearVN, subDaysVN } from "@/lib/utils/vn-date";
import type { AdmissionWeeklyReport, ReportGroupBy } from "@/lib/zod/reports";

import { ActionNeeded } from "./ActionNeeded";
import { DebtPanel } from "./DebtPanel";
import { OfficerMajorHeatmap } from "./OfficerMajorHeatmap";
import { OverviewFunnel } from "./OverviewFunnel";
import { OverviewTrend } from "./OverviewTrend";
import { QuotaRunway } from "./QuotaRunway";
import { WowStrip } from "./WowStrip";
import {
  ALL_ROUNDS,
  ALL_UNITS,
  CURRENT_YEAR,
  canonicalizeOverviewState,
  describeExportScope,
  isSliceCurrent,
  resolveApiUnitId,
  serializeOverviewParams,
  useOverviewUrlState,
  type HeatmapTab,
  type OverviewTab,
} from "./useOverviewUrlState";

/** Empty ổn định — tránh churn dep của effect canonicalize khi filters đang tải. */
const NO_ROUNDS: readonly string[] = [];

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
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border bg-card p-4 shadow-sm", className)}>
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** Panel body state: lỗi (role=alert) → dữ liệu → skeleton (role=status). */
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
      <div
        role="alert"
        className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
      >
        {errMessage(query.error)}
      </div>
    );
  }
  if (query.data) return <>{children}</>;
  return (
    <div role="status" aria-live="polite" aria-busy>
      <span className="sr-only">Đang tải dữ liệu…</span>
      <Skeleton className={skeleton} />
    </div>
  );
}

interface FlatUnit {
  id: number;
  name: string;
  depth: number;
}

export function AdmissionOverviewClient() {
  // URL = NGUỒN TRẠNG THÁI (deep-link · reload · Back/Forward khôi phục cùng lát
  // dữ liệu). Không mirror useState → không có vòng lặp state ↔ URL.
  const { state, patch, commit, search } = useOverviewUrlState();
  const { tab, year, round, unit, groupBy, period, weekStart, heatmap } = state;

  const [exporting, setExporting] = React.useState(false);
  const mountedRef = React.useRef(true);
  React.useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );

  // Filter option sources.
  const filtersQuery = useReportFilters(year);
  const filters = filtersQuery.data;
  const { data: orgUnits = [] } = useOrganizationUnits();
  const yearOptions = React.useMemo(
    () =>
      Array.from(
        new Set([...(filters?.academic_years ?? []), CURRENT_YEAR, year]),
      ).sort((a, b) => b - a),
    [filters, year],
  );
  const roundCodes = filters?.rounds ?? NO_ROUNDS;
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

  // Round hợp lệ theo NĂM: chỉ gửi round_code khi catalog đợt của ĐÚNG năm đã tải
  // (không phải placeholder năm cũ) và mã đợt có trong danh sách → không request lỗi.
  const roundReady = filters !== undefined && !filtersQuery.isPlaceholderData;
  const roundCode =
    round !== ALL_ROUNDS && roundReady && roundCodes.includes(round)
      ? round
      : undefined;

  // Scope-probe: LUÔN gửi unit_id=undefined để học scope người dùng an toàn (không
  // bao giờ gửi unit của URL trước khi biết scope). Manager & admin-không-lọc-đơn-vị
  // trùng key với weeklyMajor → React Query dedup (1 request); chỉ admin CÓ lọc đơn
  // vị mới tách thành 2 query. Không self-cycle (key probe không phụ thuộc scope).
  const scopeProbe = useWeeklyReport({
    academic_year: year,
    group_by: "major",
    round_code: roundCode,
    unit_id: undefined,
  });
  const scopeResolved = scopeProbe.data !== undefined;
  const enforcedUnit = scopeProbe.data?.scope_unit_id ?? null;

  const urlUnitId = unit === ALL_UNITS ? undefined : Number(unit);
  const effectiveUnitId = resolveApiUnitId({ scopeResolved, enforcedUnit, urlUnitId });

  const scopeParams = {
    academic_year: year,
    round_code: roundCode,
    unit_id: effectiveUnitId,
  };

  // Query cho BẢNG chi tiết — theo toggle (group_by · period/week). KHÔNG cấp
  // KPI band (KPI dùng weeklyMajor ổn định).
  const weeklyDetail = useWeeklyReport({
    academic_year: year,
    group_by: groupBy,
    round_code: roundCode,
    unit_id: effectiveUnitId,
    week_start: weekStart,
  });
  // KPI band ĐIỀU HÀNH + "Hồ sơ nộp / chỉ tiêu" cần ngành + LŨY KẾ (chỉ tiêu theo
  // ngành, năm) — độc lập toggle. Trùng key khi major+lũy-kế → React Query dedup.
  const weeklyMajor = useWeeklyReport({
    academic_year: year,
    group_by: "major",
    round_code: roundCode,
    unit_id: effectiveUnitId,
  });
  const funnel = usePipelineFunnel(scopeParams);
  const trend = useAdmissionTrend(scopeParams);
  const matrix = useOfficerMajorMatrix(scopeParams);
  // WoW: tổng giống nhau bất kể group_by (Σ mọi hồ sơ) → fetch "major", render totals.
  const wow = useAdmissionWow({ ...scopeParams, group_by: "major" });
  const debt = useDebtReport({
    academic_year: year,
    unit_id: effectiveUnitId,
    fee_type: "tuition",
  });

  // `placeholderData: prev` giữ lát cắt CŨ hiển thị trong lúc đổi bộ lọc → phải
  // xác nhận response phản chiếu ĐÚNG (năm · đợt · đơn vị) hiện tại trước khi coi là
  // "synced". Thêm 2 điều kiện bootstrap: (a) đã học scope người dùng, (b) đợt đã
  // sẵn sàng trong catalog — nếu không, deep-link có đơn-vị/đợt lúc mới tải sẽ hiện
  // báo cáo toàn-trường/toàn-năm như dữ liệu thật. BE echo round_code + scope_unit_id.
  const expectedRound = roundCode ?? null;
  const expectedUnit = effectiveUnitId ?? enforcedUnit ?? null;
  const roundResolved =
    round === ALL_ROUNDS || (roundReady && roundCodes.includes(round));
  const sliceMatches = (d: AdmissionWeeklyReport | undefined) =>
    isSliceCurrent(d, {
      year,
      round: expectedRound,
      unit: expectedUnit,
      scopeResolved,
      roundResolved,
    });
  const syncedDetail = sliceMatches(weeklyDetail.data)
    ? weeklyDetail.data
    : undefined;
  const syncedMajor = sliceMatches(weeklyMajor.data)
    ? weeklyMajor.data
    : undefined;
  const weekMeta = syncedDetail?.week;
  const navAnchor = weekStart ?? weekMeta?.week_start;
  // Lát cắt hiện tại CÓ chỉ tiêu hay không → lái nhãn panel "Hồ sơ nộp / chỉ tiêu"
  // để tiêu đề không nói về thứ đang thiếu. BE trả quota=null khi HAI lý do độc lập:
  //   (a) lọc 1 đợt (chỉ tiêu đặt theo NĂM), hoặc
  //   (b) lát cắt theo đơn vị (chỉ tiêu là mục tiêu CẤP TRƯỜNG theo offering, KHÔNG
  //       chia theo đơn vị) — luôn đúng với manager.
  // Phân biệt lý do để copy không nói sai "lọc một đợt" khi manager chọn "Tất cả đợt".
  // Dùng EVERY (đồng bộ QuotaRunway): chỉ coi "có chỉ tiêu" khi MỌI ngành đều có —
  // lát cắt hỗn hợp (một số ngành chưa đặt chỉ tiêu) → xếp theo số hồ sơ.
  const majorRowsQ =
    syncedMajor?.rows.filter((r) => !r.is_bucket && r.group_key != null) ?? [];
  const majorHasQuota =
    majorRowsQ.length > 0 &&
    majorRowsQ.every(
      (r) => r.admission.quota != null && r.admission.quota > 0,
    );
  // Lát cắt hỗn hợp = toàn-trường + mọi-đợt nhưng CÓ ngành thiếu chỉ tiêu (khác lý
  // do lọc-đợt / theo-đơn-vị) → note nêu đúng "một số ngành chưa đặt chỉ tiêu".
  const unitScoped = syncedMajor?.scope_unit_id != null;
  const quotaMixed =
    !majorHasQuota &&
    !unitScoped &&
    round === ALL_ROUNDS &&
    majorRowsQ.some((r) => r.admission.quota != null && r.admission.quota > 0);

  // Panel overview (funnel/trend/matrix/wow/debt) fetch theo scopeParams, KHÔNG qua
  // sync-slice như weekly. Trong bootstrap deep-link (scope CHƯA resolve) chúng fetch
  // whole-school (effectiveUnitId chưa có) → CHỈ hiển thị khi ĐÃ học scope, tránh
  // admin thoáng thấy toàn-trường (không dimmed sau khi fetch xong).
  const funnelData = scopeResolved ? funnel.data : undefined;
  const trendData = scopeResolved ? trend.data : undefined;
  const matrixData = scopeResolved ? matrix.data : undefined;
  const wowData = scopeResolved ? wow.data : undefined;
  const debtData = scopeResolved ? debt.data : undefined;
  const debtBusy = !scopeResolved || debt.isLoading;

  // Chặn điều hướng tuần RA NGOÀI năm tuyển sinh: BE từ chối week_start có ISO year
  // != academic_year (đối xứng), nên nút phải tự khoá ở tuần đầu/cuối năm thay vì
  // để bấm rồi nhận 400. So bằng ISO-week-year của tuần kế/trước (mirror BE).
  const prevWeekStart = navAnchor ? subDaysVN(navAnchor, 7) : undefined;
  const nextWeekStart = navAnchor ? subDaysVN(navAnchor, -7) : undefined;
  const prevOutOfYear =
    !!prevWeekStart && isoWeekYearVN(prevWeekStart) !== year;
  const nextOutOfYear =
    !!nextWeekStart && isoWeekYearVN(nextWeekStart) !== year;

  const anyFetching =
    weeklyDetail.isFetching ||
    weeklyMajor.isFetching ||
    funnel.isFetching ||
    trend.isFetching ||
    matrix.isFetching ||
    wow.isFetching;

  // Cockpit (lũy kế + ngành): rank ngành theo % chỉ tiêu tăng dần (nguy cơ đầu).
  const cockpitRows = React.useMemo(() => {
    if (!syncedDetail) return [];
    if (period !== "ytd" || groupBy !== "major") return syncedDetail.rows;
    return rankByQuotaGap(syncedDetail.rows);
  }, [syncedDetail, period, groupBy]);

  // Hiển thị khóa đơn vị (thin-client). Người dùng bị giới hạn (manager) → picker
  // khóa & hiện đúng đơn vị; URL cũng được canonicalize về đơn vị đó (effect dưới).
  const isUnitScoped = scopeResolved && enforcedUnit != null;
  const unitPickerDisabled = !scopeResolved || isUnitScoped;
  const unitValue = isUnitScoped ? String(enforcedUnit) : unit;
  const enforcedUnitName = isUnitScoped
    ? flatUnits.find((u) => u.id === enforcedUnit)?.name
    : undefined;

  // Canonicalize URL (replace, không tạo history): round không thuộc năm → bỏ;
  // manager khóa unit về scope_unit_id (bỏ unit lạ); và LÀM SẠCH mọi param sai/rác/
  // mặc-định về dạng chuẩn (serialize LUÔN ghi year → share-link không đổi nghĩa khi
  // sang năm mới). So chuỗi canonical với URL thô → idempotent, hội tụ, không loop.
  React.useEffect(() => {
    const canonical = canonicalizeOverviewState(state, {
      roundReady,
      roundCodes,
      scopeResolved,
      enforcedUnit,
    });
    if (serializeOverviewParams(canonical) !== search) {
      commit(canonical, { replace: true });
    }
  }, [state, search, roundReady, roundCodes, scopeResolved, enforcedUnit, commit]);

  const onYearChange = (next: number) => {
    // Đổi năm: đợt & mốc tuần của năm cũ không còn hợp lệ → dọn cùng lúc (1 lần push).
    patch({ year: next, round: ALL_ROUNDS, weekStart: undefined });
  };

  // Export bám ĐÚNG lát cắt đơn vị đang xem (admin chọn đơn vị → xuất đơn vị đó;
  // manager → BE tự ép về đơn vị của họ khi unit_id bỏ trống). Nhãn derive từ
  // expectedUnit (SCOPE hiện tại) — KHÔNG từ syncedMajor (response có thể trễ/
  // toàn-trường lúc bootstrap → nhãn nhảy sai). Nút khóa tới khi scopeResolved để
  // không xuất khi effectiveUnitId chưa phản ánh đúng scope (deep-link ?unit=…).
  const exportScopeLabel = describeExportScope(expectedUnit, flatUnits);

  const onExport = async () => {
    setExporting(true);
    try {
      const { blob, filename } = await exportAdmissionSummary(
        year,
        effectiveUnitId,
      );
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
            <LayoutDashboard aria-hidden className="size-6 text-primary" /> Tổng
            quan tuyển sinh
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Chỉ tiêu · công nợ · phễu · tài chính — <strong>Điều hành</strong>{" "}
            để nắm nhanh &amp; xử lý, <strong>Phân tích chi tiết</strong>{" "}
            để tra cứu &amp; xuất Excel.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label htmlFor="filter-year" className="text-xs text-muted-foreground">
              Năm học
            </label>
            <Select value={year.toString()} onValueChange={(v) => onYearChange(Number(v))}>
              <SelectTrigger id="filter-year" className="w-24" aria-label="Năm học">
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
            <label htmlFor="filter-round" className="text-xs text-muted-foreground">
              Đợt
            </label>
            <Select value={round} onValueChange={(v) => patch({ round: v })}>
              <SelectTrigger id="filter-round" className="w-32" aria-label="Đợt">
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
            <label htmlFor="filter-unit" className="text-xs text-muted-foreground">
              Đơn vị
            </label>
            <Select
              value={unitValue}
              onValueChange={(v) => patch({ unit: v })}
              disabled={unitPickerDisabled}
            >
              <SelectTrigger id="filter-unit" className="w-44" aria-label="Đơn vị">
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

      <div
        aria-busy={anyFetching}
        className={cn("space-y-4", anyFetching && "opacity-60 transition-opacity")}
      >
        {/* KPI band ĐIỀU HÀNH — ỔN ĐỊNH (ngành · lũy kế năm), KHÔNG đổi theo toggle
            của tab Phân tích (tránh KPI đổi mà control lại không nhìn thấy). */}
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

        <Tabs value={tab} onValueChange={(v) => patch({ tab: v as OverviewTab })}>
          <TabsList>
            <TabsTrigger value="exec" className="gap-1.5">
              <LayoutDashboard aria-hidden className="size-4" /> Điều hành
            </TabsTrigger>
            <TabsTrigger value="analysis" className="gap-1.5">
              <BarChart3 aria-hidden className="size-4" /> Phân tích chi tiết
            </TabsTrigger>
          </TabsList>

          {/* ---- TAB ĐIỀU HÀNH: khu hành động trước, phân tích nguyên nhân sau ---- */}
          <TabsContent value="exec" className="mt-4 space-y-4">
            {/* 0. Cần xử lý ngay — cảnh báo hành động (đầu tab điều hành) */}
            <Panel title="Cần xử lý ngay">
              <PanelState
                query={{
                  isError: weeklyMajor.isError,
                  error: weeklyMajor.error,
                  data: syncedMajor,
                }}
                skeleton="h-24 w-full"
              >
                {syncedMajor && (
                  <ActionNeeded
                    report={syncedMajor}
                    debt={debtData}
                    debtLoading={debtBusy}
                    debtError={debt.isError}
                  />
                )}
              </PanelState>
            </Panel>

            {/* 0b. Nhịp so tuần trước — biến động 2 tuần ISO đã hoàn tất (WoW) */}
            <Panel title="Nhịp so tuần trước">
              <PanelState
                query={{ isError: wow.isError, error: wow.error, data: wowData }}
                skeleton="h-28 w-full"
              >
                {wowData && <WowStrip wow={wowData} />}
              </PanelState>
            </Panel>

            {/* 1. Chỉ tiêu — tử số là HỒ SƠ NỘP (không phải nhập học). Khi BE trả
                quota=null (lọc đợt HOẶC lát cắt theo đơn vị) → đổi CẢ tiêu đề lẫn mô
                tả sang thang "số hồ sơ", nêu ĐÚNG lý do (không nói "lọc một đợt" khi
                nguyên nhân là scope đơn vị). */}
            <Panel
              title={
                majorHasQuota
                  ? "Hồ sơ nộp / chỉ tiêu — theo ngành"
                  : "Hồ sơ nộp — theo ngành"
              }
            >
              <p className="mb-3 -mt-1 text-xs text-muted-foreground">
                {majorHasQuota ? (
                  <>
                    <strong>Độ dài thanh = chỉ tiêu</strong> (ngành chỉ tiêu lớn
                    nhất = dài nhất, vạch = mốc chỉ tiêu). Phần tô ={" "}
                    <strong>hồ sơ đã nộp</strong> (hổ phách = đã đóng học phí HK1,
                    xanh = đã nộp chưa đóng), phần trống = còn thiếu so chỉ tiêu
                    (KHÔNG phải nhập học). Ngành thiếu nhiều so chỉ tiêu hiện đầu.
                  </>
                ) : (
                  <>
                    {unitScoped ? (
                      <>
                        <strong>Lát cắt theo đơn vị chưa có chỉ tiêu được phân bổ
                        riêng</strong>; đang xếp theo số hồ sơ.
                      </>
                    ) : quotaMixed ? (
                      <>
                        <strong>Một số ngành chưa đặt chỉ tiêu</strong>; đang xếp
                        theo số hồ sơ (để không hiển thị sai).
                      </>
                    ) : (
                      <>
                        <strong>Chỉ tiêu đặt theo năm</strong> nên không áp dụng
                        khi lọc một đợt; đang xếp theo số hồ sơ.
                      </>
                    )}{" "}
                    Độ dài thanh = <strong>số hồ sơ đã nộp</strong> theo thang
                    tương đối (ngành nhiều hồ sơ nhất = thanh đầy). Trong đó hổ
                    phách = đã đóng học phí HK1, xanh = đã nộp chưa đóng. Ngành
                    nhiều hồ sơ hiện đầu.
                  </>
                )}
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
                  <QuotaRunway rows={syncedMajor.rows} matrix={matrixData} />
                )}
              </PanelState>
            </Panel>

            {/* 2. Công nợ học phí */}
            <Panel title="Công nợ học phí">
              <p className="mb-3 -mt-1 text-xs text-muted-foreground">
                Toàn bộ học phí còn nợ (mọi kỳ) · theo năm học và đơn vị — chưa lọc
                theo đợt. “Đã thu” ở đây = đã thu trên hoá đơn CÒN NỢ (khác dải KPI
                “Thu ròng tuyển sinh” = tổng cash mọi phí).
              </p>
              <DebtPanel summary={debtData?.summary} isLoading={debtBusy} />
            </Panel>

            {/* 3. Phễu + 4. Xu hướng — phân tích nguyên nhân, đặt sau khu hành động */}
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="LEAD theo giai đoạn pipeline">
                <p className="mb-3 -mt-1 text-xs text-muted-foreground">
                  Số <strong>LEAD đang ở mỗi bậc</strong> pipeline (mỗi lead đếm
                  đúng 1 lần — khớp Pipeline Board / danh sách Lead). Phân bố hiện
                  trạng, <em>không</em> lũy kế; <em>khác</em> KPI “Hồ sơ đã nộp”
                  (đếm theo hồ sơ). Không so trực tiếp hai con số.
                </p>
                <PanelState
                  query={{ isError: funnel.isError, error: funnel.error, data: funnelData }}
                  skeleton="h-64 w-full"
                >
                  {funnelData && <OverviewFunnel funnel={funnelData} />}
                </PanelState>
              </Panel>
              <Panel title="Nhịp tích luỹ 8 tuần">
                <PanelState
                  query={{ isError: trend.isError, error: trend.error, data: trendData }}
                  skeleton="h-64 w-full"
                >
                  {trendData && <OverviewTrend trend={trendData} />}
                </PanelState>
              </Panel>
            </div>

            <p className="text-xs text-muted-foreground">
              Số liệu tính lại theo phân bổ hiện tại — tuần đã qua có thể đổi sau
              khi công bố kết quả. Dải KPI · chỉ tiêu · heatmap · trend dùng chung
              nguồn milestone (nhất quán); phễu đếm LEAD (đã ghi rõ trong panel).
            </p>
          </TabsContent>

          {/* ---- TAB PHÂN TÍCH CHI TIẾT: heatmap + bảng đầy đủ (truy vấn sâu) ---- */}
          <TabsContent value="analysis" className="mt-4 space-y-4">
            <Panel title="Tải hồ sơ theo ngành × cán bộ">
              <PanelState
                query={{ isError: matrix.isError, error: matrix.error, data: matrixData }}
                skeleton="h-56 w-full"
              >
                {matrixData && (
                  <OfficerMajorHeatmap
                    matrix={matrixData}
                    tabKey={heatmap}
                    onTabKeyChange={(k) => patch({ heatmap: k as HeatmapTab })}
                  />
                )}
              </PanelState>
            </Panel>

            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <Tabs value={groupBy} onValueChange={(v) => patch({ groupBy: v as ReportGroupBy })}>
                    <TabsList>
                      <TabsTrigger value="major">Theo ngành</TabsTrigger>
                      <TabsTrigger value="officer">Theo nhân viên</TabsTrigger>
                    </TabsList>
                  </Tabs>
                  <Tabs value={period} onValueChange={(v) => patch({ period: v as Period })}>
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
                      disabled={!navAnchor || prevOutOfYear}
                      onClick={() =>
                        prevWeekStart && patch({ weekStart: prevWeekStart })
                      }
                    >
                      <ChevronLeft aria-hidden />
                    </Button>
                    <div className="min-w-[140px] rounded-md border px-3 py-1.5 text-center text-sm">
                      {weekMeta ? (
                        <>
                          <span className="font-medium">Tuần {weekMeta.iso_week}</span>
                          <span className="block text-xs text-muted-foreground">
                            {dmVN(weekMeta.week_start)} – {dmVN(weekMeta.week_end)}
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
                      disabled={!navAnchor || nextOutOfYear}
                      onClick={() =>
                        nextWeekStart && patch({ weekStart: nextWeekStart })
                      }
                    >
                      <ChevronRight aria-hidden />
                    </Button>
                    {weekStart && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => patch({ weekStart: undefined })}
                      >
                        Tuần này
                      </Button>
                    )}
                  </div>
                </div>
                <Button
                  variant="outline"
                  onClick={onExport}
                  disabled={exporting || !scopeResolved}
                  title={`Xuất số liệu tuyển sinh cả năm · ${exportScopeLabel} ra Excel (3 sheet: số liệu chung · chia theo nhân viên · quy ước)`}
                >
                  <Download aria-hidden className="mr-2 size-4" />
                  {exporting
                    ? "Đang xuất…"
                    : `Xuất Excel (cả năm · ${exportScopeLabel})`}
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
                      // Cờ từ CHÍNH response (đi kèm data) → tự đúng cả tuần lịch
                      // sử, năm quá-khứ/tương-lai (anchor≠today), và placeholderData
                      // (response cũ mang cờ cũ) — chính xác hơn suy từ weekStart.
                      snapshotAsOfNow={syncedDetail.snapshot_as_of_now}
                    />
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      {/* Thang màu chỉ hiện khi bảng THỰC SỰ có cột tiến độ chỉ tiêu
                          (BE gắn quota) — không dựa vào round vì lát cắt theo đơn vị
                          "Tất cả đợt" vẫn quota=null (khớp showQuota của bảng). */}
                      {period === "ytd" &&
                        groupBy === "major" &&
                        syncedDetail.totals.admission.quota != null && (
                          <span className="flex items-center gap-2">
                            Chỉ tiêu:
                            <span className="flex items-center gap-1">
                              <span aria-hidden className="size-2 rounded-full bg-rose-500" />&lt;50%
                            </span>
                            <span className="flex items-center gap-1">
                              <span aria-hidden className="size-2 rounded-full bg-amber-500" />50–90%
                            </span>
                            <span className="flex items-center gap-1">
                              <span aria-hidden className="size-2 rounded-full bg-emerald-500" />≥90%
                            </span>
                          </span>
                        )}
                      {period === "ytd" &&
                        groupBy === "major" &&
                        syncedDetail.totals.admission.quota == null && (
                          <span>
                            {unitScoped
                              ? "Lát cắt theo đơn vị chưa có chỉ tiêu được phân bổ riêng; tiến độ chỉ tiêu tạm ẩn."
                              : "Đang lọc đợt — tiến độ chỉ tiêu (theo cả năm) tạm ẩn."}
                          </span>
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
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
