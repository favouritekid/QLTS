"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, Copy, Eye, Plus, Trash2 } from "lucide-react";

import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { useDeletePlan, useKpiPlans } from "@/hooks/useKpiPlanning";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import type { KpiPlan } from "@/types/kpi-planning.types";
import type { OrganizationUnit } from "@/types/organization.types";

const currentYear = new Date().getFullYear();

const findUnitNameInTree = (
  units: OrganizationUnit[] | undefined,
  unitId: number,
): string | undefined => {
  if (!units?.length) return undefined;
  for (const unit of units) {
    if (unit.id === unitId) return unit.name;
    const child = findUnitNameInTree(unit.children, unitId);
    if (child) return child;
  }
  return undefined;
};

export default function KpiPlanningPage() {
  const router = useRouter();
  const [yearFilter, setYearFilter] = useState(currentYear);
  const [deleteTarget, setDeleteTarget] = useState<KpiPlan | null>(null);

  const { data: plansData, isLoading } = useKpiPlans({
    fiscal_year: yearFilter,
    limit: 100,
  });
  const { data: units } = useOrganizationUnits();
  const deleteMut = useDeletePlan();

  const unitName = useCallback(
    (unitId: number) => findUnitNameInTree(units, unitId) ?? `Đơn vị #${unitId}`,
    [units],
  );

  const openCreateBuilder = () => {
    router.push("/admin/kpi-planning/new");
  };

  const openCloneBuilder = (plan: KpiPlan) => {
    const params = new URLSearchParams({
      unit_id: String(plan.unit_id),
      fiscal_year: String(currentYear + 1),
      annual_enrollment_target: String(plan.annual_enrollment_target),
      sla_target: String(plan.sla_target),
      response_time_target: String(plan.response_time_target),
    });

    if (plan.seasonal_weights && plan.seasonal_weights.length === 12) {
      params.set("use_custom_weights", "1");
      params.set("weights", plan.seasonal_weights.join(","));
    }

    router.push(`/admin/kpi-planning/new?${params.toString()}`);
  };

  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="KPI Planning"
        description="Quản lý kế hoạch KPI theo năm và theo đơn vị"
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select
          value={String(yearFilter)}
          onValueChange={(v) => setYearFilter(Number(v))}
        >
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[currentYear - 1, currentYear, currentYear + 1].map((y) => (
              <SelectItem key={y} value={String(y)}>
                {y}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button onClick={openCreateBuilder}>
          <Plus className="mr-1.5 h-4 w-4" />Tạo kế hoạch KPI
        </Button>

        <Button
          variant="outline"
          onClick={() => router.push("/admin/kpi-planning/holidays")}
        >
          <CalendarDays className="mr-1.5 h-4 w-4" />Lịch ngày lễ
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Danh sách KPI Plans - {yearFilter}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !plansData?.items?.length ? (
            <p className="py-8 text-center text-muted-foreground">
              Chưa có KPI Plan cho năm {yearFilter}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Đơn vị</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead className="text-right">Chỉ tiêu năm</TableHead>
                  <TableHead className="text-right">Tuân thủ SLA</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead className="text-right">Hành động</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {plansData.items.map((plan) => (
                  <TableRow key={plan.id}>
                    <TableCell className="font-mono text-sm">{plan.id}</TableCell>
                    <TableCell>{unitName(plan.unit_id)}</TableCell>
                    <TableCell>
                      {plan.officer_id ? (
                        <Badge variant="outline">Officer #{plan.officer_id}</Badge>
                      ) : (
                        <Badge>Unit Plan</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      {plan.annual_enrollment_target.toLocaleString("vi-VN")}
                    </TableCell>
                    <TableCell className="text-right">{plan.sla_target}%</TableCell>
                    <TableCell>
                      <Badge variant={plan.is_active ? "default" : "secondary"}>
                        {plan.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => router.push(`/admin/kpi-planning/${plan.id}`)}
                          title="Xem chi tiết"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>

                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => openCloneBuilder(plan)}
                          title="Clone sang năm mới"
                        >
                          <Copy className="h-4 w-4" />
                        </Button>

                        {plan.is_active && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-destructive"
                            onClick={() => setDeleteTarget(plan)}
                            title="Vô hiệu hóa"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Vô hiệu hóa KPI Plan?</AlertDialogTitle>
            <AlertDialogDescription>
              Plan #{deleteTarget?.id} sẽ bị deactivate. KPI configs cho tháng
              hiện tại và tương lai sẽ bị cleanup.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground"
              onClick={async () => {
                if (deleteTarget) {
                  await deleteMut.mutateAsync(deleteTarget.id);
                  setDeleteTarget(null);
                }
              }}
            >
              Vô hiệu hóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}
