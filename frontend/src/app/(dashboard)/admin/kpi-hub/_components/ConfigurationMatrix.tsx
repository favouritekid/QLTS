"use client";

import { useState, useMemo } from "react";
import { AlertTriangle, ChevronDown, LayoutGrid } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MetricCatalogEntry } from "@/lib/api/meta";
import type { KpiConfigItem } from "@/types/kpi-setup.types";
import type { KpiTargetItem } from "@/hooks/useKpiSetup";

const PERIOD_LABELS: Record<string, string> = {
  daily: "Hàng ngày",
  monthly: "Hàng tháng",
  annual: "Hàng năm",
};

const UNIT_SUFFIXES: Record<string, string> = {
  percent: "%",
  hours: "h",
  count: "",
};

interface ConfigurationMatrixProps {
  catalog: MetricCatalogEntry[];
  catalogMap: Map<string, MetricCatalogEntry>;
  configs: KpiConfigItem[];
  targets: KpiTargetItem[];
  distributionUnitIds: Set<number>;
  distributionOfficerIds: Set<number>;
  totalDistributionUnits: number;
  totalOfficers: number;
}

interface MetricRow {
  code: string;
  displayName: string;
  period: string;
  defaultValue: string;
  globalValue: string | null;
  unitCoverage: number;
  officerCoverage: number;
}

function CoverageBadge({
  count,
  total,
}: {
  count: number;
  total: number;
}) {
  if (total === 0) return <span className="text-muted-foreground">—</span>;

  const variant =
    count >= total ? "default" : count > 0 ? "secondary" : "outline";

  return (
    <Badge variant={variant} className="text-xs tabular-nums">
      {count}/{total}
    </Badge>
  );
}

export function ConfigurationMatrix({
  catalog,
  catalogMap,
  configs,
  targets,
  distributionUnitIds,
  distributionOfficerIds,
  totalDistributionUnits,
  totalOfficers,
}: ConfigurationMatrixProps) {
  const [open, setOpen] = useState(true);

  // Ghost config detection: configs with period_type mismatch
  const ghostCount = useMemo(
    () =>
      configs.filter((c) => {
        const entry = catalogMap.get(c.kpi_code);
        return entry && c.period_type !== entry.period_type;
      }).length,
    [configs, catalogMap],
  );

  const rows: MetricRow[] = useMemo(() => {
    return catalog.map((m) => {
      const suffix = UNIT_SUFFIXES[m.unit] ?? "";
      const isAnnual = m.period_type === "annual";

      // Global value
      let globalValue: string | null = null;
      let unitCoverage = 0;
      let officerCoverage = 0;

      if (isAnnual) {
        // Annual metrics: read from targets[]
        const matched = targets.filter((t) => t.kpi_code === m.code);
        const globalTarget = matched.find(
          (t) => t.unit_id === null && t.officer_id === null,
        );
        globalValue = globalTarget
          ? `${globalTarget.annual_target}${suffix}`
          : null;

        unitCoverage = new Set(
          matched
            .filter(
              (t) =>
                t.unit_id !== null &&
                t.officer_id === null &&
                distributionUnitIds.has(t.unit_id),
            )
            .map((t) => t.unit_id),
        ).size;

        officerCoverage = new Set(
          matched
            .filter(
              (t) =>
                t.officer_id !== null &&
                distributionOfficerIds.has(t.officer_id),
            )
            .map((t) => t.officer_id),
        ).size;
      } else {
        // Daily/monthly metrics: read from configs[]
        const matched = configs.filter(
          (c) => c.kpi_code === m.code && c.period_type === m.period_type,
        );
        const globalConfig = matched.find(
          (c) => c.unit_id === null && c.officer_id === null,
        );
        globalValue = globalConfig
          ? `${globalConfig.target_value}${suffix}`
          : null;

        unitCoverage = new Set(
          matched
            .filter(
              (c) =>
                c.unit_id !== null &&
                c.officer_id === null &&
                distributionUnitIds.has(c.unit_id),
            )
            .map((c) => c.unit_id),
        ).size;

        officerCoverage = new Set(
          matched
            .filter(
              (c) =>
                c.officer_id !== null &&
                distributionOfficerIds.has(c.officer_id),
            )
            .map((c) => c.officer_id),
        ).size;
      }

      return {
        code: m.code,
        displayName: m.display_aliases.config,
        period: PERIOD_LABELS[m.period_type] ?? m.period_type,
        defaultValue: `${m.default_value}${suffix}`,
        globalValue,
        unitCoverage,
        officerCoverage,
      };
    });
  }, [
    catalog,
    configs,
    targets,
    distributionUnitIds,
    distributionOfficerIds,
  ]);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card>
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer select-none hover:bg-muted/50">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <LayoutGrid className="h-5 w-5 text-primary" />
                <CardTitle className="text-base">
                  Ma trận cấu hình KPI ({catalog.length} chỉ tiêu)
                </CardTitle>
              </div>
              <ChevronDown
                className={`h-4 w-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
              />
            </div>
          </CardHeader>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="pt-0">
            {ghostCount > 0 && (
              <Alert variant="destructive" className="mb-4">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Cấu hình không hợp lệ</AlertTitle>
                <AlertDescription>
                  {ghostCount} cấu hình có chu kỳ không khớp với catalog — không
                  có tác dụng trên hệ thống.
                </AlertDescription>
              </Alert>
            )}

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Chỉ tiêu</TableHead>
                  <TableHead>Chu kỳ</TableHead>
                  <TableHead className="text-right">Mặc định</TableHead>
                  <TableHead className="text-right">Global</TableHead>
                  <TableHead className="text-center">Đơn vị</TableHead>
                  <TableHead className="text-center">Officer</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.code}>
                    <TableCell className="font-medium">
                      {row.displayName}
                    </TableCell>
                    <TableCell>{row.period}</TableCell>
                    <TableCell className="text-right text-muted-foreground tabular-nums">
                      {row.defaultValue}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.globalValue ? (
                        <Badge variant="default" className="text-xs">
                          {row.globalValue}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          Mặc định
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-center">
                      <CoverageBadge
                        count={row.unitCoverage}
                        total={totalDistributionUnits}
                      />
                    </TableCell>
                    <TableCell className="text-center">
                      <CoverageBadge
                        count={row.officerCoverage}
                        total={totalOfficers}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <p className="mt-3 text-xs text-muted-foreground">
              Nếu không thiết lập riêng, hệ thống sử dụng giá trị mặc định.
              Chỉ hiển thị đơn vị có quy tắc phân phối tuyển sinh.
            </p>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
