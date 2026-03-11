"use client";

import Link from "next/link";
import { CalendarDays, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { HolidayStatusCoverage } from "@/types/kpi-setup.types";

interface Props {
  holiday: HolidayStatusCoverage;
  fiscalYear: number;
}

export function HolidaySection({ holiday, fiscalYear }: Props) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CalendarDays aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Lịch nghỉ {fiscalYear}</CardTitle>
          </div>
          <Badge variant={holiday.is_complete ? "default" : "destructive"}>
            {holiday.is_complete ? "Hoàn tất" : "Chưa đủ"}
          </Badge>
        </div>
        <CardDescription>
          Lịch nghỉ là tiền đề để tính ngày làm việc trong KPI Plan.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Tổng số ngày nghỉ đã cấu hình:{" "}
            <span className="font-medium text-foreground">
              {holiday.total_holidays}
            </span>
          </p>
          <Link
            href="/admin/kpi-planning"
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            Quản lý lịch nghỉ
            <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
