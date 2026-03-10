"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, Copy, Eye, Plus, RotateCcw, Trash2 } from "lucide-react";

import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

import {
  useCreatePlan, useDeletePlan, useKpiPlans, usePreviewPlan,
} from "@/hooks/useKpiPlanning";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import type { KpiPlan, KpiPlanCreate, KpiPlanPreviewResponse } from "@/types/kpi-planning.types";
import { MONTH_LABELS } from "@/types/kpi-planning.types";

const currentYear = new Date().getFullYear();

const DEFAULT_WEIGHTS = [
  0.040, 0.033, 0.050, 0.060, 0.073, 0.127, 0.153, 0.160, 0.133, 0.093, 0.043, 0.033,
];

export default function KpiPlanningPage() {
  const router = useRouter();
  const [yearFilter, setYearFilter] = useState(currentYear);
  const [showCreate, setShowCreate] = useState(false);
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

  // Weights editor state (separate from formData to allow editing)
  const [useCustomWeights, setUseCustomWeights] = useState(false);
  const [editWeights, setEditWeights] = useState<number[]>([...DEFAULT_WEIGHTS]);

  // Queries
  const { data: plansData, isLoading } = useKpiPlans({ fiscal_year: yearFilter, limit: 100 });
  const { data: units } = useOrganizationUnits();

  // Mutations
  const createMut = useCreatePlan();
  const deleteMut = useDeletePlan();
  const previewMut = usePreviewPlan();

  // Preview state + debounce + stale response guard
  const [previewData, setPreviewData] = useState<KpiPlanPreviewResponse | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewSeqRef = useRef(0);

  // Debounced preview (300ms) — triggers on any form change when unit is selected
  const triggerPreview = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (formData.unit_id <= 0 || !showCreate) return;
      const seq = ++previewSeqRef.current;
      try {
        const weights = useCustomWeights ? editWeights : null;
        const result = await previewMut.mutateAsync({
          unit_id: formData.unit_id,
          fiscal_year: formData.fiscal_year,
          annual_enrollment_target: formData.annual_enrollment_target,
          sla_target: formData.sla_target,
          response_time_target: formData.response_time_target,
          seasonal_weights: weights,
        });
        // Discard stale response: only apply if this is still the latest request
        if (seq === previewSeqRef.current) {
          setPreviewData(result);
        }
      } catch {
        // error handled by mutation
      }
    }, 300);
  }, [formData, useCustomWeights, editWeights, showCreate, previewMut]);

  // Auto-preview on form changes
  useEffect(() => {
    if (showCreate && formData.unit_id > 0) {
      triggerPreview();
    }
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [
    formData.unit_id, formData.fiscal_year, formData.annual_enrollment_target,
    formData.sla_target, formData.response_time_target,
    useCustomWeights, editWeights, showCreate, triggerPreview,
  ]);

  // Clone: prefill form from existing plan
  const handleClone = useCallback((plan: KpiPlan) => {
    const hasCustom = plan.seasonal_weights != null && plan.seasonal_weights.length === 12;
    setFormData({
      unit_id: plan.unit_id,
      fiscal_year: currentYear + 1,
      annual_enrollment_target: plan.annual_enrollment_target,
      sla_target: plan.sla_target,
      response_time_target: plan.response_time_target,
      seasonal_weights: hasCustom ? plan.seasonal_weights : null,
      officer_id: plan.officer_id,
    });
    setUseCustomWeights(hasCustom);
    if (hasCustom && plan.seasonal_weights) {
      setEditWeights([...plan.seasonal_weights]);
    } else {
      setEditWeights([...DEFAULT_WEIGHTS]);
    }
    setPreviewData(null);
    setShowCreate(true);
  }, []);

  // Create plan
  const handleCreate = useCallback(async () => {
    if (formData.unit_id <= 0) return;
    const payload = {
      ...formData,
      seasonal_weights: useCustomWeights ? editWeights : null,
    };
    await createMut.mutateAsync(payload);
    setShowCreate(false);
    setPreviewData(null);
  }, [formData, useCustomWeights, editWeights, createMut]);

  // Weights helpers
  const weightsSum = editWeights.reduce((s, w) => s + w, 0);
  const weightsValid = weightsSum >= 0.99 && weightsSum <= 1.01;

  const updateWeight = (idx: number, val: number) => {
    setEditWeights((prev) => {
      const next = [...prev];
      next[idx] = val;
      return next;
    });
  };

  const unitName = useCallback(
    (unitId: number) => units?.find((u) => u.id === unitId)?.name ?? `Unit #${unitId}`,
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
        <Select value={String(yearFilter)} onValueChange={(v) => setYearFilter(Number(v))}>
          <SelectTrigger className="w-[120px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            {[currentYear - 1, currentYear, currentYear + 1].map((y) => (
              <SelectItem key={y} value={String(y)}>{y}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={() => { setPreviewData(null); setShowCreate(true); }}>
          <Plus className="mr-1.5 h-4 w-4" />Tạo KPI Plan
        </Button>
        <Button variant="outline" onClick={() => router.push("/admin/kpi-planning/holidays")}>
          <CalendarDays className="mr-1.5 h-4 w-4" />Lịch ngày lễ
        </Button>
      </div>

      {/* Plan List */}
      <Card>
        <CardHeader><CardTitle>Danh sách KPI Plans — {yearFilter}</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
          ) : !plansData?.items?.length ? (
            <p className="py-8 text-center text-muted-foreground">Chưa có KPI Plan cho năm {yearFilter}</p>
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
                    <TableCell className="font-mono text-sm">{plan.id}</TableCell>
                    <TableCell>{unitName(plan.unit_id)}</TableCell>
                    <TableCell>
                      {plan.officer_id
                        ? <Badge variant="outline">Officer #{plan.officer_id}</Badge>
                        : <Badge>Unit Plan</Badge>}
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
                        <Button size="sm" variant="ghost" onClick={() => router.push(`/admin/kpi-planning/${plan.id}`)} title="Xem chi tiết">
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => handleClone(plan)} title="Clone sang năm mới">
                          <Copy className="h-4 w-4" />
                        </Button>
                        {plan.is_active && (
                          <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeleteTarget(plan)} title="Vô hiệu hóa">
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

      {/* Create Plan Dialog (C1 + C3 inline preview + C6 clone) */}
      <Dialog open={showCreate} onOpenChange={(open) => { setShowCreate(open); if (!open) setPreviewData(null); }}>
        <DialogContent className="max-w-5xl max-h-[90vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Tạo KPI Plan mới</DialogTitle>
            <DialogDescription>
              Nhập chỉ tiêu năm và điều chỉnh weights. Preview tự động cập nhật từ server (debounce 300ms).
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4 lg:grid-cols-2">
            {/* Left: Form inputs */}
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1 block text-sm font-medium">Đơn vị <span className="text-destructive">*</span></label>
                  <Select value={formData.unit_id ? String(formData.unit_id) : ""} onValueChange={(v) => setFormData((p) => ({ ...p, unit_id: Number(v) }))}>
                    <SelectTrigger><SelectValue placeholder="Chọn đơn vị" /></SelectTrigger>
                    <SelectContent>
                      {units?.map((u) => <SelectItem key={u.id} value={String(u.id)}>{u.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium">Năm tài chính</label>
                  <Input type="number" value={formData.fiscal_year} onChange={(e) => setFormData((p) => ({ ...p, fiscal_year: Number(e.target.value) }))} />
                </div>
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium">Chỉ tiêu nhập học/năm <span className="text-destructive">*</span></label>
                <Input type="number" min={1} max={10000} value={formData.annual_enrollment_target} onChange={(e) => setFormData((p) => ({ ...p, annual_enrollment_target: Number(e.target.value) }))} />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1 block text-sm font-medium">SLA Target (%)</label>
                  <Input type="number" min={0} max={100} step={0.1} value={formData.sla_target} onChange={(e) => setFormData((p) => ({ ...p, sla_target: Number(e.target.value) }))} />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium">Response Time (h)</label>
                  <Input type="number" min={1} max={48} step={0.5} value={formData.response_time_target} onChange={(e) => setFormData((p) => ({ ...p, response_time_target: Number(e.target.value) }))} />
                </div>
              </div>

              {/* Seasonal Weights Editor (P1 fix) */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label className="text-sm font-medium">
                    Seasonal Weights {useCustomWeights && (
                      <span className={`ml-2 text-xs ${weightsValid ? "text-green-600" : "text-destructive"}`}>
                        (tổng: {weightsSum.toFixed(4)})
                      </span>
                    )}
                  </label>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button" size="sm" variant="ghost"
                      onClick={() => { setUseCustomWeights(!useCustomWeights); }}
                    >
                      {useCustomWeights ? "Dùng mặc định" : "Tùy chỉnh"}
                    </Button>
                    {useCustomWeights && (
                      <Button type="button" size="sm" variant="ghost" onClick={() => setEditWeights([...DEFAULT_WEIGHTS])} title="Reset về default">
                        <RotateCcw className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
                {useCustomWeights && (
                  <div className="grid grid-cols-4 gap-2">
                    {editWeights.map((w, idx) => (
                      <div key={idx} className="flex items-center gap-1">
                        <span className="w-7 text-xs text-muted-foreground">{MONTH_LABELS[idx + 1]}</span>
                        <Input
                          type="number" step={0.001} min={0.001} max={1}
                          className="h-8 text-xs"
                          value={w}
                          onChange={(e) => updateWeight(idx, Number(e.target.value))}
                        />
                      </div>
                    ))}
                  </div>
                )}
                {useCustomWeights && !weightsValid && (
                  <p className="mt-1 text-xs text-destructive">Tổng weights phải nằm trong [0.99, 1.01]</p>
                )}
              </div>
            </div>

            {/* Right: Live Preview (C3 debounced) */}
            <div>
              <h4 className="mb-2 text-sm font-medium text-muted-foreground">
                Preview {previewMut.isPending && "(đang tính…)"}
              </h4>
              {previewData ? (
                <div className="overflow-x-auto rounded border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">Tháng</TableHead>
                        <TableHead className="text-right text-xs">M_t</TableHead>
                        <TableHead className="text-right text-xs">WD</TableHead>
                        <TableHead className="text-right text-xs">TV/ngày</TableHead>
                        <TableHead className="text-right text-xs">Conv%</TableHead>
                        <TableHead className="text-right text-xs">Win%</TableHead>
                        <TableHead className="text-right text-xs">Eff%</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {previewData.months.map((m) => (
                        <TableRow key={m.month}>
                          <TableCell className="text-xs font-medium">{MONTH_LABELS[m.month]}</TableCell>
                          <TableCell className="text-right text-xs">{m.enrollment_target}</TableCell>
                          <TableCell className="text-right text-xs">{m.working_days}</TableCell>
                          <TableCell className="text-right text-xs">{m.consultations_daily ?? "N/A"}</TableCell>
                          <TableCell className="text-right text-xs">{m.conversion_rate != null ? `${m.conversion_rate}%` : "N/A"}</TableCell>
                          <TableCell className="text-right text-xs">{m.win_rate != null ? `${m.win_rate}%` : "N/A"}</TableCell>
                          <TableCell className="text-right text-xs">{m.consultation_effectiveness != null ? `${m.consultation_effectiveness}%` : "N/A"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <p className="px-2 py-1 text-right text-xs text-muted-foreground">
                    Tổng M_t = {previewData.months.reduce((s, m) => s + m.enrollment_target, 0)} / {previewData.annual_enrollment_target}
                  </p>
                </div>
              ) : (
                <div className="flex h-48 items-center justify-center rounded border border-dashed text-sm text-muted-foreground">
                  {formData.unit_id > 0 ? "Đang tải preview…" : "Chọn đơn vị để xem preview"}
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button
              onClick={handleCreate}
              disabled={createMut.isPending || formData.unit_id <= 0 || (useCustomWeights && !weightsValid)}
            >
              {createMut.isPending ? "Đang tạo…" : "Tạo Plan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Vô hiệu hóa KPI Plan?</AlertDialogTitle>
            <AlertDialogDescription>
              Plan #{deleteTarget?.id} sẽ bị deactivate. KPI configs cho tháng hiện tại và tương lai sẽ bị cleanup.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground"
              onClick={async () => { if (deleteTarget) { await deleteMut.mutateAsync(deleteTarget.id); setDeleteTarget(null); } }}
            >
              Vô hiệu hóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}
