// src/app/(dashboard)/admin/kpi-config/_components/KpiCatalogOverview.tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, AlertTriangle, BookOpen } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { MetricCatalogEntry } from "@/lib/api/meta";

const UNIT_LABELS: Record<string, string> = {
  count: "Số lượng",
  percent: "%",
  hours: "Giờ",
};

const PERIOD_LABELS: Record<string, string> = {
  daily: "Hàng ngày",
  monthly: "Hàng tháng",
  annual: "Hàng năm",
};

interface KpiConfig {
  kpi_code: string;
  period_type: string;
  is_active: boolean;
}

interface KpiCatalogOverviewProps {
  catalog: MetricCatalogEntry[];
  catalogMap: Map<string, MetricCatalogEntry>;
}

export function KpiCatalogOverview({
  catalog,
  catalogMap,
}: KpiCatalogOverviewProps) {
  const [open, setOpen] = useState(false);

  // Own query for ghost detection (always active configs, not display query)
  const { data: activeConfigs } = useQuery<KpiConfig[]>({
    queryKey: ["kpi-configs", "active-for-ghost"],
    queryFn: async () => {
      const { data } = await api.get("/api/admin/kpi-config/configs", {
        params: { is_active: true },
      });
      return data;
    },
    staleTime: 30_000,
  });

  // Ghost config detection: configs with period_type mismatch
  const ghostCount =
    activeConfigs?.filter((c) => {
      const entry = catalogMap.get(c.kpi_code);
      return entry && c.period_type !== entry.period_type;
    }).length ?? 0;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card>
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer select-none hover:bg-muted/50">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BookOpen className="h-5 w-5 text-primary" />
                <CardTitle className="text-base">
                  Bộ chỉ tiêu KPI hệ thống ({catalog.length} metrics)
                </CardTitle>
              </div>
              <ChevronDown
                className={`h-4 w-4 text-muted-foreground transition-transform ${
                  open ? "rotate-180" : ""
                }`}
              />
            </div>
          </CardHeader>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="pt-0">
            {ghostCount > 0 && (
              <Alert variant="destructive" className="mb-4">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Phát hiện cấu hình không hợp lệ</AlertTitle>
                <AlertDescription>
                  {ghostCount} cấu hình có chu kỳ không khớp với catalog — không
                  có tác dụng trên hệ thống. Hãy xóa và tạo lại đúng chu kỳ.
                </AlertDescription>
              </Alert>
            )}

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tên chỉ tiêu</TableHead>
                  <TableHead>Đơn vị</TableHead>
                  <TableHead>Chu kỳ</TableHead>
                  <TableHead className="text-right">Mặc định</TableHead>
                  <TableHead>Dashboard</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {catalog.map((m) => (
                  <TableRow key={m.code}>
                    <TableCell className="font-medium">
                      {m.display_aliases.config}
                    </TableCell>
                    <TableCell>{UNIT_LABELS[m.unit] ?? m.unit}</TableCell>
                    <TableCell>
                      {PERIOD_LABELS[m.period_type] ?? m.period_type}
                    </TableCell>
                    <TableCell className="text-right">
                      {m.default_value}
                      {m.unit === "percent" ? "%" : ""}
                      {m.unit === "hours" ? "h" : ""}
                    </TableCell>
                    <TableCell>
                      {m.comparison.comparable ? (
                        <Badge variant="default" className="text-xs">
                          Có mục tiêu
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-xs">
                          Chỉ thực tế
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <p className="mt-3 text-xs text-muted-foreground">
              Nếu không thiết lập riêng, hệ thống sử dụng giá trị mặc định.
              Chỉ tiêu đánh dấu &quot;Chỉ thực tế&quot; không hiển thị mục tiêu
              trên Dashboard do khác biệt phương pháp tính.
            </p>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
