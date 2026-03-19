"use client";

import Link from "next/link";
import { CalendarDays, ExternalLink, LineChart, Settings2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

const LINKS = [
  {
    icon: LineChart,
    label: "Kế hoạch KPI",
    description: "Tạo và quản lý kế hoạch theo đơn vị",
    href: "/admin/kpi-planning",
  },
  {
    icon: Settings2,
    label: "Cấu hình chỉ tiêu",
    description: "Quản lý targets ngày/tháng/năm, thresholds",
    href: "/admin/kpi-config",
  },
  {
    icon: CalendarDays,
    label: "Lịch nghỉ",
    description: "Cấu hình ngày lễ để tính working days",
    href: "/admin/kpi-planning/holidays",
  },
];

export function QuickActionsFooter() {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {LINKS.map((item) => (
        <Card key={item.href}>
          <CardContent className="flex items-center justify-between py-4">
            <div className="flex items-center gap-2">
              <item.icon
                aria-hidden="true"
                className="h-5 w-5 text-muted-foreground"
              />
              <div>
                <p className="text-sm font-medium">{item.label}</p>
                <p className="text-xs text-muted-foreground">
                  {item.description}
                </p>
              </div>
            </div>
            <Link
              href={item.href}
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              Mở
              <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
            </Link>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
