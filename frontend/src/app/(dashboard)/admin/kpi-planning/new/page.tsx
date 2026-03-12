"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarDays, RotateCcw, Save } from "lucide-react";

import { SmartUnitSelector } from "@/components/common/selectors/SmartUnitSelector";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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

import { useCreatePlan, usePreviewPlan } from "@/hooks/useKpiPlanning";
import type {
  KpiPlanCreate,
  KpiPlanPreviewResponse,
} from "@/types/kpi-planning.types";
import { MONTH_LABELS } from "@/types/kpi-planning.types";

const currentYear = new Date().getFullYear();

const DEFAULT_WEIGHTS = [
  0.04, 0.033, 0.05, 0.06, 0.073, 0.127, 0.153, 0.16, 0.133, 0.093, 0.043, 0.033,
];
const EVEN_WEIGHTS = Array.from({ length: 12 }, () => 1 / 12);
const HIGH_SEASON_WEIGHTS = [
  0.04, 0.04, 0.05, 0.06, 0.08, 0.13, 0.16, 0.16, 0.14, 0.08, 0.03, 0.03,
];

const parseNumberParam = (raw: string | null, fallback: number): number => {
  if (!raw) return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const sanitizeWeights = (weights: unknown): number[] => {
  if (!Array.isArray(weights)) return [...DEFAULT_WEIGHTS];
  return Array.from({ length: 12 }, (_, idx) => {
    const fallback = DEFAULT_WEIGHTS[idx] ?? 1 / 12;
    const parsed = Number(weights[idx]);
    if (!Number.isFinite(parsed)) return fallback;
    return clamp(parsed, 0, 1);
  });
};

const parseWeightsParam = (raw: string | null): number[] => {
  if (!raw) return [...DEFAULT_WEIGHTS];
  return sanitizeWeights(raw.split(",").map((v) => Number(v)));
};

const parsePercentInput = (raw: string): number => {
  const normalized = raw.replace(",", ".").trim();
  if (!normalized) return 0;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
};

const normalizeWeights = (weights: number[]): number[] => {
  const sum = weights.reduce((acc, val) => acc + val, 0);
  if (sum <= 0) return [...DEFAULT_WEIGHTS];

  const normalized = weights.map((w) => Number((w / sum).toFixed(4)));
  const roundedSum = normalized.reduce((acc, val) => acc + val, 0);
  const delta = Number((1 - roundedSum).toFixed(4));

  if (Math.abs(delta) >= 0.0001) {
    const maxIdx = normalized.reduce(
      (best, val, idx, arr) => (val > arr[best] ? idx : best),
      0,
    );
    normalized[maxIdx] = Number((normalized[maxIdx] + delta).toFixed(4));
  }

  return normalized;
};

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
        <TooltipContent side="top" className="max-w-[320px] text-xs">
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function KpiPlanningCreatePage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialUseCustomWeights = searchParams.get("use_custom_weights") === "1";
  const initialWeights = initialUseCustomWeights
    ? parseWeightsParam(searchParams.get("weights"))
    : [...DEFAULT_WEIGHTS];

  const [formData, setFormData] = useState<KpiPlanCreate>({
    unit_id: parseNumberParam(searchParams.get("unit_id"), 0),
    fiscal_year: parseNumberParam(searchParams.get("fiscal_year"), currentYear),
    annual_enrollment_target: parseNumberParam(
      searchParams.get("annual_enrollment_target"),
      300,
    ),
    sla_target: parseNumberParam(searchParams.get("sla_target"), 85),
    response_time_target: parseNumberParam(searchParams.get("response_time_target"), 2),
    seasonal_weights: null,
    officer_id: null,
  });
  const [useCustomWeights, setUseCustomWeights] = useState(initialUseCustomWeights);
  const [editWeights, setEditWeights] = useState<number[]>(initialWeights);
  const [previewData, setPreviewData] = useState<KpiPlanPreviewResponse | null>(null);

  const createMut = useCreatePlan();
  const previewMut = usePreviewPlan();

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewSeqRef = useRef(0);

  const normalizedWeights = sanitizeWeights(editWeights);
  const weightsSum = normalizedWeights.reduce((acc, val) => acc + val, 0);
  const weightsSumPercent = weightsSum * 100;
  const weightsValid = weightsSum >= 0.99 && weightsSum <= 1.01;

  const previewMonths = previewData?.months ?? ([] as KpiPlanPreviewResponse["months"]);

  const previewAnnualTarget =
    typeof previewData?.annual_enrollment_target === "number"
      ? previewData.annual_enrollment_target
      : formData.annual_enrollment_target;

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (formData.unit_id <= 0) return;

    debounceRef.current = setTimeout(async () => {
      const seq = ++previewSeqRef.current;
      try {
        const response = await previewMut.mutateAsync({
          unit_id: formData.unit_id,
          fiscal_year: formData.fiscal_year,
          annual_enrollment_target: formData.annual_enrollment_target,
          sla_target: formData.sla_target,
          response_time_target: formData.response_time_target,
          seasonal_weights: useCustomWeights ? normalizedWeights : null,
        });
        if (seq === previewSeqRef.current) {
          setPreviewData(response);
        }
      } catch {
        setPreviewData(null);
      }
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [
    formData.unit_id,
    formData.fiscal_year,
    formData.annual_enrollment_target,
    formData.sla_target,
    formData.response_time_target,
    useCustomWeights,
    normalizedWeights,
    previewMut,
  ]);

  const updateWeightPercent = (idx: number, percent: number) => {
    if (Number.isNaN(percent)) return;
    setEditWeights((prev) => {
      const next = [...prev];
      next[idx] = clamp(percent / 100, 0, 1);
      return next;
    });
  };

  const applyPreset = (preset: number[]) => {
    setUseCustomWeights(true);
    setEditWeights(sanitizeWeights(preset));
  };

  const submitCreate = async () => {
    if (formData.unit_id <= 0) return;

    try {
      const created = await createMut.mutateAsync({
        ...formData,
        seasonal_weights: useCustomWeights ? normalizedWeights : null,
      });

      router.push(`/admin/kpi-planning/${created.id}`);
    } catch {
      // Error toast is handled by useCreatePlan onError.
    }
  };

  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="Tạo kế hoạch KPI"
        description="Builder dạng full-page cho cấu hình dữ liệu lớn"
        backButton={{ href: "/admin/kpi-planning", label: "Quay lại danh sách" }}
        actions={(
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => router.push("/admin/kpi-planning/holidays")}
            >
              <CalendarDays className="mr-1.5 h-4 w-4" />Lịch ngày lễ
            </Button>
            <Button
              onClick={submitCreate}
              disabled={
                createMut.isPending
                || formData.unit_id <= 0
                || (useCustomWeights && !weightsValid)
              }
            >
              <Save className="mr-1.5 h-4 w-4" />
              {createMut.isPending ? "Đang tạo..." : "Tạo kế hoạch"}
            </Button>
          </div>
        )}
      />

      {searchParams.get("unit_id") && (
        <Alert className="mb-4">
          <AlertDescription>
            Bạn đang ở chế độ clone từ kế hoạch cũ. Có thể chỉnh lại toàn bộ thông tin trước khi tạo.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Bước 1 - Thông tin kế hoạch</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium">
                Đơn vị <span className="text-destructive">*</span>
              </label>
              <SmartUnitSelector
                value={formData.unit_id > 0 ? String(formData.unit_id) : undefined}
                onChange={(value) => setFormData((prev) => ({
                  ...prev,
                  unit_id: value ? Number(value) : 0,
                }))}
                placeholder="Chọn đơn vị (bao gồm đơn vị con)"
                variant="combobox"
                activeOnly
                className="w-full"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm font-medium">Năm tài chính</label>
                <Input
                  type="number"
                  min={2020}
                  max={2100}
                  value={formData.fiscal_year}
                  onChange={(e) => setFormData((prev) => ({
                    ...prev,
                    fiscal_year: Number(e.target.value),
                  }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">
                  Chỉ tiêu nhập học/năm <span className="text-destructive">*</span>
                </label>
                <Input
                  type="number"
                  min={1}
                  max={10000}
                  value={formData.annual_enrollment_target}
                  onChange={(e) => setFormData((prev) => ({
                    ...prev,
                    annual_enrollment_target: Number(e.target.value),
                  }))}
                />
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm font-medium">Tỷ lệ tuân thủ cam kết dịch vụ (SLA) (%)</label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  step={0.1}
                  value={formData.sla_target}
                  onChange={(e) => setFormData((prev) => ({
                    ...prev,
                    sla_target: Number(e.target.value),
                  }))}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  SLA (Service Level Agreement): tỷ lệ lead được phản hồi đúng thời gian cam kết.
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Thời gian phản hồi (giờ)</label>
                <Input
                  type="number"
                  min={1}
                  max={48}
                  step={0.5}
                  value={formData.response_time_target}
                  onChange={(e) => setFormData((prev) => ({
                    ...prev,
                    response_time_target: Number(e.target.value),
                  }))}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Bước 2 - Trọng số theo tháng</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm">
                Tổng trọng số: <strong>{weightsSum.toFixed(4)}</strong> ({weightsSumPercent.toFixed(1)}%)
              </div>
              <Button
                type="button"
                size="sm"
                variant={useCustomWeights ? "default" : "outline"}
                onClick={() => setUseCustomWeights((prev) => !prev)}
              >
                {useCustomWeights ? "Đang tùy chỉnh" : "Bật tùy chỉnh"}
              </Button>
            </div>

            {useCustomWeights && (
              <>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={() => applyPreset(DEFAULT_WEIGHTS)}>
                    Mặc định
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => applyPreset(EVEN_WEIGHTS)}>
                    Đồng đều 12 tháng
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => applyPreset(HIGH_SEASON_WEIGHTS)}>
                    Cao điểm T6-T9
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setEditWeights(normalizeWeights(normalizedWeights))}
                  >
                    <RotateCcw className="mr-1 h-3.5 w-3.5" />Tự cân 100%
                  </Button>
                </div>

                <div className="overflow-x-auto rounded border">
                  <Table className="min-w-[980px]">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[160px]">KPI</TableHead>
                        {Array.from({ length: 12 }, (_, idx) => (
                          <TableHead key={idx} className="text-center">
                            {MONTH_LABELS[idx + 1]}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      <TableRow>
                        <TableCell className="font-medium">Trọng số (%)</TableCell>
                        {normalizedWeights.map((w, idx) => (
                          <TableCell key={idx} className="min-w-[92px] p-2">
                            <Input
                              type="text"
                              inputMode="decimal"
                              className="h-10 text-center"
                              value={Number.isFinite(w) ? (w * 100).toFixed(1) : "0.0"}
                              onChange={(e) => {
                                const parsed = parsePercentInput(e.target.value);
                                if (!Number.isNaN(parsed)) {
                                  updateWeightPercent(idx, parsed);
                                }
                              }}
                            />
                          </TableCell>
                        ))}
                      </TableRow>
                      <TableRow>
                        <TableCell className="font-medium">Tỷ lệ tháng</TableCell>
                        {normalizedWeights.map((w, idx) => (
                          <TableCell key={idx} className="text-center text-xs text-muted-foreground">
                            {(w * 100).toFixed(1)}%
                          </TableCell>
                        ))}
                      </TableRow>
                    </TableBody>
                  </Table>
                </div>

                {!weightsValid && (
                  <p className="text-xs text-destructive">
                    Tổng trọng số cần nằm trong khoảng 99% - 101%.
                  </p>
                )}
              </>
            )}

            {!useCustomWeights && (
              <p className="text-sm text-muted-foreground">
                Hệ thống sẽ dùng bộ trọng số mặc định theo mùa tuyển sinh.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Bước 3 - Xem trước KPI theo tháng</CardTitle>
        </CardHeader>
        <CardContent>
          {previewData ? (
            previewMonths.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tháng</TableHead>
                    <TableHead className="text-right">
                      <span className="inline-flex items-center justify-end gap-1">
                        Chỉ tiêu nhập học tháng (M_t)
                        <InfoHint content="M_t là chỉ tiêu nhập học của tháng t, được phân bổ từ chỉ tiêu năm theo trọng số mùa vụ." />
                      </span>
                    </TableHead>
                    <TableHead className="text-right">Ngày làm việc</TableHead>
                    <TableHead className="text-right">
                      <span className="inline-flex items-center justify-end gap-1">
                        Tư vấn/ngày
                        <InfoHint content="Tư vấn/ngày = ceil(M_t × k_t / số ngày làm việc). k_t là hệ số tư vấn để đạt mục tiêu nhập học của tháng." />
                      </span>
                    </TableHead>
                    <TableHead className="text-right">
                      <span className="inline-flex items-center justify-end gap-1">
                        Chuyển đổi%
                        <InfoHint content="Chuyển đổi% = (M_t / lead dự báo tháng) × 100. Cho biết mức chuyển đổi cần đạt để chạm mục tiêu nhập học tháng." />
                      </span>
                    </TableHead>
                    <TableHead className="text-right">
                      <span className="inline-flex items-center justify-end gap-1">
                        Chốt%
                        <InfoHint content="Chốt% = (M_t / lead đã tư vấn dự báo) × 100. Thể hiện tỷ lệ chốt cần đạt trên nhóm lead đã được tư vấn." />
                      </span>
                    </TableHead>
                    <TableHead className="text-right">
                      <span className="inline-flex items-center justify-end gap-1">
                        Hiệu quả%
                        <InfoHint content="Hiệu quả% = (M_t / lead đã tư vấn và có tiến triển) × 100. Dùng để theo dõi chất lượng tư vấn thực tế." />
                      </span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {previewMonths.map((m) => (
                    <TableRow key={m.month}>
                      <TableCell className="font-medium">{MONTH_LABELS[m.month]}</TableCell>
                      <TableCell className="text-right">{m.enrollment_target}</TableCell>
                      <TableCell className="text-right">{m.working_days}</TableCell>
                      <TableCell className="text-right">{m.consultations_daily ?? "-"}</TableCell>
                      <TableCell className="text-right">{m.conversion_rate != null ? `${m.conversion_rate}%` : "-"}</TableCell>
                      <TableCell className="text-right">{m.win_rate != null ? `${m.win_rate}%` : "-"}</TableCell>
                      <TableCell className="text-right">{m.consultation_effectiveness != null ? `${m.consultation_effectiveness}%` : "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
                <span>
                  Tổng chỉ tiêu nhập học tháng (∑M_t): <strong>{previewMonths.reduce((s, m) => s + m.enrollment_target, 0)}</strong>
                </span>
                <span>
                  Chỉ tiêu năm: <strong>{previewAnnualTarget}</strong>
                </span>
              </div>

              <div className="mt-3 rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">
                  (i) Giải thích nhanh cách hệ thống tính các tỷ lệ:
                </p>
                <p className="mt-1">
                  M_t là chỉ tiêu nhập học tháng t. Từ M_t, hệ thống dùng reverse-funnel để suy ra số tư vấn/ngày, tỷ lệ chuyển đổi,
                  tỷ lệ chốt và hiệu quả tư vấn cho từng tháng.
                </p>
                <p className="mt-1">
                  Giai đoạn đầu (chưa đủ dữ liệu thực), các tỷ lệ có thể giống nhau giữa các tháng do dùng bộ hệ số mặc định; sau đó
                  hệ thống sẽ tự hiệu chỉnh theo dữ liệu thực tế khi đồng bộ hàng tháng.
                </p>
              </div>
            </div>
            ) : (
              <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
                Chưa nhận được dữ liệu xem trước theo tháng. Vui lòng thử đổi tham số hoặc tải lại trang.
              </div>
            )
          ) : (
            <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
              {formData.unit_id > 0 ? "Đang tính preview..." : "Chọn đơn vị để hệ thống tính preview"}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="sticky bottom-0 z-10 mt-4 rounded-lg border bg-background/95 p-3 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            Điều kiện tạo kế hoạch: chọn đơn vị, chỉ tiêu năm hợp lệ, trọng số hợp lệ (nếu bật tùy chỉnh).
          </p>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => router.push("/admin/kpi-planning")}>Hủy</Button>
            <Button
              onClick={submitCreate}
              disabled={
                createMut.isPending
                || formData.unit_id <= 0
                || (useCustomWeights && !weightsValid)
              }
            >
              <Save className="mr-1.5 h-4 w-4" />
              {createMut.isPending ? "Đang tạo..." : "Tạo kế hoạch"}
            </Button>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}




