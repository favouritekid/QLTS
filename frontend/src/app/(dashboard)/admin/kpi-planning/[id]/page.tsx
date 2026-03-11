"use client";

import { useCallback, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Copy, Pencil, RefreshCw, RotateCcw } from "lucide-react";

import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import { Checkbox } from "@/components/ui/checkbox";

import {
  useBatchOverride,
  useClonePlan,
  useKpiPlan,
  useOverrideMonth,
  useOverrideWorkingDays,
  useRegeneratePlan,
  useResetMonthOverride,
  useUpdatePlan,
} from "@/hooks/useKpiPlanning";
import type { KpiPlanMonth } from "@/types/kpi-planning.types";
import { MONTH_LABELS, OVERRIDABLE_FIELDS } from "@/types/kpi-planning.types";

function fmtVal(val: number | null, d = 2, suf = ""): string {
  if (val == null) return "N/A";
  return `${Number(val).toFixed(d)}${suf}`;
}

function ActualCell({ target, actual, d = 2, suf = "" }: {
  target: number | null; actual: number | null; d?: number; suf?: string;
}) {
  if (actual == null) return <span className="text-muted-foreground">-</span>;
  const good = target != null && actual >= target;
  return (
    <span className={good ? "text-green-600" : "text-orange-500"}>
      {Number(actual).toFixed(d)}{suf}
    </span>
  );
}

export default function PlanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const planId = Number(id);
  const router = useRouter();

  const { data: plan, isLoading, error } = useKpiPlan(planId);
  const updateMut = useUpdatePlan(planId);
  const regenerateMut = useRegeneratePlan(planId);
  const cloneMut = useClonePlan();
  const overrideMut = useOverrideMonth(planId);
  const resetMut = useResetMonthOverride(planId);
  const wdMut = useOverrideWorkingDays(planId);
  const batchMut = useBatchOverride(planId);

  // Override dialog
  const [overrideMonth, setOverrideMonth] = useState<KpiPlanMonth | null>(null);
  const [overrideField, setOverrideField] = useState("");
  const [overrideValue, setOverrideValue] = useState("");
  const [overrideReason, setOverrideReason] = useState("");

  // Working days dialog
  const [wdMonth, setWdMonth] = useState<KpiPlanMonth | null>(null);
  const [wdValue, setWdValue] = useState("");
  const [wdReason, setWdReason] = useState("");

  // Update plan dialog
  const [showUpdate, setShowUpdate] = useState(false);
  const [updateTarget, setUpdateTarget] = useState<number | undefined>();
  const [updateSla, setUpdateSla] = useState<number | undefined>();
  const [updateResponseTime, setUpdateResponseTime] = useState<number | undefined>();

  // Clone dialog
  const [showClone, setShowClone] = useState(false);
  const [cloneYear, setCloneYear] = useState<number | undefined>();

  // Batch override
  const [batchSelected, setBatchSelected] = useState<Set<number>>(new Set());
  const [showBatch, setShowBatch] = useState(false);
  const [batchField, setBatchField] = useState("");
  const [batchValue, setBatchValue] = useState("");
  const [batchReason, setBatchReason] = useState("");

  const handleOverrideSubmit = useCallback(async () => {
    if (!overrideMonth || !overrideField || !overrideReason || overrideReason.length < 5) return;
    const val = Number(overrideValue);
    if (isNaN(val)) return;
    await overrideMut.mutateAsync({
      monthId: overrideMonth.id,
      data: { overrides: { [overrideField]: val }, reason: overrideReason },
    });
    setOverrideMonth(null);
    setOverrideField("");
    setOverrideValue("");
    setOverrideReason("");
  }, [overrideMonth, overrideField, overrideValue, overrideReason, overrideMut]);

  const handleWdSubmit = useCallback(async () => {
    if (!wdMonth || !wdReason || wdReason.length < 5) return;
    const val = Number(wdValue);
    if (isNaN(val) || val < 0) return;
    await wdMut.mutateAsync({ monthId: wdMonth.id, data: { working_days: val, reason: wdReason } });
    setWdMonth(null);
    setWdValue("");
    setWdReason("");
  }, [wdMonth, wdValue, wdReason, wdMut]);

  const handleReset = useCallback(async (month: KpiPlanMonth, field?: string) => {
    await resetMut.mutateAsync({ monthId: month.id, data: { fields: field ? [field] : null } });
  }, [resetMut]);

  const handleBatchSubmit = useCallback(async () => {
    if (batchSelected.size === 0 || !batchField || !batchReason || batchReason.length < 5) return;
    const val = Number(batchValue);
    if (isNaN(val)) return;
    await batchMut.mutateAsync({
      month_ids: Array.from(batchSelected),
      overrides: { [batchField]: val },
      reason: batchReason,
    });
    setBatchSelected(new Set());
    setShowBatch(false);
    setBatchField("");
    setBatchValue("");
    setBatchReason("");
  }, [batchSelected, batchField, batchValue, batchReason, batchMut]);

  const toggleBatchSelect = (monthId: number) => {
    setBatchSelected((prev) => {
      const next = new Set(prev);
      if (next.has(monthId)) next.delete(monthId); else next.add(monthId);
      return next;
    });
  };

  if (isLoading) {
    return <PageContainer maxWidth="full"><Skeleton className="mb-4 h-10 w-64" /><Skeleton className="h-[400px] w-full" /></PageContainer>;
  }

  if (error || !plan) {
    return (
      <PageContainer maxWidth="full">
        <PageHeader title="KPI Plan" />
        <Card><CardContent className="py-12 text-center">
          <p className="text-muted-foreground">
            {error?.response?.status === 404 ? "KPI Plan không tồn tại hoặc bạn không có quyền truy cập." : "Lỗi tải dữ liệu."}
          </p>
          <Button variant="outline" className="mt-4" onClick={() => router.push("/admin/kpi-planning")}>Quay lại</Button>
        </CardContent></Card>
      </PageContainer>
    );
  }

  const sortedMonths = [...(plan.months || [])].sort((a, b) => a.month - b.month);

  return (
    <PageContainer maxWidth="full">
      <div className="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.push("/admin/kpi-planning")}>
          <ArrowLeft className="mr-1 h-4 w-4" />Quay lại
        </Button>
      </div>

      <PageHeader
        title={`KPI Plan #${plan.id} — ${plan.fiscal_year}`}
        description={`Chỉ tiêu: ${plan.annual_enrollment_target} | SLA: ${plan.sla_target}% | Response: ${plan.response_time_target}h`}
      />

      {/* Actions */}
      <div className="mb-4 flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => { setUpdateTarget(plan.annual_enrollment_target); setUpdateSla(plan.sla_target); setUpdateResponseTime(plan.response_time_target); setShowUpdate(true); }}>
          <Pencil className="mr-1 h-4 w-4" />Sửa Plan
        </Button>
        <Button variant="outline" size="sm" onClick={() => regenerateMut.mutate()} disabled={regenerateMut.isPending}>
          <RefreshCw className="mr-1 h-4 w-4" />Tính lại KPI
        </Button>
        <Button variant="outline" size="sm" onClick={() => { setCloneYear(plan.fiscal_year + 1); setShowClone(true); }}>
          <Copy className="mr-1 h-4 w-4" />Clone sang năm mới
        </Button>
        {batchSelected.size > 0 && (
          <Button size="sm" onClick={() => setShowBatch(true)}>
            Batch Override ({batchSelected.size} tháng)
          </Button>
        )}
      </div>

      {/* Monthly Grid: 12 months × 7+2 KPIs + actuals (C2 + C5) */}
      <Card>
        <CardHeader><CardTitle>KPI Grid — Target vs Actual</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <TooltipProvider>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8"></TableHead>
                  <TableHead className="sticky left-0 z-10 bg-background">Tháng</TableHead>
                  <TableHead className="text-right">M_t</TableHead>
                  <TableHead className="text-right">WD</TableHead>
                  <TableHead className="text-right">TV/ngày</TableHead>
                  <TableHead className="text-right">Conv%</TableHead>
                  <TableHead className="text-right">Win%</TableHead>
                  <TableHead className="text-right">Eff%</TableHead>
                  <TableHead className="text-right">SLA%</TableHead>
                  <TableHead className="text-right">Resp(h)</TableHead>
                  <TableHead className="text-center">Actual Enroll</TableHead>
                  <TableHead className="text-center">Actual TV/d</TableHead>
                  <TableHead className="text-center">Actual Conv%</TableHead>
                  <TableHead className="text-center">Actual Win%</TableHead>
                  <TableHead className="text-center">Actual Eff%</TableHead>
                  <TableHead className="text-center">Actual SLA%</TableHead>
                  <TableHead className="text-center">Override</TableHead>
                  <TableHead className="text-center">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedMonths.map((m) => {
                  const hasOverride = m.overridden_fields && Object.keys(m.overridden_fields).length > 0;
                  return (
                    <TableRow key={m.id} className={batchSelected.has(m.id) ? "bg-blue-50 dark:bg-blue-950" : ""}>
                      <TableCell>
                        <Checkbox checked={batchSelected.has(m.id)} onCheckedChange={() => toggleBatchSelect(m.id)} />
                      </TableCell>
                      <TableCell className="sticky left-0 z-10 bg-background font-medium">{MONTH_LABELS[m.month]}</TableCell>
                      <TableCell className="text-right font-semibold">{m.enrollment_target}</TableCell>
                      <TableCell className="text-right">
                        <button className="cursor-pointer underline decoration-dashed hover:text-primary" onClick={() => { setWdMonth(m); setWdValue(String(m.working_days)); }}>
                          {m.working_days}
                        </button>
                      </TableCell>
                      <OverrideCell month={m} field="consultations_daily" value={m.consultations_daily} d={0} onOverride={() => { setOverrideMonth(m); setOverrideField("consultations_daily"); setOverrideValue(String(m.consultations_daily ?? "")); }} />
                      <OverrideCell month={m} field="conversion_rate" value={m.conversion_rate} suf="%" onOverride={() => { setOverrideMonth(m); setOverrideField("conversion_rate"); setOverrideValue(String(m.conversion_rate ?? "")); }} />
                      <OverrideCell month={m} field="win_rate" value={m.win_rate} suf="%" onOverride={() => { setOverrideMonth(m); setOverrideField("win_rate"); setOverrideValue(String(m.win_rate ?? "")); }} />
                      <OverrideCell month={m} field="consultation_effectiveness" value={m.consultation_effectiveness} suf="%" onOverride={() => { setOverrideMonth(m); setOverrideField("consultation_effectiveness"); setOverrideValue(String(m.consultation_effectiveness ?? "")); }} />
                      {/* SLA + Response Time (guardrails from plan, same for all months) */}
                      <TableCell className="text-right text-muted-foreground">{plan.sla_target}%</TableCell>
                      <TableCell className="text-right text-muted-foreground">{plan.response_time_target}h</TableCell>
                      {/* Actuals (C5) */}
                      <TableCell className="text-center"><ActualCell target={m.enrollment_target} actual={m.actual_enrollments} d={0} /></TableCell>
                      <TableCell className="text-center"><ActualCell target={m.consultations_daily} actual={m.actual_consultations_avg} d={1} /></TableCell>
                      <TableCell className="text-center"><ActualCell target={m.conversion_rate} actual={m.actual_conversion_rate} suf="%" /></TableCell>
                      <TableCell className="text-center"><ActualCell target={m.win_rate} actual={m.actual_win_rate} suf="%" /></TableCell>
                      <TableCell className="text-center"><ActualCell target={m.consultation_effectiveness} actual={m.actual_consultation_effectiveness} suf="%" /></TableCell>
                      <TableCell className="text-center"><ActualCell target={plan.sla_target} actual={m.actual_sla_compliance_rate} suf="%" /></TableCell>
                      <TableCell className="text-center">
                        {hasOverride ? (
                          <Tooltip><TooltipTrigger>
                            <Badge variant="secondary" className="text-xs">{Object.keys(m.overridden_fields).length}f</Badge>
                          </TooltipTrigger><TooltipContent className="max-w-xs">
                            <p className="font-medium">Override: {Object.keys(m.overridden_fields).join(", ")}</p>
                            {m.override_reason && <p className="text-xs">Lý do: {m.override_reason}</p>}
                          </TooltipContent></Tooltip>
                        ) : <span className="text-muted-foreground">-</span>}
                      </TableCell>
                      <TableCell className="text-center">
                        {hasOverride && (
                          <Button size="sm" variant="ghost" onClick={() => handleReset(m)} title="Reset all overrides">
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

          <div className="mt-3 flex items-center gap-6 text-sm text-muted-foreground">
            <span>Tổng M_t: <strong>{sortedMonths.reduce((s, m) => s + m.enrollment_target, 0)}</strong> / {plan.annual_enrollment_target}</span>
            <span>Actual YTD: <strong>{sortedMonths.reduce((s, m) => s + (m.actual_enrollments ?? 0), 0)}</strong></span>
          </div>
        </CardContent>
      </Card>

      {/* Override Dialog */}
      <Dialog open={!!overrideMonth} onOpenChange={() => setOverrideMonth(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Override KPI — {overrideMonth && MONTH_LABELS[overrideMonth.month]}</DialogTitle>
            <DialogDescription>Nhập giá trị mới cho {overrideField}.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">Field: {overrideField}</label>
              <Input type="number" step="any" value={overrideValue} onChange={(e) => setOverrideValue(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Lý do <span className="text-destructive">*</span></label>
              <Textarea value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} placeholder="Tối thiểu 5 ký tự" />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={handleOverrideSubmit} disabled={overrideMut.isPending || !overrideReason || overrideReason.length < 5}>
              {overrideMut.isPending ? "Đang lưu…" : "Xác nhận"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Working Days Dialog */}
      <Dialog open={!!wdMonth} onOpenChange={() => setWdMonth(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Sửa ngày làm việc — {wdMonth && MONTH_LABELS[wdMonth.month]}</DialogTitle></DialogHeader>
          <div className="grid gap-4 py-4">
            <div><label className="mb-1 block text-sm font-medium">Số ngày làm việc</label><Input type="number" min={0} max={31} value={wdValue} onChange={(e) => setWdValue(e.target.value)} /></div>
            <div><label className="mb-1 block text-sm font-medium">Lý do <span className="text-destructive">*</span></label><Textarea value={wdReason} onChange={(e) => setWdReason(e.target.value)} placeholder="Tối thiểu 5 ký tự" /></div>
          </div>
          <DialogFooter><Button onClick={handleWdSubmit} disabled={wdMut.isPending || !wdReason || wdReason.length < 5}>Cập nhật</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Batch Override Dialog */}
      <Dialog open={showBatch} onOpenChange={setShowBatch}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Batch Override — {batchSelected.size} tháng</DialogTitle>
            <DialogDescription>Áp dụng cùng override cho các tháng đã chọn.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">Field</label>
              <select className="w-full rounded border p-2 text-sm" value={batchField} onChange={(e) => setBatchField(e.target.value)}>
                <option value="">Chọn field</option>
                {OVERRIDABLE_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
            <div><label className="mb-1 block text-sm font-medium">Giá trị</label><Input type="number" step="any" value={batchValue} onChange={(e) => setBatchValue(e.target.value)} /></div>
            <div><label className="mb-1 block text-sm font-medium">Lý do <span className="text-destructive">*</span></label><Textarea value={batchReason} onChange={(e) => setBatchReason(e.target.value)} placeholder="Tối thiểu 5 ký tự" /></div>
          </div>
          <DialogFooter>
            <Button onClick={handleBatchSubmit} disabled={batchMut.isPending || !batchField || !batchReason || batchReason.length < 5}>
              {batchMut.isPending ? "Đang lưu…" : `Override ${batchSelected.size} tháng`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Update Plan Dialog */}
      <Dialog open={showUpdate} onOpenChange={setShowUpdate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sửa KPI Plan</DialogTitle>
            <DialogDescription>Thay đổi chỉ tiêu giữa năm sẽ redistribute cho các tháng còn lại.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div><label className="mb-1 block text-sm font-medium">Chỉ tiêu nhập học/năm</label><Input type="number" min={1} max={10000} value={updateTarget ?? ""} onChange={(e) => setUpdateTarget(Number(e.target.value))} /></div>
            <div><label className="mb-1 block text-sm font-medium">SLA Target (%)</label><Input type="number" min={0} max={100} step={0.1} value={updateSla ?? ""} onChange={(e) => setUpdateSla(Number(e.target.value))} /></div>
            <div><label className="mb-1 block text-sm font-medium">Response Time (h)</label><Input type="number" min={1} max={48} step={0.5} value={updateResponseTime ?? ""} onChange={(e) => setUpdateResponseTime(Number(e.target.value))} /></div>
          </div>
          <DialogFooter>
            <Button onClick={async () => { await updateMut.mutateAsync({ annual_enrollment_target: updateTarget, sla_target: updateSla, response_time_target: updateResponseTime }); setShowUpdate(false); }} disabled={updateMut.isPending}>
              {updateMut.isPending ? "Đang lưu…" : "Cập nhật"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Clone Plan Dialog (P5) */}
      <Dialog open={showClone} onOpenChange={setShowClone}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clone KPI Plan sang năm mới</DialogTitle>
            <DialogDescription>
              Tạo bản sao plan này cho năm tài chính khác. Chỉ tiêu, trọng số và guardrails sẽ được sao chép.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">Năm tài chính đích</label>
              <Input type="number" min={2020} max={2100} value={cloneYear ?? ""} onChange={(e) => setCloneYear(Number(e.target.value))} />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={async () => {
                if (!cloneYear) return;
                const newPlan = await cloneMut.mutateAsync({ planId, data: { fiscal_year: cloneYear } });
                setShowClone(false);
                router.push(`/admin/kpi-planning/${newPlan.id}`);
              }}
              disabled={cloneMut.isPending || !cloneYear}
            >
              {cloneMut.isPending ? "Đang clone…" : "Clone"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}

function OverrideCell({ month, field, value, d = 2, suf = "", onOverride }: {
  month: KpiPlanMonth; field: string; value: number | null; d?: number; suf?: string; onOverride: () => void;
}) {
  const isOverridden = !!month.overridden_fields?.[field];
  return (
    <TableCell className="text-right">
      <button
        className={`cursor-pointer hover:text-primary ${isOverridden ? "font-semibold text-blue-600 underline decoration-dotted" : ""}`}
        onClick={onOverride}
        title={isOverridden ? "Đã override — click để sửa" : "Click để override"}
      >
        {fmtVal(value, d, suf)}
      </button>
    </TableCell>
  );
}
