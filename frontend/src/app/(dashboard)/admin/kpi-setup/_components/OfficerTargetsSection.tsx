"use client";

import { useCallback, useEffect, useState } from "react";
import { Pencil, Plus } from "lucide-react";

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
import { useCreateKpiTarget, useUpdateKpiTarget } from "@/hooks/useKpiSetup";
import type { OfficerCoverage, UnitCoverage } from "@/types/kpi-setup.types";
import {
  STATUS_CONFIG,
  TARGET_SOURCE_CONFIG,
} from "@/types/kpi-setup.types";

interface Props {
  units: UnitCoverage[];
  fiscalYear: number;
  triggerAssignForOfficer?: number | null;
  onActionHandled?: () => void;
}

type OfficerDialogMode =
  | { type: "assign"; officerId: number; officerName: string }
  | { type: "edit"; targetId: number; officerName: string }
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
}: Props) {
  const defaultOpen = units.length <= 5 ? units.map((u) => String(u.unit_id)) : [];
  const createTargetMut = useCreateKpiTarget();
  const updateTargetMut = useUpdateKpiTarget();

  const [dialogMode, setDialogMode] = useState<OfficerDialogMode>(null);
  const [annualTarget, setAnnualTarget] = useState(0);

  const openAssignDialog = useCallback((officer: OfficerCoverage) => {
    setDialogMode({
      type: "assign",
      officerId: officer.officer_id,
      officerName: officer.officer_name,
    });
    setAnnualTarget(officer.annual_target > 0 ? officer.annual_target : 100);
  }, []);

  const openEditDialog = useCallback((officer: OfficerCoverage) => {
    if (officer.target_id == null) {
      return;
    }

    setDialogMode({
      type: "edit",
      targetId: officer.target_id,
      officerName: officer.officer_name,
    });
    setAnnualTarget(officer.annual_target);
  }, []);

  useEffect(() => {
    if (triggerAssignForOfficer == null) {
      return;
    }

    let matchedOfficer: OfficerCoverage | null = null;
    for (const unit of units) {
      const officer = unit.officers.find((o) => o.officer_id === triggerAssignForOfficer);
      if (officer) {
        matchedOfficer = officer;
        break;
      }
    }

    const officerToAssign = matchedOfficer;
    const timer = officerToAssign
      ? setTimeout(() => {
        openAssignDialog(officerToAssign);
      }, 0)
      : null;

    onActionHandled?.();

    return () => {
      if (timer != null) {
        clearTimeout(timer);
      }
    };
  }, [onActionHandled, openAssignDialog, triggerAssignForOfficer, units]);

  const handleSubmit = async () => {
    if (!dialogMode) {
      return;
    }

    const normalizedTarget = Math.max(1, Math.floor(annualTarget || 0));

    if (dialogMode.type === "assign") {
      await createTargetMut.mutateAsync({
        kpi_code: "enrollments_annual",
        annual_target: normalizedTarget,
        fiscal_year: fiscalYear,
        officer_id: dialogMode.officerId,
      });
      setDialogMode(null);
      return;
    }

    await updateTargetMut.mutateAsync({
      id: dialogMode.targetId,
      data: { annual_target: normalizedTarget },
    });
    setDialogMode(null);
  };

  const isPending = createTargetMut.isPending || updateTargetMut.isPending;

  const renderAction = (officer: OfficerCoverage) => {
    if (officer.target_source === "custom" && officer.target_id != null) {
      return (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => openEditDialog(officer)}
        >
          <Pencil aria-hidden="true" className="h-4 w-4" />
          Sửa
        </Button>
      );
    }

    if (officer.target_source === "none") {
      return (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => openAssignDialog(officer)}
        >
          <Plus aria-hidden="true" className="h-4 w-4" />
          Gán
        </Button>
      );
    }

    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => openAssignDialog(officer)}
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
            Ghi đè
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>Kế thừa từ cấp trên. Tạo chỉ tiêu riêng để ghi đè.</p>
        </TooltipContent>
      </Tooltip>
    );
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
                                {renderAction(officer)}
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

      <Dialog open={dialogMode != null} onOpenChange={(open) => !open && setDialogMode(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogMode?.type === "edit" ? "Sửa chỉ tiêu" : "Gán chỉ tiêu"}
            </DialogTitle>
            <DialogDescription>
              {dialogMode?.officerName ? `Cán bộ: ${dialogMode.officerName}` : ""}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="officer-annual-target">Chỉ tiêu nhập học/năm</Label>
            <Input
              id="officer-annual-target"
              type="number"
              min={1}
              step={1}
              value={annualTarget || ""}
              onChange={(e) => setAnnualTarget(Number(e.target.value))}
            />
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
              disabled={isPending || annualTarget < 1}
            >
              {isPending ? "Đang lưu..." : "Lưu"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}
