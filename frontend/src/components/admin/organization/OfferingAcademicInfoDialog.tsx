// src/components/admin/organization/OfferingAcademicInfoDialog.tsx
"use client";

import React, { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { CurrencyInput } from "@/components/ui/currency-input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Loader2, Save, SaveAll, Percent } from "lucide-react";
import {
  useCreateOfferingAcademicInfo,
  useUpdateOfferingAcademicInfo,
  useBulkUpsertSemesterTuitions,
} from "@/hooks/useOrganization";
import { useTuitionDiscountPolicies } from "@/hooks/useTuitionDiscount";
import { SemesterTuitionEditor } from "./SemesterTuitionEditor";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  OfferingAcademicInfo,
  ProgramOffering,
  SemesterTuitionBulkUpsertItem,
} from "@/types/organization.types";
// NOTE: AdmissionCriterion removed - use Admission Configuration Console for criteria management
// See: /admin/admission-config for the new admin UI

// =====================================================================
// FORM TYPES & SCHEMA
// =====================================================================

// NOTE: admission_criteria types and schemas REMOVED
// Use Admission Configuration Console (/admin/admission-config) for criteria management

// 2. Schema tổng thể
const academicInfoFormSchema = z.object({
  academic_year: z
    .number()
    .int("Năm học phải là số nguyên")
    .min(2000, "Năm học phải từ 2000 trở lên")
    .max(2100, "Năm học không được vượt quá 2100"),
  tuition_fee_per_year: z.number().min(0, "Học phí không được âm").nullish(),
  annual_admission_quota: z.number().int().min(0, "Chỉ tiêu không được âm").nullish(),
  target_audience: z.string().max(1000).optional(),
  cutoff_score_previous_year: z.number().min(0).max(30).nullish(),

  // Chính sách ưu đãi học phí
  applied_discount_policy_ids: z.array(z.number()).optional().nullable(),

  // NOTE: admission_criteria REMOVED - use Admission Configuration Console
  // Path: /admin/admission-config for criteria management

  is_published: z.boolean(),
});

type AcademicInfoFormValues = z.infer<typeof academicInfoFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface OfferingAcademicInfoDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  offering: ProgramOffering;
  academicInfo?: OfferingAcademicInfo | null;
  existingYears?: number[]; // Danh sách các năm đã có dữ liệu (để check trùng)
  onSaveSuccess?: (data: OfferingAcademicInfo, shouldClose: boolean) => void;
}

// =====================================================================
// HELPER FUNCTIONS (Data Transformation)
// =====================================================================

// NOTE: convertApiToFormData and convertFormToApiData REMOVED
// Admission criteria now managed via Admission Configuration Console

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function OfferingAcademicInfoDialog({
  open,
  onOpenChange,
  offering,
  academicInfo,
  existingYears = [],
  onSaveSuccess,
}: OfferingAcademicInfoDialogProps) {
  const isEditMode = !!academicInfo;
  const currentYear = new Date().getFullYear();

  // Kiểm tra logic nghiệp vụ: Năm trong quá khứ thì không cho sửa dữ liệu tài chính
  const isPastYear = useMemo(() => {
    if (!academicInfo) return false;
    return academicInfo.academic_year < currentYear;
  }, [academicInfo, currentYear]);

  const createMutation = useCreateOfferingAcademicInfo();
  const updateMutation = useUpdateOfferingAcademicInfo();
  const bulkUpsertMutation = useBulkUpsertSemesterTuitions();

  const [semesterTuitions, setSemesterTuitions] = useState<
    SemesterTuitionBulkUpsertItem[]
  >([]);
  const [semesterSaveError, setSemesterSaveError] = useState<string | null>(null);
  // After step-1 create succeeds but step-2 bulk upsert fails, we need
  // to remember the created academic_info id so the retry only re-runs
  // the semester upsert instead of creating a duplicate record.
  const [pendingAcademicInfoId, setPendingAcademicInfoId] = useState<number | null>(null);
  const hasSemesterTuitions = semesterTuitions.length > 0;

  const form = useForm<AcademicInfoFormValues>({
    resolver: zodResolver(academicInfoFormSchema),
    defaultValues: {
      academic_year: currentYear,
      tuition_fee_per_year: null,
      annual_admission_quota: null,
      target_audience: "",
      cutoff_score_previous_year: null,
      applied_discount_policy_ids: [],
      is_published: false,
    },
  });

  // Fetch discount policies for selection
  const { data: discountPoliciesData, isLoading: isLoadingDiscounts } = useTuitionDiscountPolicies({
    isActive: true,
    includeExpired: false,
  });

  // Initialize form + local state when dialog opens. Called from
  // handleOpenChange on true transitions only — NOT from useEffect,
  // to satisfy react-hooks/set-state-in-effect lint rule and to
  // prevent query-invalidation re-renders from wiping retry state.
  const initializeDialog = React.useCallback(() => {
    form.clearErrors();
    setSemesterSaveError(null);
    setPendingAcademicInfoId(null);

    if (isEditMode && academicInfo?.semester_tuitions) {
      setSemesterTuitions(
        academicInfo.semester_tuitions.map((st) => ({
          semester_no: st.semester_no,
          amount: Number(st.amount),
          notes: st.notes ?? null,
        }))
      );
    } else {
      setSemesterTuitions([]);
    }

    if (isEditMode && academicInfo) {
      form.reset({
        academic_year: Number(academicInfo.academic_year),
        tuition_fee_per_year:
          academicInfo.tuition_fee_per_year !== null
            ? Number(academicInfo.tuition_fee_per_year)
            : null,
        annual_admission_quota:
          academicInfo.annual_admission_quota !== null
            ? Number(academicInfo.annual_admission_quota)
            : null,
        cutoff_score_previous_year:
          academicInfo.cutoff_score_previous_year !== null
            ? Number(academicInfo.cutoff_score_previous_year)
            : null,
        target_audience: academicInfo.target_audience || "",
        applied_discount_policy_ids: academicInfo.applied_discount_policy_ids || [],
        is_published: academicInfo.is_published,
      });
    } else {
      let nextYear = currentYear;
      while (existingYears.includes(nextYear)) {
        nextYear++;
      }
      form.reset({
        academic_year: nextYear,
        tuition_fee_per_year: null,
        annual_admission_quota: null,
        target_audience: "",
        cutoff_score_previous_year: null,
        applied_discount_policy_ids: [],
        is_published: false,
      });
    }
  }, [isEditMode, academicInfo, form, existingYears, currentYear]);

  // Intercept dialog open/close to run initialization on open
  // transitions without using useEffect + setState (which violates
  // react-hooks/set-state-in-effect). The parent controls `open` via
  // onOpenChange; we wrap it to run init on the true→ path.
  const prevOpenRef = React.useRef(false);
  const handleOpenChange = React.useCallback(
    (nextOpen: boolean) => {
      if (nextOpen && !prevOpenRef.current) {
        initializeDialog();
      }
      prevOpenRef.current = nextOpen;
      onOpenChange(nextOpen);
    },
    [initializeDialog, onOpenChange]
  );

  // Also init on mount if dialog starts open (parent opens it by
  // setting open=true before this component mounts).
  React.useEffect(() => {
    if (open && !prevOpenRef.current) {
      prevOpenRef.current = true;
      // Defer to next microtask so React commits current render first,
      // avoiding synchronous setState during render.
      queueMicrotask(initializeDialog);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [saveAction, setSaveAction] = useState<"close" | "continue">("close");

  const onSubmit = async (values: AcademicInfoFormValues) => {
    // Skip duplicate-year check when retrying after a partial create
    // (step-1 succeeded, step-2 failed). The record already exists
    // and query invalidation may have added it to existingYears.
    if (
      !isEditMode &&
      !pendingAcademicInfoId &&
      existingYears.includes(values.academic_year)
    ) {
      form.setError("academic_year", {
        type: "manual",
        message: `Thông tin tuyển sinh năm ${values.academic_year} đã tồn tại. Vui lòng chọn năm khác hoặc chỉnh sửa bản ghi cũ.`,
      });
      return;
    }

    setSemesterSaveError(null);

    try {
      // Step 1: Save academic info (skip if we already created it on a
      // previous attempt and only the semester upsert failed).
      let academicInfoId: number;

      if (pendingAcademicInfoId) {
        // Retry path: step 1 already succeeded on a prior submit, the
        // record exists with this id. Only re-run step 2.
        academicInfoId = pendingAcademicInfoId;
      } else if (isEditMode && academicInfo) {
        const resultData = await updateMutation.mutateAsync({
          id: academicInfo.id,
          data: values,
        });
        academicInfoId = resultData.id;
      } else {
        const resultData = await createMutation.mutateAsync({
          offeringId: offering.id,
          offering_id: offering.id,
          ...values,
        });
        academicInfoId = resultData.id;
        // Remember the created id in case step 2 fails and we need to
        // retry without re-creating.
        setPendingAcademicInfoId(academicInfoId);
      }

      // Step 2: Bulk upsert semester tuitions
      try {
        await bulkUpsertMutation.mutateAsync({
          academicInfoId,
          items: semesterTuitions,
        });
      } catch (semError) {
        setSemesterSaveError(
          "Thông tin tuyển sinh đã lưu, nhưng học phí học kỳ chưa cập nhật. " +
            "Vui lòng thử lại."
        );
        console.error("Semester tuition save failed:", semError);
        return;
      }

      // Step 2 succeeded — clear the pending id so it does not leak
      // into a subsequent dialog open.
      setPendingAcademicInfoId(null);

      // Step 3: Refetch the academic info with nested semester_tuitions
      // so onSaveSuccess receives a complete object.
      let freshData: OfferingAcademicInfo | undefined;
      try {
        const { data: infos } = await api.get<OfferingAcademicInfo[]>(
          API_ENDPOINTS.ORGANIZATION.LIST_ACADEMIC_INFO(offering.id)
        );
        freshData = infos.find((i) => i.id === academicInfoId);
      } catch {
        // Refetch failed — parent will pick up fresh data on next
        // query invalidation cycle.
      }

      // Step 4: Notify parent with fresh data (or minimal fallback)
      const dataForCallback: OfferingAcademicInfo = freshData ?? {
        id: academicInfoId,
        offering_id: offering.id,
        academic_year: values.academic_year,
        is_published: values.is_published,
        is_deleted: false,
        semester_tuitions: semesterTuitions.map((st, i) => ({
          id: -(i + 1),
          academic_info_id: academicInfoId,
          ...st,
        })),
      };

      if (onSaveSuccess) {
        onSaveSuccess(dataForCallback, saveAction === "close");
      } else {
        handleOpenChange(false);
      }
    } catch (error) {
      console.error("Form submission failed:", error);
    }
  };

  const isSubmitting =
    createMutation.isPending ||
    updateMutation.isPending ||
    bulkUpsertMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[800px]">
        <DialogHeader>
          <DialogTitle>
            {isEditMode
              ? `Chỉnh sửa thông tin - Năm ${academicInfo?.academic_year}`
              : "Tạo thông tin tuyển sinh mới"}
          </DialogTitle>
          <DialogDescription>
            Loại hình: <strong>{offering.offering_type}</strong>
            {isPastYear && isEditMode && (
              <span className="mt-1 block font-medium text-warning-600">
                ⚠️ Đây là dữ liệu lịch sử (năm {academicInfo?.academic_year}). Chỉ có thể cập nhật
                thông tin mô tả, không thể sửa dữ liệu tài chính.
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Academic Year */}
            <FormField
              control={form.control}
              name="academic_year"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Năm học <span className="text-error-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      {...field}
                      onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
                      // Edit mode: Luôn disable năm học (khóa chính)
                      disabled={isSubmitting || isEditMode}
                      className={isEditMode ? "bg-muted font-bold" : ""}
                    />
                  </FormControl>
                  {!isEditMode && (
                    <FormDescription>
                      Nhập năm tuyển sinh (VD: 2025). Không được trùng với năm đã có.
                    </FormDescription>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {/* Tuition Fee (legacy — read-only when semester tuitions exist) */}
              <FormField
                control={form.control}
                name="tuition_fee_per_year"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {hasSemesterTuitions
                        ? "Học phí/năm (giá trị cũ — tham khảo)"
                        : "Học phí/năm"}
                    </FormLabel>
                    <FormControl>
                      <CurrencyInput
                        value={field.value}
                        onChange={field.onChange}
                        placeholder="VD: 15.000.000"
                        disabled={
                          isSubmitting ||
                          (isEditMode && isPastYear) ||
                          hasSemesterTuitions
                        }
                        currency="VND"
                        locale="vi-VN"
                        className={
                          (isEditMode && isPastYear) || hasSemesterTuitions
                            ? "bg-muted cursor-not-allowed"
                            : ""
                        }
                      />
                    </FormControl>
                    {hasSemesterTuitions && (
                      <FormDescription>
                        Giá trị tham khảo. Học phí chính thức được nhập theo từng học kỳ bên dưới.
                      </FormDescription>
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Admission Quota */}
              <FormField
                control={form.control}
                name="annual_admission_quota"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Chỉ tiêu tuyển sinh</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        placeholder="VD: 100"
                        {...field}
                        value={field.value ?? ""}
                        onChange={(e) =>
                          field.onChange(e.target.value ? parseInt(e.target.value) : null)
                        }
                        // 🛡️ Disable nếu là năm quá khứ
                        disabled={isSubmitting || (isEditMode && isPastYear)}
                        className={isEditMode && isPastYear ? "bg-muted cursor-not-allowed" : ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Tuition Discount Policies */}
            <FormField
              control={form.control}
              name="applied_discount_policy_ids"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-2">
                    <Percent className="h-4 w-4" />
                    Chính sách ưu đãi học phí
                  </FormLabel>
                  <FormDescription>
                    Chọn các chính sách ưu đãi áp dụng cho chương trình này
                  </FormDescription>
                  {isLoadingDiscounts ? (
                    <div className="space-y-2">
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                    </div>
                  ) : discountPoliciesData?.items && discountPoliciesData.items.length > 0 ? (
                    <div className="max-h-[200px] overflow-y-auto rounded-md border p-3 space-y-2">
                      {discountPoliciesData.items.map((policy) => {
                        const isChecked = (field.value || []).includes(policy.id);
                        return (
                          <div
                            key={policy.id}
                            className="flex items-center space-x-3 rounded-md p-2 hover:bg-muted/50"
                          >
                            <Checkbox
                              id={`policy-${policy.id}`}
                              checked={isChecked}
                              onCheckedChange={(checked) => {
                                const currentIds = field.value || [];
                                if (checked) {
                                  field.onChange([...currentIds, policy.id]);
                                } else {
                                  field.onChange(currentIds.filter((id: number) => id !== policy.id));
                                }
                              }}
                              disabled={isSubmitting}
                            />
                            <label
                              htmlFor={`policy-${policy.id}`}
                              className="flex-1 cursor-pointer text-sm"
                            >
                              <div className="font-medium">{policy.name}</div>
                              <div className="text-muted-foreground text-xs">
                                {policy.code} -{" "}
                                {policy.discount_type === "percentage"
                                  ? `${policy.discount_value}%`
                                  : `${new Intl.NumberFormat("vi-VN").format(policy.discount_value)} VNĐ`}
                              </div>
                            </label>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-muted-foreground rounded-md border border-dashed p-4 text-center text-sm">
                      Chưa có chính sách ưu đãi nào. Vui lòng tạo chính sách trong mục Quản lý Ưu đãi.
                    </div>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Semester Tuition Editor (PR 2 — ADR-002) */}
            <div className="rounded-lg border p-4">
              <SemesterTuitionEditor
                value={semesterTuitions}
                onChange={setSemesterTuitions}
                durationSemesters={offering.duration_semesters}
                disabled={isSubmitting || (isEditMode && isPastYear)}
              />
              {semesterSaveError && (
                <p className="mt-2 text-sm text-destructive">{semesterSaveError}</p>
              )}
            </div>

            {/* Target Audience */}
            <FormField
              control={form.control}
              name="target_audience"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Đối tượng tuyển sinh</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Mô tả đối tượng tuyển sinh phù hợp..."
                      className="min-h-[100px] resize-y"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Cutoff Score */}
            <FormField
              control={form.control}
              name="cutoff_score_previous_year"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Điểm chuẩn năm trước</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      step="0.01"
                      placeholder="VD: 18.5"
                      {...field}
                      value={field.value ?? ""}
                      onChange={(e) =>
                        field.onChange(e.target.value ? parseFloat(e.target.value) : null)
                      }
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />


            {/* NOTE: Dynamic Criteria section REMOVED */}
            {/* Admission criteria are now managed via Admission Configuration Console */}
            <div className="rounded-lg border border-dashed p-4 text-center">
              <div className="text-muted-foreground text-sm">
                <strong>Lưu ý:</strong> Phương thức xét tuyển và tiêu chí tuyển sinh được quản lý tại{" "}
                <span className="font-medium text-primary">Admission Configuration Console</span>
              </div>
            </div>


            <FormField
              control={form.control}
              name="is_published"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                  <div className="space-y-0.5">
                    <FormLabel className="text-base">Công khai</FormLabel>
                    <FormDescription>Cho phép hiển thị thông tin này ra công chúng</FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={isSubmitting}
              >
                Hủy
              </Button>

              {/* Nút 1: Lưu & Đóng */}
              <Button type="submit" disabled={isSubmitting} onClick={() => setSaveAction("close")}>
                {isSubmitting && saveAction === "close" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-2 h-4 w-4" />
                )}
                {isEditMode ? "Lưu thay đổi" : "Tạo và Đóng"}
              </Button>

              {/* Nút 2: Lưu & Tiếp tục (Chỉ hiện khi Tạo mới hoặc muốn giữ form) */}
              <Button
                type="submit"
                variant="secondary"
                disabled={isSubmitting}
                onClick={() => setSaveAction("continue")}
              >
                {isSubmitting && saveAction === "continue" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <SaveAll className="mr-2 h-4 w-4" />
                )}
                {isEditMode ? "Lưu và Tiếp tục" : "Tạo và Tiếp tục"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
