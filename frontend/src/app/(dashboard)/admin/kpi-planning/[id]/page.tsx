"use client";

import { useCallback, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Pencil, RefreshCw, RotateCcw } from "lucide-react";

import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

import {
  useKpiPlan,
  useOverrideMonth,
  useOverrideWorkingDays,
  useRegeneratePlan,
  useResetMonthOverride,
  useUpdatePlan,
} from "@/hooks/useKpiPlanning";
import type { KpiPlanMonth } from "@/types/kpi-planning.types";
import { MONTH_LABELS, OVERRIDABLE_FIELDS } from "@/types/kpi-planning.types";

function formatVal(val: number | null, decimals = 2, suffix = ""): string {
  if (val == null) return "N/A";
  return `${Number(val).toFixed(decimals)}${suffix}`;
}

export default function PlanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const planId = Number(id);
  const router = useRouter();

  const { data: plan, isLoading, error } = useKpiPlan(planId);
  const updateMut = useUpdatePlan(planId);
  const regenerateMut = useRegeneratePlan(planId);
  const overrideMut = useOverrideMonth(planId);
  const resetMut = useResetMonthOverride(planId);
  const wdMut = useOverrideWorkingDays(planId);

  // Override dialog state
  const [overrideMonth, setOverrideMonth] = useState<KpiPlanMonth | null>(null);
  const [overrideField, setOverrideField] = useState("");
  const [overrideValue, setOverrideValue] = useState("");
  const [overrideReason, setOverrideReason] = useState("");

  // Working days dialog state
  const [wdMonth, setWdMonth] = useState<KpiPlanMonth | null>(null);
  const [wdValue, setWdValue] = useState("");
  const [wdReason, setWdReason] = useState("");

  // Update plan dialog
  const [showUpdate, setShowUpdate] = useState(false);
  const [updateTarget, setUpdateTarget] = useState<number | undefined>();
  const [updateSla, setUpdateSla] = useState<number | undefined>();

  const handleOverrideSubmit = useCallback(async () => {
    if (!overrideMonth || !overrideField || !overrideReason) return;
    const val = Number(overrideValue);
    if (isNaN(val)) return;
    await overrideMut.mutateAsync({
      monthId: overrideMonth.id,
      data: {
        overrides: { [overrideField]: val },
        reason: overrideReason,
      },
    });
    setOverrideMonth(null);
    setOverrideField("");
    setOverrideValue("");
    setOverrideReason("");
  }, [overrideMonth, overrideField, overrideValue, overrideReason, overrideMut]);

  const handleWdSubmit = useCallback(async () => {
    if (!wdMonth || !wdReason) return;
    const val = Number(wdValue);
    if (isNaN(val) || val < 0) return;
    await wdMut.mutateAsync({
      monthId: wdMonth.id,
      data: { working_days: val, reason: wdReason },
    });
    setWdMonth(null);
    setWdValue("");
    setWdReason("");
  }, [wdMonth, wdValue, wdReason, wdMut]);

  const handleReset = useCallback(
    async (month: KpiPlanMonth, field?: string) => {
      await resetMut.mutateAsync({
        monthId: month.id,
        data: { fields: field ? [field] : null },
      });
    },
    [resetMut],
  );

  if (isLoading) {
    return (
      <PageContainer maxWidth="full">
        <Skeleton className="mb-4 h-10 w-64" />
        <Skeleton className="h-[400px] w-full" />
      </PageContainer>
    );
  }

  if (error || !plan) {
    return (
      <PageContainer maxWidth="full">
        <PageHeader title="KPI Plan" />
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">
              {error?.response?.status === 404
                ? "KPI Plan không tồn tại hoặc bạn không có quyền truy cập."
                : "Lỗi tải dữ liệu."}
            </p>
            <Button
              variant="outline"
              className="mt-4"
              onClick={() => router.push("/admin/kpi-planning")}
            >
              Quay lại danh sách
            </Button>
          </CardContent>
        </Card>
      </PageContainer>
    );
  }

  const sortedMonths = [...(plan.months || [])].sort(
    (a, b) => a.month - b.month,
  );

  return (
    <PageContainer maxWidth="full">
      <div className="mb-4 flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/admin/kpi-planning")}
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          Quay lại
        </Button>
      </div>

      <PageHeader
        title={`KPI Plan #${plan.id} — ${plan.fiscal_year}`}
        description={`Chỉ tiêu: ${plan.annual_enrollment_target} | SLA: ${plan.sla_target}% | Response: ${plan.response_time_target}h`}
      />

      {/* Actions */}
      <div className="mb-4 flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setUpdateTarget(plan.annual_enrollment_target);
            setUpdateSla(plan.sla_target);
            setShowUpdate(true);
          }}
        >
          <Pencil className="mr-1 h-4 w-4" />
          Sửa Plan
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => regenerateMut.mutate()}
          disabled={regenerateMut.isPending}
        >
          <RefreshCw className="mr-1 h-4 w-4" />
          Tính lại KPI
        </Button>
      </div>

      {/* Monthly Grid (C2) */}
      <Card>
        <CardHeader>
          <CardTitle>12 tháng KPI — Target vs Actual (C5)</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <TooltipProvider>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-10 bg-background">
                    Tháng
                  </TableHead>
                  <TableHead className="text-right">M_t</TableHead>
                  <TableHead className="text-right">WD</TableHead>
                  <TableHead className="text-right">Tư vấn/ngày</TableHead>
                  <TableHead className="text-right">Conv Rate</TableHead>
                  <TableHead className="text-right">Win Rate</TableHead>
                  <TableHead className="text-right">Effectiveness</TableHead>
                  <TableHead className="text-right">Actual Enroll</TableHead>
                  <TableHead className="text-center">Override</TableHead>
                  <TableHead className="text-center">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedMonths.map((m) => {
                  const hasOverride =
                    m.overridden_fields &&
                    Object.keys(m.overridden_fields).length > 0;

                  return (
                    <TableRow key={m.id}>
                      <TableCell className="sticky left-0 z-10 bg-background font-medium">
                        {MONTH_LABELS[m.month]}
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {m.enrollment_target}
                      </TableCell>
                      <TableCell className="text-right">
                        <button
                          className="cursor-pointer underline decoration-dashed hover:text-primary"
                          onClick={() => {
                            setWdMonth(m);
                            setWdValue(String(m.working_days));
                          }}
                        >
                          {m.working_days}
                        </button>
                      </TableCell>
                      <CellWithOverride
                        month={m}
                        field="consultations_daily"
                        value={m.consultations_daily}
                        decimals={0}
                        onOverride={() => {
                          setOverrideMonth(m);
                          setOverrideField("consultations_daily");
                          setOverrideValue(
                            String(m.consultations_daily ?? ""),
                          );
                        }}
                      />
                      <CellWithOverride
                        month={m}
                        field="conversion_rate"
                        value={m.conversion_rate}
                        suffix="%"
                        onOverride={() => {
                          setOverrideMonth(m);
                          setOverrideField("conversion_rate");
                          setOverrideValue(String(m.conversion_rate ?? ""));
                        }}
                      />
                      <CellWithOverride
                        month={m}
                        field="win_rate"
                        value={m.win_rate}
                        suffix="%"
                        onOverride={() => {
                          setOverrideMonth(m);
                          setOverrideField("win_rate");
                          setOverrideValue(String(m.win_rate ?? ""));
                        }}
                      />
                      <CellWithOverride
                        month={m}
                        field="consultation_effectiveness"
                        value={m.consultation_effectiveness}
                        suffix="%"
                        onOverride={() => {
                          setOverrideMonth(m);
                          setOverrideField("consultation_effectiveness");
                          setOverrideValue(
                            String(m.consultation_effectiveness ?? ""),
                          );
                        }}
                      />
                      {/* Actual vs Target (C5) */}
                      <TableCell className="text-right">
                        {m.actual_enrollments != null ? (
                          <span
                            className={
                              m.actual_enrollments >= m.enrollment_target
                                ? "text-green-600"
                                : "text-orange-500"
                            }
                          >
                            {m.actual_enrollments}/{m.enrollment_target}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-center">
                        {hasOverride ? (
                          <Tooltip>
                            <TooltipTrigger>
                              <Badge variant="secondary" className="text-xs">
                                {Object.keys(m.overridden_fields).length} field
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-xs">
                              <p className="font-medium">
                                Override: {Object.keys(m.overridden_fields).join(", ")}
                              </p>
                              {m.override_reason && (
                                <p className="text-xs">Lý do: {m.override_reason}</p>
                              )}
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-center">
                        {hasOverride && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleReset(m)}
                            title="Reset all overrides"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TooltipProvider>

          {/* Summary row */}
          <div className="mt-3 flex items-center gap-6 text-sm text-muted-foreground">
            <span>
              Tổng M_t:{" "}
              <strong>
                {sortedMonths.reduce((s, m) => s + m.enrollment_target, 0)}
              </strong>{" "}
              / {plan.annual_enrollment_target}
            </span>
            <span>
              Actual YTD:{" "}
              <strong>
                {sortedMonths.reduce(
                  (s, m) => s + (m.actual_enrollments ?? 0),
                  0,
                )}
              </strong>
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Override Dialog */}
      <Dialog
        open={!!overrideMonth}
        onOpenChange={() => setOverrideMonth(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Override KPI — {overrideMonth && MONTH_LABELS[overrideMonth.month]}
            </DialogTitle>
            <DialogDescription>
              Nhập giá trị mới cho {overrideField}. Giá trị cũ sẽ được ghi đè.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">
                Field: {overrideField}
              </label>
              <Input
                type="number"
                step="any"
                value={overrideValue}
                onChange={(e) => setOverrideValue(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">
                Lý do <span className="text-destructive">*</span>
              </label>
              <Textarea
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="Nhập lý do override (tối thiểu 5 ký tự)"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={handleOverrideSubmit}
              disabled={
                overrideMut.isPending ||
                !overrideReason ||
                overrideReason.length < 5
              }
            >
              {overrideMut.isPending ? "Đang lưu…" : "Xác nhận Override"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Working Days Override Dialog */}
      <Dialog open={!!wdMonth} onOpenChange={() => setWdMonth(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Sửa ngày làm việc — {wdMonth && MONTH_LABELS[wdMonth.month]}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">
                Số ngày làm việc
              </label>
              <Input
                type="number"
                min={0}
                max={31}
                value={wdValue}
                onChange={(e) => setWdValue(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">
                Lý do <span className="text-destructive">*</span>
              </label>
              <Textarea
                value={wdReason}
                onChange={(e) => setWdReason(e.target.value)}
                placeholder="Lý do sửa working days"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={handleWdSubmit}
              disabled={wdMut.isPending || !wdReason || wdReason.length < 5}
            >
              Cập nhật
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Update Plan Dialog */}
      <Dialog open={showUpdate} onOpenChange={setShowUpdate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sửa KPI Plan</DialogTitle>
            <DialogDescription>
              Thay đổi chỉ tiêu giữa năm sẽ redistribute cho các tháng còn lại.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">
                Chỉ tiêu nhập học/năm
              </label>
              <Input
                type="number"
                min={1}
                max={10000}
                value={updateTarget ?? ""}
                onChange={(e) => setUpdateTarget(Number(e.target.value))}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">
                SLA Target (%)
              </label>
              <Input
                type="number"
                min={0}
                max={100}
                step={0.1}
                value={updateSla ?? ""}
                onChange={(e) => setUpdateSla(Number(e.target.value))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={async () => {
                await updateMut.mutateAsync({
                  annual_enrollment_target: updateTarget,
                  sla_target: updateSla,
                });
                setShowUpdate(false);
              }}
              disabled={updateMut.isPending}
            >
              {updateMut.isPending ? "Đang lưu…" : "Cập nhật"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}

// =============================================================================
// CELL WITH OVERRIDE INDICATOR
// =============================================================================

function CellWithOverride({
  month,
  field,
  value,
  decimals = 2,
  suffix = "",
  onOverride,
}: {
  month: KpiPlanMonth;
  field: string;
  value: number | null;
  decimals?: number;
  suffix?: string;
  onOverride: () => void;
}) {
  const isOverridden = !!month.overridden_fields?.[field];

  return (
    <TableCell className="text-right">
      <button
        className={`cursor-pointer hover:text-primary ${
          isOverridden
            ? "font-semibold text-blue-600 underline decoration-dotted"
            : ""
        }`}
        onClick={onOverride}
        title={
          isOverridden
            ? `Đã override — click để sửa`
            : `Click để override`
        }
      >
        {formatVal(value, decimals, suffix)}
      </button>
    </TableCell>
  );
}
