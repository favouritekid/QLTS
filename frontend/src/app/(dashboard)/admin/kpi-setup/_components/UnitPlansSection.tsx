"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { UnitCoverage } from "@/types/kpi-setup.types";

interface Props {
  units: UnitCoverage[];
  fiscalYear: number;
}

export function UnitPlansSection({ units, fiscalYear }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Kế hoạch đơn vị</CardTitle>
      </CardHeader>
      <CardContent>
        {units.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Không có đơn vị nào.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Đơn vị</TableHead>
                <TableHead>Trạng thái plan</TableHead>
                <TableHead className="text-right">Chỉ tiêu năm</TableHead>
                <TableHead className="text-right">Chênh lệch</TableHead>
                <TableHead className="text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {units.map((unit) => (
                <TableRow key={unit.unit_id}>
                  <TableCell className="font-medium">
                    {unit.unit_name}
                  </TableCell>
                  <TableCell>
                    {unit.plan_status === "active" ? (
                      <Badge variant="default">Active</Badge>
                    ) : (
                      <Badge variant="destructive">Chưa có</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {unit.annual_target ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {unit.plan_id != null ? (
                      unit.target_gap !== 0 ? (
                        <Badge variant="outline" className="text-amber-600">
                          {unit.target_gap > 0 ? "+" : ""}
                          {unit.target_gap}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {unit.plan_id != null ? (
                      <Link
                        href={`/admin/kpi-planning/${unit.plan_id}`}
                        className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                      >
                        Xem chi tiết
                        <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
                      </Link>
                    ) : (
                      <Link
                        href={`/admin/kpi-planning/new?unit_id=${unit.unit_id}&fiscal_year=${fiscalYear}`}
                        className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                      >
                        Tạo KPI Plan
                        <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
                      </Link>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
