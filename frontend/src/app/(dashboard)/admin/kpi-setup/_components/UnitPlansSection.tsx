"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { Eye, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { kpiPlanningKeys, useCreatePlan, useKpiPlan } from "@/hooks/useKpiPlanning";
import { kpiSetupKeys } from "@/hooks/useKpiSetup";
import type { UnitCoverage } from "@/types/kpi-setup.types";
import { DEFAULT_SEASONAL_WEIGHTS } from "@/types/kpi-planning.types";
import { PlanDetailSheet } from "./PlanDetailSheet";

interface ApiError {
  detail: string;
}

interface Props {
  units: UnitCoverage[];
  fiscalYear: number;
  triggerCreateForUnit?: number | null;
  onActionHandled?: () => void;
  isAdmin?: boolean;
}

type DialogMode =
  | { type: "create"; unitId: number; unitName: string }
  | { type: "edit"; planId: number; unitName: string }
  | null;

export function UnitPlansSection({
  units,
  fiscalYear,
  triggerCreateForUnit = null,
  onActionHandled,
  isAdmin = true,
}: Props) {
  const qc = useQueryClient();
  const createPlanMut = useCreatePlan();

  const [dialogMode, setDialogMode] = useState<DialogMode>(null);
  const [annualTarget, setAnnualTarget] = useState(300);
  const [slaTarget, setSlaTarget] = useState(85);
  const [responseTime, setResponseTime] = useState(2);
  const [seasonalWeights, setSeasonalWeights] = useState<number[]>(
    DEFAULT_SEASONAL_WEIGHTS.map((w) => Math.round(w * 1000) / 10)
  );
  const [sheetPlan, setSheetPlan] = useState<{
    planId: number;
    unitName: string;
  } | null>(null);

  const isDialogOpen = dialogMode !== null;

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

  const editPlanId = dialogMode?.type === "edit" ? dialogMode.planId : 0;
  const shouldFetchPlan = dialogMode?.type === "edit" && editPlanId > 0;
  const { data: planDetail } = useKpiPlan(editPlanId, shouldFetchPlan);

  // Sync fetched plan detail into form state (render-time state adjustment pattern)
  const [populatedPlanId, setPopulatedPlanId] = useState<number | null>(null);
  if (planDetail && dialogMode?.type === "edit" && populatedPlanId !== planDetail.id) {
    setPopulatedPlanId(planDetail.id);
    setAnnualTarget(planDetail.annual_enrollment_target ?? 300);
    setSlaTarget(planDetail.sla_target ?? 85);
    setResponseTime(planDetail.response_time_target ?? 2);
    setSeasonalWeights(
      (planDetail.seasonal_weights ?? DEFAULT_SEASONAL_WEIGHTS).map(
        (w) => Math.round(w * 1000) / 10
      )
    );
  }

  const openCreateDialog = useCallback((unit: UnitCoverage) => {
    setDialogMode({
      type: "create",
      unitId: unit.unit_id,
      unitName: unit.unit_name,
    });
    setAnnualTarget(unit.annual_target ?? 300);
    setSlaTarget(85);
    setResponseTime(2);
    setSeasonalWeights(DEFAULT_SEASONAL_WEIGHTS.map((w) => Math.round(w * 1000) / 10));
  }, []);

  const openEditDialog = useCallback((unit: UnitCoverage) => {
    if (unit.plan_id == null) {
      return;
    }

    setDialogMode({
      type: "edit",
      planId: unit.plan_id,
      unitName: unit.unit_name,
    });
    setAnnualTarget(unit.annual_target ?? 300);
  }, []);

  const closeDialog = useCallback(() => {
    setDialogMode(null);
    setPopulatedPlanId(null);
  }, []);

  useEffect(() => {
    if (triggerCreateForUnit == null) {
      return;
    }

    const unit = units.find(
      (candidate) =>
        candidate.unit_id === triggerCreateForUnit && candidate.plan_id == null,
    );

    const timer = unit
      ? setTimeout(() => {
        openCreateDialog(unit);
      }, 0)
      : null;

    onActionHandled?.();

    return () => {
      if (timer != null) {
        clearTimeout(timer);
      }
    };
  }, [onActionHandled, openCreateDialog, triggerCreateForUnit, units]);

  const dialogTitle = useMemo(() => {
    if (!dialogMode) {
      return "";
    }
    return dialogMode.type === "create" ? "Tạo KPI Plan" : "Sửa chỉ tiêu";
  }, [dialogMode]);

  const isPending = createPlanMut.isPending || updatePlanMut.isPending;

  const handleSubmit = async () => {
    const normalizedTarget = Math.max(1, Math.floor(annualTarget || 0));

    const totalWeights = seasonalWeights.reduce((s, v) => s + (v || 0), 0);
    const isWeightsOk = Math.abs(totalWeights - 100) <= 0.5;

    if (!dialogMode || Number.isNaN(normalizedTarget) || !isWeightsOk) {
      return;
    }

    const weightsAsFractions = seasonalWeights.map((w) => w / 100);

    if (dialogMode.type === "create") {
      await createPlanMut.mutateAsync({
        unit_id: dialogMode.unitId,
        fiscal_year: fiscalYear,
        annual_enrollment_target: normalizedTarget,
        sla_target: slaTarget,
        response_time_target: responseTime,
        seasonal_weights: weightsAsFractions,
      });
      await qc.invalidateQueries({ queryKey: kpiSetupKeys.all });
      closeDialog();
      return;
    }

    await updatePlanMut.mutateAsync({
      planId: dialogMode.planId,
      annualTarget: normalizedTarget,
      slaTarget,
      responseTime,
      seasonalWeights: weightsAsFractions,
    });
    closeDialog();
  };

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
                      <div className="flex items-center justify-end gap-2">
                        {isAdmin && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => openEditDialog(unit)}
                          >
                            <Pencil aria-hidden="true" className="h-4 w-4" />
                            Sửa
                          </Button>
                        )}
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-xs text-muted-foreground"
                          onClick={() =>
                            setSheetPlan({
                              planId: unit.plan_id!,
                              unitName: unit.unit_name,
                            })
                          }
                        >
                          <Eye aria-hidden="true" className="h-3.5 w-3.5" />
                          Chi tiết tháng
                        </Button>
                      </div>
                    ) : isAdmin ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => openCreateDialog(unit)}
                      >
                        <Plus aria-hidden="true" className="h-4 w-4" />
                        Tạo
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <Dialog open={isDialogOpen} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{dialogTitle}</DialogTitle>
            <DialogDescription>
              {dialogMode?.unitName ? `Đơn vị: ${dialogMode.unitName}` : ""}
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
              <div className="flex items-center justify-between">
                <Label>Trọng số theo tháng (%)</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-auto px-2 py-0.5 text-xs"
                  onClick={() =>
                    setSeasonalWeights(
                      DEFAULT_SEASONAL_WEIGHTS.map(
                        (w) => Math.round(w * 1000) / 10,
                      ),
                    )
                  }
                >
                  Mặc định
                </Button>
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
              {(() => {
                const total = seasonalWeights.reduce((s, v) => s + (v || 0), 0);
                const isOk = Math.abs(total - 100) <= 0.5;
                return (
                  <p
                    className={`mt-1 text-xs ${isOk ? "text-muted-foreground" : "text-destructive"}`}
                  >
                    Tổng: {total.toFixed(1)}%
                    {isOk ? "" : " — cần bằng 100%"}
                  </p>
                );
              })()}
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={closeDialog}
              disabled={isPending}
            >
              Hủy
            </Button>
            <Button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={isPending || annualTarget < 1 || Math.abs(seasonalWeights.reduce((a, b) => a + (b || 0), 0) - 100) > 0.5}
            >
              {isPending ? "Đang lưu..." : "Lưu"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PlanDetailSheet
        planId={sheetPlan?.planId ?? null}
        unitName={sheetPlan?.unitName}
        onOpenChange={(open) => {
          if (!open) setSheetPlan(null);
        }}
      />
    </Card>
  );
}
