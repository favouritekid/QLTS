"use client";

import { useState } from "react";
import { ChevronDown, Eye, Pencil, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type {
  OfficerCoverage,
  UnitCoverage,
} from "@/types/kpi-setup.types";
import {
  STATUS_CONFIG,
  TARGET_SOURCE_CONFIG,
} from "@/types/kpi-setup.types";
import { CreateEditPlanDialog, type PlanDialogMode } from "./CreateEditPlanDialog";
import { AssignQuotaDialog, type QuotaDialogMode } from "./AssignQuotaDialog";
import { PlanDetailSheet } from "./PlanDetailSheet";

interface Props {
  unit: UnitCoverage;
  fiscalYear: number;
  isAdmin?: boolean;
}

// ---------------------------------------------------------------------------
// QuotaBar — visual quota allocation bar
// ---------------------------------------------------------------------------
function QuotaBar({
  unitTarget,
  totalAssigned,
}: {
  unitTarget: number;
  totalAssigned: number;
}) {
  const pct = unitTarget > 0 ? Math.round((totalAssigned / unitTarget) * 100) : 0;
  const remaining = unitTarget - totalAssigned;
  return (
    <div className="mt-2 space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>Đã gán: {totalAssigned}/{unitTarget}</span>
        <span>Còn lại: {remaining}</span>
      </div>
      <Progress value={Math.min(pct, 100)} className="h-2" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// TargetSourceBadge
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------
function StatusBadge({ status }: { status: OfficerCoverage["status"] }) {
  const config = STATUS_CONFIG[status];
  return (
    <Badge variant={config.variant} className="text-xs">
      {config.label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// OfficerTable
// ---------------------------------------------------------------------------
function OfficerTable({
  officers,
  isAdmin,
  hasPlan,
  onAssign,
  onEdit,
  onViewDetail,
}: {
  officers: OfficerCoverage[];
  isAdmin: boolean;
  hasPlan: boolean;
  onAssign: (officer: OfficerCoverage) => void;
  onEdit: (officer: OfficerCoverage) => void;
  onViewDetail: (officer: OfficerCoverage) => void;
}) {
  const renderAction = (officer: OfficerCoverage) => {
    const buttons = [];

    // Admin-only: assign/edit actions (requires unit plan)
    if (isAdmin && hasPlan) {
      if (officer.target_source === "custom" && (officer.target_id != null || officer.plan_id != null)) {
        buttons.push(
          <Button
            key="edit"
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onEdit(officer)}
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
            onClick={() => onAssign(officer)}
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
                onClick={() => onAssign(officer)}
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
    }

    // All roles: view detail (if officer has own plan)
    if (officer.plan_id != null) {
      buttons.push(
        <Button
          key="detail"
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onViewDetail(officer)}
        >
          <Eye aria-hidden="true" className="h-4 w-4" />
          Chi tiết
        </Button>,
      );
    }

    if (buttons.length === 0) return null;
    return <div className="flex gap-1 justify-end">{buttons}</div>;
  };

  return (
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
        {officers.map((officer) => (
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
  );
}

// ---------------------------------------------------------------------------
// UnitKpiCard — main component
// ---------------------------------------------------------------------------
export function UnitKpiCard({ unit, fiscalYear, isAdmin = false }: Props) {
  const [expanded, setExpanded] = useState(unit.plan_id != null);
  const [planDialog, setPlanDialog] = useState<PlanDialogMode>(null);
  const [quotaDialog, setQuotaDialog] = useState<QuotaDialogMode>(null);
  const [detailPlanId, setDetailPlanId] = useState<number | null>(null);
  const [detailLabel, setDetailLabel] = useState<string | undefined>();

  return (
    <TooltipProvider>
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <Card id={`unit-${unit.unit_id}`}>
          {/* Card Header */}
          <CollapsibleTrigger asChild>
            <CardHeader className="cursor-pointer">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="font-semibold">{unit.unit_name}</span>
                  <Badge variant={unit.plan_id ? "default" : "destructive"}>
                    {unit.plan_id ? "Có plan" : "Chưa có plan"}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    {unit.officers.length} cán bộ
                  </Badge>
                </div>
                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                  {isAdmin && !unit.plan_id && (
                    <Button
                      size="sm"
                      onClick={() =>
                        setPlanDialog({
                          type: "create",
                          unitId: unit.unit_id,
                          unitName: unit.unit_name,
                        })
                      }
                    >
                      <Plus aria-hidden="true" className="h-4 w-4" />
                      Tạo plan
                    </Button>
                  )}
                  {unit.plan_id && (
                    <>
                      {isAdmin && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setPlanDialog({
                              type: "edit",
                              planId: unit.plan_id!,
                              unitId: unit.unit_id,
                              unitName: unit.unit_name,
                            })
                          }
                        >
                          <Pencil aria-hidden="true" className="h-4 w-4" />
                          Sửa plan
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setDetailPlanId(unit.plan_id!);
                          setDetailLabel(unit.unit_name);
                        }}
                      >
                        <Eye aria-hidden="true" className="h-4 w-4" />
                        Chi tiết
                      </Button>
                    </>
                  )}
                  <ChevronDown
                    aria-hidden="true"
                    className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
                  />
                </div>
              </div>

              {/* Quota allocation bar */}
              {unit.plan_id && unit.annual_target != null && (
                <QuotaBar
                  unitTarget={unit.annual_target}
                  totalAssigned={unit.total_officer_target}
                />
              )}
            </CardHeader>
          </CollapsibleTrigger>

          {/* Expanded Content: Officer Table */}
          <CollapsibleContent>
            <CardContent>
              {unit.officers.length === 0 ? (
                <p className="text-sm text-muted-foreground">Không có cán bộ nào.</p>
              ) : (
                <OfficerTable
                  officers={unit.officers}
                  isAdmin={isAdmin}
                  hasPlan={unit.plan_id != null}
                  onAssign={(officer) =>
                    setQuotaDialog({
                      type: "assign",
                      officerId: officer.officer_id,
                      officerName: officer.officer_name,
                      unitId: unit.unit_id,
                    })
                  }
                  onEdit={(officer) => {
                    if (officer.plan_id != null) {
                      setQuotaDialog({
                        type: "edit",
                        officerId: officer.officer_id,
                        officerName: officer.officer_name,
                        planId: officer.plan_id,
                        unitId: unit.unit_id,
                      });
                    } else {
                      setQuotaDialog({
                        type: "assign",
                        officerId: officer.officer_id,
                        officerName: officer.officer_name,
                        unitId: unit.unit_id,
                      });
                    }
                  }}
                  onViewDetail={(officer) => {
                    setDetailPlanId(officer.plan_id);
                    setDetailLabel(`${officer.officer_name} (${unit.unit_name})`);
                  }}
                />
              )}
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>

      {/* Dialogs */}
      {planDialog && (
        <CreateEditPlanDialog
          mode={planDialog}
          fiscalYear={fiscalYear}
          onClose={() => setPlanDialog(null)}
        />
      )}
      {quotaDialog && (
        <AssignQuotaDialog
          mode={quotaDialog}
          unit={unit}
          fiscalYear={fiscalYear}
          onClose={() => setQuotaDialog(null)}
        />
      )}
      <PlanDetailSheet
        planId={detailPlanId}
        unitName={detailLabel}
        onOpenChange={(open) => {
          if (!open) {
            setDetailPlanId(null);
            setDetailLabel(undefined);
          }
        }}
      />
    </TooltipProvider>
  );
}
