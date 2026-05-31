/**
 * CoverageMatrix Component
 *
 * Phase 3 readiness mode inside the unified quota matrix.
 * Shows whether each admission method/path has criteria, documents, quota, and
 * activation readiness for the selected academic info.
 */

"use client";

import { useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCoverageMatrix } from "@/hooks/admissions/useAdmissionPaths";
import { useQuotaMatrix } from "@/hooks/admissions/useQuotaMatrix";

import type { CoverageRow } from "../shared/types";

const CURRENT_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = [CURRENT_YEAR - 1, CURRENT_YEAR, CURRENT_YEAR + 1, CURRENT_YEAR + 2];

interface CoverageMatrixProps {
  academicYear: number;
  onYearChange: (year: number) => void;
}

export function CoverageMatrix({ academicYear, onYearChange }: CoverageMatrixProps) {
  const { data: globalData } = useQuotaMatrix(academicYear);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const selectedAcademicInfoId = useMemo<number | undefined>(() => {
    const raw = searchParams.get("academicInfo");
    if (!raw) return undefined;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : undefined;
  }, [searchParams]);

  const updateSearchParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value === null) params.delete(key);
      else params.set(key, value);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const setSelectedAcademicInfoId = useCallback(
    (id: number) => updateSearchParam("academicInfo", id.toString()),
    [updateSearchParam],
  );

  // Validate ngành theo năm (academic_info year-bound). Đổi năm giữ academicInfo
  // cũ → mismatch. Năm có ngành + selection không thuộc năm → ngành đầu; năm
  // không có ngành nào → clear (tránh phantom matrix năm cũ).
  useEffect(() => {
    if (!globalData) return;
    const exists = globalData.rows.some(
      (r) => r.academic_info_id === selectedAcademicInfoId,
    );
    if (exists) return;
    if (globalData.rows.length > 0) {
      setSelectedAcademicInfoId(globalData.rows[0].academic_info_id);
    } else if (selectedAcademicInfoId !== undefined) {
      updateSearchParam("academicInfo", null);
    }
  }, [globalData, selectedAcademicInfoId, setSelectedAcademicInfoId, updateSearchParam]);

  const { data: matrixData, isLoading } = useCoverageMatrix(selectedAcademicInfoId);

  const rows = matrixData?.rows || [];
  const allReady = matrixData?.all_ready || false;
  const pathsReady = matrixData?.paths_ready || 0;
  const totalPaths = matrixData?.total_paths || 0;

  const renderCheckIcon = (value: boolean) => {
    return value ? (
      <CheckCircle2 className="h-5 w-5 text-success-600" aria-hidden="true" />
    ) : (
      <XCircle className="h-5 w-5 text-error-500" aria-hidden="true" />
    );
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return <Badge className="bg-success-500">Hoạt động</Badge>;
      case "draft":
        return <Badge variant="secondary">Nháp</Badge>;
      case "inactive":
        return <Badge variant="outline">Ngưng hoạt động</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <Card>
      <CardHeader className="space-y-3 pb-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base text-pretty">
              Kiểm độ sẵn sàng
            </CardTitle>
            <CardDescription>
              Kiểm tra phương thức nào đã hoàn thiện và sẵn sàng kích hoạt.
            </CardDescription>
          </div>
          <Select value={academicYear.toString()} onValueChange={(v) => onYearChange(Number(v))}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              {YEAR_OPTIONS.map((y) => (
                <SelectItem key={y} value={y.toString()}>{y}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-sm font-medium">Ngành:</label>
          <Select
            value={selectedAcademicInfoId?.toString() ?? ""}
            onValueChange={(v) => setSelectedAcademicInfoId(Number(v))}
          >
            <SelectTrigger className="w-72">
              <SelectValue placeholder="Chọn ngành..." />
            </SelectTrigger>
            <SelectContent>
              {globalData?.rows.map((r) => (
                <SelectItem key={r.academic_info_id} value={r.academic_info_id.toString()}>
                  {r.program_name}
                  {r.degree_level && (
                    <span className="text-muted-foreground"> ({r.degree_level})</span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {!selectedAcademicInfoId && (
          <div className="text-sm text-muted-foreground py-4">
            Chọn ngành để xem kiểm độ sẵn sàng.
          </div>
        )}

        {!isLoading && selectedAcademicInfoId && matrixData && (
          <div className={`rounded-md border p-3 ${allReady ? "border-success-500" : "border-amber-500"}`}>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-2xl font-bold">
                  {pathsReady} / {totalPaths}
                </p>
                <p className="text-sm text-muted-foreground mt-1">
                  Phương thức sẵn sàng kích hoạt
                </p>
              </div>
              {allReady ? (
                <div className="flex items-center gap-2 text-success-600">
                  <CheckCircle2 className="h-6 w-6" aria-hidden="true" />
                  <span className="font-medium">Tất cả đã sẵn sàng</span>
                </div>
              ) : (
                <div className="text-amber-600">
                  <p className="font-medium">{totalPaths - pathsReady} phương thức chưa hoàn thiện</p>
                  <p className="text-sm">Hoàn thiện cấu hình để kích hoạt</p>
                </div>
              )}
            </div>
          </div>
        )}

        {selectedAcademicInfoId && isLoading ? (
          <div className="flex items-center justify-center py-12" aria-live="polite">
            <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
            <span className="sr-only">Đang tải kiểm độ sẵn sàng...</span>
          </div>
        ) : selectedAcademicInfoId && rows.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-muted-foreground">Chưa có phương thức tuyển sinh nào</p>
            <p className="text-sm text-muted-foreground mt-1">
              Tạo phương thức trong ma trận để xem trạng thái.
            </p>
          </div>
        ) : rows.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-64">Phương thức</TableHead>
                  <TableHead className="w-24">Trạng thái</TableHead>
                  <TableHead className="text-center w-32">Tiêu chí</TableHead>
                  <TableHead className="text-center w-32">Hồ sơ</TableHead>
                  <TableHead className="text-center w-32">Chỉ tiêu</TableHead>
                  <TableHead className="text-center w-32">Kích hoạt?</TableHead>
                  <TableHead className="w-48">Vấn đề</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row: CoverageRow) => (
                  <TableRow
                    key={row.path_id}
                    className={row.can_activate ? "bg-success-50/50" : ""}
                  >
                    <TableCell>
                      <div>
                        <p className="font-medium">{row.method_name}</p>
                        <p className="text-sm text-muted-foreground" translate="no">
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
                        <span className="text-sm text-success-600">Không có lỗi</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
