"use client";

import { useEffect, useMemo, useState } from "react";

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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useAssignOfficerQuota,
  usePreviewPlan,
  useUpdatePlan,
} from "@/hooks/useKpiPlanning";
import type { UnitCoverage } from "@/types/kpi-setup.types";
import { MONTH_LABELS } from "@/types/kpi-planning.types";

export type QuotaDialogMode =
  | { type: "assign"; officerId: number; officerName: string; unitId: number }
  | { type: "edit"; officerId: number; officerName: string; planId: number; unitId: number }
  | null;

interface Props {
  mode: NonNullable<QuotaDialogMode>;
  unit: UnitCoverage;
  fiscalYear: number;
  onClose: () => void;
}

export function AssignQuotaDialog({ mode, unit, fiscalYear, onClose }: Props) {
  const assignQuotaMut = useAssignOfficerQuota();
  const previewMut = usePreviewPlan();
  const updatePlanMut = useUpdatePlan(
    mode.type === "edit" ? mode.planId : 0,
  );

  const initialQuota = useMemo(() => {
    const officer = unit.officers.find((o) => o.officer_id === mode.officerId);
    if (!officer) return 50;
    return officer.annual_target > 0 ? officer.annual_target : 50;
  }, [unit, mode.officerId]);

  const [quota, setQuota] = useState(initialQuota);

  // Debounced preview
  const [debouncedQuota, setDebouncedQuota] = useState(initialQuota);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuota(quota), 400);
    return () => clearTimeout(timer);
  }, [quota]);

  // Trigger preview when quota changes — uses auto_mid_year instead of FE timezone calc
  useEffect(() => {
    if (debouncedQuota < 1 || !unit.plan_id) return;

    previewMut.mutate({
      unit_id: mode.unitId,
      fiscal_year: fiscalYear,
      annual_enrollment_target: debouncedQuota,
      seasonal_weights: unit.seasonal_weights ?? undefined,
      auto_mid_year: true,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuota, mode.unitId, fiscalYear]);

  // Quota info
  const quotaInfo = useMemo(() => {
    if (unit.annual_target == null) return null;
    const unitTarget = unit.annual_target;
    const totalAssigned = unit.total_officer_target;
    const currentOfficerTarget =
      unit.officers.find((o) => o.officer_id === mode.officerId)?.annual_target ?? 0;
    const othersTotal = totalAssigned - currentOfficerTarget;
    const remaining = unitTarget - othersTotal - (quota || 0);
    return { unitTarget, othersTotal, remaining };
  }, [unit, mode.officerId, quota]);

  const handleSubmit = async () => {
    const normalizedQuota = Math.max(1, Math.floor(quota || 0));

    if (mode.type === "assign") {
      await assignQuotaMut.mutateAsync({
        unit_id: mode.unitId,
        officer_id: mode.officerId,
        fiscal_year: fiscalYear,
        quota: normalizedQuota,
      });
    } else {
      await updatePlanMut.mutateAsync({
        annual_enrollment_target: normalizedQuota,
      });
    }
    onClose();
  };

  const isPending = assignQuotaMut.isPending || updatePlanMut.isPending;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {mode.type === "edit" ? "Sửa chỉ tiêu" : "Gán chỉ tiêu"}
          </DialogTitle>
          <DialogDescription>
            Cán bộ: {mode.officerName} — Đơn vị: {unit.unit_name}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Quota info */}
          {quotaInfo && (
            <div className="grid grid-cols-3 gap-3 rounded-lg border p-3 text-sm">
              <div>
                <p className="text-muted-foreground">Chỉ tiêu ĐV</p>
                <p className="font-semibold tabular-nums">{quotaInfo.unitTarget}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Đã gán (khác)</p>
                <p className="font-semibold tabular-nums">{quotaInfo.othersTotal}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Còn lại</p>
                <p className={`font-semibold tabular-nums ${quotaInfo.remaining < 0 ? "text-destructive" : ""}`}>
                  {quotaInfo.remaining}
                </p>
              </div>
            </div>
          )}

          {/* Quota input */}
          <div className="space-y-2">
            <Label htmlFor="officer-quota">Chỉ tiêu năm (quota)</Label>
            <Input
              id="officer-quota"
              type="number"
              min={1}
              max={10000}
              step={1}
              value={quota || ""}
              onChange={(e) => setQuota(Number(e.target.value))}
            />
            {quotaInfo && quotaInfo.remaining < 0 && (
              <p className="text-xs text-destructive">
                Vượt quá chỉ tiêu đơn vị {Math.abs(quotaInfo.remaining)}
              </p>
            )}
          </div>

          {/* Preview table */}
          {previewMut.data && debouncedQuota >= 1 && (
            <div className="space-y-2">
              <Label>Dự kiến 12 tháng</Label>
              <div className="max-h-[280px] overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="sticky top-0 bg-background">Tháng</TableHead>
                      <TableHead className="sticky top-0 bg-background text-right">Chỉ tiêu</TableHead>
                      <TableHead className="sticky top-0 bg-background text-right">Ngày LV</TableHead>
                      <TableHead className="sticky top-0 bg-background text-right">TV/ngày</TableHead>
                      <TableHead className="sticky top-0 bg-background text-right">Conv%</TableHead>
                      <TableHead className="sticky top-0 bg-background text-right">Win%</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewMut.data.months.map((m) => (
                      <TableRow key={m.month} className={m.enrollment_target === 0 ? "opacity-40" : ""}>
                        <TableCell>{MONTH_LABELS[m.month] ?? `T${m.month}`}</TableCell>
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
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
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
            disabled={isPending || quota < 1 || (debouncedQuota !== quota) || previewMut.isPending}
          >
            {isPending ? "Đang lưu…" : (debouncedQuota !== quota || previewMut.isPending) ? "Đang tính…" : "Lưu"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
