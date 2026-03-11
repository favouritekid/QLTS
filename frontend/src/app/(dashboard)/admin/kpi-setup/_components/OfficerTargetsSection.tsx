"use client";

import { Badge } from "@/components/ui/badge";
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { OfficerCoverage, UnitCoverage } from "@/types/kpi-setup.types";
import {
  STATUS_CONFIG,
  TARGET_SOURCE_CONFIG,
} from "@/types/kpi-setup.types";

interface Props {
  units: UnitCoverage[];
}

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

export function OfficerTargetsSection({ units }: Props) {
  const defaultOpen = units.length <= 5 ? units.map((u) => String(u.unit_id)) : [];

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
    </TooltipProvider>
  );
}
