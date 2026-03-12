"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { kpiPlanningKeys, useCreatePlan, useKpiPlan, usePreviewPlan } from "@/hooks/useKpiPlanning";
import { kpiSetupKeys } from "@/hooks/useKpiSetup";
import {
  DEFAULT_SEASONAL_WEIGHTS,
  EVEN_WEIGHTS,
  HIGH_SEASON_WEIGHTS,
  MONTH_LABELS,
} from "@/types/kpi-planning.types";

interface ApiError {
  detail: string;
}

function normalizeToHundred(weights: number[]): number[] {
  const sum = weights.reduce((acc, v) => acc + (v || 0), 0);
  if (sum <= 0)
    return DEFAULT_SEASONAL_WEIGHTS.map((w) => Math.round(w * 1000) / 10);
  const normalized = weights.map(
    (w) => Math.round(((w || 0) / sum) * 1000) / 10,
  );
  const roundedSum = normalized.reduce((acc, v) => acc + v, 0);
  const delta = Math.round((100 - roundedSum) * 10) / 10;
  if (delta !== 0) {
    const maxIdx = normalized.reduce(
      (best, v, i, arr) => (v > arr[best] ? i : best),
      0,
    );
    normalized[maxIdx] = Math.round((normalized[maxIdx] + delta) * 10) / 10;
  }
  return normalized;
}

function InfoHint({ content }: { content: string }) {
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-muted-foreground/40 text-[10px] font-semibold leading-none text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={content}
          >
            i
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[280px] text-xs">
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export type PlanDialogMode =
  | { type: "create"; unitId: number; unitName: string }
  | { type: "edit"; planId: number; unitId: number; unitName: string }
  | null;

interface Props {
  mode: NonNullable<PlanDialogMode>;
  fiscalYear: number;
  onClose: () => void;
}

export function CreateEditPlanDialog({ mode, fiscalYear, onClose }: Props) {
  const qc = useQueryClient();
  const createPlanMut = useCreatePlan();

  const [annualTarget, setAnnualTarget] = useState(300);
  const [slaTarget, setSlaTarget] = useState(85);
  const [responseTime, setResponseTime] = useState(2);
  const [seasonalWeights, setSeasonalWeights] = useState<number[]>(
    DEFAULT_SEASONAL_WEIGHTS.map((w) => Math.round(w * 1000) / 10),
  );

  const updatePlanMut = useMutation<
    unknown,
    AxiosError<ApiError>,
    {
      planId: number;
      annualTarget: number;
      slaTarget: number;
      responseTime: number;
      seasonalWeights: number[];
    }
  >({
    mutationFn: async ({ planId, annualTarget: target, slaTarget: sla, responseTime: rt, seasonalWeights: weights }) => {
      const res = await api.put(`/api/admin/kpi-planning/plans/${planId}`, {
        annual_enrollment_target: target,
        sla_target: sla,
        response_time_target: rt,
        seasonal_weights: weights,
      });
      return res.data;
    },
    onSuccess: async (_data, variables) => {
      toast.success("Đã cập nhật chỉ tiêu KPI Plan");
      await qc.invalidateQueries({ queryKey: kpiPlanningKeys.plans() });
      await qc.invalidateQueries({ queryKey: kpiPlanningKeys.planDetail(variables.planId) });
      await qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || "Lỗi cập nhật KPI Plan");
    },
  });

  // Edit mode: fetch existing plan
  const editPlanId = mode.type === "edit" ? mode.planId : 0;
  const shouldFetchPlan = mode.type === "edit" && editPlanId > 0;
  const { data: planDetail } = useKpiPlan(editPlanId, shouldFetchPlan);

  // Sync fetched plan detail into form state
  const [populatedPlanId, setPopulatedPlanId] = useState<number | null>(null);
  useEffect(() => {
    if (planDetail && mode.type === "edit" && populatedPlanId !== planDetail.id) {
      setPopulatedPlanId(planDetail.id);
      setAnnualTarget(planDetail.annual_enrollment_target ?? 300);
      setSlaTarget(planDetail.sla_target ?? 85);
      setResponseTime(planDetail.response_time_target ?? 2);
      setSeasonalWeights(
        (planDetail.seasonal_weights ?? [...DEFAULT_SEASONAL_WEIGHTS]).map(
          (w) => Math.round(w * 1000) / 10,
        ),
      );
    }
  }, [planDetail, mode, populatedPlanId]);

  // Live preview (debounced 500ms)
  const previewMut = usePreviewPlan();
  const weightsKey = seasonalWeights.join(",");

  useEffect(() => {
    if (annualTarget < 1) return;
    const totalW = seasonalWeights.reduce((s, v) => s + (v || 0), 0);
    if (Math.abs(totalW - 100) > 0.5) return;

    const timer = setTimeout(() => {
      previewMut.mutate({
        unit_id: mode.unitId,
        fiscal_year: fiscalYear,
        annual_enrollment_target: Math.max(1, Math.floor(annualTarget)),
        sla_target: slaTarget,
        response_time_target: responseTime,
        seasonal_weights: seasonalWeights.map((w) => w / 100),
      });
    }, 500);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [annualTarget, slaTarget, responseTime, weightsKey, mode.unitId, fiscalYear]);

  const isPending = createPlanMut.isPending || updatePlanMut.isPending;

  const weightsTotal = useMemo(
    () => seasonalWeights.reduce((s, v) => s + (v || 0), 0),
    [seasonalWeights],
  );
  const isWeightsOk = Math.abs(weightsTotal - 100) <= 0.5;

  // Reset stale preview when weights become invalid
  useEffect(() => {
    if (!isWeightsOk) {
      previewMut.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isWeightsOk]);

  const handleSubmit = async () => {
    const normalizedTarget = Math.max(1, Math.floor(annualTarget || 0));
    if (Number.isNaN(normalizedTarget) || !isWeightsOk) return;

    const weightsAsFractions = seasonalWeights.map((w) => w / 100);

    if (mode.type === "create") {
      await createPlanMut.mutateAsync({
        unit_id: mode.unitId,
        fiscal_year: fiscalYear,
        annual_enrollment_target: normalizedTarget,
        sla_target: slaTarget,
        response_time_target: responseTime,
        seasonal_weights: weightsAsFractions,
      });
      await qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
      onClose();
      return;
    }

    await updatePlanMut.mutateAsync({
      planId: mode.planId,
      annualTarget: normalizedTarget,
      slaTarget,
      responseTime,
      seasonalWeights: weightsAsFractions,
    });
    onClose();
  };

  const dialogTitle = mode.type === "create" ? "Tạo KPI Plan" : "Sửa chỉ tiêu";

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-scroll">
        <DialogHeader>
          <DialogTitle>{dialogTitle}</DialogTitle>
          <DialogDescription>
            Đơn vị: {mode.unitName}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="plan-annual-target">Chỉ tiêu nhập học/năm</Label>
            <Input
              id="plan-annual-target"
              type="number"
              min={1}
              max={10000}
              step={1}
              value={annualTarget || ""}
              onChange={(e) => setAnnualTarget(Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="plan-sla-target">SLA Target (%)</Label>
            <Input
              id="plan-sla-target"
              type="number"
              min={0}
              max={100}
              step={0.1}
              value={slaTarget || ""}
              onChange={(e) => setSlaTarget(Number(e.target.value))}
            />
            <p className="text-xs text-muted-foreground">
              Tỷ lệ lead được phản hồi đúng thời gian cam kết.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="plan-response-time">Response Time (h)</Label>
            <Input
              id="plan-response-time"
              type="number"
              min={1}
              max={48}
              step={0.5}
              value={responseTime || ""}
              onChange={(e) => setResponseTime(Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label>Trọng số theo tháng (%)</Label>
              <div className="flex flex-wrap items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-auto px-2 py-0.5 text-xs"
                  onClick={() =>
                    setSeasonalWeights(
                      DEFAULT_SEASONAL_WEIGHTS.map((w) => Math.round(w * 1000) / 10),
                    )
                  }
                >
                  Mặc định
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-auto px-2 py-0.5 text-xs"
                  onClick={() =>
                    setSeasonalWeights(
                      EVEN_WEIGHTS.map((w) => Math.round(w * 1000) / 10),
                    )
                  }
                >
                  Đồng đều
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-auto px-2 py-0.5 text-xs"
                  onClick={() =>
                    setSeasonalWeights(
                      HIGH_SEASON_WEIGHTS.map((w) => Math.round(w * 1000) / 10),
                    )
                  }
                >
                  Cao điểm T6-T9
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-auto px-2 py-0.5 text-xs"
                  onClick={() =>
                    setSeasonalWeights(normalizeToHundred(seasonalWeights))
                  }
                >
                  <RotateCcw aria-hidden="true" className="mr-1 h-3 w-3" />
                  Cân 100%
                </Button>
              </div>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {seasonalWeights.map((w, i) => (
                <div key={i} className="flex items-center gap-1">
                  <span className="w-7 text-xs text-muted-foreground">T{i + 1}</span>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    step={0.1}
                    className="h-8 text-sm"
                    value={w || ""}
                    onChange={(e) => {
                      const next = [...seasonalWeights];
                      next[i] = Number(e.target.value);
                      setSeasonalWeights(next);
                    }}
                  />
                </div>
              ))}
            </div>
            <p
              className={`mt-1 text-xs ${isWeightsOk ? "text-muted-foreground" : "text-destructive"}`}
            >
              Tổng: {weightsTotal.toFixed(1)}%
              {isWeightsOk ? "" : " — cần bằng 100%"}
            </p>
          </div>

          {/* Live preview table */}
          {(previewMut.data || previewMut.isPending) && (
            <div className="space-y-2 border-t pt-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">
                  Kết quả dự kiến (12 tháng)
                </span>
                {previewMut.isPending && (
                  <Loader2
                    aria-hidden="true"
                    className="h-3.5 w-3.5 animate-spin text-muted-foreground"
                  />
                )}
              </div>
              {previewMut.data?.holiday_warning && (
                <p className="text-xs text-amber-600">
                  {previewMut.data.holiday_warning}
                </p>
              )}
              {previewMut.isError && (
                <p className="text-xs text-destructive">
                  Không thể tải preview
                </p>
              )}
              {previewMut.data && (
                <>
                  <div className="max-h-[260px] overflow-auto rounded border">
                    <Table className="text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="sticky top-0 w-12 bg-background">Tháng</TableHead>
                          <TableHead className="sticky top-0 bg-background text-right">
                            <span className="inline-flex items-center justify-end gap-1">
                              M_t
                              <InfoHint content="Chỉ tiêu nhập học tháng, phân bổ từ chỉ tiêu năm theo trọng số mùa vụ." />
                            </span>
                          </TableHead>
                          <TableHead className="sticky top-0 bg-background text-right">WD</TableHead>
                          <TableHead className="sticky top-0 bg-background text-right">
                            <span className="inline-flex items-center justify-end gap-1">
                              TV/ngày
                              <InfoHint content="Tư vấn/ngày = ceil(M_t × k_t / ngày làm việc). Số buổi tư vấn cần đạt mỗi ngày." />
                            </span>
                          </TableHead>
                          <TableHead className="sticky top-0 bg-background text-right">
                            <span className="inline-flex items-center justify-end gap-1">
                              Conv%
                              <InfoHint content="Tỷ lệ chuyển đổi = (M_t / lead dự báo) × 100." />
                            </span>
                          </TableHead>
                          <TableHead className="sticky top-0 bg-background text-right">
                            <span className="inline-flex items-center justify-end gap-1">
                              Win%
                              <InfoHint content="Tỷ lệ chốt = (M_t / lead đã tư vấn dự báo) × 100." />
                            </span>
                          </TableHead>
                          <TableHead className="sticky top-0 bg-background text-right">
                            <span className="inline-flex items-center justify-end gap-1">
                              Eff%
                              <InfoHint content="Hiệu quả tư vấn = (M_t / lead tư vấn có tiến triển) × 100." />
                            </span>
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {previewMut.data.months.map((m) => (
                          <TableRow key={m.month}>
                            <TableCell className="font-medium">{MONTH_LABELS[m.month] ?? `T${m.month}`}</TableCell>
                            <TableCell className="text-right tabular-nums">{m.enrollment_target}</TableCell>
                            <TableCell className="text-right tabular-nums">{m.working_days}</TableCell>
                            <TableCell className="text-right tabular-nums">
                              {m.consultations_daily ?? "—"}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {m.conversion_rate != null ? m.conversion_rate.toFixed(1) : "—"}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {m.win_rate != null ? m.win_rate.toFixed(1) : "—"}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {m.consultation_effectiveness != null
                                ? m.consultation_effectiveness.toFixed(1)
                                : "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                    <span>
                      ∑M_t:{" "}
                      <strong className="text-foreground">
                        {previewMut.data.months.reduce((s, m) => s + m.enrollment_target, 0)}
                      </strong>
                    </span>
                    <span>
                      Chỉ tiêu năm:{" "}
                      <strong className="text-foreground">
                        {previewMut.data.annual_enrollment_target}
                      </strong>
                    </span>
                  </div>

                  <div className="mt-2 rounded-md border bg-muted/40 p-2.5 text-[11px] text-muted-foreground">
                    <p>
                      M_t là chỉ tiêu nhập học tháng. Hệ thống dùng
                      reverse-funnel để suy ra TV/ngày, Conv%, Win% và Eff%.
                      Giai đoạn đầu dùng hệ số mặc định; sau đó tự hiệu chỉnh
                      theo dữ liệu thực tế.
                    </p>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isPending}
          >
            Hủy
          </Button>
          <Button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={isPending || annualTarget < 1 || !isWeightsOk}
          >
            {isPending ? "Đang lưu…" : "Lưu"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
