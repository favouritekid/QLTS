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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { useKpiCoverage } from "@/hooks/useKpiSetup";
import { KpiSetupProgressBar } from "./_components/KpiSetupProgressBar";
import { HolidaySection } from "./_components/HolidaySection";
import { UnitPlansSection } from "./_components/UnitPlansSection";
import { OfficerTargetsSection } from "./_components/OfficerTargetsSection";
import { ReviewSection } from "./_components/ReviewSection";

const currentYear = new Date().getFullYear();
const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - 2 + i);

export default function KpiSetupPage() {
  const [fiscalYear, setFiscalYear] = useState(currentYear);
  const [activeTab, setActiveTab] = useState("holidays");
  const { data: report, isLoading, error } = useKpiCoverage(fiscalYear);

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

          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList>
              <TabsTrigger value="holidays">Lịch nghỉ</TabsTrigger>
              <TabsTrigger value="units">Kế hoạch đơn vị</TabsTrigger>
              <TabsTrigger value="officers">Chỉ tiêu officer</TabsTrigger>
              <TabsTrigger value="review">Tổng quan</TabsTrigger>
            </TabsList>

            <TabsContent value="holidays" className="mt-4">
              <HolidaySection
                holiday={report.holiday_status}
                fiscalYear={report.fiscal_year}
              />
            </TabsContent>

            <TabsContent value="units" className="mt-4">
              <UnitPlansSection
                units={report.units}
                fiscalYear={report.fiscal_year}
              />
            </TabsContent>

            <TabsContent value="officers" className="mt-4">
              <OfficerTargetsSection units={report.units} />
            </TabsContent>

            <TabsContent value="review" className="mt-4">
              <ReviewSection
                report={report}
                onTabChange={setActiveTab}
              />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </PageContainer>
  );
}
