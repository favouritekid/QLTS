/**
 * CoverageMatrix Component
 *
 * Phase 3: Coverage Matrix View
 * Audit view showing readiness status of all admission paths:
 * - Has criteria configured?
 * - Has documents configured?
 * - Has quota assigned?
 * - Can be activated?
 */

"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CheckCircle2, XCircle, ChevronLeft, Loader2 } from "lucide-react";
import { useCoverageMatrix } from "@/hooks/admissions/useAdmissionPaths";
import type { SelectionContext, Phase3View, CoverageRow } from "../shared/types";

// ============================================
// TYPES
// ============================================

interface CoverageMatrixProps {
  context: SelectionContext;
  onNavigate: (view: Phase3View) => void;
}

// ============================================
// COMPONENT
// ============================================

export function CoverageMatrix({ context, onNavigate }: CoverageMatrixProps) {
  const { data: matrixData, isLoading } = useCoverageMatrix(context.academicInfoId);

  const rows = matrixData?.rows || [];
  const allReady = matrixData?.all_ready || false;
  const pathsReady = matrixData?.paths_ready || 0;
  const totalPaths = matrixData?.total_paths || 0;

  // Render check/cross icon
  const renderCheckIcon = (value: boolean) => {
    return value ? (
      <CheckCircle2 className="h-5 w-5 text-green-600" />
    ) : (
      <XCircle className="h-5 w-5 text-red-500" />
    );
  };

  // Get status badge
  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return <Badge className="bg-green-500">Active</Badge>;
      case "draft":
        return <Badge variant="secondary">Draft</Badge>;
      case "inactive":
        return <Badge variant="outline">Inactive</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Button variant="ghost" size="sm" onClick={() => onNavigate({ type: "list" })}>
            <ChevronLeft className="h-4 w-4 mr-1" />
            Back to Paths List
          </Button>
        </div>
        <h1 className="text-3xl font-bold">Coverage Matrix</h1>
        <p className="text-muted-foreground mt-2">
          Audit view of all admission paths for Academic Year {context.academicYear}
        </p>
      </div>

      {/* Summary Card */}
      {!isLoading && matrixData && (
        <Card className={allReady ? "border-green-500" : "border-amber-500"}>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-2xl font-bold">
                  {pathsReady} / {totalPaths}
                </p>
                <p className="text-sm text-muted-foreground mt-1">
                  Paths ready for activation
                </p>
              </div>
              {allReady ? (
                <div className="flex items-center gap-2 text-green-600">
                  <CheckCircle2 className="h-6 w-6" />
                  <span className="font-medium">All paths ready!</span>
                </div>
              ) : (
                <div className="text-amber-600">
                  <p className="font-medium">{totalPaths - pathsReady} path(s) incomplete</p>
                  <p className="text-sm">Complete configuration to activate</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Matrix Table */}
      <Card>
        <CardHeader>
          <CardTitle>Configuration Status</CardTitle>
          <CardDescription>
            Check which paths have complete configuration and are ready to activate
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : rows.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-muted-foreground">No admission paths found</p>
              <p className="text-sm text-muted-foreground mt-1">
                Create paths in the Paths List view
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-64">Admission Method</TableHead>
                    <TableHead className="w-24">Status</TableHead>
                    <TableHead className="text-center w-32">Criteria</TableHead>
                    <TableHead className="text-center w-32">Documents</TableHead>
                    <TableHead className="text-center w-32">Quota</TableHead>
                    <TableHead className="text-center w-32">Can Activate</TableHead>
                    <TableHead className="w-48">Issues</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row: CoverageRow) => (
                    <TableRow
                      key={row.path_id}
                      className={row.can_activate ? "bg-green-50/50" : ""}
                    >
                      <TableCell>
                        <div>
                          <p className="font-medium">{row.method_name}</p>
                          <p className="text-sm text-muted-foreground">
                            {row.method_code}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>{getStatusBadge(row.status)}</TableCell>
                      <TableCell className="text-center">
                        {renderCheckIcon(row.has_criteria)}
                      </TableCell>
                      <TableCell className="text-center">
                        {renderCheckIcon(row.has_documents)}
                      </TableCell>
                      <TableCell className="text-center">
                        {renderCheckIcon(row.has_quota)}
                      </TableCell>
                      <TableCell className="text-center">
                        {renderCheckIcon(row.can_activate)}
                      </TableCell>
                      <TableCell>
                        {row.validation_errors.length > 0 ? (
                          <ul className="text-sm text-muted-foreground space-y-1">
                            {row.validation_errors.map((error: string, idx: number) => (
                              <li key={idx}>• {error}</li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-sm text-green-600">No issues</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
