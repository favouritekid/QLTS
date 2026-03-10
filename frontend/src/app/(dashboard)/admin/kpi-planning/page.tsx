"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CalendarDays,
  Copy,
  Eye,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import {
  useCreatePlan,
  useDeletePlan,
  useKpiPlan,
  useKpiPlans,
  usePreviewPlan,
} from "@/hooks/useKpiPlanning";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import type {
  KpiPlan,
  KpiPlanCreate,
  KpiPlanPreviewResponse,
  PreviewMonth,
} from "@/types/kpi-planning.types";
import { KPI_FIELD_CONFIG, MONTH_LABELS } from "@/types/kpi-planning.types";

const currentYear = new Date().getFullYear();

// =============================================================================
// DEFAULT WEIGHTS (display only — backend uses its own defaults when NULL)
// =============================================================================
const DEFAULT_WEIGHTS = [
  0.04, 0.033, 0.05, 0.06, 0.073, 0.127, 0.153, 0.16, 0.133, 0.093, 0.043,
  0.033,
];

export default function KpiPlanningPage() {
  const router = useRouter();
  const [yearFilter, setYearFilter] = useState(currentYear);
  const [showCreate, setShowCreate] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [cloneSourceId, setCloneSourceId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<KpiPlan | null>(null);

  // Form state
  const [formData, setFormData] = useState<KpiPlanCreate>({
    unit_id: 0,
    fiscal_year: currentYear,
    annual_enrollment_target: 300,
    sla_target: 85,
    response_time_target: 2,
    seasonal_weights: null,
    officer_id: null,
  });

  // Queries
  const { data: plansData, isLoading } = useKpiPlans({
    fiscal_year: yearFilter,
    limit: 100,
  });
  const { data: units } = useOrganizationUnits();
  const { data: cloneSource } = useKpiPlan(cloneSourceId ?? 0, !!cloneSourceId);

  // Mutations
  const createMut = useCreatePlan();
  const deleteMut = useDeletePlan();
  const previewMut = usePreviewPlan();

  // Preview state
  const [previewData, setPreviewData] =
    useState<KpiPlanPreviewResponse | null>(null);

  // Clone: prefill form from existing plan
  const handleClone = useCallback(
    (plan: KpiPlan) => {
      setFormData({
        unit_id: plan.unit_id,
        fiscal_year: currentYear + 1,
        annual_enrollment_target: plan.annual_enrollment_target,
        sla_target: plan.sla_target,
        response_time_target: plan.response_time_target,
        seasonal_weights: plan.seasonal_weights,
        officer_id: plan.officer_id,
      });
      setShowCreate(true);
    },
    [],
  );

  // Preview: debounced call to backend
  const handlePreview = useCallback(async () => {
    if (formData.unit_id <= 0) return;
    try {
      const result = await previewMut.mutateAsync({
        unit_id: formData.unit_id,
        fiscal_year: formData.fiscal_year,
        annual_enrollment_target: formData.annual_enrollment_target,
        sla_target: formData.sla_target,
        response_time_target: formData.response_time_target,
        seasonal_weights: formData.seasonal_weights,
      });
      setPreviewData(result);
      setShowPreview(true);
    } catch {
      // error handled by mutation
    }
  }, [formData, previewMut]);

  // Create plan
  const handleCreate = useCallback(async () => {
    if (formData.unit_id <= 0) return;
    await createMut.mutateAsync(formData);
    setShowCreate(false);
    setFormData((prev) => ({ ...prev, unit_id: 0 }));
  }, [formData, createMut]);

  const unitName = useCallback(
    (unitId: number) =>
      units?.find((u) => u.id === unitId)?.name ?? `Unit #${unitId}`,
    [units],
  );

  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="KPI Planning"
        description="Quản lý kế hoạch KPI — Reverse-funnel từ chỉ tiêu năm ra 7 KPI tháng"
      />

      {/* Toolbar */}
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

        <Button onClick={() => setShowCreate(true)}>
          <Plus className="mr-1.5 h-4 w-4" />
          Tạo KPI Plan
        </Button>

        <Button
          variant="outline"
          onClick={() => router.push("/admin/kpi-planning/holidays")}
        >
          <CalendarDays className="mr-1.5 h-4 w-4" />
          Lịch ngày lễ
        </Button>
      </div>

      {/* Plan List */}
      <Card>
        <CardHeader>
          <CardTitle>
            Danh sách KPI Plans — {yearFilter}
          </CardTitle>
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
                  <TableHead className="text-right">SLA</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead className="text-right">Hành động</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {plansData.items.map((plan) => (
                  <TableRow key={plan.id}>
                    <TableCell className="font-mono text-sm">
                      {plan.id}
                    </TableCell>
                    <TableCell>{unitName(plan.unit_id)}</TableCell>
                    <TableCell>
                      {plan.officer_id ? (
                        <Badge variant="outline">
                          Officer #{plan.officer_id}
                        </Badge>
                      ) : (
                        <Badge>Unit Plan</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      {plan.annual_enrollment_target.toLocaleString("vi-VN")}
                    </TableCell>
                    <TableCell className="text-right">
                      {plan.sla_target}%
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={plan.is_active ? "default" : "secondary"}
                      >
                        {plan.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            router.push(`/admin/kpi-planning/${plan.id}`)
                          }
                          title="Xem chi tiết"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleClone(plan)}
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

      {/* Create Plan Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Tạo KPI Plan mới</DialogTitle>
            <DialogDescription>
              Nhập chỉ tiêu năm, hệ thống sẽ tự phân bổ 12 tháng theo seasonal
              weights.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium">
                  Đơn vị <span className="text-destructive">*</span>
                </label>
                <Select
                  value={formData.unit_id ? String(formData.unit_id) : ""}
                  onValueChange={(v) =>
                    setFormData((p) => ({ ...p, unit_id: Number(v) }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Chọn đơn vị" />
                  </SelectTrigger>
                  <SelectContent>
                    {units?.map((u) => (
                      <SelectItem key={u.id} value={String(u.id)}>
                        {u.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">
                  Năm tài chính
                </label>
                <Input
                  type="number"
                  value={formData.fiscal_year}
                  onChange={(e) =>
                    setFormData((p) => ({
                      ...p,
                      fiscal_year: Number(e.target.value),
                    }))
                  }
                />
              </div>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium">
                Chỉ tiêu nhập học/năm{" "}
                <span className="text-destructive">*</span>
              </label>
              <Input
                type="number"
                min={1}
                max={10000}
                value={formData.annual_enrollment_target}
                onChange={(e) =>
                  setFormData((p) => ({
                    ...p,
                    annual_enrollment_target: Number(e.target.value),
                  }))
                }
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium">
                  SLA Target (%)
                </label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  step={0.1}
                  value={formData.sla_target}
                  onChange={(e) =>
                    setFormData((p) => ({
                      ...p,
                      sla_target: Number(e.target.value),
                    }))
                  }
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">
                  Response Time (h)
                </label>
                <Input
                  type="number"
                  min={1}
                  max={48}
                  step={0.5}
                  value={formData.response_time_target}
                  onChange={(e) =>
                    setFormData((p) => ({
                      ...p,
                      response_time_target: Number(e.target.value),
                    }))
                  }
                />
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={handlePreview}
              disabled={previewMut.isPending || formData.unit_id <= 0}
            >
              <Eye className="mr-1.5 h-4 w-4" />
              Preview
            </Button>
            <Button
              onClick={handleCreate}
              disabled={createMut.isPending || formData.unit_id <= 0}
            >
              {createMut.isPending ? "Đang tạo…" : "Tạo Plan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Preview Dialog (C3) */}
      <Dialog open={showPreview} onOpenChange={setShowPreview}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Preview KPI Plan</DialogTitle>
            <DialogDescription>
              Dữ liệu tính từ server — không lưu vào DB.
            </DialogDescription>
          </DialogHeader>
          {previewData && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tháng</TableHead>
                    <TableHead className="text-right">M_t</TableHead>
                    <TableHead className="text-right">WD</TableHead>
                    <TableHead className="text-right">Tư vấn/ngày</TableHead>
                    <TableHead className="text-right">Conv. Rate</TableHead>
                    <TableHead className="text-right">Win Rate</TableHead>
                    <TableHead className="text-right">Effectiveness</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {previewData.months.map((m) => (
                    <TableRow key={m.month}>
                      <TableCell className="font-medium">
                        {MONTH_LABELS[m.month]}
                      </TableCell>
                      <TableCell className="text-right">
                        {m.enrollment_target}
                      </TableCell>
                      <TableCell className="text-right">
                        {m.working_days}
                      </TableCell>
                      <TableCell className="text-right">
                        {m.consultations_daily ?? "N/A"}
                      </TableCell>
                      <TableCell className="text-right">
                        {m.conversion_rate != null
                          ? `${m.conversion_rate}%`
                          : "N/A"}
                      </TableCell>
                      <TableCell className="text-right">
                        {m.win_rate != null ? `${m.win_rate}%` : "N/A"}
                      </TableCell>
                      <TableCell className="text-right">
                        {m.consultation_effectiveness != null
                          ? `${m.consultation_effectiveness}%`
                          : "N/A"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="mt-2 text-right text-sm text-muted-foreground">
                Tổng M_t ={" "}
                {previewData.months.reduce(
                  (s, m) => s + m.enrollment_target,
                  0,
                )}{" "}
                (target: {previewData.annual_enrollment_target})
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Vô hiệu hóa KPI Plan?</AlertDialogTitle>
            <AlertDialogDescription>
              Plan #{deleteTarget?.id} sẽ bị deactivate. KPI configs cho tháng
              hiện tại và tương lai sẽ bị cleanup. Dữ liệu lịch sử được giữ
              nguyên.
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
