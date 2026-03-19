"use client";

import { useMemo, useState, useCallback } from "react";
import { Target } from "lucide-react";

import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useKpiCoverage, useKpiConfigs, useKpiTargets } from "@/hooks/useKpiSetup";
import { useKpiCatalog } from "@/lib/hooks/use-kpi-catalog";
import { useAuth } from "@/hooks/useAuth";

// Reuse existing components from kpi-setup (cross-page import)
import { KpiSetupProgressBar } from "../kpi-setup/_components/KpiSetupProgressBar";
import { HolidaySection } from "../kpi-setup/_components/HolidaySection";
import { UnitKpiCard } from "../kpi-setup/_components/UnitKpiCard";
import { CreateEditPlanDialog, type PlanDialogMode } from "../kpi-setup/_components/CreateEditPlanDialog";

// Hub-specific components
import { ConfigurationMatrix } from "./_components/ConfigurationMatrix";
import { AggregatedWarnings } from "./_components/AggregatedWarnings";
import { QuickActionsFooter } from "./_components/QuickActionsFooter";
import { HubSummaryCards } from "./_components/HubSummaryCards";

const currentYear = new Date().getFullYear();
const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - 2 + i);

export default function KpiHubPage() {
  const [fiscalYear, setFiscalYear] = useState(currentYear);
  const [planDialog, setPlanDialog] = useState<PlanDialogMode>(null);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  // Data hooks
  const { data: report, isLoading: loadingCoverage, error: coverageError } = useKpiCoverage(fiscalYear);
  const { catalog, catalogMap } = useKpiCatalog();
  const { data: configs } = useKpiConfigs({ is_active: true });
  const { data: targets } = useKpiTargets({ fiscal_year: fiscalYear, is_active: true });

  // Derive distribution scope from coverage report (already backend-filtered)
  const { distributionUnitIds, distributionOfficerIds, totalOfficers } = useMemo(() => {
    if (!report) {
      return {
        distributionUnitIds: new Set<number>(),
        distributionOfficerIds: new Set<number>(),
        totalOfficers: 0,
      };
    }
    const unitIds = new Set(report.units.map((u) => u.unit_id));
    const officerIds = new Set(
      report.units.flatMap((u) => u.officers.map((o) => o.officer_id)),
    );
    return {
      distributionUnitIds: unitIds,
      distributionOfficerIds: officerIds,
      totalOfficers: officerIds.size,
    };
  }, [report]);

  const handleScrollToUnit = useCallback((unitId: number) => {
    document
      .getElementById(`unit-${unitId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const handleOpenPlanDialog = useCallback(
    (unitId: number, unitName: string) => {
      setPlanDialog({ type: "create", unitId, unitName });
    },
    [],
  );

  const handleIndicatorClick = useCallback((sectionId: string) => {
    document
      .getElementById(sectionId)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="Tổng quan Cấu hình KPI"
        icon={<Target aria-hidden="true" className="h-6 w-6" />}
        actions={
          <Select
            value={String(fiscalYear)}
            onValueChange={(v) => setFiscalYear(Number(v))}
          >
            <SelectTrigger className="w-[140px]" aria-label="Chọn năm tài chính">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {yearOptions.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  Năm {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {/* Loading state */}
      {loadingCoverage && (
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
          <Skeleton className="h-[300px] w-full" />
        </div>
      )}

      {/* Error state */}
      {coverageError && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {coverageError.response?.data?.detail ||
            "Không thể tải dữ liệu KPI coverage."}
        </div>
      )}

      {/* Main content */}
      {report && (
        <div className="space-y-6">
          {/* ① System Readiness */}
          <KpiSetupProgressBar
            report={report}
            onIndicatorClick={handleIndicatorClick}
          />

          {/* ② Summary Cards */}
          <HubSummaryCards report={report} />

          {/* ③ Configuration Matrix */}
          {catalog.length > 0 && (
            <ConfigurationMatrix
              catalog={catalog}
              catalogMap={catalogMap}
              configs={configs ?? []}
              targets={targets ?? []}
              distributionUnitIds={distributionUnitIds}
              distributionOfficerIds={distributionOfficerIds}
              totalDistributionUnits={report.summary.total_units}
              totalOfficers={totalOfficers}
            />
          )}

          {/* ④ Holiday Section (id="holiday-section" is on the Card inside HolidaySection) */}
          <HolidaySection
            holiday={report.holiday_status}
            fiscalYear={report.fiscal_year}
            isAdmin={isAdmin}
          />

          {/* ⑤ Unit Coverage */}
          <section id="unit-coverage-section" className="space-y-4">
            <h2 className="text-lg font-semibold">Đơn vị & Chỉ tiêu</h2>
            {report.units.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4">
                Không có đơn vị nào có quy tắc phân phối tuyển sinh.
              </p>
            ) : (
              report.units.map((unit) => (
                <UnitKpiCard
                  key={unit.unit_id}
                  unit={unit}
                  fiscalYear={report.fiscal_year}
                  isAdmin={isAdmin}
                />
              ))
            )}
          </section>

          {/* ⑥ Aggregated Warnings */}
          <AggregatedWarnings
            report={report}
            configs={configs ?? []}
            catalogMap={catalogMap}
            isAdmin={isAdmin}
            onScrollToUnit={handleScrollToUnit}
            onOpenPlanDialog={handleOpenPlanDialog}
          />

          {/* ⑦ Quick Actions */}
          <QuickActionsFooter />
        </div>
      )}

      {/* Plan dialog triggered from warnings */}
      {planDialog && (
        <CreateEditPlanDialog
          mode={planDialog}
          fiscalYear={fiscalYear}
          onClose={() => setPlanDialog(null)}
        />
      )}
    </PageContainer>
  );
}
