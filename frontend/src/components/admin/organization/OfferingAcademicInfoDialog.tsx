// src/components/admin/organization/OfferingAcademicInfoDialog.tsx
"use client";

import { useEffect, useMemo, useState } from "react";
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
} from "@/hooks/useOrganization";
import { useTuitionDiscountPolicies } from "@/hooks/useTuitionDiscount";
import type {
  OfferingAcademicInfo,
  ProgramOffering,
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

  // NOTE: useFieldArray for admission_criteria REMOVED
  // Use Admission Configuration Console for criteria management

  // --- DATA LOADING & PARSING ---
  useEffect(() => {
    if (open) {
      form.clearErrors(); // Reset lỗi cũ khi mở lại form

      if (isEditMode && academicInfo) {
        // --- EDIT MODE ---
        // NOTE: admission_criteria parsing REMOVED - use Admission Config Console

        // 🛡️ CRITICAL FIX: Ép kiểu dữ liệu từ API (Decimal/String -> Number)
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
        // --- CREATE MODE ---
        // Gợi ý năm tiếp theo chưa có trong danh sách
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
    }
  }, [open, isEditMode, academicInfo, form, existingYears, currentYear]);

  const [saveAction, setSaveAction] = useState<"close" | "continue">("close");

  const onSubmit = async (values: AcademicInfoFormValues) => {
    // 🛡️ CLIENT-SIDE VALIDATION: Unique Year Constraint
    if (!isEditMode && existingYears.includes(values.academic_year)) {
      form.setError("academic_year", {
        type: "manual",
        message: `Thông tin tuyển sinh năm ${values.academic_year} đã tồn tại. Vui lòng chọn năm khác hoặc chỉnh sửa bản ghi cũ.`,
      });
      return;
    }

    try {
      let resultData: OfferingAcademicInfo;

      if (isEditMode && academicInfo) {
        // Update logic
        resultData = await updateMutation.mutateAsync({
          id: academicInfo.id,
          data: values,
        });
      } else {
        // Create logic
        resultData = await createMutation.mutateAsync({
          offeringId: offering.id,
          offering_id: offering.id,
          ...values,
        });
      }

      // ✅ Gọi callback thay vì tự đóng
      if (onSaveSuccess) {
        onSaveSuccess(resultData, saveAction === "close");
      } else {
        // Fallback nếu không có callback (logic cũ)
        onOpenChange(false);
      }
      // Nếu "Lưu & Tiếp tục", ta reset form với dữ liệu mới nhất từ Server
      // để đảm bảo form clean (isDirty = false)
      if (saveAction === "continue") {
        // Logic reset form sẽ được useEffect xử lý khi prop `academicInfo` thay đổi
        // nhờ hàm handleSaveSuccess ở component cha.
      }
    } catch (error) {
      console.error("Form submission failed:", error);
      // Error toast handled in hooks
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
              {/* Tuition Fee */}
              <FormField
                control={form.control}
                name="tuition_fee_per_year"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Học phí/năm</FormLabel>
                    <FormControl>
                      <CurrencyInput
                        value={field.value}
                        onChange={field.onChange}
                        placeholder="VD: 15.000.000"
                        // 🛡️ Disable nếu là năm quá khứ
                        disabled={isSubmitting || (isEditMode && isPastYear)}
                        currency="VND"
                        locale="vi-VN"
                        className={isEditMode && isPastYear ? "bg-muted cursor-not-allowed" : ""}
                      />
                    </FormControl>
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
                onClick={() => onOpenChange(false)}
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
