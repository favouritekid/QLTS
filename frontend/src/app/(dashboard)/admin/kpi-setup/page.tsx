"use client";

import { useState } from "react";
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
import { useKpiCoverage } from "@/hooks/useKpiSetup";
import { useAuth } from "@/hooks/useAuth";
import { KpiSetupProgressBar } from "./_components/KpiSetupProgressBar";
import { InlineSummary } from "./_components/InlineSummary";
import { HolidaySection } from "./_components/HolidaySection";
import { UnitKpiCard } from "./_components/UnitKpiCard";
import { KpiConfigLinkCard } from "./_components/KpiConfigLinkCard";

const currentYear = new Date().getFullYear();
const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - 2 + i);

export default function KpiSetupPage() {
  const [fiscalYear, setFiscalYear] = useState(currentYear);
  const { data: report, isLoading, error } = useKpiCoverage(fiscalYear);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="Thiết lập KPI"
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

      {isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-[300px] w-full" />
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error.response?.data?.detail || "Không thể tải dữ liệu KPI coverage."}
        </div>
      )}

      {report && (
        <div className="space-y-6">
          <KpiSetupProgressBar report={report} />

          <InlineSummary report={report} isAdmin={isAdmin} />

          <HolidaySection
            holiday={report.holiday_status}
            fiscalYear={report.fiscal_year}
            isAdmin={isAdmin}
          />

          <section className="space-y-4">
            <h2 className="text-lg font-semibold">Đơn vị & Chỉ tiêu</h2>
            {report.units.map((unit) => (
              <UnitKpiCard
                key={unit.unit_id}
                unit={unit}
                fiscalYear={report.fiscal_year}
                isAdmin={isAdmin}
              />
            ))}
          </section>

          <KpiConfigLinkCard />
        </div>
      )}
    </PageContainer>
  );
}
