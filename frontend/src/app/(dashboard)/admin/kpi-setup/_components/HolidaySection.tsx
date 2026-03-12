"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { CalendarDays, ChevronDown, ExternalLink, Loader2, Sparkles } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useSeedHolidays } from "@/hooks/useKpiPlanning";
import { kpiSetupKeys } from "@/hooks/useKpiSetup";
import type { HolidayStatusCoverage } from "@/types/kpi-setup.types";

interface Props {
  holiday: HolidayStatusCoverage;
  fiscalYear: number;
  isAdmin?: boolean;
}

export function HolidaySection({
  holiday,
  fiscalYear,
  isAdmin = false,
}: Props) {
  const [open, setOpen] = useState(!holiday.is_complete);
  const [prevComplete, setPrevComplete] = useState(holiday.is_complete);
  if (holiday.is_complete !== prevComplete) {
    setPrevComplete(holiday.is_complete);
    setOpen(!holiday.is_complete);
  }
  const seedMut = useSeedHolidays();
  const qc = useQueryClient();

  const handleSeed = useCallback(async () => {
    await seedMut.mutateAsync(fiscalYear);
    await qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
  }, [fiscalYear, qc, seedMut]);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card id="holiday-section">
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CalendarDays aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">Lịch nghỉ {fiscalYear}</CardTitle>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={holiday.is_complete ? "default" : "destructive"}>
                  {holiday.is_complete ? "Hoàn tất" : "Chưa đủ"}
                </Badge>
                <ChevronDown
                  aria-hidden="true"
                  className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 ${open ? "rotate-180" : ""}`}
                />
              </div>
            </div>
            <CardDescription>
              Lịch nghỉ là tiền đề để tính ngày làm việc trong KPI Plan.
            </CardDescription>
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">
                Tổng số ngày nghỉ đã cấu hình:{" "}
                <span className="font-medium text-foreground">
                  {holiday.total_holidays}
                </span>
              </p>

              <div className="flex items-center gap-3">
                {isAdmin && (
                  <Button
                    size="sm"
                    onClick={() => void handleSeed()}
                    disabled={seedMut.isPending || holiday.is_complete}
                  >
                    {seedMut.isPending ? (
                      <>
                        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                        Đang tạo mẫu…
                      </>
                    ) : (
                      <>
                        <Sparkles aria-hidden="true" className="h-4 w-4" />
                        Tạo lịch nghỉ mẫu
                      </>
                    )}
                  </Button>
                )}

                <Link
                  href="/admin/kpi-planning/holidays"
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline"
                >
                  Quản lý chi tiết
                  <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
                </Link>
              </div>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
