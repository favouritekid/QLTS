"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Eye, Pencil, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
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
  useAssignOfficerQuota,
  usePreviewPlan,
  useUpdatePlan,
} from "@/hooks/useKpiPlanning";
import type {
  OfficerCoverage,
  UnitCoverage,
} from "@/types/kpi-setup.types";
import {
  STATUS_CONFIG,
  TARGET_SOURCE_CONFIG,
} from "@/types/kpi-setup.types";
import { MONTH_LABELS } from "@/types/kpi-planning.types";
import { PlanDetailSheet } from "./PlanDetailSheet";

interface Props {
  units: UnitCoverage[];
  fiscalYear: number;
  triggerAssignForOfficer?: number | null;
  onActionHandled?: () => void;
  isAdmin?: boolean;
}

type OfficerDialogMode =
  | { type: "assign"; officerId: number; officerName: string; unitId: number }
  | { type: "edit"; officerId: number; officerName: string; planId: number; unitId: number }
  | null;

function TargetSourceBadge({ source }: { source: OfficerCoverage["target_source"] }) {
  const config = TARGET_SOURCE_CONFIG[source];
  const badge = (
    <Badge variant={config.variant} className="text-xs">
      {config.label}
    </Badge>
  );

  if (config.tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent>
          <p>{config.tooltip}</p>
        </TooltipContent>
      </Tooltip>
    );
  }

  return badge;
}

function StatusBadge({ status }: { status: OfficerCoverage["status"] }) {
  const config = STATUS_CONFIG[status];
  return (
    <Badge variant={config.variant} className="text-xs">
      {config.label}
    </Badge>
  );
}

export function OfficerTargetsSection({
  units,
  fiscalYear,
  triggerAssignForOfficer = null,
  onActionHandled,
  isAdmin = true,
}: Props) {
  const defaultOpen = units.length <= 5 ? units.map((u) => String(u.unit_id)) : [];
  const assignQuotaMut = useAssignOfficerQuota();
  const previewMut = usePreviewPlan();

  const [dialogMode, setDialogMode] = useState<OfficerDialogMode>(null);
  const [quota, setQuota] = useState(0);
  const [detailPlanId, setDetailPlanId] = useState<number | null>(null);
  const [detailUnitName, setDetailUnitName] = useState<string | undefined>();

  // Debounced preview
  const [debouncedQuota, setDebouncedQuota] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuota(quota), 400);
    return () => clearTimeout(timer);
  }, [quota]);

  // Find unit info for current dialog
  const currentUnit = useMemo(() => {
    if (!dialogMode) return null;
    return units.find((u) => u.unit_id === dialogMode.unitId) ?? null;
  }, [dialogMode, units]);

  // Trigger preview when quota changes
  useEffect(() => {
    if (!dialogMode || debouncedQuota < 1 || !currentUnit?.plan_id) return;

    const unitPlan = currentUnit;
    if (!unitPlan) return;

    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;
    const startMonth = fiscalYear === currentYear && currentMonth > 1 ? currentMonth : undefined;

    previewMut.mutate({
      unit_id: dialogMode.unitId,
      fiscal_year: fiscalYear,
      annual_enrollment_target: debouncedQuota,
      start_month: startMonth,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuota, dialogMode?.unitId, fiscalYear]);

  const openAssignDialog = useCallback((officer: OfficerCoverage, unitId: number) => {
    setDialogMode({
      type: "assign",
      officerId: officer.officer_id,
      officerName: officer.officer_name,
      unitId,
    });
    setQuota(officer.annual_target > 0 ? officer.annual_target : 50);
  }, []);

  const openEditDialog = useCallback((officer: OfficerCoverage, unitId: number) => {
    if (officer.plan_id != null) {
      setDialogMode({
        type: "edit",
        officerId: officer.officer_id,
        officerName: officer.officer_name,
        planId: officer.plan_id,
        unitId,
      });
      setQuota(officer.annual_target);
    } else {
      // Legacy: has target but no plan → treat as assign
      setDialogMode({
        type: "assign",
        officerId: officer.officer_id,
        officerName: officer.officer_name,
        unitId,
      });
      setQuota(officer.annual_target > 0 ? officer.annual_target : 50);
    }
  }, []);

  useEffect(() => {
    if (triggerAssignForOfficer == null) return;

    let matchedOfficer: OfficerCoverage | null = null;
    let matchedUnitId: number | null = null;
    for (const unit of units) {
      const officer = unit.officers.find((o) => o.officer_id === triggerAssignForOfficer);
      if (officer) {
        matchedOfficer = officer;
        matchedUnitId = unit.unit_id;
        break;
      }
    }

    if (matchedOfficer && matchedUnitId != null) {
      const o = matchedOfficer;
      const uid = matchedUnitId;
      const timer = setTimeout(() => openAssignDialog(o, uid), 0);
      onActionHandled?.();
      return () => clearTimeout(timer);
    }

    onActionHandled?.();
  }, [onActionHandled, openAssignDialog, triggerAssignForOfficer, units]);

  // Update plan mutation (for edit mode with existing plan)
  const updatePlanMut = useUpdatePlan(
    dialogMode?.type === "edit" ? dialogMode.planId : 0,
  );

  const handleSubmit = async () => {
    if (!dialogMode) return;
    const normalizedQuota = Math.max(1, Math.floor(quota || 0));

    if (dialogMode.type === "assign") {
      await assignQuotaMut.mutateAsync({
        unit_id: dialogMode.unitId,
        officer_id: dialogMode.officerId,
        fiscal_year: fiscalYear,
        quota: normalizedQuota,
      });
    } else {
      // Edit existing plan
      await updatePlanMut.mutateAsync({
        annual_enrollment_target: normalizedQuota,
      });
    }
    setDialogMode(null);
  };

  const isPending = assignQuotaMut.isPending || updatePlanMut.isPending;

  // Quota info
  const quotaInfo = useMemo(() => {
    if (!currentUnit || currentUnit.annual_target == null) return null;
    const unitTarget = currentUnit.annual_target;
    const totalAssigned = currentUnit.total_officer_target;
    // If editing, subtract current officer's target to get "others"
    const currentOfficerTarget = dialogMode
      ? currentUnit.officers.find(
          (o) => o.officer_id === ("officerId" in dialogMode ? dialogMode.officerId : 0),
        )?.annual_target ?? 0
      : 0;
    const othersTotal = totalAssigned - currentOfficerTarget;
    const remaining = unitTarget - othersTotal - (quota || 0);
    return { unitTarget, othersTotal, remaining };
  }, [currentUnit, dialogMode, quota]);

  const renderAction = (officer: OfficerCoverage, unitId: number) => {
    if (!isAdmin) return null;

    const buttons = [];

    // Edit/Assign button
    if (officer.target_source === "custom" && (officer.target_id != null || officer.plan_id != null)) {
      buttons.push(
        <Button
          key="edit"
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => openEditDialog(officer, unitId)}
        >
          <Pencil aria-hidden="true" className="h-4 w-4" />
          Sửa
        </Button>,
      );
    } else if (officer.target_source === "none") {
      buttons.push(
        <Button
          key="assign"
          type="button"
          variant="outline"
          size="sm"
          onClick={() => openAssignDialog(officer, unitId)}
        >
          <Plus aria-hidden="true" className="h-4 w-4" />
          Gán
        </Button>,
      );
    } else {
      buttons.push(
        <Tooltip key="override">
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => openAssignDialog(officer, unitId)}
            >
              <Plus aria-hidden="true" className="h-4 w-4" />
              Ghi đè
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>Kế thừa từ cấp trên. Tạo chỉ tiêu riêng để ghi đè.</p>
          </TooltipContent>
        </Tooltip>,
      );
    }

    // Detail button (only if officer has own plan)
    if (officer.plan_id != null) {
      buttons.push(
        <Button
          key="detail"
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            setDetailPlanId(officer.plan_id);
            const unitName = units.find((u) =>
              u.officers.some((o) => o.officer_id === officer.officer_id),
            )?.unit_name;
            setDetailUnitName(unitName);
          }}
        >
          <Eye aria-hidden="true" className="h-4 w-4" />
          Chi tiết
        </Button>,
      );
    }

    return <div className="flex gap-1 justify-end">{buttons}</div>;
  };

  return (
    <TooltipProvider>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Chỉ tiêu cán bộ</CardTitle>
        </CardHeader>
        <CardContent>
          {units.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Không có đơn vị nào.
            </p>
          ) : (
            <Accordion type="multiple" defaultValue={defaultOpen}>
              {units.map((unit) => (
                <AccordionItem key={unit.unit_id} value={String(unit.unit_id)}>
                  <AccordionTrigger className="hover:no-underline">
                    <div className="flex items-center gap-3 text-left">
                      <span className="font-medium">{unit.unit_name}</span>
                      <Badge variant="outline" className="text-xs">
                        {unit.officers.length} cán bộ
                      </Badge>
                      <span className="text-xs text-muted-foreground tabular-nums">
                        Tổng: {unit.total_officer_target}
                        {unit.annual_target != null && (
                          <> / {unit.annual_target}</>
                        )}
                      </span>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
                    {unit.officers.length === 0 ? (
                      <p className="text-sm text-muted-foreground py-2">
                        Không có cán bộ nào.
                      </p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Tên</TableHead>
                            <TableHead>Nguồn</TableHead>
                            <TableHead className="text-right">Chỉ tiêu</TableHead>
                            <TableHead className="text-right">Đã đạt</TableHead>
                            <TableHead className="w-[120px]">Tiến độ</TableHead>
                            <TableHead>Trạng thái</TableHead>
                            <TableHead className="text-right">Thao tác</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {unit.officers.map((officer) => (
                            <TableRow key={officer.officer_id}>
                              <TableCell className="font-medium">
                                {officer.officer_name}
                              </TableCell>
                              <TableCell>
                                <TargetSourceBadge source={officer.target_source} />
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {officer.annual_target}
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {officer.achieved_ytd}
                              </TableCell>
                              <TableCell>
                                <div className="flex items-center gap-2">
                                  <Progress
                                    value={Math.min(officer.progress_pct, 100)}
                                    className="h-2 flex-1"
                                  />
                                  <span className="text-xs tabular-nums w-10 text-right">
                                    {officer.progress_pct}%
                                  </span>
                                </div>
                              </TableCell>
                              <TableCell>
                                <StatusBadge status={officer.status} />
                              </TableCell>
                              <TableCell className="text-right">
                                {renderAction(officer, unit.unit_id)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          )}
        </CardContent>
      </Card>

      {/* Assign/Edit Dialog */}
      <Dialog open={dialogMode != null} onOpenChange={(open) => !open && setDialogMode(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {dialogMode?.type === "edit" ? "Sửa chỉ tiêu" : "Gán chỉ tiêu"}
            </DialogTitle>
            <DialogDescription>
              {dialogMode ? `Cán bộ: ${dialogMode.officerName}` : ""}
              {currentUnit ? ` — Đơn vị: ${currentUnit.unit_name}` : ""}
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
                          <TableCell>{MONTH_LABELS[m.month]}</TableCell>
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
              onClick={() => setDialogMode(null)}
              disabled={isPending}
            >
              Hủy
            </Button>
            <Button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={isPending || quota < 1}
            >
              {isPending ? "Đang lưu…" : "Lưu"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Plan Detail Sheet */}
      <PlanDetailSheet
        planId={detailPlanId}
        unitName={detailUnitName}
        onOpenChange={(open) => {
          if (!open) {
            setDetailPlanId(null);
            setDetailUnitName(undefined);
          }
        }}
      />
    </TooltipProvider>
  );
}
